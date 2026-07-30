from __future__ import annotations

import sys
from pathlib import Path

import pytest

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from brain_mcp.policy import RuntimePolicy


def policy_payload() -> dict:
    return {
        "schema_version": "v0.2",
        "contract_version": "v0.2",
        "policy_id": "policy-test-001",
        "policy_version": "v1",
        "allowed_domains": ["engineering", "research", "product"],
        "allowed_classifications": ["public", "internal"],
        "allowed_sensitivities": ["low", "medium"],
        "default_decision": "allow",
    }


def test_strict_parse_and_snapshot_fields() -> None:
    parsed = RuntimePolicy.parse(policy_payload())
    assert parsed.schema_version == "v0.2"
    assert parsed.contract_version == "v0.2"
    assert parsed.policy_id == "policy-test-001"
    assert parsed.policy_version == "v1"
    assert parsed.allowed_domains == ("engineering", "research", "product")
    assert parsed.snapshot()["policy_id"] == "policy-test-001"


def test_parse_rejects_missing_mandatory_fields() -> None:
    base = policy_payload()
    for key in [
        "schema_version",
        "contract_version",
        "policy_id",
        "policy_version",
        "allowed_domains",
        "allowed_classifications",
        "allowed_sensitivities",
        "default_decision",
    ]:
        candidate = dict(base)
        candidate.pop(key)
        with pytest.raises(ValueError):
            RuntimePolicy.parse(candidate)


def test_parse_rejects_malformed_fields() -> None:
    base = policy_payload()
    for value in ["x", 1, {}, []]:
        candidate = dict(base)
        candidate["schema_version"] = value
        with pytest.raises(ValueError):
            RuntimePolicy.parse(candidate)

    bad_types = dict(base)
    bad_types["allowed_domains"] = "engineering"
    with pytest.raises(ValueError):
        RuntimePolicy.parse(bad_types)


def test_evaluate_fail_closed_for_invalid_metadata_and_policy_rules() -> None:
    parsed = RuntimePolicy.parse(policy_payload())
    ok = parsed.evaluate({"domain": "engineering", "classification": "public", "sensitivity": "low"})
    assert ok.allowed
    assert ok.reason == "policy_allowed"

    denied_domain = parsed.evaluate({"domain": "finance", "classification": "public", "sensitivity": "low"})
    assert denied_domain.allowed is False
    assert denied_domain.reason == "policy_domain_denied"

    denied_classification = parsed.evaluate({"domain": "engineering", "classification": "restricted", "sensitivity": "low"})
    assert denied_classification.allowed is False
    assert denied_classification.reason == "policy_classification_denied"

    denied_sensitivity = parsed.evaluate({"domain": "engineering", "classification": "public", "sensitivity": "critical"})
    assert denied_sensitivity.allowed is False
    assert denied_sensitivity.reason == "policy_sensitivity_denied"

    denied_missing = parsed.evaluate({"domain": "engineering", "classification": "public"})
    assert denied_missing.allowed is False
    assert denied_missing.reason == "policy_metadata_invalid"
