#!/usr/bin/env python3
"""Activate cron registration for second-brain health checks."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from kitlib import config_path, hermes_home, inventory_path, load_config, profile_name


def _validate_inventory_profile_chain(home: Path, profile: str) -> None:
    root = home.expanduser().resolve(strict=True)
    relative = Path("second-brain-kit") / "profiles" / profile_name(profile)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlinked directory is not allowed beneath {root}")
        if not current.exists():
            raise ValueError(f"directory path is not a directory: {current}")
        if not current.is_dir():
            raise ValueError(f"directory path is not a directory: {current}")
        if not current.resolve(strict=True).is_relative_to(root):
            raise ValueError(f"directory escapes configured root: {current}")


def _write_atomic_json(path: Path, payload: dict[str, Any]) -> None:
    payload_text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(payload_text, encoding="utf-8")
        tmp.chmod(0o600)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes-home")
    parser.add_argument("--profile", default="second-brain")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--hermes-cli", default="hermes")
    args = parser.parse_args()

    if not args.apply:
        print(json.dumps({"ok": False, "error": "--apply is required for cron activation"}))
        return 2

    home = hermes_home(args.hermes_home)
    try:
        _validate_inventory_profile_chain(home, args.profile)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2

    ip = inventory_path(home, args.profile)
    if not ip.exists():
        print(json.dumps({"ok": False, "error": f"install inventory not found: {ip}"}))
        return 2
    if ip.is_symlink():
        print(json.dumps({"ok": False, "error": f"install inventory path is a symlink: {ip}"}))
        return 2

    cfg_path = config_path(home, args.profile)
    if not cfg_path.exists() or cfg_path.is_symlink():
        print(json.dumps({"ok": False, "error": f"config not materialized: {cfg_path}"}))
        return 2
    wrapper = home / "scripts" / f"second-brain-health-{args.profile}.py"
    if not wrapper.exists() or wrapper.is_dir() or wrapper.is_symlink():
        print(json.dumps({"ok": False, "error": f"cron wrapper not materialized: {wrapper}"}))
        return 2

    try:
        cfg = load_config(cfg_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"invalid config: {exc}"}))
        return 2

    try:
        inventory = json.loads(ip.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"invalid install inventory: {exc}"}))
        return 2

    if inventory.get("cron_registered"):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "cron is already registered in install inventory; remove first",
                    "cron_job_id": inventory.get("cron_job_id"),
                }
            )
        )
        return 2

    cmd = [
        args.hermes_cli,
        "cron",
        "create",
        cfg["cron"]["schedule"],
        "--name",
        f"second-brain-health-{args.profile}",
        "--deliver",
        cfg["cron"]["deliver"],
        "--script",
        wrapper.name,
        "--no-agent",
    ]

    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "HERMES_HOME": str(home)},
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", None) or getattr(exc, "stdout", None) or str(exc)
        print(json.dumps({"ok": False, "error": f"failed to register cron job: {detail}"}))
        return 2

    match = re.search(r"^Created job:\s*(\S+)\s*$", result.stdout, flags=re.MULTILINE)
    if not match:
        print(json.dumps({"ok": False, "error": "cron create output did not include a job id"}))
        return 2

    inventory["cron_registered"] = True
    inventory["cron_job_id"] = match.group(1)
    try:
        _write_atomic_json(ip, inventory)
    except OSError as exc:
        print(json.dumps({"ok": False, "error": f"failed to record cron job id: {exc}"}))
        return 2

    print(
        json.dumps(
            {
                "ok": True,
                "cron_job_id": inventory["cron_job_id"],
                "inventory": str(ip),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
