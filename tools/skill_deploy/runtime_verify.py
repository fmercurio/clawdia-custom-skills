from __future__ import annotations

from pathlib import Path

from .manifest import ManifestError, _hash_path
from .rollback import _load_applied_state, _resolve_destination_path


def verify_applied_state(plan_id: str, sandbox_root: str | Path) -> dict[str, object]:
    sandbox, _state_path, operations = _load_applied_state(plan_id, sandbox_root)
    drift: list[str] = []

    for operation in operations:
        destination = operation["destination"]
        expected_hash = operation["source_sha256"]
        try:
            destination_path = _resolve_destination_path(sandbox, destination)
        except ManifestError:
            drift.append(f"unsafe_destination:{destination}")
            continue

        if not destination_path.exists():
            drift.append(f"missing_destination:{destination}")
            continue

        try:
            actual_hash = _hash_path(destination_path)
        except ManifestError:
            drift.append(f"unsafe_destination:{destination}")
            continue

        if actual_hash != expected_hash:
            drift.append(f"hash_mismatch:{destination}")

    return {"valid": not drift, "drift": drift, "checked": len(operations)}
