#!/usr/bin/env python3
"""Install managed second-brain-kit artifacts into an explicit HERMES_HOME."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import secrets
import stat
from pathlib import Path
from typing import Any

from kitlib import (
    config_path,
    hermes_home,
    install_bin_root,
    ensure_inventory_directory,
    install_skill_root,
    inventory_path,
    load_config,
    private_directory,
    profile_name,
    require_supported_python,
    sha256,
    write_bytes_beneath,
)


PACKAGE = Path(__file__).resolve().parent.parent
SKILLS = ("second-brain-operations", "pull-brain", "push-brain", "brain-search")
RUNTIME_SCRIPTS = (
    "bootstrap.py",
    "brain_ops.py",
    "run_mcp.py",
    "run_mcp.sh",
    "doctor.py",
    "kitlib.py",
    "okf_render.py",
    "uninstall.py",
    "service_plan.py",
)
RUNTIME_SCRIPT_SOURCES = (
    ("brain_search.py", PACKAGE / "skills" / "brain-search" / "scripts" / "brain_search.py"),
    (
        "brain_health_check.py",
        PACKAGE / "skills" / "second-brain-operations" / "scripts" / "brain_health_check.py",
    ),
)
MCP_HELPER_SCRIPTS = ("brain_policy_check.py", "mcp_smoke.py")
MCP_RUNTIME_ROOT = PACKAGE / "runtime" / "brain_mcp"
MCP_POLICY_SOURCE = PACKAGE / "runtime" / "policies" / "policy.example.json"
MCP_RUNTIME_CONFIG_SCHEMA_VERSION = "v0.2"
MCP_INSTANCE_ROOT = "instances"
MCP_INSTANCE_CONFIG_NAME = "runtime-config.json"
MCP_INSTANCE_POLICY_NAME = "policy.json"
MCP_INSTANCE_MANIFEST_NAME = "projection-manifest.json"
MCP_INSTANCE_TOKEN_NAME = "access-token"
MCP_LISTENER_HOST = "127.0.0.1"
MCP_LISTENER_PORT = 8765
MCP_LISTENER_PATH = "/mcp"
DEFAULT_MCP_INSTANCE_SUFFIX = "readonly"


def _bytes_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _json_payload(value: Any) -> bytes:
    return (_canonical_json(value) + "\n").encode("utf-8")


def _expected_instance_name(cfg: dict[str, Any], profile: str) -> str:
    candidate = cfg.get("mcp_readonly", {}).get("instance_name") if isinstance(cfg.get("mcp_readonly", {}), dict) else None
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return f"{profile}-{DEFAULT_MCP_INSTANCE_SUFFIX}"


def _instance_runtime_config(
    instance_name: str,
    policy_path: Path,
    projection_manifest_path: Path,
    auth_token_path: Path,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    for artifact in (policy_path, projection_manifest_path, auth_token_path):
        if artifact.is_absolute() or any(part == ".." for part in artifact.parts):
            raise ValueError("artifact references must be instance-relative")
    return {
        "instance_name": instance_name,
        "runtime_schema_version": MCP_RUNTIME_CONFIG_SCHEMA_VERSION,
        "mode": "readonly",
        "transport": "http",
        "listener": {
            "host": MCP_LISTENER_HOST,
            "port": MCP_LISTENER_PORT,
            "path": MCP_LISTENER_PATH,
        },
        "kit_version": cfg.get("kit_version"),
        "profile": cfg.get("profile"),
        "owner": cfg.get("owner"),
        "policy_path": str(policy_path),
        "projection_manifest_path": str(projection_manifest_path),
        "auth_token_path": str(auth_token_path),
        "artifacts": [
            MCP_INSTANCE_CONFIG_NAME,
            MCP_INSTANCE_POLICY_NAME,
            MCP_INSTANCE_MANIFEST_NAME,
            MCP_INSTANCE_TOKEN_NAME,
        ],
    }


def _mcp_token_payload(token_path: Path) -> bytes:
    """Reuse a valid installed secret or create a new high-entropy token."""
    if token_path.exists():
        if token_path.is_symlink() or not token_path.is_file():
            raise ValueError(f"invalid MCP access token path: {token_path}")
        token = token_path.read_text(encoding="utf-8").strip()
        if len(token) < 32:
            raise ValueError(f"invalid MCP access token: {token_path}")
        return (token + "\n").encode("utf-8")
    return (secrets.token_urlsafe(32) + "\n").encode("utf-8")


def _add_entry(
    plan: list[dict[str, Any]],
    *,
    dst: Path,
    mode: int,
    src: Path | None = None,
    payload: bytes | None = None,
) -> None:
    if src is not None:
        if src.is_dir() or src.is_symlink():
            raise ValueError(f"symlinked package source is not installable: {src}")
        plan.append({"kind": "source", "dst": dst, "src": src, "mode": mode, "hash": sha256(src)})
        return
    if payload is None:
        raise ValueError("generated entries require bytes payload")
    plan.append({"kind": "payload", "dst": dst, "payload": payload, "mode": mode, "hash": _bytes_sha256(payload)})


def _file_state(path: Path, expected_hash: str) -> str:
    if not path.exists():
        return "created"
    try:
        return "unchanged" if sha256(path) == expected_hash else "updated"
    except (OSError, ValueError):
        return "updated"


def cron_wrapper(config: Path, health_script: Path) -> str:
    return (
        "#!/usr/bin/env python3\n"
        "import json, subprocess, sys\n"
        f"from pathlib import Path\n"
        f"cfg=json.loads(Path({str(config)!r}).read_text(encoding='utf-8'))\n"
        f"cmd=[{repr(__import__('sys').executable)}, {str(health_script)!r}, '--vault', cfg['vault_path'], '--mode', cfg.get('mode','hybrid')]\n"
        "result=subprocess.run(cmd,capture_output=True,text=True)\n"
        "if result.stdout.strip():\n"
        "    print(result.stdout.strip())\n"
        "if result.stderr.strip():\n"
        "    print(result.stderr.strip(),file=sys.stderr)\n"
        "raise SystemExit(result.returncode)\n"
    )


def _add_package_tree(plan: list[dict[str, Any]], root: Path, destination: Path) -> None:
    for src in sorted(root.rglob("*")):
        if src.is_symlink():
            raise ValueError(f"symlinked package source is not installable: {src}")
        if src.is_file() and "__pycache__" not in src.parts:
            _add_entry(plan, src=src, dst=destination / src.relative_to(root), mode=src.stat().st_mode & 0o777)


def _load_previous_inventory(home: Path, profile: str) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    _validate_inventory_profile_chain(home, profile)
    ip = inventory_path(home, profile)
    if ip.is_symlink():
        raise ValueError(f"install inventory path is a symlink: {ip}")
    if not ip.exists():
        return {}, {}
    prior = json.loads(ip.read_text(encoding="utf-8"))
    managed_by_path = {}
    for item in prior.get("managed_files", []):
        path = item.get("path")
        if isinstance(path, str):
            target = Path(path)
            if target.exists():
                managed_by_path[path] = {"path": path, "sha256": item.get("sha256")}
    return prior, managed_by_path


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes-home")
    parser.add_argument("--profile", default="second-brain")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--enable-mcp", action="store_true", help="manage optional read-only MCP instance artifacts")
    parser.add_argument("--enable-cron", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        require_supported_python()
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2

    home = hermes_home(args.hermes_home)
    cfg_path = config_path(home, args.profile)
    if not cfg_path.exists():
        print(json.dumps({"ok": False, "error": f"missing config: {cfg_path}"}))
        return 2

    try:
        cfg = load_config(cfg_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"invalid config: {exc}"}))
        return 2

    try:
        _validate_inventory_profile_chain(home, args.profile)
        bin_root = install_bin_root(home)
        skill_root = install_skill_root(home, args.profile)

        plan: list[dict[str, Any]] = []
        for skill in SKILLS:
            _add_package_tree(plan, PACKAGE / "skills" / skill, skill_root / skill)

        for name in RUNTIME_SCRIPTS:
            _add_entry(plan, src=PACKAGE / "scripts" / name, dst=bin_root / name, mode=0o755)
        for name, src in RUNTIME_SCRIPT_SOURCES:
            _add_entry(plan, src=src, dst=bin_root / name, mode=0o755)

        instance_name = None
        config_snapshot = None
        previous_inventory: dict[str, Any] = {}
        previous_snapshot: dict[str, Any] | None = None
        if args.apply:
            previous_inventory, _ = _load_previous_inventory(home, args.profile)
            previous_snapshot = previous_inventory.get("mcp_config_snapshot")

        if args.enable_mcp:
            if MCP_POLICY_SOURCE.is_symlink():
                print(json.dumps({"ok": False, "error": f"invalid MCP policy source: {MCP_POLICY_SOURCE}"}))
                return 2
            if not MCP_POLICY_SOURCE.is_file():
                print(json.dumps({"ok": False, "error": "MCP policy source file is missing"}))
                return 2
            try:
                json.loads(MCP_POLICY_SOURCE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                print(json.dumps({"ok": False, "error": "invalid MCP policy source data"}))
                return 2

            _add_package_tree(plan, MCP_RUNTIME_ROOT, bin_root / "brain_mcp")
            for name in MCP_HELPER_SCRIPTS:
                _add_entry(plan, src=PACKAGE / "scripts" / name, dst=bin_root / name, mode=0o755)

            instance_name = _expected_instance_name(cfg, args.profile)
            instances_root = home / "second-brain-kit" / MCP_INSTANCE_ROOT
            instance_root = instances_root / instance_name
            runtime_cfg_path = instance_root / MCP_INSTANCE_CONFIG_NAME
            policy_path = instance_root / MCP_INSTANCE_POLICY_NAME
            token_path = instance_root / MCP_INSTANCE_TOKEN_NAME
            _ = instance_root / MCP_INSTANCE_MANIFEST_NAME

            _add_entry(
                plan,
                dst=runtime_cfg_path,
                payload=_json_payload(
                    _instance_runtime_config(
                        instance_name,
                        Path(MCP_INSTANCE_POLICY_NAME),
                        Path(MCP_INSTANCE_MANIFEST_NAME),
                        Path(MCP_INSTANCE_TOKEN_NAME),
                        cfg,
                    )
                ),
                mode=0o600,
            )
            _add_entry(plan, src=MCP_POLICY_SOURCE, dst=policy_path, mode=0o600)
            _add_entry(plan, dst=token_path, payload=_mcp_token_payload(token_path), mode=0o600)

            desired_cfg = dict(cfg)
            desired_cfg["mcp_readonly"] = {"enabled": True, "instance_name": instance_name}
            if desired_cfg != cfg:
                preinstall_payload = cfg_path.read_bytes()
                postinstall_payload = _json_payload(desired_cfg)
                _add_entry(plan, dst=cfg_path, payload=postinstall_payload, mode=0o600)
                cfg = desired_cfg
                config_snapshot = {
                    "config_path": str(cfg_path),
                    "preinstall_sha256": hashlib.sha256(preinstall_payload).hexdigest(),
                    "preinstall_payload_b64": base64.b64encode(preinstall_payload).decode("ascii"),
                    "postinstall_sha256": _bytes_sha256(postinstall_payload),
                }
            elif isinstance(previous_snapshot, dict):
                config_snapshot = previous_snapshot

        wrapper = home / "scripts" / f"second-brain-health-{args.profile}.py"
        wrapper_content = cron_wrapper(cfg_path, bin_root / "brain_health_check.py") if args.enable_cron else None

        conflicts: list[str] = []
        for item in plan:
            if item["dst"].exists() and item["dst"] == cfg_path:
                continue
            if item["dst"].exists() and _file_state(item["dst"], item["hash"]) == "updated":
                conflicts.append(str(item["dst"]))
        if wrapper_content is not None and wrapper.exists():
            if wrapper.read_text(encoding="utf-8") != wrapper_content:
                conflicts.append(str(wrapper))

        operations = [{"path": str(item["dst"]), "state": _file_state(item["dst"], item["hash"])} for item in plan]
        if wrapper_content is not None:
            operations.append(
                {
                    "path": str(wrapper),
                    "state": "created" if not wrapper.exists() else ("unchanged" if wrapper.read_text(encoding="utf-8") == wrapper_content else "updated"),
                }
            )

        if conflicts and not args.force:
            print(json.dumps({"ok": False, "error": "preflight conflicts", "conflicts": conflicts}, ensure_ascii=False, indent=2))
            return 2

    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2

    operations = sorted(operations, key=lambda item: item["path"])
    if not args.apply:
        print(
            json.dumps(
                {
                    "ok": True,
                    "dry_run": True,
                    "operations": operations,
                    "inventory": str(inventory_path(home, args.profile)),
                    "instance": instance_name,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if re.search(r"[\\/]+\\.\\.", str(cfg_path)):
        print(json.dumps({"ok": False, "error": f"unsafe config path: {cfg_path}"}))
        return 2

    try:
        ensure_inventory_directory(home, args.profile)
        prior_inventory, prior_managed = _load_previous_inventory(home, args.profile)
        previous_cron_job = prior_inventory.get("cron_job_id")
        previous_cron_state = bool(prior_inventory.get("cron_registered"))
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2

    managed_by_path: dict[str, dict[str, str]] = dict(prior_managed)

    try:
        for item in plan:
            dst = item["dst"]
            if item["kind"] == "source":
                payload = item["src"].read_bytes()
            else:
                payload = item["payload"]
            write_bytes_beneath(
                home,
                dst.relative_to(home),
                payload,
                file_mode=item["mode"],
            )
            managed_by_path[str(dst)] = {"path": str(dst), "sha256": item["hash"]}

        if wrapper_content is not None:
            write_bytes_beneath(
                home,
                wrapper.relative_to(home),
                wrapper_content.encode("utf-8"),
                file_mode=0o755,
            )
            managed_by_path[str(wrapper)] = {"path": str(wrapper), "sha256": _bytes_sha256(wrapper_content.encode("utf-8"))}

        if args.enable_mcp:
            instances_root = home / "second-brain-kit" / MCP_INSTANCE_ROOT
            instances_root.mkdir(parents=True, exist_ok=True)
            instances_root.chmod(0o700)
            instance_root = private_directory(instances_root, Path(instance_name))
            for name in (MCP_INSTANCE_CONFIG_NAME, MCP_INSTANCE_POLICY_NAME, MCP_INSTANCE_TOKEN_NAME):
                target = instance_root / name
                if not target.exists():
                    print(json.dumps({"ok": False, "error": f"failed to create MCP artifact: {target}"}))
                    return 2
                if stat.S_IMODE(target.stat().st_mode) != 0o600:
                    target.chmod(0o600)

        inventory_payload: dict[str, Any] = {
            "kit_version": cfg["kit_version"],
            "profile": args.profile,
            "vault_path": cfg["vault_path"],
            "managed_files": sorted(managed_by_path.values(), key=lambda item: item["path"]),
            "cron_registered": previous_cron_state,
            "cron_job_id": previous_cron_job,
        }
        if config_snapshot is not None:
            inventory_payload["mcp_config_snapshot"] = config_snapshot

        ip = inventory_path(home, args.profile)
        if ip.is_symlink():
            print(json.dumps({"ok": False, "error": f"install inventory path is a symlink: {ip}"}))
            return 2
        write_bytes_beneath(
            home,
            ip.relative_to(home),
            (json.dumps(inventory_payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            file_mode=0o600,
        )

    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2

    print(
        json.dumps(
            {
                "ok": True,
                "dry_run": False,
                "operations": operations,
                "inventory": str(ip),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
