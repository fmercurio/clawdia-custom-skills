#!/usr/bin/env python3
"""Shared stdlib-only helpers for second-brain-kit."""
from __future__ import annotations
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
from pathlib import Path
from typing import Any

VERSION = "0.2.0-rc1"
SCHEMA_VERSION = 1
MINIMUM_PYTHON_VERSION = (3, 11)
LAYERS = {
    "inbox": "00_Inbox",
    "project": "10_Projects",
    "area": "20_Areas",
    "resource": "30_Resources",
    "archive": "40_Archives",
}
REQUIRED_DIRS = [*LAYERS.values(), "50_Templates", "_Hermes", "_Meta"]
ROOT_DOCS = ["README.md", "MAPA.md", "PARA.md", "HERMES.md"]


def require_supported_python(version_info: tuple[int, int] | None = None) -> None:
    """Fail before lifecycle work when the documented Python baseline is unmet."""
    current = version_info or sys.version_info[:2]
    if current < MINIMUM_PYTHON_VERSION:
        required = ".".join(map(str, MINIMUM_PYTHON_VERSION))
        detected = ".".join(map(str, current))
        raise RuntimeError(
            f"Python {required}+ is required (detected {detected}). "
            "Run second-brain-kit with a Python 3.11+ interpreter."
        )


def real_directory_root(
    value: Path,
    *,
    label: str = "directory root",
    require_exists: bool = True,
) -> Path:
    """Return an absolute directory root only when no existing lexical component is a symlink."""
    root = Path(os.path.abspath(os.fspath(Path(value).expanduser())))
    current = Path(root.anchor)
    for part in root.parts[1:]:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            if require_exists:
                raise ValueError(f"{label} does not exist: {root}")
            break
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"symlinked {label} is not allowed: {current}")
        if current != root and not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"{label} ancestor is not a directory: {current}")
    if root.exists() and not root.is_dir():
        raise ValueError(f"{label} is not a directory: {root}")
    if require_exists and not root.is_dir():
        raise ValueError(f"{label} is not a directory: {root}")
    return root


def real_vault_root(value: Path, *, require_exists: bool = True) -> Path:
    """Validate a vault root without resolving symlinks first."""
    return real_directory_root(value, label="vault root", require_exists=require_exists)


def _safe_relative_parts(relative: Path) -> tuple[str, ...]:
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("path must be a non-empty relative path without traversal")
    return relative.parts


def _validate_private_directory_chain(root: Path, relative: Path) -> Path:
    root = real_directory_root(root)
    parts = _safe_relative_parts(relative)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlinked directory is not allowed beneath {root}")
        if not current.is_dir():
            raise ValueError(f"directory path is not a directory: {current}")
        if not current.resolve(strict=True).is_relative_to(root):
            raise ValueError(f"directory escapes configured root: {current}")
    return current


def private_directory(root: Path, relative: Path, *, create: bool = True) -> Path:
    """Create or validate an owner-only real directory beneath a trusted root."""
    root = real_directory_root(root)
    parts = _safe_relative_parts(relative)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlinked directory is not allowed beneath {root}")
        if create and not current.exists():
            current.mkdir(mode=0o700, exist_ok=True)
        if not current.exists():
            raise ValueError(f"directory path is not a directory: {current}")
        if not current.is_dir():
            raise ValueError(f"directory path is not a directory: {current}")
        if current.is_symlink() or not current.resolve(strict=True).is_relative_to(root):
            raise ValueError(f"directory escapes configured root: {current}")
    current.chmod(0o700)
    return current


def write_bytes_beneath(
    root: Path,
    relative: Path,
    content: bytes,
    *,
    file_mode: int = 0o666,
    overwrite: bool = False,
    exact_mode: bool = False,
) -> Path:
    """Write a regular file beneath root without following directory or leaf links."""
    root = real_directory_root(root)
    parts = _safe_relative_parts(relative)
    if os.open not in os.supports_dir_fd or os.mkdir not in os.supports_dir_fd:
        raise OSError("secure contained writes require directory-relative filesystem operations")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current_fd = os.open(root, directory_flags)
    try:
        for part in parts[:-1]:
            try:
                next_fd = os.open(part, directory_flags, dir_fd=current_fd)
            except FileNotFoundError:
                os.mkdir(part, mode=0o700, dir_fd=current_fd)
                next_fd = os.open(part, directory_flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        flags |= os.O_TRUNC if overwrite else os.O_EXCL
        file_fd = os.open(parts[-1], flags, file_mode, dir_fd=current_fd)
        try:
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise ValueError("destination is not a regular file")
            if exact_mode:
                os.fchmod(file_fd, file_mode)
            with os.fdopen(file_fd, "wb", closefd=False) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(file_fd)
        finally:
            os.close(file_fd)
    finally:
        os.close(current_fd)
    return root.joinpath(*parts)


def write_text_beneath(
    root: Path,
    relative: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    file_mode: int = 0o666,
    overwrite: bool = False,
    exact_mode: bool = False,
) -> Path:
    return write_bytes_beneath(
        root,
        relative,
        content.encode(encoding),
        file_mode=file_mode,
        overwrite=overwrite,
        exact_mode=exact_mode,
    )


def read_bytes_beneath(root: Path, relative: Path) -> bytes:
    """Read one regular file beneath root without following directory or leaf links."""
    root = real_directory_root(root)
    parts = _safe_relative_parts(relative)
    if os.open not in os.supports_dir_fd:
        raise OSError("secure contained reads require directory-relative filesystem operations")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current_fd = os.open(root, directory_flags)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, directory_flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        file_fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=current_fd)
        try:
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise ValueError("source is not a regular file")
            with os.fdopen(file_fd, "rb", closefd=False) as stream:
                return stream.read()
        finally:
            os.close(file_fd)
    finally:
        os.close(current_fd)


def validate_path_beneath(root: Path, relative: Path, *, leaf_kind: str = "file") -> Path:
    """Reject existing symlink components before planning or conflict checks."""
    root = real_directory_root(root)
    parts = _safe_relative_parts(relative)
    current = root
    for index, part in enumerate(parts):
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlinked destination is not allowed beneath {root}: {current}")
        if not current.exists():
            break
        is_leaf = index == len(parts) - 1
        if not is_leaf and not current.is_dir():
            raise ValueError(f"destination component is not a directory: {current}")
        if is_leaf and leaf_kind == "file" and not current.is_file():
            raise ValueError(f"destination is not a regular file: {current}")
        if not current.resolve(strict=True).is_relative_to(root):
            raise ValueError(f"destination escapes configured root: {current}")
    return root.joinpath(*parts)


def hermes_home(value: str | None = None) -> Path:
    return Path(value or os.environ.get("HERMES_HOME", "~/.hermes")).expanduser().resolve()


def profile_name(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", value):
        raise ValueError("profile must be lowercase alphanumeric with optional hyphens")
    return value


def service_identifier(value: object) -> str:
    """Validate the portable identifier used in rendered service labels."""
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", value):
        raise ValueError("service identifier must be lowercase alphanumeric with optional hyphens")
    return value


def require_capability(capability: str, granted: set[str] | frozenset[str]) -> None:
    """Require a named capability selected by the local owner policy."""
    if capability not in granted:
        raise PermissionError(f"missing required capability: {capability}")


def config_path(home: Path, profile: str) -> Path:
    return home / "second-brain-kit" / "profiles" / profile_name(profile) / "config.yaml"


def install_skill_root(home: Path, profile: str) -> Path:
    if profile == "default":
        return home / "skills" / "note-taking"
    return home / "profiles" / profile_name(profile) / "skills" / "note-taking"


def install_bin_root(home: Path) -> Path:
    return home / "second-brain-kit" / "bin"


def inventory_path(home: Path, profile: str) -> Path:
    return home / "second-brain-kit" / "profiles" / profile_name(profile) / "install-inventory.json"


def ensure_inventory_directory(home: Path, profile: str) -> Path:
    """Ensure the install inventory parent chain is trusted and owner-only."""
    return private_directory(
        home.expanduser().resolve(strict=True),
        Path("second-brain-kit") / "profiles" / profile_name(profile),
    )


def default_config(owner: str, vault: Path, profile: str, organization: str | None = None, mode: str = "hybrid", vault_mode: str = "new") -> dict[str, Any]:
    if mode not in {"para", "hybrid", "okf"}:
        raise ValueError("mode must be para, hybrid, or okf")
    if vault_mode not in {"new", "existing"}:
        raise ValueError("vault_mode must be new or existing")
    return {
        "schema_version": SCHEMA_VERSION,
        "kit_version": VERSION,
        "owner": owner,
        "organization": organization,
        "vault_path": str(vault.expanduser().resolve()),
        "vault_mode": vault_mode,
        "profile": profile_name(profile),
        "locale": "pt-BR",
        "mode": mode,
        "sensitivity": {"default": "internal", "restricted_search": False},
        "git": {"enabled": False, "remote": None, "push_policy": "confirm"},
        "obsidian": {"enabled": False},
        "okf": {
            "enabled": "auto",
            "version": "1.6.0",
            "render": {"enabled": False, "title": None, "layout": None, "link": None, "output": None},
        },
        "embeddings": {"enabled": "auto", "provider": None, "endpoint": None, "model": None, "allow_remote": False},
        "cron": {"enabled": False, "schedule": "0 9 * * 1", "deliver": "local"},
        "mcp_readonly": {"enabled": False, "instance_name": None},
    }


def validate_config(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if not isinstance(data.get("owner"), str) or not data.get("owner", "").strip():
        errors.append("owner is required")
    elif any(char in data["owner"] for char in "\r\n"):
        errors.append("owner must be a single line")
    try:
        profile_name(str(data.get("profile", "")))
    except ValueError as exc:
        errors.append(str(exc))
    vault = data.get("vault_path")
    if not isinstance(vault, str) or not Path(vault).expanduser().is_absolute():
        errors.append("vault_path must be absolute")
    if data.get("mode") not in {"para", "hybrid", "okf"}:
        errors.append("mode must be para, hybrid, or okf")
    if data.get("vault_mode") not in {"new", "existing"}:
        errors.append("vault_mode must be new or existing")
    mcp_cfg = data.get("mcp_readonly", {"enabled": False, "instance_name": None})
    if not isinstance(mcp_cfg, dict):
        errors.append("mcp_readonly must be a mapping")
    else:
        if "enabled" not in mcp_cfg:
            errors.append("mcp_readonly.enabled is required")
        elif not isinstance(mcp_cfg.get("enabled"), bool):
            errors.append("mcp_readonly.enabled must be a boolean")
        instance_name = mcp_cfg.get("instance_name")
        if instance_name is None:
            pass
        elif not isinstance(instance_name, str):
            errors.append("mcp_readonly.instance_name must be null or a string")
        else:
            if not instance_name.strip():
                errors.append("mcp_readonly.instance_name must not be blank")
            elif re.search(r"[\\\/]", instance_name):
                errors.append("mcp_readonly.instance_name must not contain path separators")
    emb = data.get("embeddings", {})
    endpoint = emb.get("endpoint") if isinstance(emb, dict) else None
    if endpoint and not emb.get("allow_remote", False):
        from urllib.parse import urlsplit
        host = (urlsplit(endpoint).hostname or "").lower()
        if host not in {"localhost", "127.0.0.1", "::1"}:
            errors.append("remote embeddings require embeddings.allow_remote=true")
    return errors


def save_config(path: Path, data: dict[str, Any]) -> None:
    errors = validate_config(data)
    if errors:
        raise ValueError("; ".join(errors))
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    # JSON is a strict, deterministic subset of YAML and remains human-readable.
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def load_config(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_config(data)
    if errors:
        raise ValueError("; ".join(errors))
    return data


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"unsafe existing vault file: {path}")
        path.chmod(0o600)
        return False
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return True


def parse_yaml_scalar(value: str) -> str:
    value = value.strip()
    quote: str | None = None
    escaped = False
    for index, char in enumerate(value):
        if quote:
            if quote == '"' and char == "\\" and not escaped:
                escaped = True
                continue
            if char == quote and not escaped:
                quote = None
            escaped = False
            continue
        if char in {"'", '"'} and index == 0:
            quote = char
        elif char == "#" and index > 0 and value[index - 1].isspace():
            value = value[:index].rstrip()
            break
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    meta: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" in line and not line.lstrip().startswith("-"):
            key, value = line.split(":", 1)
            meta[key.strip()] = parse_yaml_scalar(value)
    return meta, text[end + 5:]


def note_is_restricted(path: Path) -> bool:
    try:
        meta, _ = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False
    sensitivity = meta.get("sensitivity", "internal").lower()
    return sensitivity not in {"public", "internal"}


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "note"


def fts5_available() -> bool:
    try:
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE probe USING fts5(body)")
        con.close()
        return True
    except sqlite3.DatabaseError:
        return False
