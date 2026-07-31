#!/usr/bin/env python3
"""Post-install diagnostics for second-brain-kit."""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

SOURCE_RUNTIME = Path(__file__).resolve().parent.parent / "runtime"
if SOURCE_RUNTIME.is_dir() and str(SOURCE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(SOURCE_RUNTIME))

from kitlib import (REQUIRED_DIRS, ROOT_DOCS, config_path, fts5_available, hermes_home, install_bin_root, install_skill_root, load_config)


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


def _check_mcp_state(home: Path, cfg: dict, profile: str, check_optional: bool) -> dict:
    mcp_cfg = cfg.get("mcp_readonly", {}) if isinstance(cfg.get("mcp_readonly", {}), dict) else {}
    enabled = bool(mcp_cfg.get("enabled"))
    if not enabled:
        return {
            "name": "mcp_readonly",
            "ok": True,
            "detail": "disabled",
            "path": None,
            "instance": None,
        }

    instance_name = _expected_instance_name(cfg, profile)
    instance_root = home / "second-brain-kit" / "instances" / instance_name
    runtime_cfg_path = instance_root / "runtime-config.json"
    policy_path = instance_root / "policy.json"

    detail = {
        "enabled": True,
        "instance": instance_name,
        "instance_root": str(instance_root),
        "runtime_config": str(runtime_cfg_path),
        "policy": str(policy_path),
    }

    ok = True
    if not instance_root.is_dir():
        detail["instance_root_state"] = "missing"
        ok = False
    else:
        detail["instance_root_state"] = "present"

    for artifact_path in (runtime_cfg_path, policy_path):
        if not artifact_path.is_file():
            detail[artifact_path.name] = "missing"
            ok = False
            continue
        detail[f"{artifact_path.name}_mode"] = _safe_mode(artifact_path)
        if _safe_mode(artifact_path) != "0o600":
            detail[f"{artifact_path.name}_mode"] = _safe_mode(artifact_path)
            ok = False

    runtime_config_ok = False
    if runtime_cfg_path.is_file():
        try:
            runtime_cfg = json.loads(runtime_cfg_path.read_text(encoding="utf-8"))
            if not isinstance(runtime_cfg, dict):
                detail["runtime-config"] = "invalid-json"
            else:
                runtime_config_ok = isinstance(runtime_cfg.get("policy_path"), str) and str(policy_path) == runtime_cfg.get("policy_path")
                detail["runtime-config"] = "valid"
        except (OSError, json.JSONDecodeError):
            detail["runtime-config"] = "invalid-json"
            ok = False

    policy_ok = False
    try:
        from brain_mcp.policy import RuntimePolicy

        if policy_path.is_file():
            payload = json.loads(policy_path.read_text(encoding="utf-8"))
            RuntimePolicy.parse(payload)
            detail["policy"] = "valid"
            policy_ok = True
    except Exception:
        detail["policy"] = "invalid"
    if not runtime_config_ok:
        ok = False
    if not policy_ok:
        ok = False

    installed_bin = install_bin_root(home)
    helper_paths = [
        installed_bin / "brain_policy_check.py",
        installed_bin / "mcp_smoke.py",
        installed_bin / "brain_mcp" / "__init__.py",
        installed_bin / "brain_mcp" / "config.py",
        installed_bin / "brain_mcp" / "policy.py",
    ]
    for helper in helper_paths:
        if not helper.is_file():
            detail[f"missing:{helper.name}"] = "missing"
            if check_optional:
                ok = False

    result_ok = ok
    if not check_optional:
        # Keep the report non-blocking unless the user explicitly asks for strict check.
        result_ok = True

    return {
        "name": "mcp_readonly",
        "ok": result_ok,
        "detail": detail,
        "path": str(runtime_cfg_path),
        "instance": instance_name,
        "reason": None if ok else "mcp artifacts missing or invalid",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes-home")
    parser.add_argument("--profile", default="second-brain")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--check-optional", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

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
        checks.append(_check_mcp_state(home, cfg, args.profile, args.check_optional))

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
