from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
PROBE = SKILL_ROOT / "scripts" / "probe.py"


def clean_env() -> dict[str, str]:
    blocked = ("CAPROVER_",)
    exact = {
        "NODE_OPTIONS",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "NODE_TLS_REJECT_UNAUTHORIZED",
    }
    return {
        key: value
        for key, value in os.environ.items()
        if key not in exact and not key.startswith(blocked)
    }


def invoke_raw(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PROBE), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env or clean_env(),
        timeout=10,
        check=False,
    )


def invoke(*args: str, env: dict[str, str] | None = None) -> tuple[int, dict]:
    completed = invoke_raw(*args, env=env)
    return completed.returncode, json.loads(completed.stdout)


@pytest.mark.parametrize("args", [(), ("--timeout", "999")])
def test_missing_or_invalid_flags_are_configuration_not_authentication(args: tuple[str, ...]) -> None:
    code, report = invoke(*args)
    assert code == 2
    assert report["status"] == "inconclusive"
    assert report["reason"] == "configuration_error"
    assert "auth" not in report["reason"]


@pytest.mark.parametrize(
    "args",
    [("--unknown-option=argument-canary",), ("--timeout", "timeout-canary")],
)
def test_parser_errors_do_not_echo_supplied_values(args: tuple[str, ...]) -> None:
    completed = invoke_raw(*args)
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["reason"] == "configuration_error"
    assert "canary" not in completed.stdout
    assert "canary" not in completed.stderr
    assert completed.stderr == ""


def test_help_remains_useful_and_successful() -> None:
    completed = invoke_raw("--help")
    assert completed.returncode == 0
    assert "--targets" in completed.stdout
    assert completed.stderr == ""


@pytest.fixture
def cli_root() -> Path:
    configured = os.environ.get("CAPROVER_TEST_CLI_ROOT")
    if not configured:
        pytest.skip("CAPROVER_TEST_CLI_ROOT is required for real CLI fixture tests")
    return Path(configured)


@pytest.fixture
def node() -> str:
    value = shutil.which("node")
    if not value:
        pytest.skip("node is required for real CLI fixture tests")
    return value


class FixtureHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, str, str | None]] = []
    mode = "valid"
    redirect_origin = ""
    mutate = None

    def do_GET(self) -> None:  # noqa: N802 - stdlib interface
        type(self).requests.append(("GET", self.path, self.headers.get("x-captain-auth")))
        if type(self).mutate and self.path.endswith("appDefinitions"):
            type(self).mutate()
        if type(self).mode == "timeout":
            threading.Event().wait(2)
        if type(self).mode == "eof":
            self.connection.shutdown(2)
            self.connection.close()
            return
        if type(self).mode == "redirect":
            self.send_response(302)
            self.send_header("location", type(self).redirect_origin + "/capture")
            self.end_headers()
            return
        if type(self).mode == "transport":
            self.send_response(500)
            self.end_headers()
            return
        if type(self).mode == "forbidden":
            self.send_response(403)
            self.end_headers()
            return
        if type(self).mode == "oversized":
            encoded = json.dumps({"status": 100, "data": {"padding": "x" * 100_000}}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return
        if self.path == "/api/v2/user/apps/appDefinitions":
            if type(self).mode == "invalid_token":
                status = 1106
            elif type(self).mode == "generic_warning":
                status = 1999
            else:
                status = 100
            body = {"status": status, "description": "fixture", "data": {"appDefinitions": []}}
        elif self.path == "/api/v2/user/system/info":
            body = {
                "status": 100,
                "description": "ok",
                "data": {
                    "hasRootSsl": False,
                    "forceSsl": False,
                    "rootDomain": "example.invalid",
                    "captainSubDomain": "captain",
                },
            }
            if type(self).mode == "schema_error":
                body["data"] = {"unknown": True}
            elif type(self).mode == "leak":
                body["data"]["echo"] = self.headers.get("x-captain-auth")
        else:
            body = {"status": 999, "description": "unexpected", "data": {}}
        encoded = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self) -> None:  # noqa: N802 - stdlib interface
        type(self).requests.append(("POST", self.path, self.headers.get("x-captain-auth")))
        self.send_response(500)
        self.end_headers()

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture
def loopback_server():
    FixtureHandler.requests = []
    FixtureHandler.mode = "valid"
    FixtureHandler.redirect_origin = ""
    FixtureHandler.mutate = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, FixtureHandler.requests
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


@pytest.fixture
def capture_server():
    captured: list[tuple[str, str, str | None]] = []

    class CaptureHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib interface
            captured.append(("GET", self.path, self.headers.get("x-captain-auth")))
            self.send_response(500)
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802 - stdlib interface
            captured.append(("POST", self.path, self.headers.get("x-captain-auth")))
            self.send_response(500)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), CaptureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, captured
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def protected_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def protected_bytes(path: Path, value: bytes) -> None:
    path.write_bytes(value)
    path.chmod(0o600)


def json_bytes(value: object) -> bytes:
    return json.dumps(value).encode()


def assert_source_state(path: Path, expected: bytes | None) -> None:
    if expected is None:
        assert not path.exists()
    else:
        assert path.read_bytes() == expected


def probe_args(tmp_path: Path, cli_root: Path, node: str, origin: str, token: str) -> list[str]:
    targets = tmp_path / "targets.json"
    registry = tmp_path / "registry.json"
    protected_json(targets, {"version": 1, "targets": [{"alias": "fixture", "origin": origin}]})
    protected_json(
        registry,
        {"CapMachines": [{"name": "fixture", "baseUrl": origin, "authToken": token}]},
    )
    return [
        "--targets", str(targets), "--target", "fixture",
        "--registry", str(registry), "--cli-root", str(cli_root),
        "--node", node, "--fixture-loopback",
    ]


def test_real_cli_valid_session_schema(
    tmp_path: Path, cli_root: Path, node: str, loopback_server
) -> None:
    server, requests = loopback_server
    token = "fixture-token-canary-not-secret"
    origin = f"http://127.0.0.1:{server.server_port}"
    code, result = invoke(*probe_args(tmp_path, cli_root, node, origin, token))
    assert code == 0
    assert result["status"] == "valid"
    assert result["reason"] == "session_valid"
    assert result["request_count"] == 3
    assert [path for _, path, _ in requests] == [
        "/api/v2/user/apps/appDefinitions",
        "/api/v2/user/system/info",
        "/api/v2/user/system/info",
    ]
    assert all(seen == token for _, _, seen in requests)
    assert token not in json.dumps(result)


def test_secret_canary_never_reaches_probe_console_or_report(
    tmp_path: Path, cli_root: Path, node: str, loopback_server
) -> None:
    server, _ = loopback_server
    FixtureHandler.mode = "leak"
    token = "console-secret-canary"
    origin = f"http://127.0.0.1:{server.server_port}"
    completed = invoke_raw(*probe_args(tmp_path, cli_root, node, origin, token))
    assert completed.returncode == 0
    result = json.loads(completed.stdout)
    assert result["status"] == "valid"
    assert token not in completed.stdout
    assert token not in completed.stderr


def test_invalid_token_is_concrete_auth_evidence_and_never_posts_login(
    tmp_path: Path, cli_root: Path, node: str, loopback_server
) -> None:
    server, requests = loopback_server
    FixtureHandler.mode = "invalid_token"
    origin = f"http://127.0.0.1:{server.server_port}"
    token = "synthetic-token"
    args = probe_args(tmp_path, cli_root, node, origin, token)
    targets, registry = Path(args[1]), Path(args[5])
    targets_before, registry_before = targets.read_bytes(), registry.read_bytes()
    code, result = invoke(*args)
    assert code == 1
    assert result["status"] == "invalid"
    assert result["reason"] == "authentication_rejected"
    assert result["request_count"] == 1
    assert requests == [("GET", "/api/v2/user/apps/appDefinitions", token)]
    assert not any(method == "POST" for method, _, _ in requests)
    assert targets.read_bytes() == targets_before
    assert registry.read_bytes() == registry_before


def test_http_403_is_authorization_evidence(
    tmp_path: Path, cli_root: Path, node: str, loopback_server
) -> None:
    server, requests = loopback_server
    FixtureHandler.mode = "forbidden"
    origin = f"http://127.0.0.1:{server.server_port}"
    code, result = invoke(*probe_args(tmp_path, cli_root, node, origin, "synthetic-token"))
    assert code == 1
    assert result["status"] == "invalid"
    assert result["reason"] == "authorization_denied"
    assert len(requests) == 1


@pytest.mark.parametrize("mode,reason", [
    ("transport", "http_error"),
    ("schema_error", "schema_inconclusive"),
    ("oversized", "guard_violation"),
    ("eof", "network_error"),
    ("generic_warning", "cli_inconclusive"),
])
def test_fail_closed_without_unwarranted_logout_diagnosis(
    mode: str, reason: str, tmp_path: Path, cli_root: Path, node: str, loopback_server
) -> None:
    server, _ = loopback_server
    FixtureHandler.mode = mode
    origin = f"http://127.0.0.1:{server.server_port}"
    code, result = invoke(*probe_args(tmp_path, cli_root, node, origin, "synthetic-token"))
    assert code == 1
    assert result["status"] == "inconclusive"
    assert result["reason"] == reason
    assert "logout" not in json.dumps(result).lower()


def test_timeout_is_inconclusive(
    tmp_path: Path, cli_root: Path, node: str, loopback_server
) -> None:
    server, _ = loopback_server
    FixtureHandler.mode = "timeout"
    origin = f"http://127.0.0.1:{server.server_port}"
    args = probe_args(tmp_path, cli_root, node, origin, "synthetic-token") + ["--timeout", "0.2"]
    code, result = invoke(*args)
    assert code == 1
    assert result["status"] == "inconclusive"
    assert result["reason"] == "timeout"


def child_pids(parent: int) -> list[int]:
    completed = subprocess.run(
        ["/bin/ps", "-axo", "pid=,ppid="],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True,
    )
    rows = (tuple(int(value) for value in line.split()) for line in completed.stdout.splitlines())
    return [pid for pid, ppid in rows if ppid == parent]


def test_child_pids_uses_portable_process_table_and_exact_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "101 7\n102 70\n103 7\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert child_pids(7) == [101, 103]
    assert calls[0][0] == ["/bin/ps", "-axo", "pid=,ppid="]
    assert calls[0][1]["check"] is True


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def terminate_probe_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def test_interrupt_reaps_cli_process_group_and_stops_requests(
    tmp_path: Path, cli_root: Path, node: str, loopback_server
) -> None:
    server, requests = loopback_server
    FixtureHandler.mode = "timeout"
    origin = f"http://127.0.0.1:{server.server_port}"
    process = subprocess.Popen(
        [sys.executable, str(PROBE), *probe_args(tmp_path, cli_root, node, origin, "interrupt-token")],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=clean_env(),
    )
    try:
        deadline = threading.Event()
        observed_children: list[int] = []
        for _ in range(100):
            observed_children = child_pids(process.pid)
            if requests and observed_children:
                break
            deadline.wait(0.02)
        assert requests
        assert observed_children
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=5)
        request_count = len(requests)
        deadline.wait(0.3)
        assert process.returncode == 130
        assert json.loads(stdout)["reason"] == "interrupted"
        assert stderr == ""
        assert len(requests) == request_count
        assert not any(process_exists(pid) for pid in observed_children)
    finally:
        terminate_probe_process(process)


def test_timeout_reaps_cli_process_group_and_stops_requests(
    tmp_path: Path, cli_root: Path, node: str, loopback_server
) -> None:
    server, requests = loopback_server
    FixtureHandler.mode = "timeout"
    origin = f"http://127.0.0.1:{server.server_port}"
    command = [
        sys.executable, str(PROBE),
        *probe_args(tmp_path, cli_root, node, origin, "timeout-token"),
        "--timeout", "0.3",
    ]
    process = subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=clean_env(),
    )
    try:
        observed_children: list[int] = []
        waiter = threading.Event()
        for _ in range(100):
            observed_children = child_pids(process.pid)
            if requests and observed_children:
                break
            waiter.wait(0.01)
        assert requests
        assert observed_children
        stdout, stderr = process.communicate(timeout=5)
        request_count = len(requests)
        waiter.wait(0.3)
        assert process.returncode == 1
        assert json.loads(stdout)["reason"] == "timeout"
        assert stderr == ""
        assert len(requests) == request_count
        assert not any(process_exists(pid) for pid in observed_children)
    finally:
        terminate_probe_process(process)


@pytest.mark.parametrize("case,reason", [
    ("absent", "target_binding_error"),
    ("duplicate", "target_binding_error"),
    ("mismatch", "origin_mismatch"),
])
def test_target_preflight_failures_make_zero_requests(
    case: str, reason: str, tmp_path: Path, cli_root: Path, node: str
) -> None:
    origin = "http://127.0.0.1:9"
    args = probe_args(tmp_path, cli_root, node, origin, "synthetic-token")
    targets = Path(args[1])
    if case == "absent":
        protected_json(targets, {"version": 1, "targets": []})
    elif case == "duplicate":
        item = {"alias": "fixture", "origin": origin}
        protected_json(targets, {"version": 1, "targets": [item, item]})
    else:
        protected_json(targets, {"version": 1, "targets": [{"alias": "fixture", "origin": "http://127.0.0.1:10"}]})
    code, result = invoke(*args)
    assert code == 2
    assert result["reason"] == reason


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:",
        "http://127.0.0.1:080",
        "http://127.0.0.1:0",
        "http://127.0.0.1:65536",
        "http://127.0.0.1:9/path",
        "http://user@127.0.0.1:9",
        "http://127.0.0.1:9?query=1",
        "http://127.0.0.1:9\n",
        "http://127.0.0.1: 9",
    ],
)
def test_malformed_origins_fail_before_cli_execution(
    origin: str, tmp_path: Path, cli_root: Path, node: str
) -> None:
    args = probe_args(tmp_path, cli_root, node, "http://127.0.0.1:9", "synthetic-token")
    targets, registry = Path(args[1]), Path(args[5])
    protected_json(targets, {"version": 1, "targets": [{"alias": "fixture", "origin": origin}]})
    protected_json(registry, {"CapMachines": [{"name": "fixture", "baseUrl": origin, "authToken": "token"}]})
    code, result = invoke(*args)
    assert code == 2
    assert result["reason"] == "configuration_error"


@pytest.mark.parametrize("which", ["targets", "registry"])
def test_duplicate_json_keys_are_rejected(which: str, tmp_path: Path, cli_root: Path, node: str) -> None:
    args = probe_args(tmp_path, cli_root, node, "http://127.0.0.1:9", "synthetic-token")
    path = Path(args[1] if which == "targets" else args[5])
    if which == "targets":
        path.write_text('{"version":1,"version":1,"targets":[]}', encoding="utf-8")
    else:
        path.write_text('{"CapMachines":[],"CapMachines":[]}', encoding="utf-8")
    path.chmod(0o600)
    code, result = invoke(*args)
    assert code == 2
    assert result["reason"] == "configuration_error"


@pytest.mark.parametrize(
    "registry",
    [
        {"bogus": []},
        {"CapMachines": "fixture"},
        {"CapMachines": [{"name": 1, "baseUrl": "http://127.0.0.1:9", "authToken": "token"}]},
        {"CapMachines": [{"name": "fixture", "baseUrl": "http://127.0.0.1:9", "authToken": 1}]},
    ],
)
def test_bogus_registry_schema_fails_closed(
    registry: object, tmp_path: Path, cli_root: Path, node: str
) -> None:
    args = probe_args(tmp_path, cli_root, node, "http://127.0.0.1:9", "synthetic-token")
    protected_json(Path(args[5]), registry)
    code, result = invoke(*args)
    assert code == 2
    assert result["reason"] == "registry_schema_error"


@pytest.mark.parametrize("case", ["symlink", "fifo", "loose_permissions"])
def test_protected_config_inputs_fail_closed(
    case: str, tmp_path: Path, cli_root: Path, node: str
) -> None:
    args = probe_args(tmp_path, cli_root, node, "http://127.0.0.1:9", "synthetic-token")
    target = Path(args[1])
    if case == "symlink":
        source = tmp_path / "source.json"
        protected_json(source, {"version": 1, "targets": []})
        target.unlink()
        target.symlink_to(source)
    elif case == "fifo":
        target.unlink()
        os.mkfifo(target, 0o600)
    else:
        target.chmod(0o644)
    code, result = invoke(*args)
    assert code == 2
    assert result["reason"] == "protected_file_permissions"


@pytest.mark.parametrize("marker_kind", ["directory", "file"])
def test_protected_config_inside_git_fails_before_http(
    marker_kind: str, tmp_path: Path, cli_root: Path, node: str
) -> None:
    repository = tmp_path / "synthetic-repository"
    repository.mkdir()
    marker = repository / ".git"
    if marker_kind == "directory":
        marker.mkdir()
    else:
        marker.write_text("gitdir: /nonexistent\n", encoding="utf-8")
    credentials = repository / "private" / "config"
    credentials.mkdir(parents=True)
    args = probe_args(credentials, cli_root, node, "http://127.0.0.1:9", "synthetic-token")
    code, result = invoke(*args)
    assert code == 2
    assert result["status"] == "inconclusive"
    assert result["reason"] == "configuration_error"
    assert result["request_count"] == 0
    assert result["response_count"] == 0


def test_source_mutation_cannot_redirect_or_overwrite_registry(
    tmp_path: Path, cli_root: Path, node: str, loopback_server, capture_server
) -> None:
    server, requests = loopback_server
    changed_server, captured = capture_server
    origin = f"http://127.0.0.1:{server.server_port}"
    changed_origin = f"http://127.0.0.1:{changed_server.server_port}"
    token = "mutation-canary"
    args = probe_args(tmp_path, cli_root, node, origin, token)
    targets, registry = Path(args[1]), Path(args[5])
    targets_after = json_bytes(
        {"version": 1, "targets": [{"alias": "fixture", "origin": changed_origin}]}
    )
    registry_after = json_bytes({"CapMachines": []})

    def mutate() -> None:
        protected_bytes(targets, targets_after)
        protected_bytes(registry, registry_after)

    FixtureHandler.mutate = mutate
    code, result = invoke(*args)
    assert code != 0
    assert result["status"] == "inconclusive"
    assert result["reason"] == "source_changed"
    assert requests == [
        ("GET", "/api/v2/user/apps/appDefinitions", token),
        ("GET", "/api/v2/user/system/info", token),
        ("GET", "/api/v2/user/system/info", token),
    ]
    assert captured == []
    assert_source_state(targets, targets_after)
    assert_source_state(registry, registry_after)


@pytest.mark.parametrize(
    ("source", "mutation"),
    [
        ("targets", "content"),
        ("registry", "content"),
        ("targets", "same_content_replacement"),
        ("registry", "same_content_replacement"),
        ("targets", "deletion"),
        ("registry", "deletion"),
    ],
)
def test_single_source_mutation_is_inconclusive_without_redirect_or_overwrite(
    source: str,
    mutation: str,
    tmp_path: Path,
    cli_root: Path,
    node: str,
    loopback_server,
    capture_server,
) -> None:
    server, requests = loopback_server
    changed_server, captured = capture_server
    origin = f"http://127.0.0.1:{server.server_port}"
    changed_origin = f"http://127.0.0.1:{changed_server.server_port}"
    token = "single-source-mutation-canary"
    args = probe_args(tmp_path, cli_root, node, origin, token)
    targets, registry = Path(args[1]), Path(args[5])
    before = {"targets": targets.read_bytes(), "registry": registry.read_bytes()}
    paths = {"targets": targets, "registry": registry}
    mutated = paths[source]
    expected: dict[str, bytes | None] = dict(before)
    identity: dict[str, tuple[int, int]] = {}

    if source == "targets":
        changed_bytes = json_bytes(
            {"version": 1, "targets": [{"alias": "fixture", "origin": changed_origin}]}
        )
    else:
        changed_bytes = json_bytes(
            {
                "CapMachines": [
                    {
                        "name": "fixture",
                        "baseUrl": changed_origin,
                        "authToken": "changed-destination-token",
                    }
                ]
            }
        )

    def mutate() -> None:
        if mutation == "content":
            protected_bytes(mutated, changed_bytes)
            expected[source] = changed_bytes
        elif mutation == "same_content_replacement":
            replacement = mutated.with_name(f".{mutated.name}.replacement")
            protected_bytes(replacement, before[source])
            old = mutated.stat()
            os.replace(replacement, mutated)
            new = mutated.stat()
            identity["old"] = (old.st_dev, old.st_ino)
            identity["new"] = (new.st_dev, new.st_ino)
        else:
            mutated.unlink()
            expected[source] = None

    FixtureHandler.mutate = mutate
    code, result = invoke(*args)
    assert code != 0
    assert result["status"] == "inconclusive"
    assert result["reason"] == "source_changed"
    assert requests == [
        ("GET", "/api/v2/user/apps/appDefinitions", token),
        ("GET", "/api/v2/user/system/info", token),
        ("GET", "/api/v2/user/system/info", token),
    ]
    assert captured == []
    assert_source_state(targets, expected["targets"])
    assert_source_state(registry, expected["registry"])
    if mutation == "same_content_replacement":
        assert identity["new"] != identity["old"]


def test_unchanged_sources_remain_valid_and_preserve_both_files(
    tmp_path: Path, cli_root: Path, node: str, loopback_server
) -> None:
    server, requests = loopback_server
    origin = f"http://127.0.0.1:{server.server_port}"
    token = "preserve-canary"
    args = probe_args(tmp_path, cli_root, node, origin, token)
    targets, registry = Path(args[1]), Path(args[5])
    targets_before, registry_before = targets.read_bytes(), registry.read_bytes()
    code, result = invoke(*args)
    assert code == 0
    assert result["status"] == "valid"
    assert result["reason"] == "session_valid"
    assert requests == [
        ("GET", "/api/v2/user/apps/appDefinitions", token),
        ("GET", "/api/v2/user/system/info", token),
        ("GET", "/api/v2/user/system/info", token),
    ]
    assert targets.read_bytes() == targets_before
    assert registry.read_bytes() == registry_before


def test_source_change_takes_precedence_over_authentication_rejection(
    tmp_path: Path,
    cli_root: Path,
    node: str,
    loopback_server,
    capture_server,
) -> None:
    server, requests = loopback_server
    changed_server, captured = capture_server
    FixtureHandler.mode = "invalid_token"
    origin = f"http://127.0.0.1:{server.server_port}"
    changed_origin = f"http://127.0.0.1:{changed_server.server_port}"
    token = "rejected-mutation-canary"
    args = probe_args(tmp_path, cli_root, node, origin, token)
    targets, registry = Path(args[1]), Path(args[5])
    registry_before = registry.read_bytes()
    targets_after = json_bytes(
        {"version": 1, "targets": [{"alias": "fixture", "origin": changed_origin}]}
    )

    def mutate() -> None:
        protected_bytes(targets, targets_after)

    FixtureHandler.mutate = mutate
    code, result = invoke(*args)
    assert code != 0
    assert result["status"] == "inconclusive"
    assert result["reason"] == "source_changed"
    assert requests == [("GET", "/api/v2/user/apps/appDefinitions", token)]
    assert captured == []
    assert_source_state(targets, targets_after)
    assert_source_state(registry, registry_before)


def test_redirect_is_rejected_without_external_token_delivery(
    tmp_path: Path, cli_root: Path, node: str, loopback_server
) -> None:
    source, _ = loopback_server
    captured: list[tuple[str, str, str | None]] = []

    class CaptureHandler(FixtureHandler):
        requests = captured

    external = ThreadingHTTPServer(("127.0.0.1", 0), CaptureHandler)
    thread = threading.Thread(target=external.serve_forever, daemon=True)
    thread.start()
    try:
        FixtureHandler.mode = "redirect"
        FixtureHandler.redirect_origin = f"http://127.0.0.1:{external.server_port}"
        origin = f"http://127.0.0.1:{source.server_port}"
        code, result = invoke(*probe_args(tmp_path, cli_root, node, origin, "redirect-canary"))
        assert code == 1
        assert result["reason"] == "guard_violation"
        assert captured == []
    finally:
        external.shutdown(); thread.join(timeout=2); external.server_close()


def test_missing_guard_fails_closed(tmp_path: Path, cli_root: Path, node: str) -> None:
    copied = tmp_path / "copy"
    copied.mkdir()
    copied_probe = copied / "probe.py"
    shutil.copyfile(PROBE, copied_probe)
    origin = "http://127.0.0.1:9"
    args = probe_args(tmp_path, cli_root, node, origin, "synthetic-token")
    completed = subprocess.run(
        [sys.executable, str(copied_probe), *args], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, text=True, env=clean_env(), check=False,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["reason"] == "guard_incompatible"


def test_incompatible_guard_fails_closed(tmp_path: Path, cli_root: Path, node: str) -> None:
    copied = tmp_path / "copy"
    copied.mkdir()
    copied_probe = copied / "probe.py"
    copied_guard = copied / "readonly_guard.cjs"
    shutil.copyfile(PROBE, copied_probe)
    source = (SKILL_ROOT / "scripts" / "readonly_guard.cjs").read_text(encoding="utf-8")
    copied_guard.write_text(source.replace("not a general Node.js sandbox", "not a generic Node.js sandbox"), encoding="utf-8")
    origin = "http://127.0.0.1:9"
    args = probe_args(tmp_path, cli_root, node, origin, "synthetic-token")
    completed = subprocess.run(
        [sys.executable, str(copied_probe), *args], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, text=True, env=clean_env(), check=False,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["reason"] == "guard_incompatible"


def test_mutated_cli_source_is_incompatible_before_execution(
    tmp_path: Path, cli_root: Path, node: str
) -> None:
    copied = tmp_path / "cli"
    for relative in [
        "package.json",
        "built/commands/caprover.js",
        "built/commands/api.js",
        "built/api/HttpClient.js",
        "built/api/CliApiManager.js",
        "built/api/ApiManager.js",
        "built/utils/StorageHelper.js",
        "built/utils/CliHelper.js",
    ]:
        destination = copied / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cli_root / relative, destination)
    source = copied / "built/api/ApiManager.js"
    source.write_bytes(source.read_bytes() + b"\n// changed\n")
    args = probe_args(tmp_path, copied, node, "http://127.0.0.1:9", "synthetic-token")
    code, result = invoke(*args)
    assert code == 2
    assert result["reason"] == "cli_incompatible"


def guard_run(node: str, origin: str, script: str, token: str = "fixture-token") -> tuple[subprocess.CompletedProcess[bytes], str]:
    read_fd, write_fd = os.pipe()
    nonce = "fixture-nonce"
    policy = base64.urlsafe_b64encode(json.dumps({
        "guardVersion": 1,
        "origin": origin,
        "nonce": nonce,
        "authTokenSha256": hashlib.sha256(token.encode()).hexdigest(),
        "appTokenSha256": None,
    }).encode()).decode().rstrip("=")
    env = {
        "PATH": str(Path(node).parent), "HOME": "/nonexistent", "CI": "1",
        "CAPROVER_PROBE_INTERNAL_POLICY": policy,
        "CAPROVER_PROBE_INTERNAL_EVENT_FD": str(write_fd),
    }
    try:
        completed = subprocess.run(
            [node, "--require", str(SKILL_ROOT / "scripts" / "readonly_guard.cjs"), "-e", script],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, pass_fds=(write_fd,), timeout=5, check=False,
        )
    finally:
        os.close(write_fd)
    events = os.read(read_fd, 65536).decode()
    os.close(read_fd)
    return completed, events


@pytest.mark.parametrize(
    "method,path",
    [("POST", "/api/v2/login"), ("GET", "/api/v2/user/registries")],
)
def test_guard_blocks_forbidden_method_or_endpoint(node: str, method: str, path: str) -> None:
    script = (
        "require('http').request({hostname:'127.0.0.1',port:9,"
        f"path:{json.dumps(path)},method:{json.dumps(method)}}}).end()"
    )
    completed, events = guard_run(node, "http://127.0.0.1:9", script)
    assert completed.returncode != 0
    assert '"type":"violation"' in events
    assert '"kind":"method"' in events or '"kind":"sequence"' in events


def test_guard_uses_final_merged_destination_and_delivers_no_token(
    node: str, loopback_server
) -> None:
    trusted, trusted_requests = loopback_server
    captured: list[tuple[str, str, str | None]] = []

    class CaptureHandler(FixtureHandler):
        requests = captured

    other = ThreadingHTTPServer(("127.0.0.1", 0), CaptureHandler)
    thread = threading.Thread(target=other.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f"http://127.0.0.1:{trusted.server_port}"
        url = origin + "/api/v2/user/apps/appDefinitions"
        script = (
            "require('http').request("
            f"{json.dumps(url)},"
            "{hostname:'127.0.0.1',"
            f"port:{other.server_port},"
            "method:'GET',headers:{'x-captain-auth':'fixture-token','x-namespace':'captain'}}"
            ").end()"
        )
        completed, events = guard_run(node, origin, script)
        assert completed.returncode != 0
        assert '"kind":"origin"' in events
        assert trusted_requests == []
        assert captured == []
    finally:
        other.shutdown()
        thread.join(timeout=2)
        other.server_close()


@pytest.mark.parametrize(
    "options,kind",
    [
        ("socketPath:'/tmp/nonexistent-probe-socket'", "socket_path"),
        ("createConnection:()=>{throw new Error('unexpected')}", "custom_connection"),
        ("lookup:()=>{}", "custom_connection"),
        ("proxy:'http://127.0.0.1:10'", "proxy"),
        ("agent:{addRequest(){}}", "agent"),
    ],
)
def test_guard_rejects_custom_egress_controls(node: str, options: str, kind: str) -> None:
    script = (
        "require('http').request({hostname:'127.0.0.1',port:9,"
        "path:'/api/v2/user/apps/appDefinitions',method:'GET',"
        "headers:{'x-captain-auth':'fixture-token','x-namespace':'captain'},"
        f"{options}}}).end()"
    )
    completed, events = guard_run(node, "http://127.0.0.1:9", script)
    assert completed.returncode != 0
    assert f'"kind":"{kind}"' in events
    assert '"type":"request"' not in events


def test_guard_allows_nodes_standard_http_agent(node: str) -> None:
    script = (
        "const h=require('http');"
        "const r=h.request({hostname:'127.0.0.1',port:9,path:'/api/v2/user/apps/appDefinitions',"
        "method:'GET',headers:{'x-captain-auth':'fixture-token','x-namespace':'captain'},agent:new h.Agent()});"
        "r.on('error',()=>{});r.end()"
    )
    completed, events = guard_run(node, "http://127.0.0.1:9", script)
    assert completed.returncode == 0
    assert '"type":"request"' in events
    assert '"type":"violation"' not in events


@pytest.mark.parametrize(
    "url_suffix",
    ["?query=1", "#fragment", "?path=/api/v2/user/system/info"],
)
def test_guard_rejects_query_and_fragment_tricks(node: str, url_suffix: str) -> None:
    url = "http://127.0.0.1:9/api/v2/user/apps/appDefinitions" + url_suffix
    script = (
        f"require('http').request({json.dumps(url)},"
        "{method:'GET',headers:{'x-captain-auth':'fixture-token','x-namespace':'captain'}}).end()"
    )
    completed, events = guard_run(node, "http://127.0.0.1:9", script)
    assert completed.returncode != 0
    assert '"type":"violation"' in events


def test_guard_rejects_url_userinfo(node: str) -> None:
    script = (
        "require('http').request('http://user@127.0.0.1:9/api/v2/user/apps/appDefinitions',"
        "{method:'GET',headers:{'x-captain-auth':'fixture-token','x-namespace':'captain'}}).end()"
    )
    completed, events = guard_run(node, "http://127.0.0.1:9", script)
    assert completed.returncode != 0
    assert '"kind":"userinfo"' in events
    assert '"type":"request"' not in events


def test_guard_requires_expected_token_header(node: str) -> None:
    script = (
        "require('http').request({hostname:'127.0.0.1',port:9,"
        "path:'/api/v2/user/apps/appDefinitions',method:'GET',"
        "headers:{'x-captain-auth':'wrong-token','x-namespace':'captain'}}).end()"
    )
    completed, events = guard_run(node, "http://127.0.0.1:9", script)
    assert completed.returncode != 0
    assert '"kind":"token_header"' in events
    assert '"type":"request"' not in events


def test_guard_pins_three_request_event_sequence_and_blocks_a_fourth(node: str) -> None:
    paths = [
        "/api/v2/user/apps/appDefinitions",
        "/api/v2/user/system/info",
        "/api/v2/user/system/info",
        "/api/v2/user/system/info",
    ]
    calls = "".join(
        "{const r=h.request({hostname:'127.0.0.1',port:9,"
        f"path:{json.dumps(path)},method:'GET',"
        "headers:{'x-captain-auth':'fixture-token','x-namespace':'captain'}});"
        "r.on('error',()=>{});r.end();}"
        for path in paths
    )
    completed, raw_events = guard_run(node, "http://127.0.0.1:9", "const h=require('http');" + calls)
    events = [json.loads(line) for line in raw_events.splitlines()]
    requests = [
        (event["sequence"], event["endpoint"])
        for event in events if event.get("type") == "request"
    ]
    assert completed.returncode != 0
    assert requests == [(1, "auth_check"), (2, "captain_info"), (3, "session_probe")]
    assert any(event.get("type") == "violation" and event.get("kind") == "sequence" for event in events)


def test_environment_pollution_fails_before_network(
    tmp_path: Path, cli_root: Path, node: str
) -> None:
    origin = "http://127.0.0.1:9"
    env = clean_env()
    env["CAPROVER_URL"] = origin
    code, result = invoke(*probe_args(tmp_path, cli_root, node, origin, "synthetic-token"), env=env)
    assert code == 2
    assert result["reason"] == "environment_pollution"


def test_loopback_transport_failure_is_network_not_logout(
    tmp_path: Path, cli_root: Path, node: str
) -> None:
    # Port 9 is an explicit loopback-only negative fixture; no external host or
    # CapRover service is contacted.
    args = probe_args(tmp_path, cli_root, node, "http://127.0.0.1:9", "transport-canary")
    code, result = invoke(*args, *("--timeout", "2"))
    assert code == 1
    assert result["status"] == "inconclusive"
    assert result["reason"] in {"network_error", "cli_error"}
    assert "logout" not in json.dumps(result).lower()
