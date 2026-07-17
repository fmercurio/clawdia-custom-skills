#!/usr/bin/env python3
"""Shared stdlib-only helpers for second-brain-kit."""
from __future__ import annotations
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

VERSION = "0.1.0-rc1"
SCHEMA_VERSION = 1
LAYERS = {
    "inbox": "00_Inbox",
    "project": "10_Projects",
    "area": "20_Areas",
    "resource": "30_Resources",
    "archive": "40_Archives",
}
REQUIRED_DIRS = [*LAYERS.values(), "50_Templates", "_Hermes", "_Meta"]
ROOT_DOCS = ["README.md", "MAPA.md", "PARA.md", "HERMES.md"]


def _safe_relative_parts(relative: Path) -> tuple[str, ...]:
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("path must be a non-empty relative path without traversal")
    return relative.parts


def private_directory(root: Path, relative: Path) -> Path:
    """Create or validate an owner-only real directory beneath a trusted root."""
    root = root.expanduser().resolve(strict=True)
    parts = _safe_relative_parts(relative)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlinked directory is not allowed beneath {root}")
        if current.exists() and not current.is_dir():
            raise ValueError(f"directory path is not a directory: {current}")
        current.mkdir(mode=0o700, exist_ok=True)
        if current.is_symlink() or not current.resolve(strict=True).is_relative_to(root):
            raise ValueError(f"directory escapes configured root: {current}")
    current.chmod(0o700)
    return current


def write_text_beneath(
    root: Path,
    relative: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    file_mode: int = 0o666,
) -> Path:
    """Exclusively create a file beneath root without following directory or leaf links."""
    root = root.expanduser().resolve(strict=True)
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
                os.mkdir(part, mode=0o777, dir_fd=current_fd)
                next_fd = os.open(part, directory_flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        file_fd = os.open(parts[-1], flags, file_mode, dir_fd=current_fd)
        with os.fdopen(file_fd, "w", encoding=encoding) as stream:
            stream.write(content)
    finally:
        os.close(current_fd)
    return root.joinpath(*parts)


def hermes_home(value: str | None = None) -> Path:
    return Path(value or os.environ.get("HERMES_HOME", "~/.hermes")).expanduser().resolve()


def profile_name(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", value):
        raise ValueError("profile must be lowercase alphanumeric with optional hyphens")
    return value


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
    path.parent.mkdir(parents=True, exist_ok=True)
    # JSON is a strict, deterministic subset of YAML and remains human-readable.
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


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
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
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
