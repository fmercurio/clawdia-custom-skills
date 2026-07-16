#!/usr/bin/env python3
"""Remove only managed runtime artifacts; never remove vault data."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from kitlib import hermes_home, inventory_path, sha256


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--hermes-home")
    p.add_argument("--profile", default="second-brain")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--cron-removed", action="store_true", help="Confirm a registered Hermes cron job was removed separately")
    a = p.parse_args()
    home = hermes_home(a.hermes_home)
    ip = inventory_path(home, a.profile)
    if not ip.exists():
        print(json.dumps({"ok": False, "error": "inventory not found"}))
        return 2
    inv = json.loads(ip.read_text(encoding="utf-8"))
    vault = Path(inv["vault_path"]).resolve()
    if inv.get("cron_registered") and not a.cron_removed:
        print(json.dumps({"ok": False, "error": "remove the registered Hermes cron job first, then pass --cron-removed", "inventory_preserved": str(ip), "vault_preserved": str(vault)}, indent=2))
        return 2
    removable, skipped = [], []
    for item in reversed(inv.get("managed_files", [])):
        path = Path(item["path"])
        try:
            path.resolve().relative_to(home)
        except ValueError:
            skipped.append({"path": str(path), "reason": "outside HERMES_HOME"})
            continue
        if path.exists() and not a.force and sha256(path) != item["sha256"]:
            skipped.append({"path": str(path), "reason": "modified"})
            continue
        removable.append(path)
    if skipped and not a.force:
        print(json.dumps({"ok": False, "error": "uninstall preflight refused modified or unsafe files", "skipped": skipped, "inventory_preserved": str(ip), "vault_preserved": str(vault)}, indent=2))
        return 2
    if a.apply:
        for path in removable:
            if path.exists():
                path.unlink()
        ip.unlink(missing_ok=True)
    print(json.dumps({"ok": True, "dry_run": not a.apply, "removed": [str(path) for path in removable], "skipped": skipped, "vault_preserved": str(vault)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
