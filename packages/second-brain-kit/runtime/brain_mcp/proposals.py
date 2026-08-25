"""Bounded staging-only Brain Delta proposal artifacts."""

from __future__ import annotations

import json
import os
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .dlp import DECISION_DENIED, DECISION_REVIEW, assess_content

PROPOSAL_SCHEMA_VERSION = "brain-delta-proposal-v1"
PROPOSAL_ID_PREFIX = "bdp-"
ALLOWED_CHANGE_KINDS = frozenset({"decision", "project_update", "reference", "playbook"})
MAX_TITLE_CHARS = 160
MAX_SUMMARY_CHARS = 4000
MAX_CHANGES = 12
MAX_PROVENANCE = 12
MAX_CHANGE_SUMMARY_CHARS = 1200
MAX_TARGET_HINT_CHARS = 160
MAX_PROVENANCE_CHARS = 500


class ProposalError(ValueError):
    """Base error for proposal validation and staging failures."""


class ProposalRejected(ProposalError):
    """Safe caller-facing rejection without echoing untrusted input."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class StagedProposal:
    proposal_id: str

    @property
    def citation(self) -> str:
        return f"proposal:{self.proposal_id}"


def _normalize_string(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ProposalRejected("proposal_validation_failed")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ProposalRejected("proposal_validation_failed")
    return normalized


def _validate_dlp(values: Sequence[str]) -> None:
    for value in values:
        decision = assess_content(value)
        if decision.decision == DECISION_DENIED:
            raise ProposalRejected("proposal_dlp_denied")
        if decision.decision == DECISION_REVIEW:
            raise ProposalRejected("proposal_requires_human_review")


def _validate_relative_staging_path(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise ProposalError("proposal_staging_path must be a string")
    candidate = value.strip()
    if not candidate or candidate.startswith(("/", "\\")) or "\\" in candidate:
        raise ProposalError("proposal_staging_path must be an instance-relative path")
    parts = tuple(part for part in candidate.split("/") if part)
    if not parts or any(part in {".", ".."} for part in parts):
        raise ProposalError("proposal_staging_path must not contain traversal")
    return parts


def _require_private_directory(path: Path) -> None:
    if not path.is_dir() or path.is_symlink():
        raise ProposalError("proposal staging directory must be a regular directory")
    metadata = path.stat()
    if metadata.st_uid != os.getuid():
        raise ProposalError("proposal staging directory must be owned by the runtime user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ProposalError("proposal staging directory must be owner-only")


def resolve_proposal_staging_root(instance_root: Path, configured_path: Any) -> Path:
    """Resolve a pre-existing private directory below the trusted instance root."""

    if not instance_root.is_dir() or instance_root.is_symlink():
        raise ProposalError("instance root must be a regular directory")
    _require_private_directory(instance_root)
    parts = _validate_relative_staging_path(configured_path)
    current = instance_root
    for part in parts:
        current = current / part
        _require_private_directory(current)

    resolved_instance = instance_root.resolve(strict=True)
    resolved_root = current.resolve(strict=True)
    try:
        resolved_root.relative_to(resolved_instance)
    except ValueError as exc:
        raise ProposalError("proposal staging directory escapes instance root") from exc
    return resolved_root


def _validate_target_hint(value: Any) -> str:
    """Keep a target hint semantic; it must never resemble a filesystem destination."""

    target_hint = _normalize_string(value, "target_hint", MAX_TARGET_HINT_CHARS)
    lowered = target_hint.lower()
    if "/" in target_hint or "\\" in target_hint or ".." in target_hint or lowered.startswith("file:"):
        raise ProposalRejected("proposal_validation_failed")
    return target_hint


def _validated_changes(value: Any) -> tuple[list[dict[str, str]], list[str]]:
    if not isinstance(value, list) or not (1 <= len(value) <= MAX_CHANGES):
        raise ProposalRejected("proposal_validation_failed")
    changes: list[dict[str, str]] = []
    dlp_values: list[str] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"kind", "summary", "target_hint"}:
            raise ProposalRejected("proposal_validation_failed")
        kind = _normalize_string(item.get("kind"), "kind", 32)
        if kind not in ALLOWED_CHANGE_KINDS:
            raise ProposalRejected("proposal_validation_failed")
        summary = _normalize_string(item.get("summary"), "summary", MAX_CHANGE_SUMMARY_CHARS)
        target_hint = _validate_target_hint(item.get("target_hint"))
        changes.append({"kind": kind, "summary": summary, "target_hint": target_hint})
        dlp_values.extend((kind, summary, target_hint))
    return changes, dlp_values


def _validated_provenance(value: Any) -> tuple[list[str], list[str]]:
    if not isinstance(value, list) or not (1 <= len(value) <= MAX_PROVENANCE):
        raise ProposalRejected("proposal_validation_failed")
    provenance = [_normalize_string(item, "provenance", MAX_PROVENANCE_CHARS) for item in value]
    if len(set(provenance)) != len(provenance):
        raise ProposalRejected("proposal_validation_failed")
    return provenance, provenance


class ProposalStager:
    """Persist only schema-validated, DLP-clean proposal artifacts in private staging."""

    def __init__(self, staging_root: Path) -> None:
        _require_private_directory(staging_root)
        self._staging_root = staging_root.resolve(strict=True)

    @classmethod
    def from_instance_root(cls, instance_root: Path, configured_path: Any) -> "ProposalStager":
        return cls(resolve_proposal_staging_root(instance_root, configured_path))

    def stage(
        self,
        *,
        title: Any,
        summary: Any,
        proposed_changes: Any,
        provenance: Any,
    ) -> StagedProposal:
        normalized_title = _normalize_string(title, "title", MAX_TITLE_CHARS)
        normalized_summary = _normalize_string(summary, "summary", MAX_SUMMARY_CHARS)
        changes, change_dlp_values = _validated_changes(proposed_changes)
        normalized_provenance, provenance_dlp_values = _validated_provenance(provenance)
        _validate_dlp((normalized_title, normalized_summary, *change_dlp_values, *provenance_dlp_values))

        proposal_id = f"{PROPOSAL_ID_PREFIX}{uuid.uuid4().hex}"
        payload = {
            "schema_version": PROPOSAL_SCHEMA_VERSION,
            "proposal_id": proposal_id,
            "status": "proposed",
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "title": normalized_title,
            "summary": normalized_summary,
            "proposed_changes": changes,
            "provenance": normalized_provenance,
        }
        serialized = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        self._atomic_write(proposal_id, serialized)
        return StagedProposal(proposal_id=proposal_id)

    def _atomic_write(self, proposal_id: str, payload: bytes) -> None:
        _require_private_directory(self._staging_root)
        temporary = self._staging_root / f".{proposal_id}.{uuid.uuid4().hex}.tmp"
        destination = self._staging_root / f"{proposal_id}.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor: int | None = None
        try:
            descriptor = os.open(temporary, flags, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, destination)
            os.unlink(temporary)
        except FileExistsError as exc:
            raise ProposalError("proposal identifier collision") from exc
        except OSError as exc:
            raise ProposalError("proposal staging write failed") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary.exists():
                temporary.unlink()
