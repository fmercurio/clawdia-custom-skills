"""Small stdlib-only security boundaries for future caller migration.

This module intentionally contains no product defaults. Callers must supply
their own resource budgets, approved origins, and granted capabilities.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
import re
import stat
from typing import Iterable
from urllib.parse import urlsplit


class BoundaryError(ValueError):
    """Raised before a sensitive operation crosses its security boundary."""


@dataclass(frozen=True)
class ResourceBudget:
    max_bytes: int
    max_items: int

    def __post_init__(self) -> None:
        if self.max_bytes < 1 or self.max_items < 1:
            raise BoundaryError("resource budgets must be positive")


_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


def validate_service_identifier(value: object) -> str:
    """Return a portable identifier safe for service labels and filenames."""
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise BoundaryError("service identifier must be lowercase alphanumeric with optional hyphens")
    return value


def admit_payload(*, byte_count: int, item_count: int, budget: ResourceBudget) -> None:
    """Reject resource usage before a parser or buffer materializes input."""
    if byte_count < 0 or item_count < 0:
        raise BoundaryError("payload counts must not be negative")
    if byte_count > budget.max_bytes:
        raise BoundaryError("payload exceeds byte budget")
    if item_count > budget.max_items:
        raise BoundaryError("payload exceeds item budget")


def validate_public_https_origin(
    url: str,
    *,
    allowed_origins: Iterable[tuple[str, int]],
    resolved_addresses: Iterable[str],
) -> str:
    """Validate a pinned HTTPS destination after the caller resolves the host."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or not parsed.hostname:
        raise BoundaryError("origin must be credential-free HTTPS")
    port = parsed.port or 443
    allowed = {(host.lower(), allowed_port) for host, allowed_port in allowed_origins}
    if (parsed.hostname.lower(), port) not in allowed:
        raise BoundaryError("origin is not approved")
    addresses = tuple(resolved_addresses)
    if not addresses:
        raise BoundaryError("origin requires resolved addresses")
    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError as exc:
            raise BoundaryError("origin has an invalid resolved address") from exc
        if not parsed_address.is_global:
            raise BoundaryError("origin resolved to a non-public address")
    return parsed.hostname.lower()


def require_capability(capability: str, granted: Iterable[str]) -> None:
    """Require an exact, explicit capability rather than a convenience flag."""
    if capability not in set(granted):
        raise BoundaryError(f"missing required capability: {capability}")


def _safe_relative_parts(relative: Path) -> tuple[str, ...]:
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise BoundaryError("path must be a non-empty relative path without traversal")
    return relative.parts


def _directory_flags() -> int:
    if os.open not in os.supports_dir_fd or os.mkdir not in os.supports_dir_fd:
        raise OSError("secure filesystem operations require directory-relative support")
    return os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


def _open_directory_beneath(root: Path, parts: tuple[str, ...], *, create: bool) -> tuple[Path, int]:
    root = root.expanduser().resolve(strict=True)
    flags = _directory_flags()
    current_fd = os.open(root, flags)
    try:
        for part in parts:
            try:
                next_fd = os.open(part, flags, dir_fd=current_fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, mode=0o700, dir_fd=current_fd)
                next_fd = os.open(part, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
    except Exception:
        os.close(current_fd)
        raise
    return root, current_fd


def ensure_directory_beneath(root: Path, relative: Path) -> Path:
    """Create a private directory chain beneath ``root`` without following links."""
    parts = _safe_relative_parts(relative)
    resolved_root, directory_fd = _open_directory_beneath(root, parts, create=True)
    os.close(directory_fd)
    return resolved_root.joinpath(*parts)


def safe_read_bytes_beneath(root: Path, relative: Path) -> bytes:
    """Read one regular file below ``root`` without following a leaf or parent link."""
    parts = _safe_relative_parts(relative)
    resolved_root, directory_fd = _open_directory_beneath(root, parts[:-1], create=False)
    del resolved_root
    try:
        file_fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
        try:
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise BoundaryError("source is not a regular file")
            with os.fdopen(file_fd, "rb", closefd=False) as stream:
                return stream.read()
        finally:
            os.close(file_fd)
    finally:
        os.close(directory_fd)


def safe_rename_directory_beneath(root: Path, source: Path, destination: Path) -> Path:
    """Atomically rename a directory inside ``root`` without traversing linked parents."""
    source_parts = _safe_relative_parts(source)
    destination_parts = _safe_relative_parts(destination)
    resolved_root, source_parent_fd = _open_directory_beneath(root, source_parts[:-1], create=False)
    try:
        _destination_root, destination_parent_fd = _open_directory_beneath(root, destination_parts[:-1], create=False)
        try:
            source_mode = os.stat(source_parts[-1], dir_fd=source_parent_fd, follow_symlinks=False).st_mode
            if not stat.S_ISDIR(source_mode):
                raise BoundaryError("source is not a directory")
            try:
                os.stat(destination_parts[-1], dir_fd=destination_parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise BoundaryError("destination already exists")
            os.rename(
                source_parts[-1],
                destination_parts[-1],
                src_dir_fd=source_parent_fd,
                dst_dir_fd=destination_parent_fd,
            )
        finally:
            os.close(destination_parent_fd)
    finally:
        os.close(source_parent_fd)
    return resolved_root.joinpath(*destination_parts)


def safe_write_bytes_beneath(
    root: Path,
    relative: Path,
    content: bytes,
    *,
    mode: int = 0o600,
    overwrite: bool = False,
) -> Path:
    """Write a regular file below an existing root without following links."""
    parts = _safe_relative_parts(relative)
    root, current_fd = _open_directory_beneath(root, parts[:-1], create=True)
    try:
        flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        flags |= os.O_TRUNC if overwrite else os.O_EXCL
        file_fd = os.open(parts[-1], flags, mode, dir_fd=current_fd)
        try:
            if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                raise BoundaryError("destination is not a regular file")
            os.fchmod(file_fd, mode)
            with os.fdopen(file_fd, "wb", closefd=False) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(file_fd)
        finally:
            os.close(file_fd)
    finally:
        os.close(current_fd)
    return root.joinpath(*parts)
