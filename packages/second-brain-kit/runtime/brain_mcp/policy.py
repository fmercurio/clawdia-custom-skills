"""Deterministic policy parsing and eligibility checks for v0.2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .config import CONTRACT_VERSION


REASON_ALLOWED = "policy_allowed"
REASON_METADATA_INVALID = "policy_metadata_invalid"
REASON_DOMAIN_DENIED = "policy_domain_denied"
REASON_CLASSIFICATION_DENIED = "policy_classification_denied"
REASON_SENSITIVITY_DENIED = "policy_sensitivity_denied"
REASON_DEFAULT_DENIED = "policy_default_denied"

ALLOWED_DECISIONS = {"allow", "deny"}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class RuntimePolicy:
    schema_version: str
    contract_version: str
    policy_id: str
    policy_version: str
    allowed_domains: tuple[str, ...]
    allowed_classifications: tuple[str, ...]
    allowed_sensitivities: tuple[str, ...]
    default_decision: str
    max_record_age_days: int | None

    @classmethod
    def parse(cls, payload: Mapping[str, Any]) -> "RuntimePolicy":
        if not isinstance(payload, Mapping):
            raise ValueError("policy payload must be a mapping")

        schema_version = _as_str(payload, "schema_version")
        contract_version = _as_str(payload, "contract_version")
        policy_id = _as_str(payload, "policy_id")
        policy_version = _as_str(payload, "policy_version")

        if schema_version != CONTRACT_VERSION:
            raise ValueError("schema_version must be v0.2")
        if contract_version != CONTRACT_VERSION:
            raise ValueError("contract_version must be v0.2")
        if not policy_id or not policy_version:
            raise ValueError("policy_id and policy_version are required")

        allowed_domains = _as_str_tuple(payload, "allowed_domains")
        allowed_classifications = _as_str_tuple(payload, "allowed_classifications")
        allowed_sensitivities = _as_str_tuple(payload, "allowed_sensitivities")
        default_decision = _as_str(payload, "default_decision").lower()
        if default_decision not in ALLOWED_DECISIONS:
            raise ValueError("default_decision must be allow or deny")

        max_record_age_days = None
        if "max_record_age_days" in payload:
            max_record_age_days = _as_positive_int(payload["max_record_age_days"], "max_record_age_days")

        return cls(
            schema_version=schema_version,
            contract_version=contract_version,
            policy_id=policy_id,
            policy_version=policy_version,
            allowed_domains=allowed_domains,
            allowed_classifications=allowed_classifications,
            allowed_sensitivities=allowed_sensitivities,
            default_decision=default_decision,
            max_record_age_days=max_record_age_days,
        )

    def evaluate(self, metadata: Mapping[str, Any]) -> PolicyDecision:
        if not isinstance(metadata, Mapping):
            return PolicyDecision(False, REASON_METADATA_INVALID)

        domain = _normalized_value(metadata, "domain")
        classification = _normalized_value(metadata, "classification")
        sensitivity = _normalized_value(metadata, "sensitivity")

        if domain is None or classification is None or sensitivity is None:
            return PolicyDecision(False, REASON_METADATA_INVALID)

        if self.allowed_domains and domain not in self.allowed_domains:
            return PolicyDecision(False, REASON_DOMAIN_DENIED)

        if self.allowed_classifications and classification not in self.allowed_classifications:
            return PolicyDecision(False, REASON_CLASSIFICATION_DENIED)

        if self.allowed_sensitivities and sensitivity not in self.allowed_sensitivities:
            return PolicyDecision(False, REASON_SENSITIVITY_DENIED)

        if self.default_decision == "allow":
            return PolicyDecision(True, REASON_ALLOWED)
        return PolicyDecision(False, REASON_DEFAULT_DENIED)

    def snapshot(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "contract_version": self.contract_version,
            "max_record_age_days": self.max_record_age_days,
        }


def _as_positive_int(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"policy field {key} must be a positive integer")
    if value < 1:
        raise ValueError(f"policy field {key} must be a positive integer")
    return value


def _as_str(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"policy field {key} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"policy field {key} must be non-empty")
    return normalized


def _as_str_tuple(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    values = payload.get(key)
    if not isinstance(values, (list, tuple, set)):
        raise ValueError(f"policy field {key} must be a sequence")
    normalized = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"policy field {key} entries must be strings")
        value_normalized = value.strip().lower()
        if not value_normalized:
            raise ValueError(f"policy field {key} entries must be non-empty")
        normalized.append(value_normalized)
    if not normalized:
        raise ValueError(f"policy field {key} must contain at least one value")
    return tuple(normalized)


def _normalized_value(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    return normalized
