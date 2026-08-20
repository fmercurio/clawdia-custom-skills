from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Mapping

from .manifest import DeploymentManifest, ManifestError, _hash_path, verify_manifest
from .plan import DeploymentPlan


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
    if staging_root.exists():
        shutil.rmtree(staging_root)


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

    sandbox = _resolve_sandbox_root(sandbox_root)
    skills_root = sandbox / "skills"
    staging_root = sandbox / ".skill-deploy" / "staging" / manifest.plan_id
    applied_state_path = sandbox / ".skill-deploy" / "applied" / f"{manifest.plan_id}.json"

    skills_root.mkdir(parents=True, exist_ok=True)
    _cleanup_staging(staging_root)
    staging_root.mkdir(parents=True, exist_ok=True)

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
            if destination_path.exists():
                raise ManifestError(f"destination_exists:{skill}")

        if fail_after_staging:
            raise ManifestError("injected_failure_after_staging")

        for _skill, source_sha256, staged_path, destination_path in staged:
            staged_path.rename(destination_path)
            applied_operations.append(
                {
                    "destination": destination_path.relative_to(sandbox).as_posix(),
                    "source_sha256": source_sha256,
                }
            )
    finally:
        _cleanup_staging(staging_root)

    applied_state = {"operations": applied_operations}
    applied_state_path.parent.mkdir(parents=True, exist_ok=True)
    applied_state_path.write_text(
        json.dumps(applied_state, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    return applied_state
