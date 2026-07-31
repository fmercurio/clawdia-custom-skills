from __future__ import annotations

from pathlib import Path
import sys

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from brain_mcp.core import V02Core
from brain_mcp.policy import RuntimePolicy


def policy_data() -> dict:
    return {
        "schema_version": "v0.2",
        "contract_version": "v0.2",
        "policy_id": "test-policy",
        "policy_version": "policy-001",
        "allowed_domains": ["engineering", "research", "product"],
        "allowed_classifications": ["public", "internal"],
        "allowed_sensitivities": ["low", "medium"],
        "default_decision": "allow",
    }


def synthetic_records() -> list[dict]:
    return [
        {
            "frontmatter": {
                "id": "alpha-note",
                "title": "Alpha Note",
                "domain": "engineering",
                "classification": "public",
                "sensitivity": "low",
            },
            "content": "alpha planning update for synthesis",
            "path": "notes/alpha.md",
        },
        {
            "frontmatter": {
                "id": "finance-note",
                "title": "Finance Note",
                "domain": "finance",
                "classification": "public",
                "sensitivity": "low",
            },
            "content": "finance domain guidance for policy tests",
            "path": "notes/finance.md",
        },
        {
            "frontmatter": {
                "id": "pii-note",
                "title": "PII Note",
                "domain": "engineering",
                "classification": "public",
                "sensitivity": "low",
            },
            "content": "contact investigator@example.com for onboarding",
            "path": "notes/pii.md",
        },
        {
            "frontmatter": {
                "id": "mutable-note",
                "title": "Mutable Note",
                "domain": "engineering",
                "classification": "public",
                "sensitivity": "low",
            },
            "content": "mutable text for stale hash checks",
            "path": "notes/mutable.md",
        },
    ]


def make_core() -> tuple[V02Core, list[dict]]:
    records = synthetic_records()
    return V02Core(policy_data(), records), records


def test_search_returns_ok_and_public_only_result_fields() -> None:
    core, _ = make_core()
    response = core.search_brain("planning")
    assert response["status"] == "ok"
    assert response["results"]
    result = response["results"][0]
    assert response["classification"] is None or response["classification"] == "public"
    assert response["state"] == "ok"
    assert response["confidence"] in {"explicit", "inferred"}
    assert response["selected_because"] == "search_query_match"
    assert "note_id" in result
    assert "path" not in result
    assert response["citations"][0]["canonical_ref"] == "alpha-note"
    assert "path" not in response["citations"][0]
    assert response["citations"][0]["classification"] == "public"
    assert response["citations"][0]["confidence"] in {"explicit", "inferred"}


def test_search_no_evidence_when_only_denied_records_match() -> None:
    core, _ = make_core()
    assert "finance-note" not in core._records
    assert "pii-note" not in core._records
    assert "finance-note" in core._blocked_records
    assert "pii-note" in core._blocked_records
    response = core.search_brain("finance")
    assert response["status"] == "no_evidence"
    assert response["results"] == []
    assert response["citations"] == []


def test_read_denied_record_still_redacted() -> None:
    core, _ = make_core()
    response = core.read_brain_note("finance-note")
    assert response["status"] == "denied"
    assert response["classification"] == "public"
    assert response["state"] == "denied"
    assert response["confidence"] in {"explicit", "inferred", "unknown"}
    assert response["results"] == []
    assert response["citations"] == []
    assert "title" not in response
    assert "excerpt" not in response


def test_read_review_record_is_denied_with_generic_reason() -> None:
    core, _ = make_core()
    response = core.read_brain_note("pii-note")
    assert response["status"] == "denied"
    assert response["warnings"] == ["policy_or_dlp_blocked"]
    assert response["results"] == []


def test_read_returns_stale_when_content_mutates() -> None:
    core, records = make_core()
    records[3]["content"] = "mutated content for stale simulation"
    response = core.read_brain_note("mutable-note")
    assert response["status"] == "stale"
    assert "excerpt" not in response


def test_read_returns_stale_when_policy_version_changes() -> None:
    core, _ = make_core()
    altered = policy_data()
    altered["policy_version"] = "policy-999"
    core.policy = RuntimePolicy.parse(altered)
    response = core.read_brain_note("alpha-note")
    assert response["status"] == "stale"
    assert "excerpt" not in response


def test_recheck_policy_at_search_and_read_time() -> None:
    core, records = make_core()
    records[0]["frontmatter"]["sensitivity"] = "critical"

    search = core.search_brain("planning")
    assert search["status"] == "no_evidence"
    assert search["results"] == []
    assert search["citations"] == []

    read = core.read_brain_note("alpha-note")
    assert read["status"] == "denied"
    assert read["results"] == []
    assert read["citations"] == []


def test_error_payload_keeps_the_public_contract_shape() -> None:
    core, _ = make_core()
    response = core.search_brain(None)  # type: ignore[arg-type]
    expected = {
        "status", "contract_version", "resolved_intent", "results", "citations",
        "classification", "state", "confidence", "selected_because", "limits",
        "warnings", "policy", "retrieval_mode",
    }
    assert expected.issubset(response)
    assert response["status"] == "error"
    assert response["results"] == []
    assert response["citations"] == []
    assert response["confidence"] == "unknown"


def test_brain_status_has_snapshot_counts() -> None:
    core, _ = make_core()
    response = core.brain_status()
    assert response["status"] == "ok"
    counts = response["counts"]
    assert counts["total"] == 4
    assert "eligible" in counts and "denied" in counts and "review" in counts and "stale" in counts
    assert counts["eligible"] == 2
    assert counts["denied"] == 1
    assert counts["review"] == 1
    assert counts["stale"] == 0
    assert response["classification"] is None
    assert response["state"] == "ok"
    assert response["confidence"] == "unknown"
    assert "policy_snapshot" in response
    assert response["results"] == []
