"""Loopback-only integration tests for the real controller and pinned CLI.

The post-deploy generation/image evidence in these tests is simulated by the
HTTP fixture. No image build, Docker execution, or application-health check is
performed.
"""

import http.client
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "caprover_deploy.py"
PYTHON = Path(sys.executable)
NODE = Path(shutil.which("node") or "/nonexistent/node")
APP = "fixture-app"
ALIAS = "fixture-target"
CANARY = "SYNTHETIC-CANARY-CAPROVER-TOKEN"


@pytest.fixture(scope="module")
def cli_root():
    configured = os.environ.get("CAPROVER_TEST_CLI_ROOT")
    if configured is None:
        pytest.skip("CAPROVER_TEST_CLI_ROOT is absent")
    root = Path(configured)
    required = (root / "package.json", root / "built/commands/caprover.js")
    if not root.is_dir() or any(not path.is_file() for path in required):
        pytest.fail("CAPROVER_TEST_CLI_ROOT does not contain the pinned CapRover CLI")
    if not PYTHON.is_file() or not NODE.is_file():
        pytest.fail("the pinned Python or Node runtime is unavailable")
    return root.resolve()


def _definition(version, git_hash="0" * 40):
    versions = []
    if version:
        versions.append({
            "version": version,
            "deployedImageName": f"fixture.invalid/simulated-image:v{version}",
            "timeStamp": "2026-09-15T00:00:00.000Z",
            "gitHash": git_hash,
        })
    return {
        "appName": APP,
        "description": "loopback fixture",
        "instanceCount": 1,
        "captainDefinitionRelativeFilePath": "captain-definition",
        "envVars": [],
        "volumes": [],
        "notExposeAsWebApp": False,
        "forceSsl": False,
        "ports": [],
        "websocketSupport": False,
        "hasPersistentData": False,
        "hasDefaultSubDomainSsl": False,
        "customDomain": [],
        "networks": ["captain-overlay-network"],
        "deployedVersion": version,
        "versions": versions,
        "isAppBuilding": False,
    }


def _read_request_body(handler):
    length = handler.headers.get("Content-Length")
    if length is not None:
        return handler.rfile.read(int(length))
    if handler.headers.get("Transfer-Encoding", "").lower() != "chunked":
        return b""
    chunks = []
    while True:
        size = int(handler.rfile.readline().split(b";", 1)[0], 16)
        if size == 0:
            handler.rfile.readline()
            return b"".join(chunks)
        chunks.append(handler.rfile.read(size))
        handler.rfile.read(2)


class _FixtureServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, result_mode):
        self.result_mode = result_mode
        self.post_accepted = False
        self.accepted_git_hash = ""
        self.schedule_completed = threading.Event()
        self.requests = []
        super().__init__(("127.0.0.1", 0), _FixtureHandler)


class _FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        return

    def _send_json(self, status, payload):
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        headers = {key.lower(): value for key, value in self.headers.items()}
        self.server.requests.append(("GET", self.path, headers, b""))
        if self.path == "/api/v2/user/system/info/":
            self._send_json(200, {"status": 100, "data": {
                "hasRootSsl": False,
                "forceSsl": False,
                "rootDomain": "fixture.invalid",
                "captainSubDomain": "captain",
            }})
            return
        if self.path in {
            "/api/v2/user/apps/appDefinitions",
            "/api/v2/user/apps/appDefinitions/",
        }:
            deployed = self.server.post_accepted and self.server.result_mode in {
                "updated",
                "wrong_source",
                "async_same_source",
            }
            version = 8 if deployed else 7
            git_hash = (
                "f" * 40
                if self.server.result_mode == "wrong_source"
                else self.server.accepted_git_hash
            )
            definition = _definition(version, git_hash)
            self._send_json(200, {"status": 100, "data": {
                "appDefinitions": [definition]
            }})
            return
        if self.path in {
            f"/api/v2/user/apps/appData/{APP}",
            f"/api/v2/user/apps/appData/{APP}/",
        }:
            self._send_json(200, {"status": 100, "data": {
                "isAppBuilding": False,
                "isBuildFailed": False,
                "logs": {"lines": [], "firstLineNumber": 0},
            }})
            return
        self._send_json(404, {"status": 1100, "data": {}})

    def do_POST(self):
        body = _read_request_body(self)
        headers = {key.lower(): value for key, value in self.headers.items()}
        self.server.requests.append(("POST", self.path, headers, body))
        allowed_path = f"/api/v2/user/apps/appData/{APP}"
        if (
            self.path != allowed_path
            and not (
                self.server.result_mode == "async_same_source"
                and self.path == f"{allowed_path}?detached=1"
            )
        ):
            self._send_json(404, {"status": 1100, "data": {}})
            return
        if self.server.result_mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "/api/v2/login/")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            return
        match = re.search(br'name="gitHash"\r\n\r\n([^\r\n]*)', body)
        assert match is not None
        self.server.accepted_git_hash = match.group(1).decode("ascii")
        self.server.post_accepted = True
        if self.server.result_mode == "schedule_rejected":
            self._send_json(200, {"status": 1108, "data": {}})
            return
        if self.server.result_mode == "async_same_source":
            self._send_json(200, {"status": 101, "data": {}})
            return
        time.sleep(0.05)
        self.server.schedule_completed.set()
        self._send_json(200, {"status": 100, "data": {}})

    def _reject_other_method(self):
        body = _read_request_body(self)
        headers = {key.lower(): value for key, value in self.headers.items()}
        self.server.requests.append((self.command, self.path, headers, body))
        self._send_json(405, {"status": 1100, "data": {}})

    do_DELETE = _reject_other_method
    do_PATCH = _reject_other_method
    do_PUT = _reject_other_method


@contextmanager
def _server(result_mode):
    server = _FixtureServer(result_mode)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _fetch_served_app_definition(server):
    connection = http.client.HTTPConnection(
        server.server_address[0], server.server_address[1], timeout=2
    )
    try:
        connection.request("GET", "/api/v2/user/apps/appDefinitions/")
        response = connection.getresponse()
        body = json.loads(response.read())
    finally:
        connection.close()
    assert response.status == 200
    definitions = body["data"]["appDefinitions"]
    assert len(definitions) == 1
    return definitions[0]


def _protected_json(path, value):
    path.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    path.chmod(0o600)
    return path


def _make_tarball(tmp_path):
    tarball = tmp_path / "fixture-source.tar"
    definition = b'{"schemaVersion":2,"dockerfilePath":"./Dockerfile"}\n'
    with tarfile.open(tarball, "w") as archive:
        info = tarfile.TarInfo("captain-definition")
        info.size = len(definition)
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(definition))
    return tarball


def _make_git_fixture(tmp_path):
    checkout = tmp_path / "source-checkout"
    checkout.mkdir(mode=0o700)
    (checkout / "captain-definition").write_text(
        '{"schemaVersion":2,"dockerfilePath":"./Dockerfile"}\n', encoding="utf-8"
    )
    (checkout / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "LANG": "C"}
    commands = (
        ["/usr/bin/git", "init", "-b", "fixture-main", str(checkout)],
        ["/usr/bin/git", "-C", str(checkout), "add", "captain-definition", "Dockerfile"],
        [
            "/usr/bin/git", "-C", str(checkout),
            "-c", "user.name=Fixture User", "-c", "user.email=fixture@invalid.example",
            "commit", "-m", "fixture commit",
        ],
    )
    for command in commands:
        result = subprocess.run(command, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    return checkout


def _invoke(tmp_path, cli_root, server, source_kind):
    origin = f"http://127.0.0.1:{server.server_port}"
    targets = _protected_json(
        tmp_path / "targets.json",
        {"version": 1, "targets": [{"alias": ALIAS, "origin": origin}]},
    )
    registry = _protected_json(
        tmp_path / "registry.json",
        {"CapMachines": [{"name": ALIAS, "baseUrl": origin, "authToken": CANARY}]},
    )
    original_targets = targets.read_bytes()
    original_registry = registry.read_bytes()
    args = [
        str(PYTHON), str(SCRIPT),
        "--caprover-url", origin,
        "--expected-host", f"127.0.0.1:{server.server_port}",
        "--allow-insecure",
        "--app-name", APP,
        "--method", "cli",
        "--apply",
        "--caprover-name", ALIAS,
        "--targets", str(targets),
        "--registry", str(registry),
        "--cli-root", str(cli_root),
        "--node", str(NODE),
        "--timeout", "3",
    ]
    if source_kind == "tarball":
        args += ["--tarball", str(_make_tarball(tmp_path))]
    else:
        checkout = _make_git_fixture(tmp_path)
        args += ["--source-dir", str(checkout), "--branch", "fixture-main"]
    child_home = tmp_path / "empty-home"
    child_home.mkdir(mode=0o700)
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(child_home),
        "LANG": "C",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )
    assert targets.read_bytes() == original_targets
    assert registry.read_bytes() == original_registry
    assert targets.stat().st_mode & 0o777 == 0o600
    assert registry.stat().st_mode & 0o777 == 0o600
    assert CANARY not in result.stdout + result.stderr
    if source_kind == "branch":
        assert not (tmp_path / "source-checkout" / "temporary-captain-to-deploy.tar").exists()
    return result


def _assert_request_boundary(server):
    allowed_gets = {
        "/api/v2/user/system/info/",
        "/api/v2/user/apps/appDefinitions",
        "/api/v2/user/apps/appDefinitions/",
        f"/api/v2/user/apps/appData/{APP}",
        f"/api/v2/user/apps/appData/{APP}/",
    }
    posts = [request for request in server.requests if request[0] == "POST"]
    assert all(method in {"GET", "POST"} for method, _, _, _ in server.requests)
    assert len(posts) == 1
    assert posts[0][1] == f"/api/v2/user/apps/appData/{APP}"
    assert posts[0][2].get("x-captain-auth") == CANARY
    assert posts[0][2].get("x-namespace") == "captain"
    assert "multipart/form-data" in posts[0][2].get("content-type", "")
    assert b'name="sourceFile"' in posts[0][3]
    assert b'name="gitHash"' in posts[0][3]
    assert all(path in allowed_gets for method, path, _, _ in server.requests if method == "GET")
    assert all("/login" not in path for _, path, _, _ in server.requests)
    assert all("appDefinitions/update" not in path for _, path, _, _ in server.requests)
    assert all("appDefinitions/register" not in path for _, path, _, _ in server.requests)
    assert all("/appData/other" not in path for _, path, _, _ in server.requests)


@pytest.mark.parametrize("source_kind", ["tarball", "branch"])
def test_real_cli_deploy_with_simulated_new_generation(tmp_path, cli_root, source_kind):
    with _server("updated") as server:
        result = _invoke(tmp_path, cli_root, server, source_kind)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "deployment_evidence_verified" in result.stdout
    assert server.schedule_completed.is_set()
    _assert_request_boundary(server)


def test_real_cli_accepted_post_with_stale_simulated_generation_requires_reconciliation(
    tmp_path, cli_root
):
    with _server("stale") as server:
        result = _invoke(tmp_path, cli_root, server, "tarball")

    assert result.returncode != 0
    assert "reconcile_required" in result.stdout
    assert "deployment_evidence_verified" not in result.stdout
    _assert_request_boundary(server)


def test_real_cli_newer_generation_with_wrong_git_sha_is_not_confirmed(tmp_path, cli_root):
    with _server("wrong_source") as server:
        result = _invoke(tmp_path, cli_root, server, "branch")

    assert result.returncode != 0
    assert "reconcile_required" in result.stdout
    assert "deployment_evidence_verified" not in result.stdout
    _assert_request_boundary(server)


def test_real_cli_async_ack_and_matching_source_from_other_build_is_not_confirmed(
    tmp_path, cli_root
):
    with _server("async_same_source") as server:
        result = _invoke(tmp_path, cli_root, server, "branch")
        served_definition = _fetch_served_app_definition(server)
        accepted_git_hash = server.accepted_git_hash

    assert re.fullmatch(r"[a-f0-9]{40}", accepted_git_hash)
    assert served_definition["deployedVersion"] == 8
    assert len(served_definition["versions"]) == 1
    assert served_definition["versions"][0]["version"] == 8
    assert served_definition["versions"][0]["gitHash"] == accepted_git_hash
    assert result.returncode != 0
    assert "reconcile_required" in result.stdout
    assert "deployment_evidence_verified" not in result.stdout
    _assert_request_boundary(server)


def test_real_cli_synchronous_schedule_rejection_is_not_confirmed(tmp_path, cli_root):
    with _server("schedule_rejected") as server:
        result = _invoke(tmp_path, cli_root, server, "tarball")

    assert result.returncode != 0
    assert "reconcile_required" in result.stdout
    assert "deployment_evidence_verified" not in result.stdout
    _assert_request_boundary(server)


def test_real_cli_rejects_deploy_redirect_without_login_or_retry(tmp_path, cli_root):
    with _server("redirect") as server:
        result = _invoke(tmp_path, cli_root, server, "tarball")

    assert result.returncode != 0
    assert "deployment_evidence_verified" not in result.stdout
    _assert_request_boundary(server)
