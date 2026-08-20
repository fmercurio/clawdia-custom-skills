from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .apply import _is_within, _resolve_sandbox_root
from .manifest import ManifestError

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _applied_state_path(sandbox: Path, plan_id: str) -> Path:
    return sandbox / ".skill-deploy" / "applied" / f"{plan_id}.json"


def _load_applied_state(
    plan_id: str, sandbox_root: str | Path
) -> tuple[Path, Path, tuple[dict[str, str], ...]]:
    sandbox = _resolve_sandbox_root(sandbox_root)
    state_path = _applied_state_path(sandbox, plan_id)

    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"invalid applied state: {exc}") from exc

    operations_raw = raw.get("operations")
    if not isinstance(operations_raw, list):
        raise ManifestError("invalid applied state: operations must be a list")

    operations: list[dict[str, str]] = []
    for item in operations_raw:
        if not isinstance(item, dict):
            raise ManifestError("invalid applied state: operation must be an object")
        destination = item.get("destination")
        source_sha256 = item.get("source_sha256")
        if not isinstance(destination, str) or not destination:
            raise ManifestError("invalid applied state: destination must be a non-empty string")
        if not isinstance(source_sha256, str) or not _SHA256_RE.fullmatch(source_sha256):
            raise ManifestError("invalid applied state: source_sha256 must be a SHA-256 value")
        operations.append({"destination": destination, "source_sha256": source_sha256})

    return sandbox, state_path, tuple(operations)


def _resolve_destination_path(sandbox: Path, destination: str) -> Path:
    relative = Path(destination)
    if relative.is_absolute():
        raise ManifestError(f"unsafe_destination:{destination}")
    resolved = (sandbox / relative).resolve()
    if resolved == sandbox or not _is_within(resolved, sandbox):
        raise ManifestError(f"unsafe_destination:{destination}")
    return resolved


def rollback_manifest(plan_id: str, sandbox_root: str | Path, dry_run: bool = False) -> dict[str, object]:
    sandbox, state_path, operations = _load_applied_state(plan_id, sandbox_root)
    result_operations = [dict(operation) for operation in operations]
    if dry_run:
        return {"dry_run": True, "operations": result_operations}

    for operation in operations:
        destination_path = _resolve_destination_path(sandbox, operation["destination"])
        if destination_path.is_symlink() or destination_path.is_file():
            destination_path.unlink()
            continue
        if destination_path.is_dir():
            shutil.rmtree(destination_path)
            continue
        if destination_path.exists():
            raise ManifestError(f"unsupported_destination_type:{operation['destination']}")

    state_path.unlink()
    return {"dry_run": False, "operations": result_operations}
