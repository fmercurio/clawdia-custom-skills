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


def _directory_flags() -> int:
    """Return the required POSIX descriptor-traversal flags or fail closed."""

    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise ProposalError("secure proposal staging requires O_DIRECTORY and O_NOFOLLOW")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _require_private_directory_fd(descriptor: int) -> tuple[int, int]:
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        raise ProposalError("proposal staging directory must be a regular directory")
    if metadata.st_uid != os.getuid():
        raise ProposalError("proposal staging directory must be owned by the runtime user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ProposalError("proposal staging directory must be owner-only")
    return _identity(metadata)


def _open_absolute_private_directory(path: Path) -> int:
    """Open every absolute path component without following a symlink."""

    candidate = Path(path)
    if not candidate.is_absolute():
        raise ProposalError("instance root must be absolute")
    flags = _directory_flags()
    descriptor = os.open("/", flags)
    try:
        for part in candidate.parts:
            if part in {candidate.anchor, ""}:
                continue
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        _require_private_directory_fd(descriptor)
        return descriptor
    except OSError as exc:
        os.close(descriptor)
        raise ProposalError("proposal staging directory must be a private non-symlink directory") from exc
    except Exception:
        os.close(descriptor)
        raise


def _open_private_child(parent_descriptor: int, part: str) -> int:
    try:
        descriptor = os.open(part, _directory_flags(), dir_fd=parent_descriptor)
    except OSError as exc:
        raise ProposalError("proposal staging directory must be a private non-symlink directory") from exc
    try:
        _require_private_directory_fd(descriptor)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _open_staging_descriptor(instance_root: Path, parts: tuple[str, ...]) -> tuple[int, tuple[int, int]]:
    instance_descriptor = _open_absolute_private_directory(instance_root)
    instance_identity = _identity(os.fstat(instance_descriptor))
    current_descriptor = instance_descriptor
    try:
        for part in parts:
            child_descriptor = _open_private_child(current_descriptor, part)
            os.close(current_descriptor)
            current_descriptor = child_descriptor
        return current_descriptor, instance_identity
    except Exception:
        os.close(current_descriptor)
        raise


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
    """Persist DLP-clean proposal artifacts with descriptor-pinned staging containment."""

    def __init__(self, staging_root: Path) -> None:
        self._initialize(Path(staging_root), ())

    @classmethod
    def from_instance_root(cls, instance_root: Path, configured_path: Any) -> "ProposalStager":
        stager = cls.__new__(cls)
        stager._initialize(Path(instance_root), _validate_relative_staging_path(configured_path))
        return stager

    def _initialize(self, instance_root: Path, parts: tuple[str, ...]) -> None:
        self._instance_root = Path(instance_root)
        self._staging_parts = parts
        staging_descriptor, instance_identity = _open_staging_descriptor(self._instance_root, parts)
        self._directory_fd = staging_descriptor
        self._instance_identity = instance_identity
        self._staging_identity = _require_private_directory_fd(staging_descriptor)

    def close(self) -> None:
        descriptor = getattr(self, "_directory_fd", None)
        if isinstance(descriptor, int) and descriptor >= 0:
            os.close(descriptor)
            self._directory_fd = -1

    def __enter__(self) -> "ProposalStager":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except OSError:
            pass

    def _assert_current_binding(self) -> None:
        """Re-resolve through no-follow descriptors and bind it to the held staging FD."""

        if self._directory_fd < 0:
            raise ProposalError("proposal stager is closed")
        if _require_private_directory_fd(self._directory_fd) != self._staging_identity:
            raise ProposalError("proposal staging directory identity changed")

        instance_descriptor = _open_absolute_private_directory(self._instance_root)
        current_descriptor = instance_descriptor
        try:
            if _identity(os.fstat(instance_descriptor)) != self._instance_identity:
                raise ProposalError("instance root identity changed")
            for part in self._staging_parts:
                child_descriptor = _open_private_child(current_descriptor, part)
                os.close(current_descriptor)
                current_descriptor = child_descriptor
            if _require_private_directory_fd(current_descriptor) != self._staging_identity:
                raise ProposalError("proposal staging directory identity changed")
        finally:
            os.close(current_descriptor)

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
        self._assert_current_binding()
        temporary_name = f".{proposal_id}.{uuid.uuid4().hex}.tmp"
        destination_name = f"{proposal_id}.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        descriptor: int | None = None
        published = False
        try:
            descriptor = os.open(temporary_name, flags, 0o600, dir_fd=self._directory_fd)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(
                temporary_name,
                destination_name,
                src_dir_fd=self._directory_fd,
                dst_dir_fd=self._directory_fd,
                follow_symlinks=False,
            )
            published = True
            self._assert_current_binding()
            os.unlink(temporary_name, dir_fd=self._directory_fd)
            os.fsync(self._directory_fd)
            published = False
        except FileExistsError as exc:
            raise ProposalError("proposal identifier collision") from exc
        except OSError as exc:
            raise ProposalError("proposal staging write failed") from exc
        finally:
            cleanup_errors: list[OSError] = []
            cleanup_performed = False
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError as exc:
                    cleanup_errors.append(exc)
            if published:
                try:
                    os.unlink(destination_name, dir_fd=self._directory_fd)
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    cleanup_errors.append(exc)
                else:
                    cleanup_performed = True
            try:
                os.unlink(temporary_name, dir_fd=self._directory_fd)
            except FileNotFoundError:
                pass
            except OSError as exc:
                cleanup_errors.append(exc)
            else:
                cleanup_performed = True
            if cleanup_performed:
                try:
                    os.fsync(self._directory_fd)
                except OSError as exc:
                    cleanup_errors.append(exc)
            if cleanup_errors:
                raise ProposalError("proposal staging cleanup failed") from cleanup_errors[0]
