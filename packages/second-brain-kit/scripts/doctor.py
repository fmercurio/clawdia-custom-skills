#!/usr/bin/env python3
"""Post-install diagnostics for second-brain-kit."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent
SOURCE_RUNTIME = PACKAGE_ROOT / "runtime"

from kitlib import (  # noqa: E402
    REQUIRED_DIRS,
    ROOT_DOCS,
    config_path,
    fts5_available,
    hermes_home,
    install_bin_root,
    install_skill_root,
    load_config,
    require_supported_python,
)
RUNTIME_SCHEMA_VERSION = "v0.2"


def _iter_brain_mcp_roots(home: Path):
    candidates: list[Path] = []
    installed_runtime = home / "second-brain-kit" / "bin"
    if installed_runtime.is_dir():
        candidates.append(installed_runtime)

    if SOURCE_RUNTIME.is_dir():
        candidates.append(SOURCE_RUNTIME)

    for root in candidates:
        module_root = root / "brain_mcp"
        if module_root.is_dir() and (module_root / "__init__.py").is_file():
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            yield root


def _import_runtime_policy(home: Path):
    last_error: Exception | None = None
    for runtime_root in _iter_brain_mcp_roots(home):
        try:
            from brain_mcp.policy import RuntimePolicy  # noqa: E402

            return RuntimePolicy
        except Exception as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise ModuleNotFoundError("brain_mcp package is unavailable")


def _safe_name(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _expected_instance_name(cfg: dict, profile: str) -> str:
    candidate = cfg.get("mcp_readonly", {}).get("instance_name") if isinstance(cfg.get("mcp_readonly", {}), dict) else None
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return f"{profile}-readonly"


def _mode_is(path: Path, mode: int) -> bool:
    return bool(path.exists()) and stat.S_IMODE(path.stat().st_mode) == mode


def _safe_mode(path: Path) -> str:
    return oct(stat.S_IMODE(path.stat().st_mode) & 0o777) if path.exists() else "missing"


def _owned_by_effective_user(path: Path) -> bool:
    try:
        return path.stat().st_uid == os.geteuid()
    except OSError:
        return False


def _is_instance_relative(value: object) -> bool:
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if not candidate or candidate.startswith(("/", "\\")):
        return False
    parts = [part for part in candidate.replace("\\", "/").split("/") if part]
    if any(part == ".." for part in parts):
        return False
    return True


def _check_mcp_state(home: Path, cfg: dict, profile: str, check_optional: bool, inventory: dict) -> dict:
    mcp_cfg = cfg.get("mcp_readonly", {}) if isinstance(cfg.get("mcp_readonly", {}), dict) else {}
    enabled = bool(mcp_cfg.get("enabled"))
    if not enabled:
        return {
            "name": "mcp_readonly",
            "ok": True,
            "detail": "disabled",
            "path": None,
            "instance": None,
            "service_plan": {
                "present": False,
                "applied": False,
                "details": None,
            },
        }

    instance_name = _expected_instance_name(cfg, profile)
    instance_root = home / "second-brain-kit" / "instances" / instance_name
    runtime_cfg_path = instance_root / "runtime-config.json"
    policy_path = instance_root / "policy.json"
    manifest_path = instance_root / "projection-manifest.json"
    token_path = instance_root / "access-token"

    detail = {
        "enabled": True,
        "instance": instance_name,
        "instance_root": str(instance_root),
        "runtime_config": str(runtime_cfg_path),
        "policy": str(policy_path),
        "projection_manifest": str(manifest_path),
        "access_token": str(token_path),
    }

    ok = True
    if not instance_root.is_dir() or instance_root.is_symlink():
        detail["instance_root_state"] = "missing"
        ok = False
    else:
        detail["instance_root_state"] = "present"
        detail["instance_root_owner_ok"] = _owned_by_effective_user(instance_root)
        if not detail["instance_root_owner_ok"]:
            ok = False

    for artifact_path in (runtime_cfg_path, policy_path, manifest_path, token_path):
        if artifact_path.is_symlink() or not artifact_path.is_file():
            detail[f"{artifact_path.name}"] = "missing"
            if artifact_path.name == "projection-manifest.json":
                detail["projection_manifest_present"] = False
                continue
            ok = False
            continue
        detail[f"{artifact_path.name}_mode"] = _safe_mode(artifact_path)
        detail[f"{artifact_path.name}_owner_ok"] = _owned_by_effective_user(artifact_path)
        if not detail[f"{artifact_path.name}_owner_ok"]:
            ok = False
        if artifact_path.name == "projection-manifest.json":
            detail["projection_manifest_present"] = True
            if _safe_mode(artifact_path) != "0o600":
                ok = False
            continue
        if _safe_mode(artifact_path) != "0o600":
            ok = False

    runtime_config_ok = False
    transport_ok = False
    policy_ok = False
    manifest_ok = False
    listener_ok = False
    schema_ok = False
    token_ok = False

    if token_path.is_file() and not token_path.is_symlink():
        try:
            token_ok = len(token_path.read_text(encoding="utf-8").strip()) >= 32
        except OSError:
            token_ok = False
    if not token_ok:
        ok = False

    if runtime_cfg_path.is_file():
        try:
            runtime_cfg = json.loads(runtime_cfg_path.read_text(encoding="utf-8"))
            if not isinstance(runtime_cfg, dict):
                detail["runtime-config"] = "invalid-json"
            else:
                runtime_config_ok = (
                    runtime_cfg.get("mode") == "readonly"
                    and runtime_cfg.get("transport") == "http"
                    and _is_instance_relative(runtime_cfg.get("policy_path"))
                    and runtime_cfg.get("policy_path") == policy_path.name
                    and _is_instance_relative(runtime_cfg.get("projection_manifest_path"))
                    and runtime_cfg.get("projection_manifest_path") == manifest_path.name
                    and _is_instance_relative(runtime_cfg.get("auth_token_path"))
                    and runtime_cfg.get("auth_token_path") == token_path.name
                )
                schema_ok = runtime_cfg.get("runtime_schema_version") == RUNTIME_SCHEMA_VERSION
                listener = runtime_cfg.get("listener") if isinstance(runtime_cfg.get("listener"), dict) else None
                listener_ok = bool(
                    listener
                    and listener.get("host") == "127.0.0.1"
                    and listener.get("path") == "/mcp"
                    and isinstance(listener.get("port"), int)
                    and 1 <= int(listener.get("port")) <= 65535
                )
                detail["runtime-config"] = "valid"
                detail["runtime_schema_version"] = runtime_cfg.get("runtime_schema_version")
                detail["runtime_transport"] = runtime_cfg.get("transport")
                detail["runtime_listener"] = listener
                detail["runtime_policy_path"] = runtime_cfg.get("policy_path")
                detail["runtime_projection_manifest_path"] = runtime_cfg.get("projection_manifest_path")
                detail["runtime_auth_token_path"] = runtime_cfg.get("auth_token_path")
                detail["runtime_schema_ok"] = schema_ok
                detail["runtime_listener_ok"] = listener_ok
        except (OSError, json.JSONDecodeError):
            detail["runtime-config"] = "invalid-json"

    if not runtime_config_ok:
        ok = False

    if policy_path.is_file():
        try:
            RuntimePolicy = _import_runtime_policy(home)
            payload = json.loads(policy_path.read_text(encoding="utf-8"))
            RuntimePolicy.parse(payload)
            detail["policy"] = "valid"
            policy_ok = True
        except (ModuleNotFoundError, OSError, json.JSONDecodeError, ValueError, RuntimeError):
            detail["policy"] = "invalid"
            ok = False

    if runtime_cfg_path.is_file() and _safe_mode(runtime_cfg_path) != "0o600":
        ok = False
    if policy_path.is_file() and _safe_mode(policy_path) != "0o600":
        ok = False

    if manifest_path.is_file() and not manifest_path.is_symlink():
        manifest_ok = (
            _safe_mode(manifest_path) == "0o600"
            and _owned_by_effective_user(manifest_path)
        )

    detail.update(
        {
            "runtime_config_ok": runtime_config_ok,
            "runtime_schema_ok": schema_ok,
            "listener_ok": listener_ok,
            "access_token_ok": token_ok,
            "projection_manifest_ok": manifest_ok,
            "policy_ok": policy_ok,
            "projection_manifest_present": manifest_path.is_file(),
            "schema_ok": runtime_config_ok and schema_ok and policy_ok and listener_ok,
        }
    )

    service_plan = inventory.get("service_plan") if isinstance(inventory.get("service_plan"), dict) else None
    service_plan_detail = {
        "planned": bool(service_plan),
        "applied": bool(service_plan.get("applied")) if isinstance(service_plan, dict) else False,
        "required_owner_ack": bool(service_plan.get("required_owner_ack")) if isinstance(service_plan, dict) else False,
        "required_domain_ack": bool(service_plan.get("required_domain_ack")) if isinstance(service_plan, dict) else False,
        "summary": service_plan,
    }

    result_ok = ok if check_optional else True

    return {
        "name": "mcp_readonly",
        "ok": result_ok,
        "detail": detail,
        "path": str(runtime_cfg_path),
        "instance": instance_name,
        "reason": None if ok else "mcp artifacts missing or invalid",
        "service_plan": service_plan_detail,
    }



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes-home")
    parser.add_argument("--profile", default="second-brain")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--check-optional", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        require_supported_python()
    except RuntimeError as exc:
        report = {"ok": False, "error": str(exc)}
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else report["error"])
        return 2

    home = hermes_home(args.hermes_home)
    checks: list[dict] = []

    cfg_path = config_path(home, args.profile)
    if not cfg_path.exists():
        checks.append({"name": "config", "ok": False, "detail": f"missing config: {cfg_path}"})
        cfg = None
    else:
        try:
            cfg = load_config(cfg_path)
            checks.append({"name": "config", "ok": True, "detail": str(cfg_path)})
        except Exception as exc:
            cfg = None
            checks.append({"name": "config", "ok": False, "detail": str(exc)})

    checks.append({"name": "sqlite_fts5", "ok": fts5_available(), "detail": sqlite3.sqlite_version})

    inventory = {}
    if cfg is not None:
        vault = Path(cfg["vault_path"])
        checks.append({"name": "vault", "ok": vault.is_dir(), "detail": str(vault)})
        missing_dirs = [name for name in REQUIRED_DIRS if not (vault / name).is_dir()]
        missing_docs = [name for name in ROOT_DOCS if not (vault / name).is_file()]
        checks.append({"name": "vault_structure", "ok": not missing_dirs and not missing_docs, "detail": {"dirs": missing_dirs, "docs": missing_docs}})

        skill_root = install_skill_root(home, args.profile)
        missing_skill = [
            name
            for name in ("second-brain-operations", "pull-brain", "push-brain", "brain-search")
            if not (skill_root / name / "SKILL.md").is_file()
        ]
        checks.append({"name": "skills", "ok": not missing_skill, "detail": missing_skill})

        okf = shutil.which("okf")
        checks.append({"name": "okf_optional", "ok": True, "detail": "detected" if okf else "not detected; optional"})
        if args.check_optional and okf and cfg.get("okf", {}).get("enabled") in {True, "auto"}:
            run = subprocess.run([okf, "--version"], capture_output=True, text=True)
            checks.append({"name": "okf_version", "ok": run.returncode == 0, "detail": (run.stdout or run.stderr).strip()})

        checks.append({"name": "embeddings_optional", "ok": True, "detail": cfg.get("embeddings", {})})
        checks.append({"name": "obsidian_optional", "ok": True, "detail": cfg.get("obsidian", {})})
        checks.append({"name": "git_remote_optional", "ok": True, "detail": cfg.get("git", {})})

        # Read inventory lazily; doctor should still be resilient if malformed.
        ip = home / "second-brain-kit" / "profiles" / args.profile / "install-inventory.json"
        if ip.exists():
            try:
                inventory = json.loads(ip.read_text(encoding="utf-8")) if ip.exists() else {}
                if not isinstance(inventory, dict):
                    inventory = {}
            except (OSError, json.JSONDecodeError):
                inventory = {}

        checks.append(_check_mcp_state(home, cfg, args.profile, args.check_optional, inventory))

        if args.smoke:
            search = install_bin_root(home) / "brain_search.py"
            if search.exists():
                rebuild = subprocess.run(
                    [sys.executable, str(search), "--vault", str(vault), "--rebuild", "--json"],
                    capture_output=True,
                    text=True,
                )
                checks.append(
                    {
                        "name": "search_rebuild",
                        "ok": rebuild.returncode == 0,
                        "detail": rebuild.stdout.strip() or rebuild.stderr.strip(),
                    }
                )
            else:
                checks.append({"name": "search_rebuild", "ok": False, "detail": "brain_search.py not installed"})

    ok = all(item["ok"] for item in checks)
    report = {"ok": ok, "profile": args.profile, "checks": checks}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("\n".join(f"[{'OK' if item['ok'] else 'FAIL'}] {item['name']}: {item['detail']}" for item in checks))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
