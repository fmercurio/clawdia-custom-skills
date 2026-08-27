"""Simple deterministic DLP heuristics for synthetic content."""

from __future__ import annotations

import re
from dataclasses import dataclass

from typing import Any


DECISION_ELIGIBLE = "eligible"
DECISION_REVIEW = "review"
DECISION_DENIED = "denied"

REASON_CLEAN = "content_clean"
REASON_PII = "heuristic_pii"
REASON_SECRET = "secret_shape"


@dataclass(frozen=True)
class DLPDecision:
    decision: str
    reason: str


HEURISTIC_PII_PATTERN = re.compile(
    r"\b(?:"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|"
    r"\d{3}-\d{2}-\d{4}|"
    r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}|"
    r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}"
    r")\b"
)
SECRET_PATTERN = re.compile(r"\b(?:AKIA[0-9A-Z]{16}|"
                           r"sk_[A-Za-z0-9]{24,}|"
                           r"\b[a-zA-Z0-9]{40,}\b)\b")
PROVIDER_SECRET_PATTERN = re.compile(
    r"\b(?:"
    r"(?:AKIA|ASIA)[0-9A-Z]{16}|"
    r"gh[pousr]_[A-Za-z0-9_-]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"glpat-[A-Za-z0-9_-]{16,}|"
    r"xox[baprs]-[A-Za-z0-9-]{20,}|"
    r"AIza[A-Za-z0-9_-]{20,}|"
    r"(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}|"
    r"sk-(?:proj-|svcacct-|ant-)?[A-Za-z0-9_-]{20,}|"
    r"xai-[A-Za-z0-9_-]{20,}"
    r")\b"
)
PRIVATE_KEY_MARKER_PATTERN = re.compile(
    r"-----BEGIN (?:"
    r"(?:RSA|EC|DSA|OPENSSH|ENCRYPTED) PRIVATE KEY|"
    r"PRIVATE KEY|"
    r"PGP PRIVATE KEY BLOCK"
    r")-----",
    re.IGNORECASE,
)
AUTHORIZATION_SECRET_PATTERN = re.compile(
    r"\b(?:proxy-)?authorization\b[ \t]*[:=][ \t]*[\"']?"
    r"(?:(?:bearer|basic|token|api[-_]?key)[ \t]+)?"
    r"[A-Za-z0-9._~+/=-]{12,}",
    re.IGNORECASE,
)


def assess_content(content: str | bytes) -> DLPDecision:
    if isinstance(content, bytes):
        text = content.decode("utf-8", errors="ignore")
    elif isinstance(content, str):
        text = content
    else:
        raise TypeError("content must be a string or bytes")

    if (
        SECRET_PATTERN.search(text)
        or PROVIDER_SECRET_PATTERN.search(text)
        or PRIVATE_KEY_MARKER_PATTERN.search(text)
        or AUTHORIZATION_SECRET_PATTERN.search(text)
    ):
        return DLPDecision(DECISION_DENIED, REASON_SECRET)

    if HEURISTIC_PII_PATTERN.search(text):
        return DLPDecision(DECISION_REVIEW, REASON_PII)

    return DLPDecision(DECISION_ELIGIBLE, REASON_CLEAN)


def sanitize_decision(decision: DLPDecision) -> dict[str, Any]:
    return {"decision": decision.decision, "reason": decision.reason}
