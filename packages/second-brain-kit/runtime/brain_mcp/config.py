"""Configuration and contract helpers for v0.2 synthetic runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


CONTRACT_VERSION = "v0.2"

EVIDENCE_STATUS_OK = "ok"
EVIDENCE_STATUS_NO_EVIDENCE = "no_evidence"
EVIDENCE_STATUS_DENIED = "denied"
EVIDENCE_STATUS_STALE = "stale"
EVIDENCE_STATUS_ERROR = "error"
EVIDENCE_CONFIDENCE_EXPLICIT = "explicit"
EVIDENCE_CONFIDENCE_INFERRED = "inferred"
EVIDENCE_CONFIDENCE_UNKNOWN = "unknown"
EVIDENCE_CONFIDENCE_VALUES = (
    EVIDENCE_CONFIDENCE_EXPLICIT,
    EVIDENCE_CONFIDENCE_INFERRED,
    EVIDENCE_CONFIDENCE_UNKNOWN,
)
EVIDENCE_STATUSES = (
    EVIDENCE_STATUS_OK,
    EVIDENCE_STATUS_NO_EVIDENCE,
    EVIDENCE_STATUS_DENIED,
    EVIDENCE_STATUS_STALE,
    EVIDENCE_STATUS_ERROR,
)

DEFAULT_RETRIEVAL_MODE = "lexical"
DEFAULT_SEARCH_LIMIT = 8
DEFAULT_PULL_LIMIT = 20
DEFAULT_MAX_LIMIT = 20
DEFAULT_MAX_READ_CHARS = 50000


def _to_sequence(value: Any) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    return tuple(value)


@dataclass(frozen=True)
class RuntimeConfig:
    """Small immutable v0.2 runtime configuration."""

    policy: Any
    records: tuple[Mapping[str, Any], ...] = ()
    retrieval_mode: str = DEFAULT_RETRIEVAL_MODE
    search_limit: int = DEFAULT_SEARCH_LIMIT
    pull_limit: int = DEFAULT_PULL_LIMIT
    max_read_chars: int = DEFAULT_MAX_READ_CHARS

    def __init__(
        self,
        *,
        policy: Any,
        records: Sequence[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = (),
        retrieval_mode: str = DEFAULT_RETRIEVAL_MODE,
        search_limit: int = DEFAULT_SEARCH_LIMIT,
        pull_limit: int = DEFAULT_PULL_LIMIT,
        max_read_chars: int = DEFAULT_MAX_READ_CHARS,
    ):
        if policy is None:
            raise ValueError("policy is required for synthetic v0.2 runtime")
        if retrieval_mode != DEFAULT_RETRIEVAL_MODE:
            raise ValueError("retrieval_mode must be lexical for v0.2")
        if search_limit < 1 or search_limit > DEFAULT_MAX_LIMIT:
            raise ValueError("search_limit must be within [1,20]")
        if pull_limit < 1 or pull_limit > DEFAULT_MAX_LIMIT:
            raise ValueError("pull_limit must be within [1,20]")
        if max_read_chars < 1:
            raise ValueError("max_read_chars must be positive")

        object.__setattr__(self, "policy", policy)
        object.__setattr__(self, "records", _to_sequence(records))
        object.__setattr__(self, "retrieval_mode", retrieval_mode)
        object.__setattr__(self, "search_limit", search_limit)
        object.__setattr__(self, "pull_limit", pull_limit)
        object.__setattr__(self, "max_read_chars", max_read_chars)

    @classmethod
    def with_policy_data(
        cls,
        *,
        policy_data: Mapping[str, Any],
        records: Sequence[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = (),
    ) -> "RuntimeConfig":
        from .policy import RuntimePolicy

        return cls(
            policy=RuntimePolicy.parse(policy_data),
            records=_to_sequence(records),
        )


def policy_summary(policy: Any) -> dict[str, str]:
    return {
        "policy_id": str(getattr(policy, "policy_id", "unknown")),
        "policy_version": str(getattr(policy, "policy_version", "unknown")),
        "contract_version": str(getattr(policy, "contract_version", CONTRACT_VERSION)),
    }


def contract_payload(
    *,
    status: str,
    resolved_intent: str,
    results: Sequence[Any] | None,
    citations: Sequence[Any] | None,
    classification: str | None = None,
    state: str | None = None,
    confidence: str = EVIDENCE_CONFIDENCE_UNKNOWN,
    selected_because: str = "",
    limits: Mapping[str, Any] | None = None,
    warnings: Sequence[str] | None = None,
    policy: Any = None,
    retrieval_mode: str = DEFAULT_RETRIEVAL_MODE,
) -> dict[str, Any]:
    if status not in EVIDENCE_STATUSES:
        raise ValueError(f"unsupported contract status: {status}")
    if confidence not in EVIDENCE_CONFIDENCE_VALUES:
        raise ValueError(f"unsupported evidence confidence: {confidence}")

    return {
        "status": status,
        "contract_version": CONTRACT_VERSION,
        "resolved_intent": resolved_intent,
        "classification": classification,
        "state": state or status,
        "confidence": confidence,
        "selected_because": selected_because,
        "results": list(results or ()),
        "citations": list(citations or ()),
        "limits": dict(limits or {}),
        "warnings": list(warnings or ()),
        "policy": policy_summary(policy),
        "retrieval_mode": retrieval_mode,
    }


def contract_error_payload(
    *,
    resolved_intent: str,
    policy: Any,
    retrieval_mode: str,
    warnings: Sequence[str] | None = None,
    limits: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return contract_payload(
        status=EVIDENCE_STATUS_ERROR,
        resolved_intent=resolved_intent,
        results=(),
        citations=(),
        classification=None,
        state=EVIDENCE_STATUS_ERROR,
        confidence=EVIDENCE_CONFIDENCE_UNKNOWN,
        selected_because="internal_error",
        limits=limits or {},
        warnings=list(warnings or ["internal_error"]),
        policy=policy,
        retrieval_mode=retrieval_mode,
    )
