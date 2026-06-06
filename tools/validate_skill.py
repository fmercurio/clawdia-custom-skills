#!/usr/bin/env python3
"""Validate a SKILL.md file against Hermes authoring conventions.

Usage:
    python validate_skill.py path/to/SKILL.md [--json]

Checks:
    - Frontmatter starts with --- at byte 0
    - Frontmatter contains name and description
    - name ≤64 chars, lowercase+hyphens
    - description ≤1024 chars
    - Body non-empty after closing ---
    - Total file ≤100,000 chars

No external dependencies (PyYAML not required).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_SKILL_CHARS = 100_000


def extract_yaml_value(text: str, key: str) -> str | None:
    """Extract a scalar value from simple YAML frontmatter without PyYAML."""
    # Handle quoted strings (single or double)
    m = re.search(rf'{key}:\s*"((?:[^"\\]|\\.)*)"', text)
    if m:
        return m.group(1)
    m = re.search(rf"{key}:\s*'((?:[^'\\]|\\.)*)'", text)
    if m:
        return m.group(1)
    # Handle unquoted scalars
    m = re.search(rf"{key}:\s*(\S+)", text)
    if m:
        return m.group(1)
    return None


def validate(path: str) -> dict:
    p = Path(path)
    errors = []
    warnings = []

    if not p.exists():
        return {"valid": False, "errors": [f"File not found: {p}"], "warnings": []}

    content = p.read_text(encoding="utf-8")
    size = len(content)

    # Check starts with ---
    if not content.startswith("---"):
        errors.append("Frontmatter must start with '---' at byte 0 (no leading blank lines or BOM)")

    # Find closing ---
    m = re.search(r"\n---\s*\n", content[3:])
    if not m:
        errors.append("Could not find closing '---' after frontmatter")
        return {"valid": False, "errors": errors, "warnings": warnings, "size": size}

    fm_text = content[3:m.start() + 3]
    body = content[m.end():]

    # name
    name = extract_yaml_value(fm_text, "name") or ""
    if not name:
        errors.append("Missing 'name' field")
    else:
        if len(name) > MAX_NAME_LENGTH:
            errors.append(f"'name' exceeds {MAX_NAME_LENGTH} chars: {len(name)}")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name):
            warnings.append(f"'name' contains unexpected characters: {name!r}")

    # description
    desc = extract_yaml_value(fm_text, "description") or ""
    if not desc:
        errors.append("Missing 'description' field")
    else:
        if len(desc) > MAX_DESCRIPTION_LENGTH:
            errors.append(f"'description' exceeds {MAX_DESCRIPTION_LENGTH} chars: {len(desc)}")

    # body
    if not body.strip():
        errors.append("Body is empty after frontmatter")

    # total size
    if size > MAX_SKILL_CHARS:
        errors.append(f"File exceeds {MAX_SKILL_CHARS} chars: {size}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "name": name,
        "description_length": len(desc),
        "body_length": len(body),
        "size": size,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: validate_skill.py <path-to-SKILL.md> [--json]", file=sys.stderr)
        return 1

    path = sys.argv[1]
    as_json = "--json" in sys.argv

    result = validate(path)

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        if result["valid"]:
            print(f"✅ {path} — VALID")
            for w in result.get("warnings", []):
                print(f"  ⚠️  {w}")
        else:
            print(f"❌ {path} — INVALID")
            for e in result["errors"]:
                print(f"  ❌ {e}")
            for w in result.get("warnings", []):
                print(f"  ⚠️  {w}")

    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
