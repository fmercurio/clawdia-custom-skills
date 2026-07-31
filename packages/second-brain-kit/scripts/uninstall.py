#!/usr/bin/env python3
"""Remove only managed runtime artifacts; never remove vault data."""
from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path

from kitlib import hermes_home, inventory_path, sha256


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes-home")
    parser.add_argument("--profile", default="second-brain")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--cron-removed", action="store_true", help="confirm a registered cron job was removed separately")
    args = parser.parse_args()

    home = hermes_home(args.hermes_home)
    ip = inventory_path(home, args.profile)
    if not ip.exists():
        print(json.dumps({"ok": False, "error": "inventory not found"}))
        return 2

    inv = json.loads(ip.read_text(encoding="utf-8"))
    vault = Path(inv["vault_path"]).resolve()

    if inv.get("cron_registered") and not args.cron_removed:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "remove the registered Hermes cron job first, then pass --cron-removed",
                    "cron_job_id": inv.get("cron_job_id"),
                    "inventory_preserved": str(ip),
                    "vault_preserved": str(vault),
                },
                indent=2,
            )
        )
        return 2

    removable: list[Path] = []
    skipped: list[dict[str, str]] = []
    for item in reversed(inv.get("managed_files", [])):
        path = Path(item["path"])

        try:
            path.relative_to(home)
        except ValueError:
            skipped.append({"path": str(path), "reason": "outside HERMES_HOME"})
            continue

        if not path.exists():
            continue

        if item.get("sha256") != sha256(path) and not args.force:
            skipped.append({"path": str(path), "reason": "modified"})
            continue

        removable.append(path)

    if skipped and not args.force:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "uninstall preflight refused modified or unsafe files",
                    "skipped": skipped,
                    "inventory_preserved": str(ip),
                    "vault_preserved": str(vault),
                },
                indent=2,
            )
        )
        return 2

    if args.apply:
        for path in removable:
            try:
                path.unlink()
            except FileNotFoundError:
                continue
        # Best-effort cleanup for managed instance directories that become empty.
        instance_roots = {path.parent for path in removable if "instances" in path.parts}
        for path in sorted(instance_roots, key=lambda item: len(item.parts), reverse=True):
            if path.exists() and path.is_dir() and not any(path.iterdir()):
                try:
                    path.rmdir()
                except OSError:
                    continue
        instances_root = home / "second-brain-kit" / "instances"
        if instances_root.exists() and instances_root.is_dir() and not any(instances_root.iterdir()):
            try:
                instances_root.rmdir()
            except OSError:
                pass
        ip.unlink(missing_ok=True)

    print(
        json.dumps(
            {
                "ok": True,
                "dry_run": not args.apply,
                "removed": [str(path) for path in removable],
                "skipped": skipped,
                "vault_preserved": str(vault),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
