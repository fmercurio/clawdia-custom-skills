#!/usr/bin/env python3
"""Validate a local MCP policy payload against the v0.2 RuntimePolicy model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent
RUNTIME_ROOT = PACKAGE_ROOT / "runtime"
RUNTIME_PACKAGE = PACKAGE_ROOT / "bin" / "brain_mcp"
RUNTIME_SCRIPT_PACKAGE = SCRIPT_DIR / "brain_mcp"
for runtime_root in (RUNTIME_ROOT, RUNTIME_PACKAGE, RUNTIME_SCRIPT_PACKAGE):
    if runtime_root.is_dir() and str(runtime_root) not in sys.path:
        sys.path.insert(0, str(runtime_root))

from brain_mcp.policy import RuntimePolicy


def _safe_result(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def validate(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"failed to read policy JSON: {exc}"}

    try:
        policy = RuntimePolicy.parse(raw)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "path": str(path)}

    return {
        "ok": True,
        "path": str(path),
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "contract_version": policy.contract_version,
        "schema_version": policy.schema_version,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("policy")
    args = parser.parse_args()

    payload = validate(Path(args.policy))
    print(_safe_result(payload))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
