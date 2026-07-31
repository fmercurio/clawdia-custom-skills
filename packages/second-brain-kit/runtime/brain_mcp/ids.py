"""Canonical identity helpers for synthetic note records."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{1,126}[a-z0-9])$")
SECTION_PATTERN = re.compile(r"^[a-z0-9._-]{1,64}$")


class IdError(ValueError):
    """Raised when a note id or section reference is malformed."""


def validate_note_id(value: Any) -> str:
    if not isinstance(value, str):
        raise IdError("note id must be a string")
    normalized = value.strip()
    if not ID_PATTERN.fullmatch(normalized):
        raise IdError("note id must be 3 to 128 chars of [a-z0-9._-]")
    return normalized


def validate_section_ref(value: Any) -> str:
    if not isinstance(value, str):
        raise IdError("section_ref must be a string")
    normalized = value.strip()
    if normalized in {".", ".."} or not SECTION_PATTERN.fullmatch(normalized):
        raise IdError("section_ref must be 1 to 64 chars of [a-z0-9._-]")
    return normalized


def canonical_reference(note_id: str, section_ref: str | None = None) -> str:
    validated_note_id = validate_note_id(note_id)
    if section_ref is None:
        return validated_note_id
    return f"{validated_note_id}#{validate_section_ref(section_ref)}"


def extract_note_id(record: Mapping[str, Any]) -> str:
    frontmatter = record.get("frontmatter")
    if not isinstance(frontmatter, Mapping):
        raise IdError("frontmatter mapping is required")
    raw_note_id = frontmatter.get("id")
    return validate_note_id(raw_note_id)


def content_hash(content: str | bytes) -> str:
    if isinstance(content, str):
        content_bytes = content.encode("utf-8")
    elif isinstance(content, bytes):
        content_bytes = content
    else:
        raise IdError("content must be a string or bytes")
    return hashlib.sha256(content_bytes).hexdigest()
