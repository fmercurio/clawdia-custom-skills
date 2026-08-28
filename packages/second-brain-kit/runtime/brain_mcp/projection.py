"""Strict parser for externally supplied tenant projection manifests.

The parser is intentionally stdlib-only: it accepts JSON documents only and
validates the record schema into fully-typed runtime payloads.
"""
from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .ids import validate_note_id, validate_section_ref

MANIFEST_SCHEMA_VERSION = "v0.2"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 1000
MAX_SECTIONS_PER_RECORD = 64
MAX_STRING_CHARS = 50_000
MAX_TOTAL_STRING_CHARS = 2_000_000

MANIFEST_FIELDS = {
    "manifest_version",
    "identity",
    "generation",
    "records",
}
PROVENANCE_FIELDS = frozenset({"generated_by", "source"})
FRESHNESS_FIELDS = frozenset({"updated_at"})
RECORD_FIELDS = {
    "canonical_id",
    "domain",
    "classification",
    "sensitivity",
    "mcp_eligible",
    "mcp_projection",
    "provenance",
    "freshness",
}
REQUIRED_PROJECTION_FIELD = (
    "content",
    "body",
    "text",
)
_RFC3339_UTC_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)


def parse_rfc3339_utc(value: Any, field: str = "timestamp") -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an RFC3339 UTC timestamp")
    normalized = value.strip()
    if not _RFC3339_UTC_TIMESTAMP.fullmatch(normalized):
        raise ValueError(f"{field} must be an RFC3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(normalized[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be an RFC3339 UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ValueError(f"{field} must be an RFC3339 UTC timestamp")
    return parsed



def _as_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _as_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


@dataclass
class _StringBudget:
    total_chars: int = 0

    def consume(self, value: str, field: str) -> str:
        if len(value) > MAX_STRING_CHARS:
            raise ValueError(f"{field} exceeds string limit of {MAX_STRING_CHARS}")
        self.total_chars += len(value)
        if self.total_chars > MAX_TOTAL_STRING_CHARS:
            raise ValueError(
                f"manifest exceeds aggregate string limit of {MAX_TOTAL_STRING_CHARS}"
            )
        return value


def _as_str(value: Any, field: str, budget: _StringBudget) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    budget.consume(value, field)
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _validate_no_path_shape(value: str, field: str) -> None:
    if value.startswith(("/", "\\")):
        raise ValueError(f"{field} must not be absolute")
    if value.lower().startswith("file:"):
        raise ValueError(f"{field} must not include file scheme references")
    if "/" in value or "\\" in value:
        raise ValueError(f"{field} must not include path separators")
    lowered = value.lower()
    if "../" in lowered or lowered.startswith("../") or lowered == "..":
        raise ValueError(f"{field} contains path traversal")
    if "://" in value:
        raise ValueError(f"{field} contains non-tenant path reference syntax")
    if any(ch in value for ch in ("\\", "?", "*", "<", ">", "|") ):
        raise ValueError(f"{field} contains unsupported reference characters")
    if "file" in field.lower() and value.startswith("file:"):
        raise ValueError(f"{field} must not include file scheme")


def _ensure_scalar_mapping(
    field_name: str,
    value: Any,
    allowed_fields: frozenset[str],
    budget: _StringBudget,
) -> dict[str, Any]:
    raw = _as_mapping(value, field_name)
    unexpected = set(raw.keys()) - allowed_fields
    if unexpected:
        raise ValueError(f"{field_name} contains unknown fields: {', '.join(sorted(unexpected))}")
    payload: dict[str, Any] = {}
    for key, val in raw.items():
        if not isinstance(key, str):
            raise ValueError(f"{field_name} keys must be strings")
        normalized = key.strip()
        if not normalized:
            raise ValueError(f"{field_name} key must not be empty")
        payload[normalized] = val
        if isinstance(val, (Mapping, Sequence)) and not isinstance(val, (str, bytes)):
            raise ValueError(f"{field_name}.{normalized} must be scalar")
        if isinstance(val, str):
            budget.consume(val, f"{field_name}.{normalized}")
            _validate_no_path_shape(val.strip(), f"{field_name}.{normalized}")
    return payload


def _ensure_projection_payload(
    value: Any,
    budget: _StringBudget,
) -> tuple[str, dict[str, str], str | None]:
    projection = _as_mapping(value, "mcp_projection")
    extra = set(projection.keys()) - {"title", "sections", *REQUIRED_PROJECTION_FIELD}
    if extra:
        raise ValueError(f"mcp_projection has unknown fields: {', '.join(sorted(extra))}")

    content: str | None = None
    for candidate in REQUIRED_PROJECTION_FIELD:
        if candidate not in projection:
            continue
        normalized = _as_str(
            projection[candidate],
            f"mcp_projection.{candidate}",
            budget,
        )
        if content is None:
            content = normalized
    if content is None:
        raise ValueError("mcp_projection requires one of content, body, or text")

    title = None
    if "title" in projection:
        title = _as_str(projection["title"], "mcp_projection.title", budget)

    sections: dict[str, str] = {}
    if "sections" in projection:
        raw_sections = _as_mapping(projection["sections"], "mcp_projection.sections")
        if len(raw_sections) > MAX_SECTIONS_PER_RECORD:
            raise ValueError(
                f"mcp_projection.sections exceed section limit of {MAX_SECTIONS_PER_RECORD}"
            )
        for key, section_value in raw_sections.items():
            normalized_key = validate_section_ref(
                _as_str(key, "mcp_projection.sections key", budget)
            )
            normalized_value = _as_str(
                section_value,
                f"mcp_projection.sections.{normalized_key}",
                budget,
            )
            sections[normalized_key] = normalized_value

    return content, sections, title


@dataclass(frozen=True)
class ProjectionRecord:
    canonical_id: str
    domain: str
    classification: str
    sensitivity: str
    mcp_projection_content: str
    provenance: dict[str, Any]
    freshness: dict[str, Any]
    sections: dict[str, str]
    title: str | None


@dataclass(frozen=True)
class ProjectionManifest:
    identity: str
    manifest_version: str
    generation: int
    records: tuple[ProjectionRecord, ...]


def parse_projection_manifest_payload(payload: Mapping[str, Any]) -> ProjectionManifest:
    if not isinstance(payload, Mapping):
        raise ValueError("manifest must be a JSON object")

    manifest_keys = set(payload.keys())
    if manifest_keys != MANIFEST_FIELDS:
        missing = MANIFEST_FIELDS - manifest_keys
        extra = manifest_keys - MANIFEST_FIELDS
        if missing:
            raise ValueError(f"manifest missing fields: {', '.join(sorted(missing))}")
        raise ValueError(f"manifest has unknown fields: {', '.join(sorted(extra))}")

    records_payload = payload["records"]
    if not isinstance(records_payload, Sequence) or isinstance(records_payload, (str, bytes, bytearray)):
        raise ValueError("records must be a list")
    if not records_payload:
        raise ValueError("records must contain at least one record")
    if len(records_payload) > MAX_RECORDS:
        raise ValueError(f"records exceed record limit of {MAX_RECORDS}")

    budget = _StringBudget()
    manifest_version = _as_str(payload["manifest_version"], "manifest_version", budget)
    if manifest_version != MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"manifest_version must be {MANIFEST_SCHEMA_VERSION}")

    identity = _as_str(payload["identity"], "identity", budget)
    _validate_no_path_shape(identity, "identity")
    generation = _as_int(payload["generation"], "generation")

    records: list[ProjectionRecord] = []
    seen_ids: set[str] = set()
    for raw in records_payload:
        record = _as_mapping(raw, "record")
        record_keys = set(record.keys())
        if record_keys != RECORD_FIELDS:
            missing = RECORD_FIELDS - record_keys
            extra = record_keys - RECORD_FIELDS
            if missing:
                raise ValueError(f"record missing fields: {', '.join(sorted(missing))}")
            raise ValueError(f"record has unknown fields: {', '.join(sorted(extra))}")

        canonical_id = validate_note_id(
            _as_str(record["canonical_id"], "canonical_id", budget)
        )
        if canonical_id in seen_ids:
            raise ValueError(f"duplicate canonical_id: {canonical_id}")
        seen_ids.add(canonical_id)

        sensitivity = _as_str(record["sensitivity"], "sensitivity", budget).lower()
        if sensitivity == "restricted":
            raise ValueError(f"record {canonical_id} is restricted")
        classification = _as_str(record["classification"], "classification", budget).lower()
        if classification == "restricted":
            raise ValueError(f"record {canonical_id} is restricted")
        if not _as_bool(record["mcp_eligible"], "mcp_eligible"):
            raise ValueError(f"record {canonical_id} is not mcp-eligible")

        domain = _as_str(record["domain"], "domain", budget).lower()
        projection_content, sections, title = _ensure_projection_payload(
            record["mcp_projection"], budget
        )
        provenance = _ensure_scalar_mapping(
            "provenance", record["provenance"], PROVENANCE_FIELDS, budget
        )
        freshness = _ensure_scalar_mapping(
            "freshness", record["freshness"], FRESHNESS_FIELDS, budget
        )
        if "updated_at" in freshness:
            parse_rfc3339_utc(freshness["updated_at"], "freshness.updated_at")

        records.append(
            ProjectionRecord(
                canonical_id=canonical_id,
                domain=domain,
                classification=classification,
                sensitivity=sensitivity,
                mcp_projection_content=projection_content,
                provenance=provenance,
                freshness=freshness,
                sections=sections,
                title=title,
            )
        )

    return ProjectionManifest(
        identity=identity,
        manifest_version=manifest_version,
        generation=generation,
        records=tuple(records),
    )


def _manifest_open_flags() -> tuple[int, int]:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise ValueError("secure manifest path traversal is unavailable on this platform")
    return os.O_RDONLY | nofollow, os.O_RDONLY | directory | nofollow


def _open_manifest_descriptor(manifest_path: Path, trusted_root: Path | None) -> int:
    file_flags, directory_flags = _manifest_open_flags()
    if trusted_root is None:
        if manifest_path.is_symlink():
            raise ValueError(f"manifest path must not be a symlink: {manifest_path}")
        try:
            return os.open(manifest_path, file_flags)
        except OSError as exc:
            raise ValueError(f"manifest path must be a readable regular file: {manifest_path}") from exc

    root = Path(trusted_root).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    candidate = Path(manifest_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("manifest path must remain beneath its trusted root") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("manifest path must be a non-empty trusted-root-relative path")

    try:
        current_fd = os.open(root, directory_flags)
    except OSError as exc:
        raise ValueError(f"trusted manifest root must be a real directory: {root}") from exc
    try:
        for part in relative.parts[:-1]:
            try:
                next_fd = os.open(part, directory_flags, dir_fd=current_fd)
            except OSError as exc:
                raise ValueError("manifest path must not traverse a symlinked ancestor") from exc
            os.close(current_fd)
            current_fd = next_fd
        try:
            return os.open(relative.parts[-1], file_flags, dir_fd=current_fd)
        except OSError as exc:
            raise ValueError("manifest path must be a readable regular file beneath its trusted root") from exc
    finally:
        os.close(current_fd)


def parse_projection_manifest(
    path: str | Path,
    *,
    trusted_root: str | Path | None = None,
) -> ProjectionManifest:
    manifest_path = Path(path)
    trusted_root_path = Path(trusted_root) if trusted_root is not None else None
    descriptor = _open_manifest_descriptor(manifest_path, trusted_root_path)
    try:
        file_stat = os.fstat(descriptor)
        file_mode = getattr(file_stat, "st_mode", None)
        if file_mode is not None and not stat.S_ISREG(file_mode):
            raise ValueError("manifest path must be a regular file")
        if file_stat.st_size > MAX_MANIFEST_BYTES:
            raise ValueError(f"manifest exceeds byte limit of {MAX_MANIFEST_BYTES}")
        chunks: list[bytes] = []
        remaining = MAX_MANIFEST_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload_bytes = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(payload_bytes) > MAX_MANIFEST_BYTES:
        raise ValueError(f"manifest exceeds byte limit of {MAX_MANIFEST_BYTES}")
    try:
        payload = payload_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("manifest must be UTF-8 JSON") from exc
    return parse_projection_manifest_payload(json.loads(payload))


def manifest_records_to_core_payload(manifest: ProjectionManifest) -> tuple[dict[str, Any], ...]:
    payload: list[dict[str, Any]] = []
    for record in manifest.records:
        frontmatter = {
            "id": record.canonical_id,
            "domain": record.domain,
            "classification": record.classification,
            "sensitivity": record.sensitivity,
            "provenance": record.provenance,
            "freshness": record.freshness,
        }
        if record.title:
            frontmatter["title"] = record.title
        payload.append(
            {
                "frontmatter": frontmatter,
                "content": record.mcp_projection_content,
                "sections": record.sections,
            }
        )
    return tuple(payload)
