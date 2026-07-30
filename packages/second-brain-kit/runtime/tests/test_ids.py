from __future__ import annotations

import hashlib
import sys
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from brain_mcp.ids import (
    IdError,
    canonical_reference,
    content_hash,
    extract_note_id,
    validate_note_id,
    validate_section_ref,
)


def test_note_id_validation_is_strict_and_lowercase() -> None:
    assert validate_note_id("note-alpha_01") == "note-alpha_01"
    for value in ("AA", "ab", "a b", "a*bad", "A-note", ""):
        try:
            validate_note_id(value)
        except IdError:
            pass
        else:
            raise AssertionError(f"expected invalid note id: {value!r}")


def test_section_ref_validation_rejects_dot_and_uppercase() -> None:
    assert validate_section_ref("summary") == "summary"
    for value in ("bad section", "", "A", ".", "..", 10):
        try:
            validate_section_ref(value)
        except IdError:
            pass
        else:
            raise AssertionError(f"expected invalid section ref: {value!r}")


def test_safe_reference_hash_and_frontmatter_identity() -> None:
    assert canonical_reference("note-1", "intro") == "note-1#intro"
    assert canonical_reference("note-1") == "note-1"
    assert content_hash("hello") == hashlib.sha256(b"hello").hexdigest()
    assert content_hash("hello") == content_hash("hello")
    assert extract_note_id({"frontmatter": {"id": "note-1"}}) == "note-1"
    try:
        extract_note_id({"frontmatter": {}})
    except IdError:
        pass
    else:
        raise AssertionError("missing frontmatter id must fail")
