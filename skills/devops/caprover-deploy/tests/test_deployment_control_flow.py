import importlib.util
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "caprover_deploy.py"
spec = importlib.util.spec_from_file_location("caprover_deploy_control", SCRIPT)
cd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cd)

CLI_ROOT = "/fixture/caprover-2.4.4"
NODE = shutil.which("node") or "node"


@pytest.fixture(autouse=True)
def _stub_cli_layout_validation(monkeypatch):
    monkeypatch.setattr(
        cd,
        "_trusted_cli_capability",
        lambda args: (Path(args.cli_root), Path(args.node)),
    )


def _protected_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)
    return str(path)


def _saved_session_args(tmp_path, origin="https://captain.example.com"):
    targets = _protected_json(
        tmp_path / "targets.json",
        {"version": 1, "targets": [{"alias": "prod", "origin": origin}]},
    )
    registry = _protected_json(
        tmp_path / "registry.json",
        {"CapMachines": [{"name": "prod", "baseUrl": origin, "authToken": "saved-token"}]},
    )
    return [
        "--caprover-name", "prod",
        "--targets", targets,
        "--registry", registry,
        "--cli-root", CLI_ROOT,
        "--node", NODE,
    ]


def test_explicit_cli_rejects_remote_repo_before_credentials_or_fallback(monkeypatch, capsys):
    monkeypatch.setattr(cd, "get_password", lambda args: pytest.fail("password resolved"))
    monkeypatch.setattr(cd, "get_github_creds", lambda args: pytest.fail("repo credential resolved"))
    monkeypatch.setattr(cd, "deploy_via_api", lambda *args: pytest.fail("API fallback attempted"))
    monkeypatch.setattr(cd, "deploy_via_playwright", lambda *args: pytest.fail("browser fallback attempted"))

    with pytest.raises(SystemExit) as exc:
        cd.main([
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--app-name", "my-app",
            "--repo", "https://github.com/org/repo",
            "--branch", "main",
            "--method", "cli",
            "--apply",
        ])

    assert exc.value.code == 2
    assert "caprover_config_invalid" in capsys.readouterr().out


def test_api_tarball_is_rejected_before_any_write_or_credential(monkeypatch, tmp_path, capsys):
    tarball = tmp_path / "source.tar"
    tarball.write_bytes(b"fixture")
    monkeypatch.setattr(cd, "get_password", lambda args: pytest.fail("password resolved"))
    monkeypatch.setattr(cd, "CapRoverAPI", lambda *args: pytest.fail("HTTP client created"))

    with pytest.raises(SystemExit) as exc:
        cd.main([
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--app-name", "my-app",
            "--tarball", str(tarball),
            "--method", "api",
            "--apply",
        ])

    assert exc.value.code == 2
    assert "caprover_config_invalid" in capsys.readouterr().out


def test_keepass_exception_detail_is_sanitized(monkeypatch, capsys):
    monkeypatch.delenv("CAPROVER_PASSWORD", raising=False)
    monkeypatch.setenv("KEEPASS_DB", "/private/SENSITIVE-CANARY.kdbx")
    monkeypatch.setenv("KEEPASS_KEY", "/private/SENSITIVE-CANARY.key")
    monkeypatch.setattr(
        cd.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("SENSITIVE-CANARY-token-path")),
    )
    monkeypatch.setitem(sys.modules, "getpass", SimpleNamespace(getpass=lambda prompt: "fallback"))

    assert cd.get_password(SimpleNamespace(keepass_entry="entry")) == "fallback"
    captured = capsys.readouterr()
    assert "SENSITIVE-CANARY" not in captured.out + captured.err


def test_safe_plan_selects_api_without_resolving_credentials(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cd, "get_password", lambda args: pytest.fail("password resolved"))
    monkeypatch.setattr(cd, "get_github_creds", lambda args: pytest.fail("repo credential resolved"))

    assert cd.main([
        "--caprover-url", "https://captain.example.com",
        "--expected-host", "captain.example.com",
        "--app-name", "my-app",
        "--repo", "https://github.com/org/repo",
        "--branch", "main",
        "--configure-only",
        "--recovery-snapshot", str(tmp_path / "recovery.json"),
    ]) == 0

    output = capsys.readouterr().out
    assert "deployment_plan" in output
    assert "method=api" in output
    assert "apply_required" in output


def test_valid_saved_cli_session_never_resolves_password_or_logs_in(monkeypatch, tmp_path, capsys):
    tarball = tmp_path / "source.tar"
    tarball.write_bytes(b"fixture")
    calls = []

    class API:
        def __init__(self, base_url, token=None):
            calls.append(("api", base_url, token))

        def login(self, password):
            pytest.fail("login attempted")

        def preflight(self, app_name, allow_create=False):
            return True

        def get_app_definition(self, app_name):
            return {"appName": app_name, "deployedVersion": 7, "versions": []}

        def _validate_app_definition(self, value, app_name):
            pass

        def wait_for_build(self, app_name, timeout=300, baseline=None):
            return True, {"isAppBuilding": False, "isBuildFailed": False}

    monkeypatch.setattr(cd, "CapRoverAPI", API)
    monkeypatch.setattr(cd, "get_password", lambda args: pytest.fail("password resolved"))
    monkeypatch.setattr(cd, "try_cli_deploy", lambda args, session: calls.append(("cli", session.copy())) or True)
    monkeypatch.setattr(
        cd,
        "verify_deploy",
        lambda api, app, ssh_cmd=None, baseline=None, expected_source_id=None: True,
    )

    assert cd.main([
        "--caprover-url", "https://captain.example.com",
        "--expected-host", "captain.example.com",
        "--app-name", "my-app",
        "--tarball", str(tarball),
        "--method", "cli",
        "--apply",
        *_saved_session_args(tmp_path),
    ]) == 0

    assert calls[0] == ("api", "https://captain.example.com", "saved-token")
    assert calls[1][0] == "cli"
    assert "deployment_evidence_verified" in capsys.readouterr().out


def test_saved_session_url_mismatch_makes_zero_http_requests(monkeypatch, tmp_path, capsys):
    tarball = tmp_path / "source.tar"
    tarball.write_bytes(b"fixture")
    monkeypatch.setattr(cd, "CapRoverAPI", lambda *args, **kwargs: pytest.fail("HTTP client created"))
    monkeypatch.setattr(cd, "get_password", lambda args: pytest.fail("password resolved"))

    with pytest.raises(SystemExit) as exc:
        cd.main([
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--app-name", "my-app",
            "--tarball", str(tarball),
            "--method", "cli",
            "--apply",
            *_saved_session_args(tmp_path, origin="https://other.example.com"),
        ])

    assert exc.value.code == 2
    assert "caprover_config_invalid" in capsys.readouterr().out


@pytest.mark.parametrize(
    "typed_code",
    ["caprover_network_blocked", "caprover_response_inconclusive"],
)
def test_explicit_login_preserves_typed_failure_code(monkeypatch, tmp_path, capsys, typed_code):
    class API:
        def __init__(self, base_url, token=None):
            pass

        def login(self, password):
            raise cd.CapRoverDeployError(typed_code)

    monkeypatch.setattr(cd, "CapRoverAPI", API)
    monkeypatch.setattr(cd, "get_password", lambda args: "synthetic-password")
    monkeypatch.setattr(cd.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setenv("CAPROVER_CREDENTIAL_ORIGIN", "https://captain.example.com")
    _install_fake_playwright(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        cd.main([
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--app-name", "my-app",
            "--rebuild-only",
            "--git-sha", "1" * 40,
            "--method", "playwright",
            "--apply",
            "--allow-login",
        ])

    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert typed_code in output
    assert "caprover_auth_blocked" not in output


@pytest.mark.parametrize(
    "targets",
    [
        {"version": 1, "targets": [{"alias": 7, "origin": "https://captain.example.com"}]},
        {"version": 1, "targets": [{"alias": "prod", "origin": 7}]},
        {"version": 1, "targets": [{"alias": "prod", "origin": "https://@captain.example.com"}]},
    ],
)
def test_malformed_protected_target_values_fail_typed_before_http(
    monkeypatch, tmp_path, capsys, targets
):
    registry = _protected_json(
        tmp_path / "registry.json",
        {"CapMachines": [{"name": "prod", "baseUrl": "https://captain.example.com", "authToken": "token"}]},
    )
    target_path = _protected_json(tmp_path / "targets.json", targets)
    monkeypatch.setattr(cd, "CapRoverAPI", lambda *args, **kwargs: pytest.fail("HTTP client created"))
    args = SimpleNamespace(
        targets=target_path,
        registry=registry,
        caprover_name="prod",
        caprover_url="https://captain.example.com",
        allow_insecure=False,
    )

    with pytest.raises(cd.CapRoverDeployError) as exc:
        cd.load_saved_session(args)

    assert exc.value.code == "caprover_config_invalid"
    assert "Traceback" not in capsys.readouterr().err


def test_protected_session_files_inside_git_are_rejected(tmp_path):
    git_root = tmp_path / "checkout"
    git_root.mkdir()
    (git_root / ".git").mkdir()
    protected = _protected_json(git_root / "targets.json", {"version": 1, "targets": []})

    with pytest.raises(cd.CapRoverDeployError) as exc:
        cd._read_protected_json(protected)

    assert exc.value.code == "caprover_config_invalid"


def test_cli_uses_pinned_binary_private_session_and_clean_environment(monkeypatch, tmp_path, capsys):
    tarball = tmp_path / "source.tar"
    tarball.write_bytes(b"fixture")
    seen = {}

    class Process:
        pid = 12345
        returncode = 0

        def __init__(self, command, **kwargs):
            seen["command"] = command
            seen["kwargs"] = kwargs
            seen["source_bytes"] = Path(
                command[command.index("--tarFile") + 1]
            ).read_bytes()
            registry = Path(kwargs["env"]["XDG_CONFIG_HOME"]) / "configstore" / "caprover.json"
            seen["registry"] = json.loads(registry.read_text(encoding="utf-8"))
            self.event_fd = kwargs["pass_fds"][0]

        def wait(self, timeout):
            for event in (
                {"type": "guard_ready"},
                {"type": "deploy_request", "app": "my-app"},
                {"type": "deploy_response", "captainStatus": 100},
            ):
                os.write(self.event_fd, (json.dumps(event) + "\n").encode())
            return self.returncode

        def poll(self):
            return self.returncode

    def popen(command, **kwargs):
        return Process(command, **kwargs)

    monkeypatch.setattr(cd.subprocess, "Popen", popen)
    monkeypatch.setenv("CAPROVER_URL", "https://attacker.example")
    monkeypatch.setenv("CAPROVER_PASSWORD", "caller-secret")
    monkeypatch.setenv("HTTP_PROXY", "http://attacker.example")
    args = type("Args", (), {
        "app_name": "my-app",
        "tarball": str(tarball),
        "source_dir": None,
        "branch": None,
        "timeout": 30,
        "cli_capability": (Path(CLI_ROOT), Path(NODE)),
        "expected_source_id": "sha256:" + hashlib.sha256(tarball.read_bytes()).hexdigest(),
    })()
    session = {
        "name": "prod",
        "baseUrl": "https://captain.example.com",
        "authToken": "saved-token",
    }

    assert cd.try_cli_deploy(args, session) is True
    command = seen["command"]
    assert command[0] == NODE
    assert command[1:3] == ["--require", str(SCRIPT.parent / "deployment_guard.cjs")]
    assert "--caproverName" in command and command[command.index("--caproverName") + 1] == "prod"
    assert "--caproverApp" in command and command[command.index("--caproverApp") + 1] == "my-app"
    assert "--tarFile" in command
    private_snapshot = Path(command[command.index("--tarFile") + 1])
    assert private_snapshot != tarball
    assert private_snapshot.parent.name.startswith("caprover-deploy-")
    assert seen["source_bytes"] == tarball.read_bytes()
    assert "saved-token" not in command and "caller-secret" not in command
    assert seen["registry"] == {"CapMachines": [session]}
    env = seen["kwargs"]["env"]
    assert "CAPROVER_URL" not in env and "CAPROVER_PASSWORD" not in env and "HTTP_PROXY" not in env
    assert "saved-token" not in repr(env)
    assert seen["kwargs"]["stdin"] is cd.subprocess.DEVNULL
    assert seen["kwargs"]["start_new_session"] is True
    policy = json.loads(base64.urlsafe_b64decode(
        env["CAPROVER_DEPLOY_INTERNAL_POLICY"] + "=="
    ))
    assert policy["guardVersion"] == 3
    assert policy["expectedSourceId"] == args.expected_source_id
    captured = capsys.readouterr()
    assert "SENSITIVE" not in captured.out + captured.err
    assert "saved-token" not in captured.out + captured.err


def test_cli_rejects_asynchronous_upload_acknowledgement(monkeypatch, tmp_path):
    tarball = tmp_path / "source.tar"
    tarball.write_bytes(b"fixture")

    class Process:
        pid = 12345
        returncode = 0

        def __init__(self, command, **kwargs):
            self.event_fd = kwargs["pass_fds"][0]

        def wait(self, timeout):
            for event in (
                {"type": "guard_ready"},
                {"type": "deploy_request", "app": "my-app"},
                {"type": "deploy_response", "captainStatus": 101},
            ):
                os.write(self.event_fd, (json.dumps(event) + "\n").encode())

        def poll(self):
            return self.returncode

    monkeypatch.setattr(cd.subprocess, "Popen", Process)
    args = SimpleNamespace(
        app_name="my-app",
        tarball=str(tarball),
        source_dir=None,
        branch=None,
        timeout=30,
        cli_capability=(Path(CLI_ROOT), Path(NODE)),
        expected_source_id="sha256:" + hashlib.sha256(tarball.read_bytes()).hexdigest(),
    )
    session = {
        "name": "prod",
        "baseUrl": "https://captain.example.com",
        "authToken": "saved-token",
    }

    with pytest.raises(cd.CapRoverDeployError, match="reconcile_required"):
        cd.try_cli_deploy(args, session)


def test_local_git_archive_uses_resolved_commit_not_movable_branch(
    monkeypatch, tmp_path
):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    resolved_sha = "1" * 40
    seen = {}

    class Process:
        pid = 12345
        returncode = 0

        def __init__(self, command, **kwargs):
            seen["command"] = command
            self.event_fd = kwargs["pass_fds"][0]

        def wait(self, timeout):
            for event in (
                {"type": "guard_ready"},
                {"type": "deploy_request", "app": "my-app"},
                {"type": "deploy_response", "captainStatus": 100},
            ):
                os.write(self.event_fd, (json.dumps(event) + "\n").encode())

        def poll(self):
            return self.returncode

    monkeypatch.setattr(cd.subprocess, "Popen", Process)
    args = SimpleNamespace(
        app_name="my-app",
        tarball=None,
        source_dir=str(checkout),
        branch="moving-main",
        timeout=30,
        cli_capability=(Path(CLI_ROOT), Path(NODE)),
        git_capability=Path("/usr/bin/git"),
        expected_source_id=resolved_sha,
    )
    session = {
        "name": "prod",
        "baseUrl": "https://captain.example.com",
        "authToken": "saved-token",
    }

    assert cd.try_cli_deploy(args, session) is True
    command = seen["command"]
    assert command[command.index("--branch") + 1] == resolved_sha


@pytest.mark.parametrize("interruption", ["timeout", "keyboard"])
def test_cli_interruption_terminates_the_private_process_group(
    monkeypatch, tmp_path, interruption
):
    tarball = tmp_path / "source.tar"
    tarball.write_bytes(b"fixture")
    signals = []

    class Process:
        pid = 24680
        returncode = None

        def __init__(self, command, **kwargs):
            assert kwargs["start_new_session"] is True

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            if not signals:
                if interruption == "keyboard":
                    raise KeyboardInterrupt
                raise subprocess.TimeoutExpired("caprover", timeout)
            if len(signals) < 2:
                raise subprocess.TimeoutExpired("caprover", timeout)
            self.returncode = -9
            return self.returncode

    monkeypatch.setattr(cd.subprocess, "Popen", Process)
    monkeypatch.setattr(cd.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    args = SimpleNamespace(
        app_name="my-app",
        tarball=str(tarball),
        source_dir=None,
        branch=None,
        timeout=1,
        cli_capability=(Path(CLI_ROOT), Path(NODE)),
        expected_source_id="sha256:" + hashlib.sha256(tarball.read_bytes()).hexdigest(),
    )
    session = {
        "name": "prod",
        "baseUrl": "https://captain.example.com",
        "authToken": "saved-token",
    }

    with pytest.raises(cd.CapRoverDeployError, match="reconcile_required"):
        cd.try_cli_deploy(args, session)

    assert signals == [(24680, cd.signal.SIGTERM), (24680, cd.signal.SIGKILL)]


@pytest.mark.parametrize("path,method", [("/api/v2/login", "POST"), ("/api/v2/user/apps/appData/other?detached=1", "POST")])
def test_deployment_guard_blocks_login_and_unselected_app_before_network(tmp_path, path, method):
    guard = SCRIPT.parent / "deployment_guard.cjs"
    events_path = tmp_path / "events.jsonl"
    token = "fixture-token"
    policy = {
        "guardVersion": 3,
        "origin": "https://captain.example.com",
        "appName": "my-app",
        "sourceMode": "tarball",
        "sourcePath": str(tmp_path / "source.tar"),
        "expectedSourceId": "sha256:" + "0" * 64,
        "authTokenSha256": hashlib.sha256(token.encode()).hexdigest(),
        "appTokenSha256": None,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(policy).encode()).decode().rstrip("=")
    script = f"""
const https = require('https');
try {{
  https.request({{
    protocol: 'https:', hostname: 'captain.example.com', port: 443,
    path: {json.dumps(path)}, method: {json.dumps(method)},
    headers: {{'x-captain-auth': {json.dumps(token)}, 'x-namespace': 'captain'}}
  }});
  process.exit(9);
}} catch (error) {{
  process.exit(error.code === 'CAPROVER_DEPLOY_GUARD_BLOCKED' ? 0 : 8);
}}
"""
    with events_path.open("w+b") as events:
        env = {
            "PATH": str(Path(NODE).parent),
            "HOME": str(tmp_path),
            "CI": "1",
            "CAPROVER_DEPLOY_INTERNAL_POLICY": encoded,
            "CAPROVER_DEPLOY_INTERNAL_EVENT_FD": str(events.fileno()),
        }
        result = subprocess.run(
            [NODE, "--require", str(guard), "-e", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            pass_fds=(events.fileno(),),
            timeout=5,
            check=False,
        )
        events.seek(0)
        evidence = events.read().decode()

    assert result.returncode == 0
    assert '"type":"violation"' in evidence


def test_deployment_guard_hash_is_pinned():
    guard = SCRIPT.parent / "deployment_guard.cjs"
    assert hashlib.sha256(guard.read_bytes()).hexdigest() == cd.DEPLOYMENT_GUARD_SHA256


@pytest.mark.parametrize("guard_state", ["missing", "tampered"])
def test_missing_or_tampered_deployment_guard_blocks_before_cli(
    monkeypatch, tmp_path, guard_state
):
    tarball = tmp_path / "source.tar"
    tarball.write_bytes(b"fixture")
    args = cd.build_arg_parser().parse_args([
        "--caprover-url", "https://captain.example.com",
        "--app-name", "my-app",
        "--tarball", str(tarball),
        "--method", "cli",
    ])
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path):
        if path.name == "deployment_guard.cjs":
            if guard_state == "missing":
                raise OSError("synthetic missing guard")
            return b"synthetic tampered guard"
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)

    with pytest.raises(cd.CapRoverDeployError) as exc:
        cd._validate_source_capability(args, "cli")

    assert exc.value.code == "capability_unavailable"


def test_uppercase_git_sha_is_rejected_without_rewriting_caller_input(
    monkeypatch, tmp_path
):
    original_sha = "ABCDEF" * 6 + "ABCD"
    args = cd.build_arg_parser().parse_args([
        "--caprover-url", "https://captain.example.com",
        "--app-name", "my-app",
        "--repo", "https://github.com/org/repo",
        "--branch", "main",
        "--git-sha", original_sha,
        "--method", "playwright",
        "--recovery-snapshot", str(tmp_path / "recovery.json"),
    ])
    monkeypatch.setattr(cd.importlib.util, "find_spec", lambda name: object())

    with pytest.raises(cd.CapRoverDeployError) as exc:
        cd._validate_source_capability(args, "playwright")

    assert exc.value.code == "caprover_config_invalid"
    assert args.git_sha == original_sha


def test_timeout_after_cli_possible_post_requires_reconciliation_without_fallback(monkeypatch, tmp_path, capsys):
    tarball = tmp_path / "source.tar"
    tarball.write_bytes(b"fixture")

    class API:
        def __init__(self, base_url, token=None):
            pass

        def preflight(self, app_name, allow_create=False):
            return True

        def get_app_definition(self, app_name):
            return {"appName": app_name, "deployedVersion": 7, "versions": []}

        def _validate_app_definition(self, value, app_name):
            pass

    monkeypatch.setattr(cd, "CapRoverAPI", API)
    monkeypatch.setattr(
        cd,
        "try_cli_deploy",
        lambda args, session: (_ for _ in ()).throw(cd.CapRoverDeployError("reconcile_required")),
    )
    monkeypatch.setattr(cd, "deploy_via_api", lambda *args: pytest.fail("API fallback attempted"))
    monkeypatch.setattr(cd, "deploy_via_playwright", lambda *args: pytest.fail("browser fallback attempted"))
    monkeypatch.setattr(cd, "verify_deploy", lambda *args: pytest.fail("verification attempted"))

    with pytest.raises(SystemExit) as exc:
        cd.main([
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--app-name", "my-app",
            "--tarball", str(tarball),
            "--method", "cli",
            "--apply",
            *_saved_session_args(tmp_path),
        ])

    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "reconcile_required" in output
    assert "deployment_evidence_verified" not in output


@pytest.mark.parametrize("triggered,verify_result", [(False, True), (True, False)])
def test_only_successful_trigger_reaches_verification_and_false_verification_is_nonzero(
    monkeypatch, tmp_path, capsys, triggered, verify_result
):
    tarball = tmp_path / "source.tar"
    tarball.write_bytes(b"fixture")
    calls = []

    class API:
        def __init__(self, base_url, token=None):
            pass

        def preflight(self, app_name, allow_create=False):
            return True

        def get_app_definition(self, app_name):
            return {"appName": app_name, "deployedVersion": 7, "versions": []}

        def _validate_app_definition(self, value, app_name):
            pass

        def wait_for_build(self, app_name, timeout=300, baseline=None):
            calls.append(("wait", baseline))
            return True, {"isAppBuilding": False, "isBuildFailed": False}

    monkeypatch.setattr(cd, "CapRoverAPI", API)
    monkeypatch.setattr(cd, "try_cli_deploy", lambda args, session: triggered)
    monkeypatch.setattr(cd, "get_password", lambda args: pytest.fail("password/login fallback attempted"))

    def verify(api, app_name, ssh_cmd=None, baseline=None, expected_source_id=None):
        calls.append(("verify", baseline))
        return verify_result

    monkeypatch.setattr(cd, "verify_deploy", verify)

    with pytest.raises(SystemExit) as exc:
        cd.main([
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--app-name", "my-app",
            "--tarball", str(tarball),
            "--method", "cli",
            "--apply",
            *_saved_session_args(tmp_path),
        ])

    assert exc.value.code == 1
    if triggered:
        assert [name for name, _ in calls] == ["wait", "verify"]
        assert "reconcile_required" in capsys.readouterr().out
    else:
        assert calls == []
        assert "deployment_trigger_failed" in capsys.readouterr().out


@pytest.mark.parametrize("allow_create", [False, True])
def test_missing_app_requires_explicit_create_and_successful_readback(
    monkeypatch, tmp_path, capsys, allow_create
):
    calls = []

    class API:
        def __init__(self, base_url, token=None):
            pass

        def preflight(self, app_name, allow_create=False):
            calls.append(("preflight", allow_create))
            return False

        def create_app(self, app_name):
            calls.append(("create", app_name))
            return {"status": 100, "data": {}}

        def _require_ok_data(self, response):
            return response["data"]

        def get_app_definition(self, app_name):
            calls.append(("readback", app_name))
            return None

    monkeypatch.setattr(cd, "CapRoverAPI", API)
    monkeypatch.setattr(cd, "get_github_creds", lambda args: ("user", "token"))
    monkeypatch.setattr(cd, "deploy_via_api", lambda *args: pytest.fail("configuration attempted"))

    command = [
        "--caprover-url", "https://captain.example.com",
        "--expected-host", "captain.example.com",
        "--app-name", "my-app",
        "--repo", "https://github.com/org/repo",
        "--branch", "main",
        "--configure-only",
        "--method", "api",
        "--apply",
        "--recovery-snapshot", str(tmp_path / "recovery.json"),
        *_saved_session_args(tmp_path),
    ]
    if allow_create:
        command.append("--allow-create")

    with pytest.raises(SystemExit) as exc:
        cd.main(command)

    assert exc.value.code == 1
    if allow_create:
        assert calls == [("preflight", True), ("create", "my-app"), ("readback", "my-app")]
        assert "reconcile_required" in capsys.readouterr().out
    else:
        assert calls == [("preflight", False)]
        assert "caprover_config_invalid" in capsys.readouterr().out


def test_api_configure_only_snapshots_privately_and_never_claims_deployment(
    monkeypatch, tmp_path, capsys
):
    definition = {"appName": "my-app", "deployedVersion": 7, "marker": "private-definition"}
    calls = []

    class API:
        def __init__(self, base_url, token=None):
            pass

        def preflight(self, app_name, allow_create=False):
            calls.append("preflight")
            return True

        def get_app_definition(self, app_name):
            calls.append("definition")
            return definition.copy()

        def _validate_app_definition(self, value, app_name):
            assert value == definition

        def configure_github(self, app_name, repo, branch, user, token):
            calls.append("configure")
            return {"status": 100, "data": {}}

    monkeypatch.setattr(cd, "CapRoverAPI", API)
    monkeypatch.setattr(cd, "get_github_creds", lambda args: ("user", "repo-token"))
    monkeypatch.setattr(cd, "verify_deploy", lambda *args: pytest.fail("verification attempted"))
    snapshot = tmp_path / "recovery.json"

    assert cd.main([
        "--caprover-url", "https://captain.example.com",
        "--expected-host", "captain.example.com",
        "--app-name", "my-app",
        "--repo", "https://github.com/org/repo",
        "--branch", "main",
        "--configure-only",
        "--method", "api",
        "--apply",
        "--recovery-snapshot", str(snapshot),
        *_saved_session_args(tmp_path),
    ]) == 0

    assert calls == ["preflight", "definition", "configure"]
    assert json.loads(snapshot.read_text(encoding="utf-8")) == definition
    assert snapshot.stat().st_mode & 0o777 == 0o600
    output = capsys.readouterr().out
    assert "configured_not_deployed" in output
    assert "deployment_evidence_verified" not in output


def test_allow_create_creates_once_and_reads_back_before_configuration(monkeypatch, tmp_path):
    calls = []
    definition = {"appName": "my-app", "deployedVersion": 0, "marker": "created"}

    class API:
        def __init__(self, base_url, token=None):
            pass

        def preflight(self, app_name, allow_create=False):
            calls.append(("preflight", allow_create))
            return False

        def create_app(self, app_name):
            calls.append(("create", app_name))
            return {"status": 100, "data": {}}

        def _require_ok_data(self, response):
            return response["data"]

        def get_app_definition(self, app_name):
            calls.append(("definition", app_name))
            return definition.copy()

        def _validate_app_definition(self, value, app_name):
            calls.append(("validate", app_name))

        def configure_github(self, *args):
            calls.append(("configure", args[0]))
            return {"status": 100, "data": {}}

    monkeypatch.setattr(cd, "CapRoverAPI", API)
    monkeypatch.setattr(cd, "get_github_creds", lambda args: ("user", "token"))

    assert cd.main([
        "--caprover-url", "https://captain.example.com",
        "--expected-host", "captain.example.com",
        "--app-name", "my-app",
        "--repo", "https://github.com/org/repo",
        "--branch", "main",
        "--configure-only",
        "--method", "api",
        "--apply",
        "--allow-create",
        "--recovery-snapshot", str(tmp_path / "recovery.json"),
        *_saved_session_args(tmp_path),
    ]) == 0

    assert calls == [
        ("preflight", True),
        ("create", "my-app"),
        ("definition", "my-app"),
        ("validate", "my-app"),
        ("definition", "my-app"),
        ("validate", "my-app"),
        ("configure", "my-app"),
    ]


def test_confirmed_create_then_cli_pretrigger_failure_requires_reconciliation(
    monkeypatch, tmp_path, capsys
):
    tarball = tmp_path / "source.tar"
    tarball.write_bytes(b"fixture")
    calls = []
    definition = {"appName": "my-app", "deployedVersion": 0, "versions": []}

    class API:
        def __init__(self, base_url, token=None):
            pass

        def preflight(self, app_name, allow_create=False):
            calls.append(("preflight", allow_create))
            return False

        def create_app(self, app_name):
            calls.append(("create", app_name))
            return {"status": 100, "data": {}}

        def _require_ok_data(self, response):
            return response["data"]

        def get_app_definition(self, app_name):
            calls.append(("definition", app_name))
            return definition.copy()

        def _validate_app_definition(self, value, app_name):
            calls.append(("validate", app_name))

    monkeypatch.setattr(cd, "CapRoverAPI", API)
    monkeypatch.setattr(cd, "try_cli_deploy", lambda args, session: calls.append(("trigger", args.app_name)) or False)
    monkeypatch.setattr(cd, "verify_deploy", lambda *args: pytest.fail("verification attempted"))

    with pytest.raises(SystemExit) as exc:
        cd.main([
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--app-name", "my-app",
            "--tarball", str(tarball),
            "--method", "cli",
            "--apply",
            "--allow-create",
            *_saved_session_args(tmp_path),
        ])

    assert exc.value.code == 1
    assert calls == [
        ("preflight", True),
        ("create", "my-app"),
        ("definition", "my-app"),
        ("validate", "my-app"),
        ("definition", "my-app"),
        ("validate", "my-app"),
        ("trigger", "my-app"),
    ]
    output = capsys.readouterr().out
    assert "reconcile_required" in output
    assert "deployment_trigger_failed" not in output


def test_confirmed_configuration_then_missing_baseline_requires_reconciliation(
    monkeypatch, tmp_path, capsys
):
    calls = []
    definition = {"appName": "my-app", "deployedVersion": 7, "versions": []}

    class API:
        def __init__(self, base_url, token=None):
            pass

        def preflight(self, app_name, allow_create=False):
            calls.append("preflight")
            return True

        def get_app_definition(self, app_name):
            calls.append("definition")
            if calls.count("definition") == 1:
                return definition.copy()
            return None

        def _validate_app_definition(self, value, app_name):
            calls.append("validate")

        def configure_github(self, app_name, repo, branch, user, token):
            calls.append("configure")
            return {"status": 100, "data": {}}

    monkeypatch.setattr(cd, "CapRoverAPI", API)
    monkeypatch.setattr(cd.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setenv("CAPROVER_CREDENTIAL_ORIGIN", "https://captain.example.com")
    monkeypatch.setattr(cd, "get_password", lambda args: "synthetic-password")
    monkeypatch.setattr(cd, "get_github_creds", lambda args: ("user", "repo-token"))
    monkeypatch.setattr(cd, "deploy_via_playwright", lambda *args: pytest.fail("browser trigger attempted"))
    _install_fake_playwright(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        cd.main([
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--app-name", "my-app",
            "--repo", "https://github.com/org/repo",
            "--branch", "main",
            "--git-sha", "1" * 40,
            "--method", "playwright",
            "--apply",
            "--allow-login",
            "--recovery-snapshot", str(tmp_path / "recovery.json"),
            *_saved_session_args(tmp_path),
        ])

    assert exc.value.code == 1
    assert calls == ["preflight", "definition", "validate", "configure", "definition"]
    output = capsys.readouterr().out
    assert "reconcile_required" in output
    assert "caprover_response_inconclusive" not in output


def test_playwright_baseline_is_after_config_and_ack_remains_unconfirmed(
    monkeypatch, tmp_path, capsys
):
    calls = []
    definition = {
        "appName": "my-app",
        "deployedVersion": 7,
        "marker": "private-definition",
        "isAppBuilding": False,
        "appPushWebhook": {"pushWebhookToken": "synthetic-approved-token"},
    }

    class API:
        def __init__(self, base_url, token=None):
            pass

        def preflight(self, app_name, allow_create=False):
            calls.append("preflight")
            return True

        def get_app_definition(self, app_name):
            calls.append("definition")
            return definition.copy()

        def _validate_app_definition(self, value, app_name):
            pass

        def configure_github(self, app_name, repo, branch, user, token):
            calls.append("configure")
            return {"status": 100, "data": {}}

        def wait_for_build(self, app_name, timeout=300, baseline=None):
            calls.append("wait")
            return True, {}

    monkeypatch.setattr(cd, "CapRoverAPI", API)
    monkeypatch.setattr(cd.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setenv("CAPROVER_CREDENTIAL_ORIGIN", "https://captain.example.com")
    monkeypatch.setattr(cd, "get_password", lambda args: "password")
    monkeypatch.setattr(cd, "get_github_creds", lambda args: ("user", "repo-token"))
    monkeypatch.setattr(cd, "deploy_via_playwright", lambda *args: calls.append("trigger") or True)
    _install_fake_playwright(monkeypatch)
    monkeypatch.setattr(
        cd, "verify_deploy", lambda *args, **kwargs: pytest.fail("definitive verification attempted")
    )

    with pytest.raises(SystemExit) as exc:
        cd.main([
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--app-name", "my-app",
            "--repo", "https://github.com/org/repo",
            "--branch", "main",
            "--git-sha", "1" * 40,
            "--method", "playwright",
            "--apply",
            "--allow-login",
            "--recovery-snapshot", str(tmp_path / "recovery.json"),
            *_saved_session_args(tmp_path),
        ])

    assert exc.value.code == 1
    assert calls == [
        "preflight", "definition", "configure", "definition",
        "trigger", "wait", "definition",
    ]
    output = capsys.readouterr().out
    assert "acknowledged" in output.lower()
    assert "deployment_evidence_verified" not in output


def test_playwright_ack_and_matching_source_remain_acknowledged_but_unconfirmed(
    monkeypatch, tmp_path, capsys
):
    expected_sha = "1" * 40
    definitions = iter([
        {
            "appName": "my-app",
            "deployedVersion": 7,
            "versions": [],
            "isAppBuilding": False,
            "appPushWebhook": {"pushWebhookToken": "synthetic-approved-token"},
        },
        {
            "appName": "my-app",
            "deployedVersion": 8,
            "versions": [{
                "version": 8,
                "deployedImageName": "fixture.invalid/app:8",
                "gitHash": expected_sha,
            }],
            "isAppBuilding": False,
        },
    ])
    original_api = cd.CapRoverAPI

    class API:
        _baseline_version = staticmethod(original_api._baseline_version)
        _has_deployment_evidence = staticmethod(original_api._has_deployment_evidence)

        def __init__(self, base_url, token=None):
            pass

        def preflight(self, app_name, allow_create=False):
            return True

        def get_app_definition(self, app_name):
            return next(definitions)

        def _validate_app_definition(self, value, app_name):
            pass

        def wait_for_build(self, app_name, timeout=300, baseline=None):
            return True, {"isAppBuilding": False, "isBuildFailed": False}

        def get_build_status(self, app_name):
            return {"isAppBuilding": False, "isBuildFailed": False}

    monkeypatch.setattr(cd, "CapRoverAPI", API)
    monkeypatch.setattr(cd.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setenv("CAPROVER_CREDENTIAL_ORIGIN", "https://captain.example.com")
    monkeypatch.setattr(cd, "get_password", lambda args: "synthetic-password")
    monkeypatch.setattr(cd, "deploy_via_playwright", lambda *args: True)
    _install_fake_playwright(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        cd.main([
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--app-name", "my-app",
            "--rebuild-only",
            "--git-sha", expected_sha,
            "--method", "playwright",
            "--apply",
            "--allow-login",
            *_saved_session_args(tmp_path),
        ])

    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "reconcile_required" in output
    assert "acknowledged" in output.lower()
    assert "deployment_evidence_verified" not in output


def test_existing_build_is_rejected_before_trigger_even_if_it_later_completes(
    monkeypatch, tmp_path, capsys
):
    tarball = tmp_path / "source.tar"
    tarball.write_bytes(b"fixture")
    calls = []

    class API:
        def __init__(self, base_url, token=None):
            pass

        def preflight(self, app_name, allow_create=False):
            return True

        def get_app_definition(self, app_name):
            version = 7 if "trigger" not in calls else 8
            return {
                "appName": app_name,
                "deployedVersion": version,
                "versions": [{
                    "version": version,
                    "deployedImageName": f"fixture.invalid/app:{version}",
                    "gitHash": "unrelated-source",
                }],
                "isAppBuilding": version == 7,
            }

        def _validate_app_definition(self, value, app_name):
            pass

        def wait_for_build(self, app_name, timeout=300, baseline=None):
            calls.append("wait")
            return True, {"isAppBuilding": False, "isBuildFailed": False}

        def get_build_status(self, app_name):
            return {"isAppBuilding": False, "isBuildFailed": False}

    monkeypatch.setattr(cd, "CapRoverAPI", API)
    monkeypatch.setattr(cd, "try_cli_deploy", lambda *args: calls.append("trigger") or True)

    with pytest.raises(SystemExit) as exc:
        cd.main([
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--app-name", "my-app",
            "--tarball", str(tarball),
            "--method", "cli",
            "--apply",
            *_saved_session_args(tmp_path),
        ])

    assert exc.value.code == 1
    assert "trigger" not in calls
    output = capsys.readouterr().out
    assert "deployment_evidence_verified" not in output


def test_newer_generation_with_wrong_artifact_identity_is_not_confirmed(
    monkeypatch, tmp_path, capsys
):
    tarball = tmp_path / "source.tar"
    tarball.write_bytes(b"reviewed artifact")
    definitions = iter([
        {
            "appName": "my-app",
            "deployedVersion": 7,
            "versions": [],
            "isAppBuilding": False,
        },
        {
            "appName": "my-app",
            "deployedVersion": 8,
            "versions": [{
                "version": 8,
                "deployedImageName": "fixture.invalid/app:8",
                "gitHash": "sha256:" + "f" * 64,
            }],
            "isAppBuilding": False,
        },
    ])

    original_api = cd.CapRoverAPI

    class API:
        _baseline_version = staticmethod(original_api._baseline_version)
        _has_deployment_evidence = staticmethod(original_api._has_deployment_evidence)

        def __init__(self, base_url, token=None):
            pass

        def preflight(self, app_name, allow_create=False):
            return True

        def get_app_definition(self, app_name):
            return next(definitions)

        def _validate_app_definition(self, value, app_name):
            pass

        def wait_for_build(self, app_name, timeout=300, baseline=None):
            return True, {"isAppBuilding": False, "isBuildFailed": False}

        def get_build_status(self, app_name):
            return {"isAppBuilding": False, "isBuildFailed": False}

    monkeypatch.setattr(cd, "CapRoverAPI", API)
    monkeypatch.setattr(cd, "try_cli_deploy", lambda *args: True)

    with pytest.raises(SystemExit) as exc:
        cd.main([
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--app-name", "my-app",
            "--tarball", str(tarball),
            "--method", "cli",
            "--apply",
            *_saved_session_args(tmp_path),
        ])

    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "reconcile_required" in output
    assert "deployment_evidence_verified" not in output


def test_https_and_websocket_flags_default_false_and_requested_flags_fail_before_credentials(
    monkeypatch, tmp_path, capsys
):
    parsed = cd.build_arg_parser().parse_args([
        "--caprover-url", "https://captain.example.com",
        "--app-name", "my-app",
        "--rebuild-only",
    ])
    assert parsed.enable_https is False
    assert parsed.enable_websocket is False
    monkeypatch.setattr(cd, "get_password", lambda args: pytest.fail("password resolved"))
    monkeypatch.setattr(cd, "CapRoverAPI", lambda *args: pytest.fail("HTTP client created"))
    monkeypatch.setattr(cd.importlib.util, "find_spec", lambda name: object())

    with pytest.raises(SystemExit) as exc:
        cd.main([
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--app-name", "my-app",
            "--rebuild-only",
            "--method", "playwright",
            "--apply",
            "--allow-login",
            "--enable-https",
        ])

    assert exc.value.code == 2
    assert "capability_unavailable" in capsys.readouterr().out


def _install_fake_playwright(
    monkeypatch,
    *,
    actions=None,
    login_succeeds=True,
    force_disabled=False,
    force_click_error=None,
    cross_origin_on=None,
    response_mode="accepted",
    launch_error=None,
    context_error=None,
):
    if actions is None:
        actions = []

    class ResponseWaiter:
        def __init__(self, predicate):
            self.predicate = predicate
            self.response = None

        def __enter__(self):
            return self

        def __exit__(self, exception_type, exception, traceback):
            if exception_type is None and self.response is None:
                raise RuntimeError("synthetic response timeout")

        @property
        def value(self):
            return self.response

    class RequestWaiter:
        def __init__(self, predicate):
            self.predicate = predicate
            self.request = None

        def __enter__(self):
            return self

        def __exit__(self, exception_type, exception, traceback):
            if exception_type is None and self.request is None:
                raise RuntimeError("synthetic request timeout")

        @property
        def value(self):
            return self.request

    class RequestFinishedWaiter:
        def __init__(self, predicate):
            self.predicate = predicate
            self.request = None

        def __enter__(self):
            return self

        def __exit__(self, exception_type, exception, traceback):
            if exception_type is None and self.request is None:
                raise RuntimeError("PRIVATE-SYNTHETIC-FINISH-TIMEOUT")

        @property
        def value(self):
            return self.request

    class Locator:
        def __init__(self, kind, page):
            self.kind = kind
            self.page = page

        @property
        def first(self):
            return self

        def count(self):
            if self.kind == "password":
                return 0 if self.page.logged_in else 1
            return 1

        def fill(self, value):
            actions.append(("fill", self.kind))

        def click(self):
            actions.append(("click", self.kind))
            if self.kind == "login" and login_succeeds:
                self.page.logged_in = True
            if self.kind == cross_origin_on:
                self.page.emit_cross_origin_request()
            if self.kind == "force" and force_click_error is not None:
                raise force_click_error
            if self.kind == "force" and response_mode in {
                "accepted", "headers_only", "unrelated", "different_response"
            }:
                trigger_request = SimpleNamespace(
                    method="POST",
                    url=(
                        "https://captain.example.com/api/v2/user/apps/webhooks/triggerbuild"
                        "?token=synthetic-approved-token&namespace=captain"
                        if response_mode != "unrelated"
                        else "https://captain.example.com/api/v2/user/apps/appDefinitions"
                    ),
                )
                if (
                    self.page.request_waiter is not None
                    and self.page.request_waiter.predicate(trigger_request)
                ):
                    self.page.request_waiter.request = trigger_request
                response_request = (
                    SimpleNamespace(method=trigger_request.method, url=trigger_request.url)
                    if response_mode == "different_response"
                    else trigger_request
                )
                response = SimpleNamespace(
                    request=response_request,
                    status=200,
                    body=lambda: b'{"status":100,"data":{}}',
                )
                if self.page.response_waiter.predicate(response):
                    self.page.response_waiter.response = response
                if (
                    response_mode in {"accepted", "different_response"}
                    and self.page.request_finished_waiter is not None
                    and self.page.request_finished_waiter.predicate(response_request)
                ):
                    self.page.request_finished_waiter.request = response_request

        def is_disabled(self):
            return self.kind == "force" and force_disabled

        def is_visible(self):
            return True

    class Page:
        def __init__(self):
            self.url = ""
            self.logged_in = False
            self.route_handler = None
            self.request_waiter = None
            self.response_waiter = None
            self.request_finished_waiter = None

        def route(self, pattern, handler):
            self.route_handler = handler

        def emit_cross_origin_request(self):
            class Route:
                def abort(self):
                    actions.append(("route", "abort"))

                def continue_(self):
                    actions.append(("route", "continue"))

            request = SimpleNamespace(url="https://cross-origin.invalid/private-canary")
            self.route_handler(Route(), request)

        def goto(self, url):
            self.url = url
            stage = "login_navigation" if url.endswith("/#/login") else "app_navigation"
            if stage == cross_origin_on:
                self.emit_cross_origin_request()

        def wait_for_timeout(self, milliseconds):
            pass

        def expect_response(self, predicate, timeout):
            actions.append(("expect_response", timeout))
            self.response_waiter = ResponseWaiter(predicate)
            return self.response_waiter

        def expect_request(self, predicate, timeout):
            actions.append(("expect_request", timeout))
            self.request_waiter = RequestWaiter(predicate)
            return self.request_waiter

        def expect_request_finished(self, predicate, timeout):
            actions.append(("expect_request_finished", timeout))
            self.request_finished_waiter = RequestFinishedWaiter(predicate)
            return self.request_finished_waiter

        def locator(self, selector):
            if "password" in selector:
                kind = "password"
            elif "Login" in selector:
                kind = "login"
            elif "Force" in selector or "Forçar" in selector:
                kind = "force"
            elif "Save" in selector or "Salvar" in selector:
                actions.append(("located", "save"))
                kind = "save"
            else:
                kind = "deployment"
            return Locator(kind, self)

    page = Page()

    def new_context(**kwargs):
        actions.append(("context", kwargs.copy()))
        if context_error is not None:
            raise context_error
        return SimpleNamespace(
            new_page=lambda: page,
            close=lambda: actions.append(("close", "context")),
        )

    browser = SimpleNamespace(new_context=new_context, close=lambda: actions.append(("close", "browser")))

    def launch(**kwargs):
        actions.append(("launch", kwargs.copy()))
        if launch_error is not None:
            raise launch_error
        return browser

    manager = SimpleNamespace(chromium=SimpleNamespace(launch=launch))

    class SyncPlaywright:
        def __enter__(self):
            actions.append(("manager", "enter"))
            return manager

        def __exit__(self, *args):
            actions.append(("manager", "exit"))

    module = SimpleNamespace(sync_playwright=lambda: SyncPlaywright())
    monkeypatch.setitem(sys.modules, "playwright", SimpleNamespace(sync_api=module))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", module)
    return actions


def test_playwright_launch_failure_precedes_creation_configuration_and_deploy_posts(
    monkeypatch, tmp_path, capsys
):
    actions = []
    definition = {
        "appName": "my-app",
        "deployedVersion": 0,
        "versions": [],
        "isAppBuilding": False,
        "appPushWebhook": {"pushWebhookToken": "synthetic-approved-token"},
    }

    class API:
        def __init__(self, base_url, token=None):
            actions.append(("api", "constructed"))

        def login(self, password):
            actions.append(("post", "login"))

        def preflight(self, app_name, allow_create=False):
            actions.append(("get", "preflight"))
            return False

        def create_app(self, app_name):
            actions.append(("post", "create"))
            return {"status": 100, "data": {}}

        def _require_ok_data(self, response):
            return response["data"]

        def get_app_definition(self, app_name):
            actions.append(("get", "definition"))
            return definition.copy()

        def _validate_app_definition(self, value, app_name):
            pass

        def configure_github(self, app_name, repo, branch, user, token):
            actions.append(("post", "configure"))
            return {"status": 100, "data": {}}

    monkeypatch.setattr(cd, "CapRoverAPI", API)
    monkeypatch.setattr(cd.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setenv("CAPROVER_CREDENTIAL_ORIGIN", "https://captain.example.com")
    monkeypatch.setattr(cd, "get_password", lambda args: "synthetic-password")
    monkeypatch.setattr(cd, "get_github_creds", lambda args: ("user", "synthetic-token"))
    _install_fake_playwright(
        monkeypatch,
        actions=actions,
        launch_error=RuntimeError("synthetic chromium launch failure"),
    )

    with pytest.raises(SystemExit) as exc:
        cd.main([
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--app-name", "my-app",
            "--repo", "https://github.com/org/repo",
            "--branch", "main",
            "--git-sha", "1" * 40,
            "--method", "playwright",
            "--apply",
            "--allow-login",
            "--allow-create",
            "--recovery-snapshot", str(tmp_path / "recovery.json"),
        ])

    assert exc.value.code == 1
    assert [action for action in actions if action[0] == "post" and action[1] != "login"] == []
    assert ("click", "force") not in actions
    assert not (tmp_path / "recovery.json").exists()
    assert "capability_unavailable" in capsys.readouterr().out


def test_playwright_apply_launches_once_before_credentials_and_reuses_prepared_resources(
    monkeypatch, capsys
):
    actions = []
    definition = {
        "appName": "my-app",
        "deployedVersion": 7,
        "versions": [],
        "isAppBuilding": False,
        "appPushWebhook": {"pushWebhookToken": "synthetic-approved-token"},
    }

    class API:
        def __init__(self, base_url, token=None):
            actions.append(("api", "constructed"))

        def login(self, password):
            actions.append(("credential", "login"))

        def preflight(self, app_name, allow_create=False):
            actions.append(("get", "preflight"))
            return True

        def get_app_definition(self, app_name):
            actions.append(("get", "definition"))
            return definition.copy()

        def _validate_app_definition(self, value, app_name):
            pass

        def wait_for_build(self, app_name, timeout=300, baseline=None):
            actions.append(("get", "wait"))
            return True, {"isAppBuilding": False, "isBuildFailed": False}

    monkeypatch.setattr(cd, "CapRoverAPI", API)
    monkeypatch.setattr(cd.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setenv("CAPROVER_CREDENTIAL_ORIGIN", "https://captain.example.com")
    monkeypatch.setattr(
        cd,
        "get_password",
        lambda args: actions.append(("credential", "password")) or "synthetic-password",
    )
    _install_fake_playwright(monkeypatch, actions=actions)

    with pytest.raises(SystemExit) as exc:
        cd.main([
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--app-name", "my-app",
            "--rebuild-only",
            "--git-sha", "1" * 40,
            "--method", "playwright",
            "--apply",
            "--allow-login",
        ])

    assert exc.value.code == 1
    assert actions.count(("launch", {"headless": True})) == 1
    assert actions.index(("launch", {"headless": True})) < actions.index(("credential", "password"))
    assert actions.count(("context", {"ignore_https_errors": False})) == 1
    assert actions.count(("click", "force")) == 1
    assert actions.count(("close", "context")) == 1
    assert actions.count(("close", "browser")) == 1
    assert actions.count(("manager", "exit")) == 1
    assert "reconcile_required" in capsys.readouterr().out


def test_playwright_context_creation_failure_closes_browser_before_controller_actions(
    monkeypatch, capsys
):
    actions = []
    monkeypatch.setattr(cd.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setenv("CAPROVER_CREDENTIAL_ORIGIN", "https://captain.example.com")
    monkeypatch.setattr(cd, "get_password", lambda args: pytest.fail("credential consulted"))
    monkeypatch.setattr(cd, "CapRoverAPI", lambda *args: pytest.fail("API client created"))
    _install_fake_playwright(
        monkeypatch,
        actions=actions,
        context_error=RuntimeError("synthetic context failure"),
    )

    with pytest.raises(SystemExit) as exc:
        cd.main([
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--app-name", "my-app",
            "--rebuild-only",
            "--git-sha", "1" * 40,
            "--method", "playwright",
            "--apply",
            "--allow-login",
        ])

    assert exc.value.code == 1
    assert actions.count(("close", "browser")) == 1
    assert actions.count(("manager", "exit")) == 1
    assert ("close", "context") not in actions
    assert "capability_unavailable" in capsys.readouterr().out


@pytest.mark.parametrize("later_failure", ["preflight", "configuration"])
def test_prepared_playwright_resources_close_on_later_controller_failure(
    monkeypatch, tmp_path, capsys, later_failure
):
    actions = []
    definition = {
        "appName": "my-app",
        "deployedVersion": 7,
        "versions": [],
        "isAppBuilding": False,
        "appPushWebhook": {"pushWebhookToken": "synthetic-approved-token"},
    }

    class API:
        def __init__(self, base_url, token=None):
            pass

        def login(self, password):
            pass

        def preflight(self, app_name, allow_create=False):
            if later_failure == "preflight":
                raise RuntimeError("synthetic preflight failure")
            return True

        def get_app_definition(self, app_name):
            return definition.copy()

        def _validate_app_definition(self, value, app_name):
            pass

        def configure_github(self, app_name, repo, branch, user, token):
            actions.append(("post", "configure"))
            raise RuntimeError("synthetic configuration failure")

    monkeypatch.setattr(cd, "CapRoverAPI", API)
    monkeypatch.setattr(cd.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setenv("CAPROVER_CREDENTIAL_ORIGIN", "https://captain.example.com")
    monkeypatch.setattr(cd, "get_password", lambda args: "synthetic-password")
    monkeypatch.setattr(cd, "get_github_creds", lambda args: ("user", "synthetic-token"))
    _install_fake_playwright(monkeypatch, actions=actions)
    command = [
        "--caprover-url", "https://captain.example.com",
        "--expected-host", "captain.example.com",
        "--app-name", "my-app",
        "--git-sha", "1" * 40,
        "--method", "playwright",
        "--apply",
        "--allow-login",
    ]
    if later_failure == "preflight":
        command.append("--rebuild-only")
    else:
        command.extend([
            "--repo", "https://github.com/org/repo",
            "--branch", "main",
            "--recovery-snapshot", str(tmp_path / "recovery.json"),
        ])

    with pytest.raises(SystemExit) as exc:
        cd.main(command)

    assert exc.value.code == 1
    assert actions.count(("close", "context")) == 1
    assert actions.count(("close", "browser")) == 1
    assert actions.count(("manager", "exit")) == 1
    assert "reconcile_required" in capsys.readouterr().out or later_failure == "preflight"


def test_playwright_plan_is_static_without_launch_or_credentials(monkeypatch, capsys):
    actions = []
    monkeypatch.setattr(cd.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(cd, "get_password", lambda args: pytest.fail("password resolved"))
    monkeypatch.setattr(cd, "get_github_creds", lambda args: pytest.fail("repo credential resolved"))
    monkeypatch.setattr(cd, "load_saved_session", lambda args: pytest.fail("session read"))
    monkeypatch.setattr(cd, "CapRoverAPI", lambda *args: pytest.fail("API client created"))
    _install_fake_playwright(monkeypatch, actions=actions)

    assert cd.main([
        "--caprover-url", "https://captain.example.com",
        "--expected-host", "captain.example.com",
        "--app-name", "my-app",
        "--rebuild-only",
        "--git-sha", "1" * 40,
        "--method", "playwright",
    ]) == 0

    assert not any(action[0] in {"manager", "launch", "context"} for action in actions)
    output = capsys.readouterr().out
    assert "deployment_plan method=playwright apply_required" in output


@pytest.mark.parametrize("response_mode", ["missing", "unrelated"])
def test_playwright_click_without_exact_observed_response_is_inconclusive_and_not_retried(
    monkeypatch, response_mode
):
    actions = _install_fake_playwright(monkeypatch, response_mode=response_mode)
    args = SimpleNamespace(
        caprover_url="https://captain.example.com",
        app_name="my-app",
        allow_insecure=False,
        timeout=1,
        playwright_trigger_token="synthetic-approved-token",
    )

    with pytest.raises(cd.CapRoverDeployError) as exc:
        cd.deploy_via_playwright(args, "password", "", "")

    assert exc.value.code == "reconcile_required"
    assert actions.count(("click", "force")) == 1
    assert ("close", "context") in actions
    assert ("close", "browser") in actions


def test_playwright_headers_without_completed_body_time_out_once_and_do_not_leak(
    monkeypatch, capsys
):
    actions = _install_fake_playwright(monkeypatch, response_mode="headers_only")
    args = SimpleNamespace(
        caprover_url="https://captain.example.com",
        app_name="my-app",
        allow_insecure=False,
        timeout=1,
        playwright_trigger_token="synthetic-approved-token",
    )

    with pytest.raises(cd.CapRoverDeployError) as exc:
        cd.deploy_via_playwright(args, "password", "", "")

    assert exc.value.code == "reconcile_required"
    assert actions.count(("click", "force")) == 1
    assert ("expect_response", 1000) in actions
    assert ("expect_request_finished", 1000) in actions
    assert ("close", "context") in actions
    assert ("close", "browser") in actions
    captured = capsys.readouterr()
    assert "PRIVATE-SYNTHETIC-FINISH-TIMEOUT" not in captured.out + captured.err


def test_playwright_response_from_different_request_cannot_confirm_the_click(
    monkeypatch
):
    actions = _install_fake_playwright(
        monkeypatch, response_mode="different_response"
    )
    args = SimpleNamespace(
        caprover_url="https://captain.example.com",
        app_name="my-app",
        allow_insecure=False,
        timeout=1,
        playwright_trigger_token="synthetic-approved-token",
    )

    with pytest.raises(cd.CapRoverDeployError) as exc:
        cd.deploy_via_playwright(args, "password", "", "")

    assert exc.value.code == "reconcile_required"
    assert actions.count(("click", "force")) == 1
    assert ("expect_request", 1000) in actions


def test_playwright_completed_exact_response_is_accepted_once(monkeypatch):
    actions = _install_fake_playwright(monkeypatch, response_mode="accepted")
    args = SimpleNamespace(
        caprover_url="https://captain.example.com",
        app_name="my-app",
        allow_insecure=False,
        timeout=1,
        playwright_trigger_token="synthetic-approved-token",
    )

    assert cd.deploy_via_playwright(args, "password", "", "") is True
    assert actions.count(("click", "force")) == 1
    assert ("expect_request", 1000) in actions
    assert ("expect_response", 1000) in actions
    assert ("expect_request_finished", 1000) in actions


@pytest.mark.parametrize(
    "login_succeeds,force_disabled",
    [(False, False), (True, True)],
)
def test_playwright_requires_authenticated_ui_and_enabled_force_build_without_save_restart(
    monkeypatch, login_succeeds, force_disabled
):
    actions = _install_fake_playwright(
        monkeypatch,
        login_succeeds=login_succeeds,
        force_disabled=force_disabled,
    )
    args = SimpleNamespace(
        caprover_url="https://captain.example.com",
        app_name="my-app",
        allow_insecure=False,
        timeout=1,
        playwright_trigger_token="synthetic-approved-token",
    )

    assert cd.deploy_via_playwright(args, "password", "", "") is False
    assert ("located", "save") not in actions
    assert ("click", "save") not in actions
    if not login_succeeds:
        assert ("click", "force") not in actions
    else:
        assert ("click", "force") not in actions


def test_playwright_never_disables_tls_verification_for_allow_insecure(monkeypatch):
    actions = _install_fake_playwright(monkeypatch, login_succeeds=False)
    args = SimpleNamespace(
        caprover_url="http://127.0.0.1:3000",
        app_name="my-app",
        allow_insecure=True,
        timeout=1,
        playwright_trigger_token="synthetic-approved-token",
    )

    assert cd.deploy_via_playwright(args, "password", "", "") is False
    context_options = [value for action, value in actions if action == "context"]
    assert context_options == [{"ignore_https_errors": False}]


def test_playwright_force_click_exception_requires_reconciliation_without_retry_or_leak(
    monkeypatch, capsys
):
    private_canary = "PRIVATE-FORCE-CLICK-CANARY"
    actions = _install_fake_playwright(
        monkeypatch,
        force_click_error=RuntimeError(private_canary),
    )
    args = SimpleNamespace(
        caprover_url="https://captain.example.com",
        app_name="my-app",
        allow_insecure=False,
        timeout=1,
        playwright_trigger_token="synthetic-approved-token",
    )

    with pytest.raises(cd.CapRoverDeployError) as exc:
        cd.deploy_via_playwright(args, "password", "", "")

    assert exc.value.code == "reconcile_required"
    assert actions.count(("click", "force")) == 1
    captured = capsys.readouterr()
    assert private_canary not in str(exc.value)
    assert private_canary not in captured.out + captured.err


def test_playwright_cross_origin_navigation_stops_before_credentials_or_force_build(
    monkeypatch
):
    actions = _install_fake_playwright(monkeypatch, cross_origin_on="login_navigation")
    args = SimpleNamespace(
        caprover_url="https://captain.example.com",
        app_name="my-app",
        allow_insecure=False,
        timeout=1,
        playwright_trigger_token="synthetic-approved-token",
    )

    assert cd.deploy_via_playwright(args, "password", "", "") is False
    assert ("route", "abort") in actions
    assert ("fill", "password") not in actions
    assert ("click", "login") not in actions
    assert ("click", "force") not in actions


def test_playwright_cross_origin_request_after_force_click_requires_reconciliation(
    monkeypatch
):
    actions = _install_fake_playwright(monkeypatch, cross_origin_on="force")
    args = SimpleNamespace(
        caprover_url="https://captain.example.com",
        app_name="my-app",
        allow_insecure=False,
        timeout=1,
        playwright_trigger_token="synthetic-approved-token",
    )

    with pytest.raises(cd.CapRoverDeployError) as exc:
        cd.deploy_via_playwright(args, "password", "", "")

    assert exc.value.code == "reconcile_required"
    assert actions.count(("click", "force")) == 1
    assert ("route", "abort") in actions
