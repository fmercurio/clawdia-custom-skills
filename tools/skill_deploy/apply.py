from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Mapping

from .manifest import DeploymentManifest, ManifestError, _hash_path, verify_manifest
from .plan import DeploymentPlan
from tools.security_boundaries import BoundaryError, ensure_directory_beneath, safe_rename_directory_beneath, safe_write_bytes_beneath


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_sandbox_root(sandbox_root: str | Path) -> Path:
    resolved = Path(sandbox_root).expanduser().resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    hermes_root = (Path.home() / ".hermes").resolve()
    if _is_within(resolved, hermes_root):
        raise ManifestError("sandbox_root must not be under ~/.hermes")
    if resolved == temp_root or not _is_within(resolved, temp_root):
        raise ManifestError("sandbox_root must resolve below tempfile.gettempdir()")
    return resolved


def _cleanup_staging(staging_root: Path) -> None:
    if staging_root.is_symlink():
        raise ManifestError("staging_root_must_not_be_symlink")
    if staging_root.exists():
        shutil.rmtree(staging_root)


def _validate_skill_name(skill: str) -> str:
    """Return one portable directory-name component for a skill operation."""
    if (
        not isinstance(skill, str)
        or not skill
        or skill in {".", ".."}
        or "/" in skill
        or "\\" in skill
        or Path(skill).is_absolute()
    ):
        raise ManifestError(f"invalid_skill_name:{skill}")
    return skill


def apply_manifest(
    manifest: DeploymentManifest,
    plan: DeploymentPlan,
    sandbox_root: str | Path,
    input_paths: Mapping[str, str | Path],
    fail_after_staging: bool = False,
) -> dict[str, list[dict[str, str]]]:
    verification = verify_manifest(manifest, plan, input_paths=input_paths)
    if not verification.valid:
        raise ManifestError(f"manifest verification failed: {','.join(verification.failures)}")

    for operation in manifest.operations:
        if operation.action != "install-copy":
            raise ManifestError(f"unsupported_manifest_operation:{operation.skill}:{operation.action}")
        _validate_skill_name(operation.skill)

    sandbox = _resolve_sandbox_root(sandbox_root)
    sandbox.mkdir(parents=True, exist_ok=True)
    if sandbox.is_symlink() or not sandbox.is_dir():
        raise ManifestError("sandbox_root_must_be_directory")
    skills_root = sandbox / "skills"
    staging_root = sandbox / ".skill-deploy" / "staging" / manifest.plan_id
    applied_state_path = sandbox / ".skill-deploy" / "applied" / f"{manifest.plan_id}.json"

    try:
        ensure_directory_beneath(sandbox, Path("skills"))
        ensure_directory_beneath(sandbox, Path(".skill-deploy") / "staging")
    except (BoundaryError, OSError) as exc:
        raise ManifestError(f"unsafe_sandbox_path:{exc}") from exc
    _cleanup_staging(staging_root)
    try:
        ensure_directory_beneath(sandbox, Path(".skill-deploy") / "staging" / manifest.plan_id)
    except (BoundaryError, OSError) as exc:
        raise ManifestError(f"unsafe_staging_path:{exc}") from exc

    staged: list[tuple[str, str, Path, Path]] = []
    applied_operations: list[dict[str, str]] = []
    try:
        for operation in manifest.operations:
            source_path = Path(operation.source)
            if source_path.is_symlink() or not source_path.is_dir():
                raise ManifestError(f"source_must_be_directory:{operation.skill}")

            staged_path = staging_root / operation.skill
            shutil.copytree(source_path, staged_path)
            staged_hash = _hash_path(staged_path)
            if staged_hash != operation.source_sha256:
                raise ManifestError(f"staged_hash_mismatch:{operation.skill}")

            destination_path = skills_root / operation.skill
            staged.append((operation.skill, operation.source_sha256, staged_path, destination_path))

        for skill, _source_sha256, _staged_path, destination_path in staged:
            if destination_path.exists() or destination_path.is_symlink():
                raise ManifestError(f"destination_exists:{skill}")

        if fail_after_staging:
            raise ManifestError("injected_failure_after_staging")

        for skill, source_sha256, _staged_path, destination_path in staged:
            try:
                safe_rename_directory_beneath(
                    sandbox,
                    Path(".skill-deploy") / "staging" / manifest.plan_id / skill,
                    Path("skills") / skill,
                )
            except (BoundaryError, OSError) as exc:
                raise ManifestError(f"unsafe_destination_path:{skill}:{exc}") from exc
            applied_operations.append(
                {
                    "destination": destination_path.relative_to(sandbox).as_posix(),
                    "source_sha256": source_sha256,
                }
            )
    finally:
        _cleanup_staging(staging_root)

    applied_state = {"operations": applied_operations}
    try:
        safe_write_bytes_beneath(
            sandbox,
            Path(".skill-deploy") / "applied" / f"{manifest.plan_id}.json",
            json.dumps(applied_state, separators=(",", ":"), sort_keys=True).encode("utf-8"),
            mode=0o600,
        )
    except (BoundaryError, OSError) as exc:
        raise ManifestError(f"unsafe_applied_state_path:{exc}") from exc
    return applied_state
