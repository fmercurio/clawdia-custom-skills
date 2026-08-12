#!/usr/bin/env python3
"""Launch read-only MCP bridge from validated tenant artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
import sys

from kitlib import require_supported_python

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_ROOT = SCRIPT_DIR.parent
RUNTIME_MODULE_ROOT = ROOT_ROOT / "runtime"
RUNTIME_MODULE_PACKAGE = ROOT_ROOT / "bin"
for runtime_root in (RUNTIME_MODULE_PACKAGE, RUNTIME_MODULE_ROOT):
    if runtime_root.is_dir() and str(runtime_root) not in sys.path:
        sys.path.insert(0, str(runtime_root))

from brain_mcp.core import V02Core
from brain_mcp.policy import RuntimePolicy
from brain_mcp.projection import (
    MANIFEST_SCHEMA_VERSION,
    manifest_records_to_core_payload,
    parse_projection_manifest,
)

RUNTIME_SCHEMA_VERSION = "v0.2"
LOOPBACK_HOST = "127.0.0.1"


def _as_json_path(value: str) -> Path:
    path = Path(value)
    if not path.exists():
        raise ValueError(f"path does not exist: {path}")
    if path.is_symlink():
        raise ValueError(f"path must not be a symlink: {path}")
    return path


def _as_instance_relative(path: object, field: str) -> Path:
    if not isinstance(path, str):
        raise ValueError(f"{field} must be a string")
    candidate = path.strip()
    if not candidate:
        raise ValueError(f"{field} must not be empty")
    if candidate.startswith(("/", "\\")):
        raise ValueError(f"{field} must be instance-relative")
    if "\\" in candidate:
        raise ValueError(f"{field} must not include backslashes")
    parts = [part for part in candidate.split("/") if part]
    if any(part == ".." for part in parts):
        raise ValueError(f"{field} must not include path traversal")
    return Path(*parts)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"manifest must be a mapping: {path}")
    return payload


def _validate_listener(payload: Any) -> tuple[str, int, str]:
    if not isinstance(payload, dict):
        raise ValueError("listener must be an object")
    if set(payload.keys()) != {"host", "port", "path"}:
        raise ValueError("listener must contain host, port, path")
    host = payload["host"]
    if not isinstance(host, str) or host.strip() != LOOPBACK_HOST:
        raise ValueError(f"listener.host must be '{LOOPBACK_HOST}'")
    port = payload["port"]
    if not isinstance(port, int) or isinstance(port, bool) or not (1 <= port <= 65535):
        raise ValueError("listener.port must be an int in range [1,65535]")
    path = payload["path"]
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("listener.path must be an absolute path")
    if path == "/":
        raise ValueError("listener.path must be explicit and non-root")
    if ".." in path.split("/"):
        raise ValueError("listener.path must not contain traversal")
    return host.strip(), port, path


def _validate_runtime_config(payload: dict[str, Any], config_path: Path) -> tuple[dict[str, Any], Path, Path, Path, V02Core]:
    required = {
        "runtime_schema_version",
        "mode",
        "transport",
        "listener",
        "policy_path",
        "projection_manifest_path",
    }
    keys = set(payload.keys())
    if not required.issubset(keys):
        missing = ", ".join(sorted(required - keys))
        raise ValueError(f"runtime config missing fields: {missing}")
    if not isinstance(payload.get("runtime_schema_version"), str) or payload["runtime_schema_version"] != RUNTIME_SCHEMA_VERSION:
        raise ValueError(f"runtime_schema_version must be {RUNTIME_SCHEMA_VERSION}")
    if payload.get("mode") != "readonly":
        raise ValueError("mode must be 'readonly'")
    if payload.get("transport") != "http":
        raise ValueError("transport must be 'http'")

    host, port, path = _validate_listener(payload.get("listener"))
    policy_relative = _as_instance_relative(payload.get("policy_path"), "policy_path")
    manifest_relative = _as_instance_relative(payload.get("projection_manifest_path"), "projection_manifest_path")

    instance_root = config_path.parent
    policy_path = instance_root / policy_relative
    manifest_path = instance_root / manifest_relative
    if not policy_path.is_file():
        raise ValueError(f"policy file missing: {policy_path}")
    if not manifest_path.is_file():
        raise ValueError(f"projection manifest file missing: {manifest_path}")

    policy_payload = _read_json(policy_path)
    policy = RuntimePolicy.parse(policy_payload)

    manifest = parse_projection_manifest(manifest_path)
    if manifest.manifest_version != MANIFEST_SCHEMA_VERSION:
        raise ValueError(f"unsupported manifest version: {manifest.manifest_version}")

    records = manifest_records_to_core_payload(manifest)
    core = V02Core(policy, records)

    return {
        "runtime_schema_version": RUNTIME_SCHEMA_VERSION,
        "mode": payload.get("mode"),
        "transport": payload.get("transport"),
        "listener": payload.get("listener"),
        "policy_path": str(payload.get("policy_path")),
        "projection_manifest_path": str(payload.get("projection_manifest_path")),
        "host": host,
        "port": port,
        "path": path,
        "manifest_identity": manifest.identity,
        "manifest_generation": manifest.generation,
        "records": len(manifest.records),
    }, policy_path, manifest_path, instance_root, core


def _run_check(payload: dict[str, Any]) -> dict[str, Any]:
    config_path = _as_json_path(payload["config"])
    config = _read_json(config_path)
    context, policy_path, manifest_path, instance_root, core = _validate_runtime_config(config, config_path)

    return {
        "ok": True,
        "mode": "check",
        "config_path": str(config_path),
        "instance_root": str(instance_root),
        "policy_path": str(policy_path),
        "projection_manifest_path": str(manifest_path),
        "listener": {
            "host": context["host"],
            "port": context["port"],
            "path": context["path"],
        },
        "manifest_identity": context["manifest_identity"],
        "manifest_generation": context["manifest_generation"],
        "records": context["records"],
    }


def _run_serve(config_path: Path) -> None:
    config = _read_json(config_path)
    context, _policy_path, _manifest_path, _instance_root, core = _validate_runtime_config(config, config_path)
    from brain_mcp.server import create_server

    mcp = create_server(core)
    mcp.run(
        transport="streamable-http",
        host=context["host"],
        port=context["port"],
        streamable_http_path=context["path"],
        json_response=True,
        stateless_http=True,
    )


def _dump(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--serve", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        require_supported_python()
        config_path = _as_json_path(args.config)
        if args.check:
            payload = _run_check({"config": str(config_path)})
            _dump(payload, args.json)
            return 0

        _run_serve(config_path)
        return 0
    except Exception as exc:  # pragma: no cover
        _dump({"ok": False, "error": str(exc)}, args.json)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
