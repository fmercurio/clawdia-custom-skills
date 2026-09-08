"""Bounded local inventory and container reading. Never extracts or executes."""

import hashlib
import io
import tarfile
import zipfile
import struct
import unicodedata
import zlib
import os
import stat
from pathlib import Path

try:
    from .clean_room_policy import (
        MAX_DEPTH,
        MAX_ENTRIES,
        MAX_FILE_BYTES,
        MAX_TOTAL_BYTES,
        relative_path,
        require,
    )
except ImportError:
    from clean_room_policy import (
        MAX_DEPTH,
        MAX_ENTRIES,
        MAX_FILE_BYTES,
        MAX_TOTAL_BYTES,
        relative_path,
        require,
    )

# Exact directory names only, at any source-tree level. Archives have no exclusions.
CONTROL_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
    }
)


class Budget:
    def __init__(self):
        self.entries = 0
        self.total = 0

    def entry(self):
        self.entries += 1
        require(self.entries <= MAX_ENTRIES)

    def read(self, stream, limit=MAX_FILE_BYTES):
        data = bytearray()
        while True:
            chunk = stream.read(
                min(65536, limit - len(data) + 1, MAX_TOTAL_BYTES - self.total + 1)
            )
            if not chunk:
                return bytes(data)
            data.extend(chunk)
            self.total += len(chunk)
            require(len(data) <= limit and self.total <= MAX_TOTAL_BYTES)


def regular_bytes(path, budget):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
    require(info.st_size <= MAX_FILE_BYTES)
    with path.open("rb") as stream:
        return budget.read(stream)


def source_entries(root, budget):
    root = Path(root)
    require(root.is_absolute() and not root.is_symlink() and root.is_dir())
    stack = [root]
    paths = Paths()
    while stack:
        directory = stack.pop()
        children = []
        with os.scandir(directory) as iterator:
            for child in iterator:
                require(len(children) < MAX_ENTRIES)
                children.append(child)
        for child in sorted(children, key=lambda c: c.name):
            path = Path(child.path)
            info = child.stat(follow_symlinks=False)
            require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
            if stat.S_ISDIR(info.st_mode) and child.name in CONTROL_DIRS:
                continue
            name = inventory_path(path.relative_to(root).as_posix())
            paths.add(name, stat.S_ISDIR(info.st_mode))
            budget.entry()
            if stat.S_ISDIR(info.st_mode):
                yield name, None
                stack.append(path)
            else:
                yield name, regular_bytes(path, budget)


def archive_kind(name, data):
    lower = name.lower()
    if data.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return "zip"
    if data.startswith(b"\x1f\x8b"):
        return "tgz"
    if len(data) >= 512 and data[257:262] == b"ustar":
        return "tar"
    unsupported = (
        b"BZh",
        b"\xfd7zXZ",
        b"7z\xbc\xaf",
        b"Rar!",
        b"%PDF-",
        b"\x28\xb5\x2f\xfd",
        b"\x89PNG",
        b"GIF8",
        b"\xff\xd8",
    )
    require(not data.startswith(unsupported))
    if lower.endswith(
        (
            ".zip",
            ".tar",
            ".tar.gz",
            ".tgz",
            ".gz",
            ".bz2",
            ".xz",
            ".zst",
            ".7z",
            ".rar",
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
        )
    ):
        require(False)
    return None


def inventory_path(name):
    relative_path(name)
    require(not any(part.startswith("@") for part in name.split("/")))
    return name


class Paths:
    def __init__(self):
        self.explicit = set()
        self.kinds = {}

    def add(self, name, directory):
        inventory_path(name)
        key = unicodedata.normalize("NFKC", name).casefold()
        require(key not in self.explicit)
        require(key not in self.kinds or (directory and self.kinds[key]))
        parts = key.split("/")
        for end in range(1, len(parts)):
            parent = "/".join(parts[:end])
            require(self.kinds.get(parent, True))
            self.kinds[parent] = True
        self.kinds[key] = directory
        self.explicit.add(key)


def zip_extra(raw):
    # Extended timestamps are the only supported extra field (including git archive).
    while raw:
        require(len(raw) >= 4)
        kind, size = struct.unpack("<HH", raw[:4])
        require(kind == 0x5455 and size in (5, 9, 13) and len(raw) >= size + 4)
        raw = raw[4 + size :]


MAX_EXPANSION = 200


def inflate(data, budget, window):
    decoder = zlib.decompressobj(window)
    result = bytearray()
    for offset in range(0, len(data), 65536):
        chunk = decoder.decompress(
            data[offset : offset + 65536],
            min(MAX_FILE_BYTES - len(result), MAX_TOTAL_BYTES - budget.total) + 1,
        )
        result.extend(chunk)
        budget.total += len(chunk)
        require(len(result) <= MAX_FILE_BYTES and budget.total <= MAX_TOTAL_BYTES)
        require(not decoder.unconsumed_tail and not decoder.unused_data)
    require(decoder.eof and len(result) <= max(1, len(data)) * MAX_EXPANSION)
    return bytes(result)


def zip_members(data, budget):
    end = data.rfind(b"PK\x05\x06")
    require(end >= 0 and len(data) >= end + 22)
    _, disk, central_disk, count_disk, count, size, offset, comment = struct.unpack(
        "<4s4H2IH", data[end : end + 22]
    )
    require(disk == central_disk == 0 and count_disk == count <= MAX_ENTRIES)
    require(offset + size == end and end + 22 + comment == len(data))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        require(len(entries) == count)
        require(
            sum(
                46
                + len(e.filename.encode("utf-8" if e.flag_bits & 0x800 else "cp437"))
                + len(e.extra)
                + len(e.comment)
                for e in entries
            )
            == size
        )
        if archive.comment:
            yield None, archive.comment, "metadata"
        cursor = 0
        for entry in sorted(entries, key=lambda e: e.header_offset):
            budget.entry()
            require(entry.header_offset == cursor)
            require(entry.flag_bits & ~0x808 == 0)
            require(entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED))
            require(entry.file_size <= MAX_FILE_BYTES)
            mode = entry.external_attr >> 16
            require(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR))
            require(not stat.S_ISDIR(mode) or entry.is_dir())
            require(entry.orig_filename == entry.filename)
            zip_extra(entry.extra)
            if entry.extra:
                yield (
                    entry.filename.removesuffix("/"),
                    entry.extra.decode("latin-1").encode("utf-8"),
                    "raw_metadata",
                )
            header = data[cursor : cursor + 30]
            require(len(header) == 30)
            values = struct.unpack("<4s5H3I2H", header)
            signature, _, flags, method, _, _, crc, compressed, expanded, nlen, xlen = (
                values
            )
            require(
                signature == b"PK\x03\x04"
                and flags == entry.flag_bits
                and method == entry.compress_type
            )
            name = data[cursor + 30 : cursor + 30 + nlen].decode(
                "utf-8" if flags & 0x800 else "cp437"
            )
            require(name == entry.filename)
            extra = data[cursor + 30 + nlen : cursor + 30 + nlen + xlen]
            zip_extra(extra)
            if extra:
                yield (
                    entry.filename.removesuffix("/"),
                    extra.decode("latin-1").encode("utf-8"),
                    "raw_metadata",
                )
            body_start = cursor + 30 + nlen + xlen
            cursor = body_start + entry.compress_size
            require(cursor <= offset)
            if flags & 8:
                # Local placeholders or matching values only, before descriptor replacement.
                require(compressed != 0xFFFFFFFF and expanded != 0xFFFFFFFF)
                require(
                    crc in (0, entry.CRC)
                    and compressed in (0, entry.compress_size)
                    and expanded in (0, entry.file_size)
                )
                if data[cursor : cursor + 4] == b"PK\x07\x08":
                    cursor += 4
                require(len(data[cursor : cursor + 12]) == 12)
                crc, compressed, expanded = struct.unpack(
                    "<3I", data[cursor : cursor + 12]
                )
                cursor += 12
            require(
                (crc, compressed, expanded)
                == (entry.CRC, entry.compress_size, entry.file_size)
            )
            if entry.comment:
                yield entry.filename.removesuffix("/"), entry.comment, "metadata"
            packed = data[body_start : body_start + entry.compress_size]
            if entry.compress_type == zipfile.ZIP_DEFLATED:
                body = inflate(packed, budget, -15)
            else:
                body = budget.read(io.BytesIO(packed))
            require(len(body) == entry.file_size and zlib.crc32(body) == entry.CRC)
            require(not entry.is_dir() or not body)
            yield entry.filename, body, "directory" if entry.is_dir() else "file"
        require(cursor == offset)


def tar_members(data, budget):
    require(len(data) % 512 == 0)
    offset = 0
    while offset + 512 <= len(data):
        header = data[offset : offset + 512]
        if not any(header):
            require(len(data) - offset >= 1024 and not any(data[offset:]))
            return
        entry = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
        raw_name = header[:100].split(b"\0", 1)[0].decode("utf-8")
        prefix = header[345:500].split(b"\0", 1)[0].decode("utf-8")
        name = (prefix + "/" if prefix else "") + raw_name
        if entry.isdir():
            name = name.removesuffix("/")
        inventory_path(name)
        budget.entry()
        require(entry.size >= 0 and entry.size <= MAX_FILE_BYTES)
        require(
            entry.type
            in (
                tarfile.REGTYPE,
                tarfile.AREGTYPE,
                tarfile.DIRTYPE,
                tarfile.XGLTYPE,
                tarfile.XHDTYPE,
            )
        )
        end = offset + 512 + entry.size
        following = (end + 511) // 512 * 512
        require(following <= len(data) and not any(data[end:following]))
        body = data[offset + 512 : end]
        # TAR headers carry names, owner names, and implementation metadata.
        yield name, header.replace(b"\0", b" "), "metadata"
        if entry.type in (tarfile.XGLTYPE, tarfile.XHDTYPE):
            # Only inert comment/time PAX records. Path overrides, sparse and vendor
            # extensions have ambiguous or unsupported semantics and fail closed.
            cursor = 0
            keys = set()
            while cursor < len(body):
                space = body.find(b" ", cursor)
                require(space > cursor)
                length = int(body[cursor:space])
                require(length > space - cursor + 1 and cursor + length <= len(body))
                record = body[space + 1 : cursor + length]
                require(record.endswith(b"\n") and b"=" in record)
                key = record.split(b"=", 1)[0]
                require(
                    key in (b"comment", b"mtime", b"atime", b"ctime")
                    and key not in keys
                )
                keys.add(key)
                cursor += length
            yield None, body, "metadata"
        else:
            require(not entry.linkname and (not entry.isdir() or entry.size == 0))
            yield name, body, "directory" if entry.isdir() else "file"
        offset = following
    require(False)


def members(data, kind, budget):
    if kind == "zip":
        yield from zip_members(data, budget)
        return
    if kind == "tgz":
        # Optional gzip fields can carry opaque metadata; this version rejects them.
        require(len(data) >= 18 and data[3] == 0)
        yield None, data[:10].decode("latin-1").encode("utf-8"), "raw_metadata"
        data = inflate(data, budget, 31)
    yield from tar_members(data, budget)


def inspect_payload(scanner, path, data, budget, depth=0):
    kind = archive_kind(path, data)
    if kind:
        require(depth < MAX_DEPTH)
        identity = path + "/@" + hashlib.sha256(data).hexdigest()
        paths = Paths()
        for name, body, entry_kind in members(data, kind, budget):
            scanner.entries = budget.entries
            if entry_kind in ("metadata", "raw_metadata"):
                metadata_path = (
                    identity if name is None else identity + "/" + inventory_path(name)
                )
                text = body.decode("utf-8")
                if entry_kind == "metadata":
                    require(not any(ord(c) < 32 and c not in "\t\r\n" for c in text))
                else:
                    text = text.replace("\0", "")
                scanner.inspect(metadata_path, "content", text)
                continue
            name = name.removesuffix("/") if entry_kind == "directory" else name
            paths.add(name, entry_kind == "directory")
            member_path = identity + "/" + name
            scanner.inspect(member_path, "path", name)
            if entry_kind != "directory":
                inspect_payload(scanner, member_path, body, budget, depth + 1)
    else:
        binary = data.startswith(b"P6")
        try:
            text = data.decode("utf-8")
            binary = binary or any(ord(c) < 32 and c not in "\t\r\n" for c in text)
        except UnicodeError:
            binary = True
        if binary:
            inspect_binary(scanner, path, data)
        else:
            scanner.inspect(
                path, "content", text, content_sha256=hashlib.sha256(data).hexdigest()
            )


def inspect_binary(scanner, path, data):
    import re

    require(
        any(
            e["path"] == path and e["sha256"] == hashlib.sha256(data).hexdigest()
            for e in scanner.policy["reviewed_assets"]
        )
    )
    # A deliberately narrow PPM P6 grammar: ASCII comments/whitespace, RGB8,
    # exactly one raster, no trailing payload or embedded container.
    whitespace = rb"(?:[ \t\r\n]|\#[ -~]*\n)+"
    header = re.match(
        rb"P6"
        + whitespace
        + rb"([0-9]{1,5})"
        + whitespace
        + rb"([0-9]{1,5})"
        + whitespace
        + rb"255[ \t\r\n]",
        data,
    )
    require(header is not None)
    width, height = map(int, header.groups())
    require(width > 0 and height > 0 and len(data) - header.end() == width * height * 3)
    # Every raw byte is inspected; NUL removal exposes ASCII in UTF-16-like runs.
    # PPM has no compressed, executable, or opaque metadata sections.
    scanner.inspect(path, "content", data.decode("latin-1").replace("\0", ""))
