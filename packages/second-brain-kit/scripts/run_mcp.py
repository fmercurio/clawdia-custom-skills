#!/usr/bin/env python3
"""Launch read-only MCP bridge from validated tenant artifacts."""
from __future__ import annotations

import argparse
import json
import os
import stat
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
from brain_mcp.proposals import ProposalStager
from brain_mcp.projection import (
    MANIFEST_SCHEMA_VERSION,
    manifest_records_to_core_payload,
    parse_projection_manifest,
)

RUNTIME_SCHEMA_VERSION = "v0.2"
LOOPBACK_HOST = "127.0.0.1"
MAX_TOKEN_BYTES = 4096


def _as_json_path(value: str) -> Path:
    path = Path(value)
    if not path.exists():
        raise ValueError(f"path does not exist: {path}")
    if path.is_symlink():
        raise ValueError(f"path must not be a symlink: {path}")
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"path could not be canonicalized: {path}") from exc


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


def _read_private_token(path: Path, instance_root: Path) -> str:
    """Read an owner-only token through a pinned, no-follow path walk."""
    try:
        relative = path.relative_to(instance_root)
    except ValueError as exc:
        raise ValueError("MCP access token must stay inside the instance") from exc
    if not relative.parts:
        raise ValueError("MCP access token path must name a file")

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        current_fd = os.open(instance_root, directory_flags)
    except OSError as exc:
        raise ValueError("MCP instance directory must be a real directory") from exc
    try:
        root_stat = os.fstat(current_fd)
        if not stat.S_ISDIR(root_stat.st_mode) or root_stat.st_uid != os.geteuid():
            raise ValueError("MCP instance directory must be owner-owned")
        for component in relative.parts[:-1]:
            try:
                next_fd = os.open(component, directory_flags, dir_fd=current_fd)
            except OSError as exc:
                raise ValueError("MCP access token path must not contain symlinks or unreadable directories") from exc
            try:
                component_stat = os.fstat(next_fd)
                if not stat.S_ISDIR(component_stat.st_mode) or component_stat.st_uid != os.geteuid():
                    raise ValueError("MCP access token path must contain owner-owned directories")
            except Exception:
                os.close(next_fd)
                raise
            os.close(current_fd)
            current_fd = next_fd

        try:
            token_fd = os.open(relative.parts[-1], file_flags, dir_fd=current_fd)
        except OSError as exc:
            raise ValueError("MCP access token is unreadable or symlinked") from exc
        try:
            token_stat = os.fstat(token_fd)
            if not stat.S_ISREG(token_stat.st_mode):
                raise ValueError("MCP access token must be a regular file")
            if token_stat.st_uid != os.geteuid():
                raise ValueError("MCP access token must be owned by the service user")
            if stat.S_IMODE(token_stat.st_mode) & 0o077:
                raise ValueError("MCP access token must be owner-only (mode 0600)")
            payload = b""
            while len(payload) <= MAX_TOKEN_BYTES:
                chunk = os.read(token_fd, MAX_TOKEN_BYTES + 1 - len(payload))
                if not chunk:
                    break
                payload += chunk
            if len(payload) > MAX_TOKEN_BYTES:
                raise ValueError("MCP access token is too large")
        finally:
            os.close(token_fd)
    finally:
        os.close(current_fd)
    try:
        token = payload.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("MCP access token must be UTF-8") from exc
    if len(token) < 32:
        raise ValueError("MCP access token is invalid")
    return token


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


def _validate_runtime_config(payload: dict[str, Any], config_path: Path) -> tuple[dict[str, Any], Path, Path, Path, V02Core, str | None]:
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
    proposal_stager = None
    if "proposal_staging_path" in payload:
        proposal_stager = ProposalStager.from_instance_root(instance_root, payload["proposal_staging_path"])

    try:
        policy_path = instance_root / policy_relative
        manifest_path = instance_root / manifest_relative
        token: str | None = None
        if "auth_token_path" in payload:
            token_relative = _as_instance_relative(payload.get("auth_token_path"), "auth_token_path")
            token = _read_private_token(instance_root / token_relative, instance_root)
        if not policy_path.is_file():
            raise ValueError(f"policy file missing: {policy_path}")
        if not manifest_path.is_file():
            raise ValueError(f"projection manifest file missing: {manifest_path}")

        policy_payload = _read_json(policy_path)
        policy = RuntimePolicy.parse(policy_payload)

        manifest = parse_projection_manifest(manifest_path, trusted_root=instance_root)
        if manifest.manifest_version != MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"unsupported manifest version: {manifest.manifest_version}")

        records = manifest_records_to_core_payload(manifest)
        core = V02Core(policy, records, proposal_stager=proposal_stager)

        return {
            "runtime_schema_version": RUNTIME_SCHEMA_VERSION,
            "mode": payload.get("mode"),
            "transport": payload.get("transport"),
            "listener": payload.get("listener"),
            "policy_path": str(payload.get("policy_path")),
            "projection_manifest_path": str(payload.get("projection_manifest_path")),
            "auth_token_path": str(payload.get("auth_token_path")),
            "host": host,
            "port": port,
            "path": path,
            "manifest_identity": manifest.identity,
            "manifest_generation": manifest.generation,
            "records": len(manifest.records),
            "proposal_staging_enabled": proposal_stager is not None,
        }, policy_path, manifest_path, instance_root, core, token
    except Exception:
        if proposal_stager is not None:
            proposal_stager.close()
        raise


def _run_check(payload: dict[str, Any]) -> dict[str, Any]:
    config_path = _as_json_path(payload["config"])
    config = _read_json(config_path)
    context, policy_path, manifest_path, instance_root, core, _token = _validate_runtime_config(config, config_path)
    try:
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
            "proposal_staging_enabled": context["proposal_staging_enabled"],
        }
    finally:
        core.close()


def _run_serve(config_path: Path) -> None:
    config = _read_json(config_path)
    context, _policy_path, _manifest_path, _instance_root, core, token = _validate_runtime_config(config, config_path)
    if token is None:
        core.close()
        raise ValueError("runtime config must configure auth_token_path before --serve")
    from brain_mcp.server import create_server

    resource_server_url = f"http://{context['host']}:{context['port']}{context['path']}"
    mcp = create_server(core, bearer_token=token, resource_server_url=resource_server_url)
    try:
        mcp.run(
            transport="streamable-http",
            host=context["host"],
            port=context["port"],
            streamable_http_path=context["path"],
            json_response=True,
            stateless_http=True,
        )
    finally:
        core.close()


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
