from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from .plan import DeploymentPlan, PlanOperation

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$", re.IGNORECASE)
_FORBIDDEN_PROVENANCE_KEY_RE = re.compile(r"(?:secret|password|token|api[_-]?key)", re.IGNORECASE)


class ManifestError(ValueError):
    """Raised when a metadata-only deployment manifest cannot be safely handled."""


@dataclass(frozen=True)
class ManifestOperation:
    skill: str
    action: str
    source: str
    destination: str
    source_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "action": self.action,
            "destination": self.destination,
            "skill": self.skill,
            "source": self.source,
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True)
class DeploymentManifest:
    version: int
    plan_id: str
    plan_input_hashes: dict[str, str]
    source_commit: str
    provenance: dict[str, str]
    operations: tuple[ManifestOperation, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "operations": [operation.to_dict() for operation in self.operations],
            "plan_id": self.plan_id,
            "plan_input_hashes": dict(sorted(self.plan_input_hashes.items())),
            "provenance": dict(sorted(self.provenance.items())),
            "source_commit": self.source_commit,
            "version": self.version,
        }


@dataclass(frozen=True)
class ManifestVerification:
    valid: bool
    failures: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"failures": list(self.failures), "valid": self.valid}


def _hash_path(path: Path) -> str:
    """Hash a regular file or directory tree without following symlinks."""
    if not path.exists():
        raise ManifestError(f"source path does not exist: {path}")
    if path.is_symlink():
        raise ManifestError(f"symlink source is not allowed: {path}")
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    if not path.is_dir():
        raise ManifestError(f"source path is neither regular file nor directory: {path}")

    hasher = hashlib.sha256()
    for entry in sorted(path.rglob("*"), key=lambda item: item.as_posix()):
        if entry.is_dir():
            continue
        if entry.is_symlink() or not entry.is_file():
            raise ManifestError(f"non-regular entry in source tree: {entry}")
        relative = entry.relative_to(path).as_posix()
        hasher.update(relative.encode("utf-8"))
        hasher.update(b"\n")
        hasher.update(hashlib.sha256(entry.read_bytes()).hexdigest().encode("ascii"))
        hasher.update(b"\n")
    return hasher.hexdigest()


def _validate_hashes(values: Mapping[str, str], label: str) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in values.items():
        if not isinstance(key, str) or not key or not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
            raise ManifestError(f"{label} must contain non-empty keys and SHA-256 values")
        normalized[key] = value
    return normalized


def _validate_provenance(provenance: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in provenance.items():
        if not isinstance(key, str) or not key or not isinstance(value, str) or not value:
            raise ManifestError("provenance must contain non-empty string keys and values")
        if len(key) > 128 or len(value) > 512:
            raise ManifestError("provenance values exceed metadata bounds")
        if _FORBIDDEN_PROVENANCE_KEY_RE.search(key):
            raise ManifestError("provenance must not contain secret-bearing fields")
        normalized[key] = value
    return normalized


def _selected_operations(plan: DeploymentPlan, operations: Iterable[PlanOperation] | None) -> tuple[PlanOperation, ...]:
    if operations is None:
        return tuple(operation for operation in plan.operations if operation.action == "install-copy")
    selected = tuple(operations)
    allowed = {(op.skill, op.action, op.source, op.destination) for op in plan.operations}
    for operation in selected:
        identity = (operation.skill, operation.action, operation.source, operation.destination)
        if identity not in allowed:
            raise ManifestError("manifest operation is not declared in the plan")
    return selected


def create_manifest(
    plan: DeploymentPlan,
    *,
    source_commit: str,
    provenance: Mapping[str, str],
    operations: Iterable[PlanOperation] | None = None,
) -> DeploymentManifest:
    """Create an intent manifest containing hashes and metadata only; it writes nothing."""
    if not _SHA256_RE.fullmatch(plan.plan_id):
        raise ManifestError("plan_id must be a SHA-256 value")
    if not _COMMIT_RE.fullmatch(source_commit):
        raise ManifestError("source_commit must be a git SHA")

    input_hashes = _validate_hashes(plan.input_hashes, "plan_input_hashes")
    safe_provenance = _validate_provenance(provenance)
    manifest_operations = tuple(
        ManifestOperation(
            skill=operation.skill,
            action=operation.action,
            source=operation.source,
            destination=operation.destination,
            source_sha256=_hash_path(Path(operation.source)),
        )
        for operation in _selected_operations(plan, operations)
    )
    return DeploymentManifest(
        version=1,
        plan_id=plan.plan_id,
        plan_input_hashes=dict(sorted(input_hashes.items())),
        source_commit=source_commit.lower(),
        provenance=dict(sorted(safe_provenance.items())),
        operations=tuple(sorted(manifest_operations, key=lambda item: (item.skill, item.action, item.destination))),
    )


def verify_manifest(
    manifest: DeploymentManifest,
    plan: DeploymentPlan,
    *,
    input_paths: Mapping[str, str | Path] | None = None,
) -> ManifestVerification:
    """Verify plan identity, recorded inputs and source-tree hashes without applying anything."""
    failures: list[str] = []
    if manifest.version != 1:
        failures.append("unsupported_manifest_version")
    if manifest.plan_id != plan.plan_id:
        failures.append("plan_id_mismatch")
    if manifest.plan_input_hashes != plan.input_hashes:
        failures.append("plan_input_hashes_mismatch")

    declared = {(op.skill, op.action, op.source, op.destination) for op in plan.operations}
    for operation in manifest.operations:
        if (operation.skill, operation.action, operation.source, operation.destination) not in declared:
            failures.append(f"undeclared_operation:{operation.skill}")
            continue
        try:
            actual = _hash_path(Path(operation.source))
        except ManifestError:
            failures.append(f"missing_or_unsafe_source:{operation.skill}")
            continue
        if actual != operation.source_sha256:
            failures.append(f"source_hash_mismatch:{operation.skill}")

    if input_paths is not None:
        for name, path_value in sorted(input_paths.items()):
            expected = manifest.plan_input_hashes.get(name)
            if expected is None:
                failures.append(f"unexpected_input:{name}")
                continue
            try:
                actual = _hash_path(Path(path_value))
            except ManifestError:
                failures.append(f"missing_or_unsafe_input:{name}")
                continue
            if actual != expected:
                failures.append(f"input_hash_mismatch:{name}")

    return ManifestVerification(valid=not failures, failures=tuple(sorted(set(failures))))


def write_manifest_json(manifest: DeploymentManifest, path: Path) -> None:
    """Write only the metadata representation supplied by DeploymentManifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


def load_manifest_json(path: Path) -> DeploymentManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        operations = tuple(
            ManifestOperation(
                skill=item["skill"],
                action=item["action"],
                source=item["source"],
                destination=item["destination"],
                source_sha256=item["source_sha256"],
            )
            for item in raw["operations"]
        )
        manifest = DeploymentManifest(
            version=raw["version"],
            plan_id=raw["plan_id"],
            plan_input_hashes=_validate_hashes(raw["plan_input_hashes"], "plan_input_hashes"),
            source_commit=raw["source_commit"],
            provenance=_validate_provenance(raw["provenance"]),
            operations=operations,
        )
    except (KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"invalid manifest: {exc}") from exc
    if manifest.version != 1 or not _SHA256_RE.fullmatch(manifest.plan_id) or not _COMMIT_RE.fullmatch(manifest.source_commit):
        raise ManifestError("invalid manifest metadata")
    for operation in manifest.operations:
        if not _SHA256_RE.fullmatch(operation.source_sha256):
            raise ManifestError("invalid source hash in manifest")
    return manifest
