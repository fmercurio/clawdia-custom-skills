"""Strict parser for externally supplied tenant projection manifests.

The parser is intentionally stdlib-only: it accepts JSON documents only and
validates the record schema into fully-typed runtime payloads.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .ids import validate_note_id, validate_section_ref

MANIFEST_SCHEMA_VERSION = "v0.2"

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


def _as_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
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


def _ensure_scalar_mapping(field_name: str, value: Any, allowed_fields: frozenset[str]) -> dict[str, Any]:
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
            _validate_no_path_shape(val.strip(), f"{field_name}.{normalized}")
    return payload


def _ensure_projection_payload(value: Any) -> tuple[str, dict[str, str], str | None]:
    projection = _as_mapping(value, "mcp_projection")
    extra = set(projection.keys()) - {"title", "sections", *REQUIRED_PROJECTION_FIELD}
    if extra:
        raise ValueError(f"mcp_projection has unknown fields: {', '.join(sorted(extra))}")

    content: str | None = None
    for candidate in REQUIRED_PROJECTION_FIELD:
        if candidate not in projection:
            continue
        candidate_value = projection[candidate]
        if not isinstance(candidate_value, str):
            raise ValueError("mcp_projection content must be a string")
        normalized = candidate_value.strip()
        if not normalized:
            raise ValueError("mcp_projection content must not be empty")
        content = normalized
        break
    if content is None:
        raise ValueError("mcp_projection requires one of content, body, or text")

    title = None
    if "title" in projection:
        title = _as_str(projection["title"], "mcp_projection.title")

    sections: dict[str, str] = {}
    if "sections" in projection:
        for key, value in _as_mapping(projection["sections"], "mcp_projection.sections").items():
            normalized_key = validate_section_ref(key)
            if not isinstance(value, str):
                raise ValueError("mcp_projection.sections values must be strings")
            normalized_value = value.strip()
            if not normalized_value:
                raise ValueError("mcp_projection.section value must not be empty")
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

    manifest_version = _as_str(payload["manifest_version"], "manifest_version")
    if manifest_version != MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"manifest_version must be {MANIFEST_SCHEMA_VERSION}")

    identity = _as_str(payload["identity"], "identity")
    _validate_no_path_shape(identity, "identity")

    generation = _as_int(payload["generation"], "generation")

    records_payload = payload["records"]
    if not isinstance(records_payload, Sequence) or isinstance(records_payload, (str, bytes, bytearray)):
        raise ValueError("records must be a list")
    if not records_payload:
        raise ValueError("records must contain at least one record")

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

        canonical_id = validate_note_id(record["canonical_id"])
        if canonical_id in seen_ids:
            raise ValueError(f"duplicate canonical_id: {canonical_id}")
        seen_ids.add(canonical_id)

        sensitivity = _as_str(record["sensitivity"], "sensitivity").lower()
        if sensitivity == "restricted":
            raise ValueError(f"record {canonical_id} is restricted")

        classification = _as_str(record["classification"], "classification").lower()
        if classification == "restricted":
            raise ValueError(f"record {canonical_id} is restricted")

        if not _as_bool(record["mcp_eligible"], "mcp_eligible"):
            raise ValueError(f"record {canonical_id} is not mcp-eligible")

        domain = _as_str(record["domain"], "domain").lower()

        projection_content, sections, title = _ensure_projection_payload(record["mcp_projection"])
        provenance = _ensure_scalar_mapping("provenance", record["provenance"], PROVENANCE_FIELDS)
        freshness = _ensure_scalar_mapping("freshness", record["freshness"], FRESHNESS_FIELDS)

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
        identity=_as_str(payload["identity"], "identity"),
        manifest_version=manifest_version,
        generation=generation,
        records=tuple(records),
    )


def parse_projection_manifest(path: str | Path) -> ProjectionManifest:
    manifest_path = Path(path)
    if manifest_path.is_symlink():
        raise ValueError(f"manifest path must not be a symlink: {manifest_path}")
    payload = manifest_path.read_text(encoding="utf-8")
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
