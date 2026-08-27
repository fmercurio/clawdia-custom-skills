from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import brain_mcp.projection as projection_module
from brain_mcp.projection import (
    MAX_MANIFEST_BYTES,
    MAX_RECORDS,
    MAX_SECTIONS_PER_RECORD,
    MAX_STRING_CHARS,
    MAX_TOTAL_STRING_CHARS,
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


def test_parse_projection_manifest_payload_rejects_invalid_freshness_timestamp() -> None:
    for timestamp in (
        "2026-01-01",
        "2026-01-01T00:00:00+00:00",
        "not-a-timestamp",
        1,
    ):
        payload = valid_manifest_payload()
        payload["records"][0]["freshness"] = {"updated_at": timestamp}
        with pytest.raises(ValueError, match="RFC3339 UTC timestamp"):
            parse_projection_manifest_payload(payload)


def test_parse_projection_manifest_rejects_symlink(tmp_path) -> None:
    target = tmp_path / "manifest.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "manifest-link.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="must not be a symlink"):
        parse_projection_manifest(link)


def test_parse_projection_manifest_rejects_symlinked_ancestor_under_trusted_root(tmp_path) -> None:
    instance_root = tmp_path / "instance"
    instance_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    external_manifest = outside / "projection-manifest.json"
    external_manifest.write_text(json.dumps(valid_manifest_payload()), encoding="utf-8")
    (instance_root / "nested").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        parse_projection_manifest(
            instance_root / "nested" / "projection-manifest.json",
            trusted_root=instance_root,
        )

    assert external_manifest.read_text(encoding="utf-8") == json.dumps(valid_manifest_payload())


def test_parse_projection_manifest_rejects_growth_after_size_check(
    tmp_path, monkeypatch
) -> None:
    manifest_path = tmp_path / "oversized-manifest.json"
    manifest_path.write_bytes(b"{" + b" " * (MAX_MANIFEST_BYTES + 128))
    monkeypatch.setattr(
        projection_module.os,
        "fstat",
        lambda _descriptor: SimpleNamespace(st_size=0),
    )

    with pytest.raises(ValueError, match="byte limit"):
        parse_projection_manifest(manifest_path)


def test_parse_projection_manifest_payload_rejects_excess_records() -> None:
    payload = valid_manifest_payload()
    base_record = payload["records"][0]
    payload["records"] = [
        {**base_record, "canonical_id": f"note-{index:04d}"}
        for index in range(MAX_RECORDS + 1)
    ]

    with pytest.raises(ValueError, match="record limit"):
        parse_projection_manifest_payload(payload)


def test_parse_projection_manifest_payload_rejects_excess_sections() -> None:
    payload = valid_manifest_payload()
    payload["records"][0]["mcp_projection"]["sections"] = {
        f"section-{index:02d}": "synthetic section"
        for index in range(MAX_SECTIONS_PER_RECORD + 1)
    }

    with pytest.raises(ValueError, match="section limit"):
        parse_projection_manifest_payload(payload)


@pytest.mark.parametrize(
    "target",
    (
        "manifest_version",
        "identity",
        "domain",
        "classification",
        "sensitivity",
        "content",
        "title",
        "section_value",
        "provenance_value",
        "freshness_value",
    ),
)
def test_parse_projection_manifest_payload_rejects_oversized_strings(target: str) -> None:
    payload = valid_manifest_payload()
    oversized = "x" * (MAX_STRING_CHARS + 1)
    record = payload["records"][0]

    if target in {"manifest_version", "identity"}:
        payload[target] = oversized
    elif target in {"domain", "classification", "sensitivity"}:
        record[target] = oversized
    elif target in {"content", "title"}:
        record["mcp_projection"][target] = oversized
    elif target == "section_value":
        record["mcp_projection"]["sections"]["overview"] = oversized
    elif target == "provenance_value":
        record["provenance"]["generated_by"] = oversized
    else:
        record["freshness"]["updated_at"] = oversized

    with pytest.raises(ValueError, match="string limit"):
        parse_projection_manifest_payload(payload)


def test_parse_projection_manifest_payload_rejects_excess_aggregate_text() -> None:
    payload = valid_manifest_payload()
    base_record = payload["records"][0]
    base_projection = base_record["mcp_projection"]
    payload["records"] = [
        {
            **base_record,
            "canonical_id": f"aggregate-{index:02d}",
            "mcp_projection": {
                **base_projection,
                "content": "x" * MAX_STRING_CHARS,
            },
        }
        for index in range(MAX_TOTAL_STRING_CHARS // MAX_STRING_CHARS + 1)
    ]

    with pytest.raises(ValueError, match="aggregate string limit"):
        parse_projection_manifest_payload(payload)


def test_projection_manifest_limits_are_inclusive_for_valid_payloads(tmp_path) -> None:
    payload = valid_manifest_payload()
    payload["records"][0]["mcp_projection"]["content"] = "x" * MAX_STRING_CHARS
    payload["records"][0]["mcp_projection"]["sections"] = {
        f"section-{index:02d}": "synthetic section"
        for index in range(MAX_SECTIONS_PER_RECORD)
    }
    manifest = parse_projection_manifest_payload(payload)
    assert len(manifest.records[0].mcp_projection_content) == MAX_STRING_CHARS
    assert len(manifest.records[0].sections) == MAX_SECTIONS_PER_RECORD

    record_limit_payload = valid_manifest_payload()
    base_record = record_limit_payload["records"][0]
    record_limit_payload["records"] = [
        {**base_record, "canonical_id": f"bounded-{index:04d}"}
        for index in range(MAX_RECORDS)
    ]
    assert len(parse_projection_manifest_payload(record_limit_payload).records) == MAX_RECORDS

    serialized = (
        b'{"manifest_version":"v0.2","identity":"tenant-test","generation":1,"records":['
        b'{"canonical_id":"alpha-note","domain":"engineering","classification":"public",'
        b'"sensitivity":"low","mcp_eligible":true,"mcp_projection":{"content":"ok"},'
        b'"provenance":{},"freshness":{}}]}'
    )
    manifest_path = tmp_path / "max-size-valid.json"
    manifest_path.write_bytes(serialized + b" " * (MAX_MANIFEST_BYTES - len(serialized)))
    assert parse_projection_manifest(manifest_path).identity == "tenant-test"
