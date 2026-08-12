#!/usr/bin/env python3
"""Remove only managed runtime artifacts; never remove vault data."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from kitlib import config_path, hermes_home, inventory_path, profile_name, require_supported_python, sha256


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


def _path_safety_reason(path: Path, home: Path) -> str | None:
    try:
        relative = path.relative_to(home)
    except ValueError:
        return "outside HERMES_HOME"
    current = home
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            return "parent_path_symlink"
    if path.is_symlink():
        return "managed_file_symlink"
    return None


def _bytes_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_atomic_bytes(path: Path, payload: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_bytes(payload)
        tmp.chmod(0o600)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _decode_mcp_snapshot(inventory: dict[str, Any]) -> dict[str, Any] | None:
    snapshot = inventory.get("mcp_config_snapshot")
    if not isinstance(snapshot, dict):
        return None

    config_path_value = snapshot.get("config_path")
    preinstall_hash = snapshot.get("preinstall_sha256")
    preinstall_payload_b64 = snapshot.get("preinstall_payload_b64")
    postinstall_hash = snapshot.get("postinstall_sha256")
    if not all(isinstance(value, str) for value in (config_path_value, preinstall_hash, preinstall_payload_b64, postinstall_hash)):
        return None

    preinstall_payload: bytes | None = None
    preinstall_payload_verified = False
    try:
        candidate = base64.b64decode(preinstall_payload_b64, validate=True)
        if candidate:
            preinstall_payload = candidate
            preinstall_payload_verified = _bytes_sha256(candidate) == preinstall_hash
    except (TypeError, ValueError):
        pass

    return {
        "config_path": Path(config_path_value),
        "preinstall_sha256": preinstall_hash,
        "preinstall_payload": preinstall_payload,
        "preinstall_payload_verified": preinstall_payload_verified,
        "postinstall_sha256": postinstall_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes-home")
    parser.add_argument("--profile", default="second-brain")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--service-removed", action="store_true")
    parser.add_argument("--cron-removed", action="store_true", help="confirm a registered cron job was removed separately")
    args = parser.parse_args()
    try:
        require_supported_python()
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2

    home = hermes_home(args.hermes_home)
    try:
        _validate_inventory_profile_chain(home, args.profile)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2

    ip = inventory_path(home, args.profile)
    if not ip.exists():
        print(json.dumps({"ok": False, "error": "inventory not found"}))
        return 2
    if ip.is_symlink():
        print(json.dumps({"ok": False, "error": f"install inventory path is a symlink: {ip}"}))
        return 2

    try:
        inv = json.loads(ip.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2

    service_plan = inv.get("service_plan")
    if isinstance(service_plan, dict) and service_plan.get("applied") and not args.service_removed:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "service plan was applied separately; pass --service-removed after removing service units",
                    "inventory": str(ip),
                },
                indent=2,
            )
        )
        return 2

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

    snapshot = _decode_mcp_snapshot(inv)
    has_snapshot_entry = "mcp_config_snapshot" in inv
    snapshot_path = snapshot["config_path"] if snapshot else None
    if snapshot_path is not None:
        try:
            snapshot_path.relative_to(home)
        except ValueError:
            snapshot_path = None

    if snapshot_path is None and has_snapshot_entry:
        snapshot_path = config_path(home, args.profile)

    removable: list[Path] = []
    skipped: list[dict[str, str]] = []
    snapshot_restore_path = None
    snapshot_restore_payload = None
    config_restored = False
    cleanup_required = False

    for item in reversed(inv.get("managed_files", [])):
        if not isinstance(item.get("path"), str):
            skipped.append({"path": str(item.get("path", "<invalid>")), "reason": "invalid_inventory_entry"})
            continue

        path = Path(item["path"])
        reason = _path_safety_reason(path, home)
        if reason is not None:
            skipped.append({"path": str(path), "reason": reason})
            continue

        if has_snapshot_entry and snapshot_path is not None and path == snapshot_path:
            continue

        if not path.exists():
            continue

        if item.get("sha256") != sha256(path) and not args.force:
            skipped.append({"path": str(path), "reason": "modified"})
            continue

        removable.append(path)

    if has_snapshot_entry:
        if snapshot is None:
            skipped.append({"path": str(snapshot_path), "reason": "snapshot_unusable"})
            cleanup_required = True
        elif snapshot_path is None:
            skipped.append({"path": "<unknown config>", "reason": "snapshot_path_unsafe"})
            cleanup_required = True
        else:
            snapshot_path_reason = _path_safety_reason(snapshot_path, home)
            if snapshot_path_reason is not None:
                skipped.append({"path": str(snapshot_path), "reason": snapshot_path_reason})
                cleanup_required = True
            elif not snapshot["preinstall_payload_verified"]:
                skipped.append({"path": str(snapshot_path), "reason": "snapshot_payload_mismatch"})
                cleanup_required = True
            elif not snapshot_path.exists():
                skipped.append({"path": str(snapshot_path), "reason": "missing"})
                cleanup_required = True
            elif snapshot["postinstall_sha256"] == sha256(snapshot_path):
                snapshot_restore_path = snapshot_path
                snapshot_restore_payload = snapshot["preinstall_payload"]
            else:
                skipped.append({"path": str(snapshot_path), "reason": "modified"})
                cleanup_required = True

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
        if snapshot_restore_path is not None:
            if snapshot_restore_payload is None:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "error": "failed to restore MCP config: missing restore payload",
                            "skipped": skipped + [{"path": str(snapshot_restore_path), "reason": "restore_failed"}],
                            "inventory_preserved": str(ip),
                            "vault_preserved": str(vault),
                        },
                        indent=2,
                    )
                )
                return 2
            try:
                snapshot_restore_path_reason = _path_safety_reason(snapshot_restore_path, home)
                if snapshot_restore_path_reason is not None:
                    raise ValueError(snapshot_restore_path_reason)
                _write_atomic_bytes(snapshot_restore_path, snapshot_restore_payload)
                config_restored = True
            except (OSError, ValueError) as exc:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "error": f"failed to restore MCP config: {exc}",
                            "skipped": skipped + [{"path": str(snapshot_restore_path), "reason": "restore_failed"}],
                            "inventory_preserved": str(ip),
                            "vault_preserved": str(vault),
                        },
                        indent=2,
                    )
                )
                return 2

        for path in removable:
            try:
                path.unlink()
            except FileNotFoundError:
                continue

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

        if not (has_snapshot_entry and cleanup_required):
            ip.unlink(missing_ok=True)

    report = {
        "ok": True,
        "dry_run": not args.apply,
        "removed": [str(path) for path in removable],
        "skipped": skipped,
        "vault_preserved": str(vault),
    }
    if config_restored:
        report["restored"] = [str(snapshot["config_path"])]
    if has_snapshot_entry and cleanup_required:
        report["cleanup_required"] = True
        report["inventory_preserved"] = str(ip)

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
