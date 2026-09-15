#!/usr/bin/env python3
"""Fail-closed CapRover session diagnostic using the pinned official CLI."""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.parse import urlsplit


SCHEMA_VERSION = 1
GUARD_VERSION = 1
GUARD_SHA256 = "24c0c604354f7c26db700be9395d804a05e5cd705aa584e361127b51ff90b930"
MAX_CONFIG_BYTES = 1_048_576
MAX_OUTPUT_BYTES = 65_536
MAX_EVENT_BYTES = 65_536
MAX_EVENT_COUNT = 64
SUPPORTED_CLI_VERSION = "2.4.4"
SUPPORTED_NODE_VERSION = "26.7.0"
LAYOUT_HASHES = {
    "built/commands/caprover.js": "6bc8eb18f5000e85fab08a2c33b6af0a6738af89441190ca2f67cad045393a4d",
    "built/commands/api.js": "2a9e6d1de63492fe9d0018d87b680ebe86cdddbdb1af417ca26408df24e66241",
    "built/api/HttpClient.js": "d96315b81f4a4d963c4be45c79e36d0ecf757cdde112eb6223e918c92ea3e74a",
    "built/api/CliApiManager.js": "7dc23cc2a8a77620d738e95310c4949e5dc0012ccdc4240eaad885b6df927f65",
    "built/api/ApiManager.js": "41c0d7c9548c277894704ce416db5cb9ce75cef892d4c718f3c171da371bba62",
    "built/utils/StorageHelper.js": "6032be2b6195e42894ea3302cd1bca7b43ac3e1dcc1ec97aa21384b3bc176b2f",
    "built/utils/CliHelper.js": "22d58af6ba29c5eeb5333131048c6c91255db028940bd353a67615562dac5f15",
}
POLLUTANT_NAMES = {
    "NODE_OPTIONS", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    "NODE_TLS_REJECT_UNAUTHORIZED", "NODE_EXTRA_CA_CERTS",
    "npm_config_proxy", "npm_config_https_proxy", "GLOBAL_AGENT_HTTP_PROXY",
}


class ProbeError(Exception):
    def __init__(self, reason: str, exit_code: int = 2):
        super().__init__(reason)
        self.reason = reason
        self.exit_code = exit_code


class NeutralArgumentError(Exception):
    """An argparse failure whose attacker-controlled input must not be echoed."""


class NeutralArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise NeutralArgumentError


def report(status: str, reason: str, **counts: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "cli_version": SUPPORTED_CLI_VERSION,
        "node_version": None,
        "request_count": 0,
        "response_count": 0,
    }
    value.update(counts)
    return value


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def load_json_object(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data, object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ProbeError("configuration_error") from None
    if not isinstance(value, dict):
        raise ProbeError("configuration_error")
    return value


def reject_git_ancestry(path: Path) -> None:
    for parent in (path.parent, *path.parent.parents):
        try:
            (parent / ".git").lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise ProbeError("configuration_error") from None
        raise ProbeError("configuration_error")


def read_protected_json(raw_path: str) -> tuple[dict[str, Any], bytes]:
    requested = Path(raw_path)
    if not requested.is_absolute():
        raise ProbeError("configuration_error")
    fd = -1
    try:
        requested = requested.parent.resolve(strict=True) / requested.name
        reject_git_ancestry(requested)
        before = requested.lstat()
        if stat.S_ISLNK(before.st_mode):
            raise ProbeError("protected_file_permissions")
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        fd = os.open(requested, flags)
        info = os.fstat(fd)
        if (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino):
            raise ProbeError("protected_file_permissions")
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ProbeError("protected_file_permissions")
        chunks: list[bytes] = []
        remaining = MAX_CONFIG_BYTES + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    except ProbeError:
        raise
    except (OSError, RuntimeError):
        raise ProbeError("configuration_error") from None
    finally:
        if fd >= 0:
            os.close(fd)
    if len(data) > MAX_CONFIG_BYTES:
        raise ProbeError("configuration_error")
    return load_json_object(data), data


def exact_origin(value: Any, fixture_loopback: bool) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2048
        or value != value.strip()
        or any(character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise ProbeError("configuration_error")
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise ProbeError("configuration_error") from None
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ProbeError("configuration_error")
    if not parsed.hostname or parsed.scheme not in ("https", "http") or parsed.scheme != parsed.scheme.lower():
        raise ProbeError("configuration_error")
    try:
        port = parsed.port
    except ValueError:
        raise ProbeError("configuration_error") from None
    authority = parsed.netloc
    if authority.startswith("["):
        closing = authority.find("]")
        suffix = authority[closing + 1:]
        if closing < 0 or (suffix and not suffix.startswith(":")):
            raise ProbeError("configuration_error")
        port_text = suffix[1:] if suffix.startswith(":") else None
        try:
            ipaddress.IPv6Address(parsed.hostname)
        except ValueError:
            raise ProbeError("configuration_error") from None
    else:
        if authority.count(":") > 1:
            raise ProbeError("configuration_error")
        port_text = authority.rsplit(":", 1)[1] if ":" in authority else None
        try:
            ipaddress.ip_address(parsed.hostname)
        except ValueError:
            labels = parsed.hostname.split(".")
            if any(
                not label
                or len(label) > 63
                or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
                for label in labels
            ):
                raise ProbeError("configuration_error")
    if port_text is not None and (not re.fullmatch(r"[1-9][0-9]{0,4}", port_text) or port is None):
        raise ProbeError("configuration_error")
    if parsed.scheme == "http":
        if not fixture_loopback or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ProbeError("insecure_origin")
    default = 443 if parsed.scheme == "https" else 80
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname.lower()
    return f"{parsed.scheme}://{host}{f':{port}' if port and port != default else ''}"


def preflight(args: argparse.Namespace) -> tuple[str, dict[str, Any], Path, Path, str]:
    if any(key.startswith("CAPROVER_") or key in POLLUTANT_NAMES for key in os.environ):
        raise ProbeError("environment_pollution")
    targets, _ = read_protected_json(args.targets)
    registry, _ = read_protected_json(args.registry)
    if type(targets.get("version")) is not int or targets.get("version") != 1 or not isinstance(targets.get("targets"), list):
        raise ProbeError("configuration_error")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", args.target):
        raise ProbeError("configuration_error")
    if any(
        not isinstance(item, dict)
        or set(item) != {"alias", "origin"}
        or not isinstance(item.get("alias"), str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", item["alias"])
        for item in targets["targets"]
    ):
        raise ProbeError("configuration_error")
    bindings = [item for item in targets["targets"] if item["alias"] == args.target]
    machines = registry.get("CapMachines")
    if len(bindings) != 1:
        raise ProbeError("target_binding_error")
    if not isinstance(machines, list):
        raise ProbeError("registry_schema_error")
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get("name"), str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", item["name"])
        for item in machines
    ):
        raise ProbeError("registry_schema_error")
    selected = [item for item in machines if item.get("name") == args.target]
    if len(selected) != 1:
        raise ProbeError("registry_binding_error")
    origin = exact_origin(bindings[0].get("origin"), args.fixture_loopback)
    registry_origin = exact_origin(selected[0].get("baseUrl"), args.fixture_loopback)
    if origin != registry_origin:
        raise ProbeError("origin_mismatch")
    token = selected[0].get("authToken")
    if not isinstance(token, str) or not token or len(token) > 8192:
        raise ProbeError("registry_schema_error")

    try:
        cli_root = Path(args.cli_root).resolve(strict=True)
    except OSError:
        raise ProbeError("cli_incompatible") from None
    if not cli_root.is_dir():
        raise ProbeError("cli_incompatible")
    try:
        package = json.loads(
            (cli_root / "package.json").read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, json.JSONDecodeError, ValueError):
        raise ProbeError("cli_incompatible") from None
    if (
        not isinstance(package, dict)
        or package.get("name") != "caprover"
        or package.get("version") != SUPPORTED_CLI_VERSION
    ):
        raise ProbeError("cli_incompatible")
    for relative, expected in LAYOUT_HASHES.items():
        try:
            actual = hashlib.sha256((cli_root / relative).read_bytes()).hexdigest()
        except OSError:
            raise ProbeError("cli_incompatible") from None
        if actual != expected:
            raise ProbeError("cli_incompatible")

    try:
        node = Path(args.node).resolve(strict=True)
    except OSError:
        raise ProbeError("node_incompatible") from None
    if not node.is_file() or not os.access(node, os.X_OK):
        raise ProbeError("node_incompatible")
    guard = Path(__file__).with_name("readonly_guard.cjs")
    try:
        guard = guard.resolve(strict=True)
        if not guard.is_file() or hashlib.sha256(guard.read_bytes()).hexdigest() != GUARD_SHA256:
            raise ProbeError("guard_incompatible")
    except OSError:
        raise ProbeError("guard_incompatible") from None
    snapshot = {"name": args.target, "baseUrl": origin, "authToken": token}
    app_token = selected[0].get("appToken")
    if app_token is not None:
        if not isinstance(app_token, str) or len(app_token) > 8192:
            raise ProbeError("registry_schema_error")
        snapshot["appToken"] = app_token
    return origin, snapshot, cli_root, node, str(guard)


def node_version(node: Path) -> str:
    try:
        completed = subprocess.run(
            [str(node), "-p", "process.versions.node"], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            env={"PATH": str(node.parent), "HOME": "/nonexistent", "CI": "1"},
            timeout=3, check=False,
        )
        value = completed.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        raise ProbeError("node_incompatible") from None
    if completed.returncode or value != SUPPORTED_NODE_VERSION:
        raise ProbeError("node_incompatible")
    return value


def terminate(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            process.kill()
        except ProcessLookupError:
            pass


def close_fd(fd: int) -> None:
    if fd < 0:
        return
    try:
        os.close(fd)
    except OSError:
        pass


def execute(args: argparse.Namespace, origin: str, machine: dict[str, Any], cli_root: Path, node: Path, guard: str) -> dict[str, Any]:
    version = node_version(node)
    nonce = os.urandom(24).hex()
    events: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="caprover-probe-") as raw_temp:
        temp = Path(raw_temp).resolve()
        temp.chmod(0o700)
        config_dir = temp / "config" / "configstore"
        config_dir.mkdir(parents=True, mode=0o700)
        config_path = config_dir / "caprover.json"
        config_path.write_text(json.dumps({"CapMachines": [machine]}), encoding="utf-8")
        config_path.chmod(0o600)
        read_fd = -1
        write_fd = -1
        process: subprocess.Popen[bytes] | None = None
        selector: selectors.BaseSelector | None = None
        cleanup_group = False
        read_fd, write_fd = os.pipe()
        policy = base64.urlsafe_b64encode(json.dumps({
            "guardVersion": GUARD_VERSION,
            "origin": origin,
            "nonce": nonce,
            "authTokenSha256": hashlib.sha256(machine["authToken"].encode()).hexdigest(),
            "appTokenSha256": (
                hashlib.sha256(machine["appToken"].encode()).hexdigest()
                if machine.get("appToken") else None
            ),
        }, separators=(",", ":")).encode()).decode().rstrip("=")
        env = {
            "PATH": str(node.parent), "HOME": str(temp), "XDG_CONFIG_HOME": str(temp / "config"),
            "CI": "1", "NO_UPDATE_NOTIFIER": "1", "TERM": "dumb", "LANG": "C",
            "CAPROVER_PROBE_INTERNAL_POLICY": policy,
            "CAPROVER_PROBE_INTERNAL_EVENT_FD": str(write_fd),
        }
        command = [
            str(node), "--require", guard, str(cli_root / "built/commands/caprover.js"),
            "api", "--caproverName", args.target, "--method", "GET",
            "--path", "/user/system/info", "--data", "{}", "--output", "true",
        ]
        try:
            try:
                process = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    env=env, pass_fds=(write_fd,), start_new_session=True,
                )
            except OSError:
                raise ProbeError("cli_execution_error", 1) from None
            close_fd(write_fd)
            write_fd = -1
            assert process.stdout is not None and process.stderr is not None
            selector = selectors.DefaultSelector()
            streams = {process.stdout.fileno(): "output", process.stderr.fileno(): "output", read_fd: "events"}
            buffers = {fd: b"" for fd in streams}
            for fd in streams:
                os.set_blocking(fd, False)
                selector.register(fd, selectors.EVENT_READ)
            deadline = time.monotonic() + args.timeout
            output_bytes = 0
            event_bytes = 0
            stop_reason: str | None = None
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    stop_reason = "timeout"
                    cleanup_group = True
                    break
                for key, _ in selector.select(min(remaining, 0.1)):
                    fd = key.fd
                    try:
                        chunk = os.read(fd, 16384)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(fd)
                        if fd == read_fd:
                            if buffers[fd]:
                                stop_reason = "guard_incompatible"
                                cleanup_group = True
                            close_fd(read_fd)
                            read_fd = -1
                        if stop_reason:
                            break
                        continue
                    if streams[fd] == "output":
                        output_bytes += len(chunk)
                        if output_bytes > MAX_OUTPUT_BYTES:
                            stop_reason = "output_limit"
                            cleanup_group = True
                            break
                    else:
                        event_bytes += len(chunk)
                        buffers[fd] += chunk
                        if event_bytes > MAX_EVENT_BYTES or len(buffers[fd]) > MAX_EVENT_BYTES:
                            stop_reason = "guard_incompatible"
                            cleanup_group = True
                            break
                        while b"\n" in buffers[fd]:
                            line, buffers[fd] = buffers[fd].split(b"\n", 1)
                            try:
                                event = json.loads(line)
                            except (UnicodeDecodeError, json.JSONDecodeError):
                                stop_reason = "guard_incompatible"
                                cleanup_group = True
                                break
                            if (
                                not isinstance(event, dict)
                                or event.get("nonce") != nonce
                                or len(events) >= MAX_EVENT_COUNT
                            ):
                                stop_reason = "guard_incompatible"
                                cleanup_group = True
                                break
                            events.append(event)
                    if stop_reason:
                        break
                if stop_reason:
                    break
                if process.poll() is not None and not selector.get_map():
                    break
            if cleanup_group:
                terminate(process)
            try:
                return_code = process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                cleanup_group = True
                terminate(process)
                return_code = process.wait(timeout=2)
        except BaseException:
            cleanup_group = True
            raise
        finally:
            if process is not None and cleanup_group:
                terminate(process)
                try:
                    process.wait(timeout=2)
                except (subprocess.TimeoutExpired, ProcessLookupError):
                    pass
            if selector is not None:
                for key in list(selector.get_map().values()):
                    try:
                        selector.unregister(key.fileobj)
                    except (KeyError, ValueError):
                        pass
                selector.close()
            if process is not None:
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()
            close_fd(read_fd)
            close_fd(write_fd)

    request_events = [event for event in events if event.get("type") == "request"]
    http_events = [event for event in events if event.get("type") == "http_response"]
    api_events = [event for event in events if event.get("type") == "api_response"]
    requests = len(request_events)
    responses = len(http_events)
    base = {"node_version": version, "request_count": requests, "response_count": responses}
    if stop_reason == "guard_incompatible":
        return report("inconclusive", stop_reason, **base)
    ready = [event for event in events if event.get("type") == "guard_ready"]
    if (
        len(ready) != 1
        or ready[0].get("guardVersion") != GUARD_VERSION
        or ready[0].get("nodeVersion") != version
    ):
        if stop_reason:
            return report("inconclusive", stop_reason, **base)
        return report("inconclusive", "guard_incompatible", **base)

    def has_transport(sequence: int, endpoint: str, statuses: set[int] | None = None) -> bool:
        requested = any(
            event.get("sequence") == sequence and event.get("endpoint") == endpoint
            for event in request_events
        )
        responded = any(
            event.get("sequence") == sequence
            and event.get("endpoint") == endpoint
            and (statuses is None or event.get("httpStatus") in statuses)
            for event in http_events
        )
        return requested and responded

    concrete_api = [
        event for event in api_events
        if isinstance(event.get("sequence"), int)
        and isinstance(event.get("endpoint"), str)
        and has_transport(event["sequence"], event["endpoint"], set(range(200, 300)))
    ]
    auth_statuses = {1105, 1106, 1112, 1113, 1115}
    if any(
        event.get("sequence") == 1
        and event.get("endpoint") == "auth_check"
        and event.get("captainStatus") in auth_statuses
        for event in concrete_api
    ):
        return report("invalid", "authentication_rejected", **base)
    if any(event.get("captainStatus") == 1102 for event in concrete_api):
        return report("invalid", "authorization_denied", **base)
    if any(
        event.get("httpStatus") == 401
        and any(
            request.get("sequence") == event.get("sequence")
            and request.get("endpoint") == event.get("endpoint")
            for request in request_events
        )
        for event in http_events
    ):
        return report("invalid", "authentication_rejected", **base)
    if any(
        event.get("httpStatus") == 403
        and any(
            request.get("sequence") == event.get("sequence")
            and request.get("endpoint") == event.get("endpoint")
            for request in request_events
        )
        for event in http_events
    ):
        return report("invalid", "authorization_denied", **base)
    if stop_reason:
        return report("inconclusive", stop_reason, **base)
    if any(event.get("type") == "violation" for event in events):
        return report("inconclusive", "guard_violation", **base)
    if any(event.get("httpStatus", 0) >= 400 for event in http_events):
        return report("inconclusive", "http_error", **base)
    errors = [event for event in events if event.get("type") == "request_error"]
    if errors:
        network_codes = {"ECONNREFUSED", "ECONNRESET", "ENOTFOUND", "EAI_AGAIN", "ETIMEDOUT", "EHOSTUNREACH"}
        reason = "network_error" if any(event.get("code") in network_codes for event in errors) else "cli_error"
        return report("inconclusive", reason, **base)
    expected_trace = [
        (1, "auth_check", "app_definitions_v1", 100),
        (2, "captain_info", "system_info_v1", 100),
        (3, "session_probe", "system_info_v1", 100),
    ]
    actual_requests = [(event.get("sequence"), event.get("endpoint")) for event in request_events]
    actual_http = [(event.get("sequence"), event.get("endpoint")) for event in http_events]
    actual_api = [
        (event.get("sequence"), event.get("endpoint"), event.get("schema"), event.get("captainStatus"))
        for event in api_events
    ]
    expected_transport = [(sequence, endpoint) for sequence, endpoint, _, _ in expected_trace]
    if (
        return_code == 0
        and actual_requests == expected_transport
        and actual_http == expected_transport
        and actual_api == expected_trace
    ):
        return report("valid", "session_valid", **base)
    if return_code in (130, -signal.SIGINT):
        return report("inconclusive", "interrupted", **base)
    if any(event.get("captainStatus") == 100 and event.get("schema") == "unknown" for event in concrete_api):
        return report("inconclusive", "schema_inconclusive", **base)
    return report("inconclusive", "cli_inconclusive", **base)


def parser() -> argparse.ArgumentParser:
    value = NeutralArgumentParser(add_help=True, exit_on_error=False)
    value.add_argument("--targets")
    value.add_argument("--target")
    value.add_argument("--registry")
    value.add_argument("--cli-root")
    value.add_argument("--node")
    value.add_argument("--timeout", type=float, default=10.0)
    value.add_argument("--fixture-loopback", action="store_true")
    return value


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
    except (argparse.ArgumentError, NeutralArgumentError):
        print(json.dumps(report("inconclusive", "configuration_error"), sort_keys=True))
        return 2
    except SystemExit as error:
        return int(error.code or 0)
    if not all((args.targets, args.target, args.registry, args.cli_root, args.node)):
        print(json.dumps(report("inconclusive", "configuration_error"), sort_keys=True))
        return 2
    if not math.isfinite(args.timeout) or not 0.1 <= args.timeout <= 60:
        print(json.dumps(report("inconclusive", "configuration_error"), sort_keys=True))
        return 2
    try:
        result = execute(args, *preflight(args))
    except ProbeError as error:
        result = report("inconclusive", error.reason)
        print(json.dumps(result, sort_keys=True))
        return error.exit_code
    except KeyboardInterrupt:
        print(json.dumps(report("inconclusive", "interrupted"), sort_keys=True))
        return 130
    except (OSError, ValueError, subprocess.SubprocessError):
        print(json.dumps(report("inconclusive", "internal_error"), sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
