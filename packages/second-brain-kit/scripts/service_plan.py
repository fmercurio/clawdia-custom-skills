#!/usr/bin/env python3
"""Render deterministic service unit files from an MCP instance config."""
from __future__ import annotations

import argparse
import json
import os
import pwd
import sys
from pathlib import Path

from kitlib import private_directory, require_supported_python

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
    "HOME_DIR",
    "MINIMAL_PATH",
)

MINIMAL_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

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


def _planner_home() -> Path:
    """Return the resolved home used by the LaunchAgent owner at render time."""

    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    if not home.is_absolute():
        raise ServiceError("planner home must be absolute")
    if home.is_symlink() or not home.is_dir():
        raise ServiceError("planner home must be an existing non-symlink directory")
    return home.resolve(strict=True)


def _log_directory(instance_root: Path) -> Path:
    return instance_root / "logs"


def _prepare_log_directory(instance_root: Path) -> Path:
    """Create the service log directory only for an explicit render apply."""

    return private_directory(instance_root, Path("logs"))


def _validate_shell_launcher(path: Path) -> Path:
    if not path.is_absolute():
        raise ServiceError("launcher must be an absolute path")
    if path.is_symlink() or not path.is_file():
        raise ServiceError("launcher must be an existing regular non-symlink file")
    if path.suffix != ".sh":
        raise ServiceError("launcher must be a shell script")
    if not os.access(path, os.X_OK):
        raise ServiceError("launcher must be executable")
    try:
        first_line = path.open("r", encoding="utf-8").readline()
    except OSError as exc:
        raise ServiceError(f"launcher is unreadable: {exc}") from exc
    if not first_line.startswith("#!"):
        raise ServiceError("launcher must declare a shebang")
    return path


def _validate_runtime_root(path: Path) -> Path:
    if not path.is_absolute():
        raise ServiceError("runtime root must be an absolute path")
    if path.is_symlink() or not path.is_dir():
        raise ServiceError("runtime root must be an existing non-symlink directory")
    return path


def _runtime_root_from_config(config_path: Path, override: str) -> Path:
    if override:
        return _validate_runtime_root(Path(override))
    # The managed instance layout is <HERMES_HOME>/second-brain-kit/instances/<name>/runtime-config.json.
    # Its compatible launcher/runtime scripts are installed in the sibling managed bin directory.
    return _validate_runtime_root(config_path.parent.parent.parent / "bin")


def _validate_runtime_python(value: str) -> str:
    path = Path(value)
    if not path.is_absolute():
        raise ServiceError("runtime Python must be an absolute executable path")
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ServiceError("runtime Python must be an absolute executable path")
    # Preserve a venv's configured executable path rather than resolving its symlink.
    return str(path)


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

    launcher = str(_validate_shell_launcher(launcher_path or (runtime_root / "run_mcp.sh")))

    values = {
        "SERVICE_LABEL": f"second-brain-readonly-{instance_name}",
        "INSTANCE_DIR": str(instance_root),
        "LAUNCHER_PATH": launcher,
        "RUNTIME_PYTHON": runtime_python,
        "RUNTIME_ROOT": str(runtime_root),
        "CONFIG_PATH": str(config_path),
        "STDOUT_LOG_PATH": str(instance_root / "logs" / "mcp-stdout.log"),
        "STDERR_LOG_PATH": str(instance_root / "logs" / "mcp-stderr.log"),
        "HOME_DIR": str(_planner_home()),
        "MINIMAL_PATH": MINIMAL_PATH,
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
    parser.add_argument("--runtime-root", default="", help="override managed runtime/bin directory")
    parser.add_argument("--launcher", default="", help="override launcher path")
    parser.add_argument("--runtime-python", default="", help="absolute prepared Python/venv executable")
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
        runtime_root = _runtime_root_from_config(config_path, args.runtime_root)
        runtime_python = _validate_runtime_python(args.runtime_python or sys.executable)
        rendered = _plan(
            config_path,
            runtime_python,
            runtime_root,
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
            instance_root = _instance_paths(config_path)
            prepared_directories = [str(_prepare_log_directory(instance_root))]
            paths = _apply(output_dir, selected)
            plan = {
                "ok": True,
                "applied": True,
                "output_dir": str(output_dir),
                "rendered": paths,
                "prepared_directories": prepared_directories,
            }
            if "second-brain-mcp-launchdaemon.plist" in selected:
                plan["service_plan"] = {"applied": True, "required_owner_ack": True, "required_domain_ack": True}
            result = plan
        else:
            result = {
                "ok": True,
                "applied": False,
                "output_dir": str(output_dir),
                "rendered": {name: text for name, text in selected.items() if name != "metadata"},
                "required_directories": [str(_log_directory(_instance_paths(config_path)))],
            }

        print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
        return 0
    except Exception as exc:  # pragma: no cover
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
