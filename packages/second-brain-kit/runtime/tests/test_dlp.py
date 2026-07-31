from __future__ import annotations

import sys
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from brain_mcp.dlp import DECISION_DENIED, DECISION_ELIGIBLE, DECISION_REVIEW, assess_content, sanitize_decision


def test_heuristic_pii_requires_review() -> None:
    decision = assess_content("Contact support@example.com for access details")
    assert decision.decision == DECISION_REVIEW
    assert decision.reason == "heuristic_pii"


def test_secret_shape_is_denied() -> None:
    decision = assess_content("api-token sk_" + "a" * 24)
    assert decision.decision == DECISION_DENIED
    assert decision.reason == "secret_shape"


def test_normal_synthetic_content_is_eligible() -> None:
    decision = assess_content("This synthetic note describes a public design decision.")
    assert decision.decision == DECISION_ELIGIBLE
    assert decision.reason == "content_clean"


def test_decision_exposes_no_raw_match() -> None:
    source = "Contact support@example.com for access details"
    public = sanitize_decision(assess_content(source))
    assert source not in repr(public)
    assert "support@example.com" not in repr(public)
