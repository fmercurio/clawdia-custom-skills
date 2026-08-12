#!/usr/bin/env python3
"""Render deterministic service unit files from an MCP instance config."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from kitlib import require_supported_python

RUNTIME_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_ROOT = RUNTIME_ROOT / "templates" / "service"

TEMPLATES = (
    ("launchagent", "launchd-second-brain-mcp.plist.tmpl", "second-brain-mcp-launchagent.plist"),
    ("launchdaemon", "launchdaemon-second-brain-mcp.plist.tmpl", "second-brain-mcp-launchdaemon.plist"),
    ("systemd", "systemd-user-second-brain-mcp.service.tmpl", "second-brain-mcp.service"),
)


PLACEHOLDERS = (
    "SERVICE_LABEL",
    "INSTANCE_DIR",
    "LAUNCHER_PATH",
    "RUNTIME_PYTHON",
    "RUNTIME_ROOT",
    "CONFIG_PATH",
    "STDOUT_LOG_PATH",
    "STDERR_LOG_PATH",
)

DAEMON_PLACEHOLDERS = (
    "USER_NAME",
    "GROUP_NAME",
)


class ServiceError(ValueError):
    pass


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _render(path: Path, values: dict[str, str]) -> str:
    template = _read(path)
    return template.format(**values)


def _safe_json_object(path: Path, field: str) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ServiceError(f"{field} must be a JSON object")
    return payload


def _is_instance_relative(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ServiceError(f"{field} must be a string")
    if value.startswith(("/", "\\")):
        raise ServiceError(f"{field} must be instance-relative")
    if "\\" in value or ".." in value:
        raise ServiceError(f"{field} must be instance-relative")


def _instance_paths(config_path: Path) -> Path:
    if not config_path.is_file():
        raise ServiceError("instance config must be a file")
    if config_path.is_symlink():
        raise ServiceError("instance config must not be a symlink")
    return config_path.parent


def _expected_config_file_fields(config: dict) -> tuple[str, str]:
    instance_name = config.get("instance_name")
    if not isinstance(instance_name, str) or not instance_name.strip():
        raise ServiceError("instance_name missing from config")
    transport = config.get("transport")
    if transport != "http":
        raise ServiceError("config transport must be http")
    listener = config.get("listener")
    if not isinstance(listener, dict):
        raise ServiceError("listener missing")
    if listener.get("host") != "127.0.0.1":
        raise ServiceError("listener host must be 127.0.0.1")
    port = listener.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not (1 <= port <= 65535):
        raise ServiceError("listener port must be in range [1,65535]")
    path = listener.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        raise ServiceError("listener path must be absolute")
    if ".." in path.split("/"):
        raise ServiceError("listener path must not contain traversal")
    for key in ("policy_path", "projection_manifest_path"):
        _is_instance_relative(config.get(key), key)
    return instance_name, path


def _plan(
    config_path: Path,
    runtime_python: str,
    runtime_root: Path,
    launcher_path: Path | None,
    user_name: str | None = None,
    group_name: str | None = None,
) -> dict[str, str]:
    instance_root = _instance_paths(config_path)
    config = _safe_json_object(config_path, "instance config")
    instance_name, listener_path = _expected_config_file_fields(config)

    launcher = str((launcher_path or (runtime_root / "run_mcp.py")).resolve())

    values = {
        "SERVICE_LABEL": f"second-brain-readonly-{instance_name}",
        "INSTANCE_DIR": str(instance_root),
        "LAUNCHER_PATH": launcher,
        "RUNTIME_PYTHON": runtime_python,
        "RUNTIME_ROOT": str(runtime_root),
        "CONFIG_PATH": str(config_path),
        "STDOUT_LOG_PATH": str(instance_root / "logs" / "mcp-stdout.log"),
        "STDERR_LOG_PATH": str(instance_root / "logs" / "mcp-stderr.log"),
    }
    output: dict[str, str] = {}
    for name, template_name, rendered_name in TEMPLATES:
        template = TEMPLATE_ROOT / template_name
        if name == "launchdaemon":
            if user_name is None or group_name is None:
                continue
            daemon_values = {
                **values,
                "USER_NAME": user_name,
                "GROUP_NAME": group_name,
            }
            output[rendered_name] = _render(template, daemon_values)
        else:
            output[rendered_name] = _render(template, values)

    output["metadata"] = json.dumps(
        {
            "instance": instance_name,
            "listener": {
                "host": "127.0.0.1",
                "port": config.get("listener", {}).get("port"),
                "path": listener_path,
            },
            "runtime_root": str(runtime_root),
            "config": str(config_path),
        },
        sort_keys=True,
    )
    return output


def _apply(output_dir: Path, rendered: dict[str, str]) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered_paths = []
    for name in sorted(rendered):
        if name == "metadata":
            continue
        content = rendered[name]
        target = output_dir / name
        target.write_text(content, encoding="utf-8")
        target.chmod(0o600)
        rendered_paths.append(str(target))
    return rendered_paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--runtime-root", default="/opt/second-brain-kit")
    parser.add_argument("--launcher", default="", help="override launcher path")
    parser.add_argument("--runtime-python", default="/usr/bin/env python3")
    parser.add_argument("--service", choices=("all", "launchagent", "launchdaemon", "systemd"), default="all")
    parser.add_argument("--user-name")
    parser.add_argument("--group-name")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--accept-owner", action="store_true")
    parser.add_argument("--accept-domain", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        require_supported_python()
        config_path = Path(args.config)
        if not config_path.is_file():
            raise ServiceError("--config must be a file")

        launchdaemon_requested = args.service in {"all", "launchdaemon"}
        if launchdaemon_requested and (not args.user_name or not args.group_name):
            raise ServiceError("launchdaemon requires --user-name and --group-name")

        launcher = Path(args.launcher) if args.launcher else None
        rendered = _plan(
            config_path,
            args.runtime_python,
            Path(args.runtime_root).resolve(),
            launcher,
            user_name=args.user_name,
            group_name=args.group_name,
        )

        selected: dict[str, str] = {}
        for name, content in rendered.items():
            if name == "metadata":
                continue
            if args.service == "all":
                selected[name] = content
                continue
            if args.service == "launchagent" and name == "second-brain-mcp-launchagent.plist":
                selected[name] = content
            elif args.service == "launchdaemon" and name == "second-brain-mcp-launchdaemon.plist":
                selected[name] = content
            elif args.service == "systemd" and name == "second-brain-mcp.service":
                selected[name] = content

        if not selected:
            raise ServiceError(f"no template selected for service={args.service}")

        launchdaemon_selected = "second-brain-mcp-launchdaemon.plist" in selected
        if launchdaemon_selected and args.apply and (not args.accept_owner or not args.accept_domain):
            raise ServiceError("launchdaemon apply requires --accept-owner and --accept-domain")

        output_dir = Path(args.output_dir)
        if output_dir.exists() and output_dir.is_symlink():
            raise ServiceError("--output-dir must not be a symlink")

        if args.apply:
            paths = _apply(output_dir, selected)
            plan = {
                "ok": True,
                "applied": True,
                "output_dir": str(output_dir),
                "rendered": paths,
            }
            if "second-brain-mcp-launchdaemon.plist" in selected:
                plan["service_plan"] = {"applied": True, "required_owner_ack": True, "required_domain_ack": True}
            result = plan
        else:
            result = {"ok": True, "applied": False, "output_dir": str(output_dir), "rendered": {name: text for name, text in selected.items() if name != "metadata"}}

        print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
        return 0
    except Exception as exc:  # pragma: no cover
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
