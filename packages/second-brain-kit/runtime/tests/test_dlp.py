from __future__ import annotations

import sys
from pathlib import Path

import pytest

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from brain_mcp.dlp import DECISION_DENIED, DECISION_ELIGIBLE, DECISION_REVIEW, assess_content, sanitize_decision


def test_heuristic_pii_requires_review() -> None:
    decision = assess_content("Contact support@example.com for access details")
    assert decision.decision == DECISION_REVIEW
    assert decision.reason == "heuristic_pii"


@pytest.mark.parametrize(
    "identifier",
    (
        "123.456.789-09",
        "12.345.678/0001-95",
        "12345678909",
        "12345678000195",
    ),
)
def test_brazilian_identifier_shapes_require_review(identifier: str) -> None:
    decision = assess_content(f"synthetic identifier: {identifier}")
    assert decision.decision == DECISION_REVIEW
    assert decision.reason == "heuristic_pii"


def test_secret_shape_is_denied() -> None:
    decision = assess_content("api-token sk_" + "a" * 24)
    assert decision.decision == DECISION_DENIED
    assert decision.reason == "secret_shape"


@pytest.mark.parametrize(
    "synthetic_credential",
    (
        "ghp_" + "g" * 32,
        "github_pat_" + "p" * 24,
        "glpat-" + "l" * 20,
        "xoxb-" + "1" * 12 + "-" + "s" * 12,
        "AIza" + "a" * 32,
        "ASIA" + "A" * 16,
        "sk_live_" + "s" * 24,
        "sk-proj-" + "o" * 24,
        "sk-svcacct-" + "v" * 24,
        "sk-ant-" + "n" * 24,
        "sk-" + "r" * 24,
        "xai-" + "x" * 24,
    ),
)
def test_provider_prefixed_secret_shapes_are_denied(synthetic_credential: str) -> None:
    decision = assess_content(f"synthetic credential: {synthetic_credential}")
    assert decision.decision == DECISION_DENIED
    assert decision.reason == "secret_shape"


@pytest.mark.parametrize(
    "marker",
    (
        "-----BEGIN PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----",
        "-----BEGIN EC PRIVATE KEY-----",
        "-----BEGIN DSA PRIVATE KEY-----",
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        "-----BEGIN ENCRYPTED PRIVATE KEY-----",
        "-----BEGIN PGP PRIVATE KEY BLOCK-----",
    ),
)
def test_private_key_markers_are_denied(marker: str) -> None:
    decision = assess_content(f"{marker}\nsynthetic-key-material-only")
    assert decision.decision == DECISION_DENIED
    assert decision.reason == "secret_shape"


@pytest.mark.parametrize(
    "authorization_context",
    (
        "Authorization: Bearer " + "b" * 24,
        "authorization = 'Basic " + "Y" * 24 + "=='",
        "Proxy-Authorization: Token " + "t" * 24,
        "AUTHORIZATION: ApiKey " + "k" * 24,
        "Authorization: " + "r" * 24,
    ),
)
def test_authorization_contexts_are_denied(authorization_context: str) -> None:
    decision = assess_content(authorization_context)
    assert decision.decision == DECISION_DENIED
    assert decision.reason == "secret_shape"


def test_normal_synthetic_content_is_eligible() -> None:
    decision = assess_content("This synthetic note describes a public design decision.")
    assert decision.decision == DECISION_ELIGIBLE
    assert decision.reason == "content_clean"


@pytest.mark.parametrize(
    "benign_text",
    (
        "Authorization is required for this endpoint.",
        "Use the Authorization header described in the public guide.",
        "The prefix sk- identifies one documented token family.",
        "Example placeholders: xai-REDACTED and ghp_REDACTED.",
        "Do not paste a BEGIN PRIVATE KEY marker here.",
    ),
)
def test_secret_like_documentation_without_secret_material_is_eligible(benign_text: str) -> None:
    decision = assess_content(benign_text)
    assert decision.decision == DECISION_ELIGIBLE
    assert decision.reason == "content_clean"


def test_decision_exposes_no_raw_match() -> None:
    source = "Contact support@example.com for access details"
    public = sanitize_decision(assess_content(source))
    assert source not in repr(public)
    assert "support@example.com" not in repr(public)
