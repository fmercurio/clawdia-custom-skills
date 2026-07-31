from __future__ import annotations

import pytest

from brain_mcp.projection import (
    ProjectionManifest,
    manifest_records_to_core_payload,
    parse_projection_manifest,
    parse_projection_manifest_payload,
)


def valid_manifest_payload() -> dict:
    return {
        "manifest_version": "v0.2",
        "identity": "tenant-test",
        "generation": 12,
        "records": [
            {
                "canonical_id": "alpha-note",
                "domain": "engineering",
                "classification": "public",
                "sensitivity": "low",
                "mcp_eligible": True,
                "mcp_projection": {
                    "content": "alpha notes",
                    "sections": {
                        "overview": "project summary",
                    },
                    "title": "Alpha",
                },
                "provenance": {
                    "generated_by": "pipeline",
                    "source": "normalized-note-ref",
                },
                "freshness": {
                    "updated_at": "2026-01-01T00:00:00Z",
                },
            }
        ],
    }


def test_parse_projection_manifest_payload_success() -> None:
    manifest = parse_projection_manifest_payload(valid_manifest_payload())
    assert isinstance(manifest, ProjectionManifest)
    assert manifest.manifest_version == "v0.2"
    assert manifest.identity == "tenant-test"
    assert manifest.generation == 12
    assert len(manifest.records) == 1

    record = manifest.records[0]
    assert record.canonical_id == "alpha-note"
    assert record.domain == "engineering"
    assert record.classification == "public"
    assert record.sensitivity == "low"
    assert record.title == "Alpha"
    assert record.mcp_projection_content == "alpha notes"
    assert record.sections == {"overview": "project summary"}
    assert record.provenance == {"generated_by": "pipeline", "source": "normalized-note-ref"}

    payload = manifest_records_to_core_payload(manifest)
    first = payload[0]
    assert first["frontmatter"]["id"] == "alpha-note"
    assert first["frontmatter"]["title"] == "Alpha"
    assert first["frontmatter"]["domain"] == "engineering"
    assert first["content"] == "alpha notes"
    assert first["sections"] == {"overview": "project summary"}


def test_parse_projection_manifest_payload_rejects_unknown_fields() -> None:
    payload = valid_manifest_payload()
    payload["policy_id"] = "surprise"
    with pytest.raises(ValueError, match="unknown fields"):
        parse_projection_manifest_payload(payload)


def test_parse_projection_manifest_payload_rejects_missing_fields() -> None:
    payload = valid_manifest_payload()
    payload.pop("identity")
    with pytest.raises(ValueError, match="manifest missing fields"):
        parse_projection_manifest_payload(payload)


def test_parse_projection_manifest_payload_rejects_duplicate_ids() -> None:
    payload = valid_manifest_payload()
    payload["records"].append(payload["records"][0].copy())
    with pytest.raises(ValueError, match="duplicate canonical_id"):
        parse_projection_manifest_payload(payload)


def test_parse_projection_manifest_payload_rejects_restricted_records() -> None:
    payload = valid_manifest_payload()
    payload["records"][0]["sensitivity"] = "restricted"
    with pytest.raises(ValueError, match="restricted"):
        parse_projection_manifest_payload(payload)

    payload = valid_manifest_payload()
    payload["records"][0]["classification"] = "restricted"
    with pytest.raises(ValueError, match="restricted"):
        parse_projection_manifest_payload(payload)

    payload = valid_manifest_payload()
    payload["records"][0]["mcp_eligible"] = False
    with pytest.raises(ValueError, match="not mcp-eligible"):
        parse_projection_manifest_payload(payload)


def test_parse_projection_manifest_payload_rejects_path_and_ref_patterns() -> None:
    payload = valid_manifest_payload()
    payload["records"][0]["canonical_id"] = "../escape"
    with pytest.raises(ValueError):
        parse_projection_manifest_payload(payload)

    payload = valid_manifest_payload()
    payload["records"][0]["provenance"] = {"source": "file:///etc/passwd"}
    with pytest.raises(ValueError):
        parse_projection_manifest_payload(payload)

    payload = valid_manifest_payload()
    payload["records"][0]["provenance"] = {"source": "notes/foo.md"}
    with pytest.raises(ValueError):
        parse_projection_manifest_payload(payload)

    payload = valid_manifest_payload()
    payload["records"][0]["freshness"] = {"path": "../unsafe"}
    with pytest.raises(ValueError):
        parse_projection_manifest_payload(payload)


def test_parse_projection_manifest_rejects_symlink(tmp_path) -> None:
    target = tmp_path / "manifest.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "manifest-link.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="must not be a symlink"):
        parse_projection_manifest(link)
