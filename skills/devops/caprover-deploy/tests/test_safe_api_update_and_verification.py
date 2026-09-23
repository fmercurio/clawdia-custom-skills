import importlib.util
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "caprover_deploy.py"
spec = importlib.util.spec_from_file_location("caprover_deploy_safe_slice", SCRIPT)
cd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cd)

CapRoverAPI = cd.CapRoverAPI
CapRoverDeployError = cd.CapRoverDeployError


class _Response:
    def __init__(self, body):
        self.body = body
        self.closed = False

    def read(self, limit):
        return self.body[:limit]

    def close(self):
        self.closed = True


def test_request_disables_inherited_proxies(monkeypatch):
    response = _Response(json.dumps({"status": 100, "data": {}}).encode())
    captured_handlers = []

    class Opener:
        def open(self, request, timeout):
            return response

    def fake_build_opener(*handlers):
        captured_handlers.extend(handlers)
        return Opener()

    monkeypatch.setattr(cd.urllib.request, "build_opener", fake_build_opener)

    assert CapRoverAPI("https://captain.example.com")._request("GET", "/safe") == {
        "status": 100,
        "data": {},
    }
    proxy_handlers = [h for h in captured_handlers if isinstance(h, cd.urllib.request.ProxyHandler)]
    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}
    assert response.closed is True


def test_redirect_rejects_urls_with_embedded_credentials():
    handler = cd.SameOriginRedirectHandler("https://captain.example.com")
    request = cd.urllib.request.Request("https://captain.example.com/start")

    with pytest.raises(CapRoverDeployError) as exc:
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://user:secret@captain.example.com/next",
        )

    assert exc.value.code == "caprover_network_blocked"


def test_credential_bearing_api_rejects_even_same_origin_redirect():
    handler = cd.RejectAPIRedirectHandler()
    request = cd.urllib.request.Request(
        "https://captain.example.com/start",
        headers={"x-captain-auth": "SENSITIVE-CANARY"},
    )

    redirected = handler.redirect_request(
        request,
        None,
        307,
        "Temporary Redirect",
        {},
        "https://captain.example.com/next",
    )

    assert redirected is None


def test_http_failure_is_closed_and_sanitized(monkeypatch):
    canary = "SENSITIVE-CANARY-token-path"
    response = _Response(canary.encode())
    error = cd.urllib.error.HTTPError(
        "https://captain.example.com/safe",
        401,
        canary,
        {},
        response,
    )

    class Opener:
        def open(self, request, timeout):
            raise error

    monkeypatch.setattr(cd.urllib.request, "build_opener", lambda *handlers: Opener())

    result = CapRoverAPI("https://captain.example.com")._request("GET", "/safe")

    assert result == {"status": 401, "failure": "http"}
    assert canary not in repr(result)
    assert response.closed is True


def test_malformed_success_body_is_inconclusive_not_transport(monkeypatch):
    response = _Response(b"not-json-SENSITIVE-CANARY")

    class Opener:
        def open(self, request, timeout):
            return response

    monkeypatch.setattr(cd.urllib.request, "build_opener", lambda *handlers: Opener())

    result = CapRoverAPI("https://captain.example.com")._request("GET", "/safe")

    assert result == {"status": -2, "failure": "response"}
    assert "SENSITIVE-CANARY" not in repr(result)
    assert response.closed is True


def test_api_failure_body_is_reduced_to_fixed_sanitized_evidence(monkeypatch):
    response = _Response(
        json.dumps(
            {
                "status": 1106,
                "description": "SENSITIVE-CANARY-token-path",
                "data": {"secret": "SENSITIVE-CANARY"},
            }
        ).encode()
    )

    class Opener:
        def open(self, request, timeout):
            return response

    monkeypatch.setattr(cd.urllib.request, "build_opener", lambda *handlers: Opener())

    result = CapRoverAPI("https://captain.example.com")._request("GET", "/safe")

    assert result == {"status": 1106, "failure": "api"}
    assert "SENSITIVE-CANARY" not in repr(result)


def _api_with_responses(system_response, apps_response):
    api = CapRoverAPI("https://captain.example.com")

    def request(method, path, payload=None):
        if path == "/api/v2/user/system/info/":
            return system_response
        if path == "/api/v2/user/apps/appDefinitions/":
            return apps_response
        pytest.fail(f"unexpected path: {path}")

    api._request = request
    return api


def _system_info():
    return {
        "status": 100,
        "data": {
            "hasRootSsl": True,
            "forceSsl": True,
            "rootDomain": "example.com",
            "captainSubDomain": "captain",
        },
    }


@pytest.mark.parametrize(
    "apps_response",
    [
        {"status": 100, "data": {}},
        {"status": 100, "data": {"appDefinitions": {}}},
        {"status": 100, "data": {"appDefinitions": [None]}},
        {"status": 100, "data": {"appDefinitions": [{"other": "field"}]}},
        {"data": {"appDefinitions": []}},
    ],
)
def test_malformed_app_list_is_never_treated_as_missing(apps_response):
    api = _api_with_responses(
        _system_info(),
        apps_response,
    )

    with pytest.raises(CapRoverDeployError) as exc:
        api.preflight("my-app", allow_create=True)

    assert exc.value.code == "caprover_response_inconclusive"


def test_duplicate_app_match_is_inconclusive():
    api = _api_with_responses(
        _system_info(),
        {
            "status": 100,
            "data": {"appDefinitions": [{"appName": "my-app"}, {"appName": "my-app"}]},
        },
    )

    with pytest.raises(CapRoverDeployError) as exc:
        api.app_exists("my-app")

    assert exc.value.code == "caprover_response_inconclusive"


def test_official_auth_token_status_is_auth_blocked():
    api = _api_with_responses(
        {"status": 1106, "description": "SENSITIVE-CANARY"},
        pytest.fail,
    )

    with pytest.raises(CapRoverDeployError) as exc:
        api.preflight("my-app")

    assert exc.value.code == "caprover_auth_blocked"
    assert "SENSITIVE-CANARY" not in str(exc.value)


def test_official_not_authorized_status_is_authorization_blocked():
    api = _api_with_responses(
        {"status": 1102, "description": "SENSITIVE-CANARY"},
        pytest.fail,
    )

    with pytest.raises(CapRoverDeployError) as exc:
        api.preflight("my-app")

    assert exc.value.code == "caprover_authorization_blocked"
    assert "SENSITIVE-CANARY" not in str(exc.value)


def test_empty_system_info_object_is_inconclusive():
    api = _api_with_responses(
        {"status": 100, "data": {}},
        pytest.fail,
    )

    with pytest.raises(CapRoverDeployError) as exc:
        api.preflight("my-app")

    assert exc.value.code == "caprover_response_inconclusive"


@pytest.mark.parametrize(
    "data",
    [
        {"ok": True},
        {"hasRootSsl": True, "forceSsl": True, "rootDomain": "example.com"},
        {
            "hasRootSsl": 1,
            "forceSsl": True,
            "rootDomain": "example.com",
            "captainSubDomain": "captain",
        },
        {
            "hasRootSsl": True,
            "forceSsl": False,
            "rootDomain": None,
            "captainSubDomain": "captain",
        },
    ],
)
def test_preflight_rejects_unknown_system_info_schema(data):
    api = _api_with_responses(
        {"status": 100, "data": data},
        {"status": 100, "data": {"appDefinitions": []}},
    )

    with pytest.raises(CapRoverDeployError) as exc:
        api.preflight("my-app", allow_create=True)

    assert exc.value.code == "caprover_response_inconclusive"


def _nondefault_app_definition():
    return {
        "appName": "my-app",
        "projectId": "project-a",
        "description": "important app",
        "instanceCount": 0,
        "captainDefinitionRelativeFilePath": "./ops/captain-definition",
        "envVars": [{"key": "MODE", "value": "production"}],
        "volumes": [{"containerPath": "/data", "volumeName": "app-data", "mode": "rw"}],
        "tags": [{"tagName": "worker"}],
        "nodeId": "node-a",
        "notExposeAsWebApp": True,
        "containerHttpPort": 8080,
        "httpAuth": {"user": "viewer", "passwordHashed": "$apr1$hashed"},
        "forceSsl": True,
        "ports": [
            {
                "containerPort": 9000,
                "hostPort": 19000,
                "protocol": "tcp",
                "publishMode": "host",
            }
        ],
        "customNginxConfig": "location /ready { return 204; }",
        "redirectDomain": "",
        "preDeployFunction": "echo ready",
        "serviceUpdateOverride": "TaskTemplate: {}",
        "websocketSupport": True,
        "appDeployTokenConfig": {"enabled": True, "appDeployToken": "deploy-secret"},
        "appPushWebhook": {
            "tokenVersion": "token-version",
            "pushWebhookToken": "push-secret",
            "repoInfo": {
                "repo": "https://github.com/old/repo",
                "branch": "old",
                "user": "old-user",
                "password": "old-secret",
                "sshKey": "old-key",
            },
        },
        "hasPersistentData": True,
        "hasDefaultSubDomainSsl": True,
        "customDomain": [{"publicDomain": "app.example.com", "hasSsl": True}],
        "networks": ["captain-overlay-network", "private-network"],
        "deployedVersion": 7,
        "versions": [
            {
                "version": 7,
                "deployedImageName": "registry.example/app:7",
                "timeStamp": "2026-09-15T12:00:00Z",
                "gitHash": "abc123",
            }
        ],
        "isAppBuilding": False,
    }


def test_configure_github_preserves_writable_state_and_excludes_read_only_fields():
    current = _nondefault_app_definition()
    original = copy.deepcopy(current)
    readback = copy.deepcopy(current)
    readback["appPushWebhook"]["repoInfo"] = {
        "repo": "https://github.com/new/repo",
        "branch": "release",
        "user": "new-user",
        "password": "new-secret",
        "sshKey": "",
    }
    posted = []
    reads = iter([current, readback])
    api = CapRoverAPI("https://captain.example.com")

    def request(method, path, payload=None):
        if method == "GET":
            app = next(reads)
            return {"status": 100, "data": {"appDefinitions": [app]}}
        assert method == "POST"
        assert path == "/api/v2/user/apps/appDefinitions/update"
        posted.append(payload)
        return {"status": 100, "data": {}}

    api._request = request

    result = api.configure_github(
        "my-app",
        "https://github.com/new/repo",
        "release",
        "new-user",
        "new-secret",
    )

    assert result["status"] == 100
    assert current == original
    assert len(posted) == 1
    payload = posted[0]
    for key in (
        "envVars",
        "volumes",
        "ports",
        "tags",
        "instanceCount",
        "httpAuth",
        "appDeployTokenConfig",
        "customNginxConfig",
        "serviceUpdateOverride",
    ):
        assert payload[key] == original[key]
    assert payload["instanceCount"] == 0
    assert payload["appPushWebhook"] == {"repoInfo": readback["appPushWebhook"]["repoInfo"]}
    for read_only in (
        "versions",
        "deployedVersion",
        "customDomain",
        "networks",
        "isAppBuilding",
        "hasPersistentData",
        "hasDefaultSubDomainSsl",
    ):
        assert read_only not in payload
    assert "tokenVersion" not in payload["appPushWebhook"]
    assert "pushWebhookToken" not in payload["appPushWebhook"]


def test_configure_github_rejects_invalid_redirect_domain_before_post():
    current = _nondefault_app_definition()
    current["redirectDomain"] = False
    posts = []
    api = CapRoverAPI("https://captain.example.com")

    def request(method, path, payload=None):
        if method == "POST":
            posts.append(payload)
        return {"status": 100, "data": {"appDefinitions": [current]}}

    api._request = request

    with pytest.raises(CapRoverDeployError) as exc:
        api.configure_github("my-app", "https://github.com/new/repo", "main", "user", "secret")

    assert exc.value.code == "caprover_response_inconclusive"
    assert posts == []


def test_configure_github_rejects_unknown_schema_before_post():
    current = _nondefault_app_definition()
    current["newWritableSetting"] = {"must": "not be stripped"}
    posts = []
    api = CapRoverAPI("https://captain.example.com")

    def request(method, path, payload=None):
        if method == "POST":
            posts.append(payload)
        return {"status": 100, "data": {"appDefinitions": [current]}}

    api._request = request

    with pytest.raises(CapRoverDeployError) as exc:
        api.configure_github("my-app", "https://github.com/new/repo", "main", "user", "secret")

    assert exc.value.code == "caprover_response_inconclusive"
    assert posts == []


def test_configure_github_status_100_readback_mismatch_is_not_success():
    current = _nondefault_app_definition()
    readback = copy.deepcopy(current)
    readback["envVars"] = []
    readback["appPushWebhook"]["repoInfo"] = {
        "repo": "https://github.com/new/repo",
        "branch": "main",
        "user": "user",
        "password": "secret",
        "sshKey": "",
    }
    reads = iter([current, readback])
    api = CapRoverAPI("https://captain.example.com")

    def request(method, path, payload=None):
        if method == "POST":
            return {"status": 100, "data": {}}
        return {"status": 100, "data": {"appDefinitions": [next(reads)]}}

    api._request = request

    with pytest.raises(CapRoverDeployError) as exc:
        api.configure_github("my-app", "https://github.com/new/repo", "main", "user", "secret")

    assert exc.value.code == "caprover_response_inconclusive"


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"isAppBuilding": False},
        {"isBuildFailed": False},
        {"isAppBuilding": 0, "isBuildFailed": False},
        {"isAppBuilding": False, "isBuildFailed": "false"},
    ],
)
def test_get_build_status_requires_explicit_boolean_flags(data):
    api = CapRoverAPI("https://captain.example.com")
    api._request = lambda method, path, payload=None: {"status": 100, "data": data}

    with pytest.raises(CapRoverDeployError) as exc:
        api.get_build_status("my-app")

    assert exc.value.code == "caprover_response_inconclusive"


def test_get_build_status_discards_arbitrary_server_fields():
    api = CapRoverAPI("https://captain.example.com")
    api._request = lambda method, path, payload=None: {
        "status": 100,
        "data": {
            "isAppBuilding": False,
            "isBuildFailed": False,
            "logs": ["SENSITIVE-CANARY"],
        },
    }

    assert api.get_build_status("my-app") == {
        "isAppBuilding": False,
        "isBuildFailed": False,
    }


def test_wait_for_build_does_not_accept_initial_idle_status(monkeypatch):
    api = CapRoverAPI("https://captain.example.com")
    samples = []
    api.get_build_status = lambda app_name: samples.append(app_name) or {
        "isAppBuilding": False,
        "isBuildFailed": False,
    }
    clock = {"now": 10.0}
    monkeypatch.setattr(cd.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(cd.time, "sleep", lambda seconds: clock.__setitem__("now", clock["now"] + seconds))

    ok, status = api.wait_for_build("my-app", timeout=2, poll_interval=1)

    assert ok is False
    assert status == {"isAppBuilding": False, "isBuildFailed": False}
    assert len(samples) >= 2


def test_wait_for_build_accepts_idle_only_with_changed_deployment_evidence(monkeypatch):
    api = CapRoverAPI("https://captain.example.com")
    api.get_build_status = lambda app_name: {
        "isAppBuilding": False,
        "isBuildFailed": False,
    }
    api.get_app_definition = lambda app_name: {
        "deployedVersion": 8,
        "versions": [{"version": 8, "deployedImageName": "registry.example/app:8"}],
    }
    clock = {"now": 10.0}
    monkeypatch.setattr(cd.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(cd.time, "sleep", lambda seconds: clock.__setitem__("now", clock["now"] + seconds))

    ok, status = api.wait_for_build("my-app", timeout=2, poll_interval=1, baseline=7)

    assert ok is True
    assert status == {"isAppBuilding": False, "isBuildFailed": False}


class _VerificationAPI:
    def __init__(self, definition, status=None):
        self.definition = definition
        self.status = status or {"isAppBuilding": False, "isBuildFailed": False}

    def get_build_status(self, app_name):
        return copy.deepcopy(self.status)

    def get_app_definition(self, app_name):
        return copy.deepcopy(self.definition)

    def wait_for_build(self, app_name, timeout=300, poll_interval=10, baseline=None):
        return False, copy.deepcopy(self.status)


SOURCE_SHA = "1" * 40
SOURCE_FINGERPRINT = "sha256:" + "2" * 64


def _deployment_definition(
    version=8, instance_count=2, source_id=SOURCE_SHA, is_legacy=False
):
    return {
        "appName": "my-app",
        "deployedVersion": version,
        "versions": [
            {
                "version": version,
                "deployedImageName": f"registry.example/app:{version}",
                "gitHash": source_id,
            }
        ],
        "instanceCount": instance_count,
        "isLegacyAppName": is_legacy,
    }


def test_verify_deploy_rejects_idle_stale_generation(capsys):
    api = _VerificationAPI(_deployment_definition(version=7))

    assert cd.verify_deploy(
        api, "my-app", baseline=7, expected_source_id=SOURCE_SHA
    ) is False

    output = capsys.readouterr().out
    assert "Deploy verified" not in output
    assert "registry.example" not in output


def test_verify_deploy_rejects_generation_older_than_baseline():
    api = _VerificationAPI(_deployment_definition(version=6))

    assert cd.verify_deploy(
        api, "my-app", baseline=7, expected_source_id=SOURCE_SHA
    ) is False


def test_verify_deploy_requires_pinned_expected_source_identity(capsys):
    api = _VerificationAPI(_deployment_definition(version=8))

    assert cd.verify_deploy(api, "my-app", baseline=7) is False

    output = capsys.readouterr().out
    assert "Deployment evidence unavailable: expected source identity required" in output
    assert "source, and image reference confirmed" not in output


def test_verify_deploy_rejects_malformed_source_identity_without_echoing_it(capsys):
    malformed_source = "SENSITIVE-CANARY-not-a-source-id"
    api = _VerificationAPI(_deployment_definition(version=8))

    assert cd.verify_deploy(
        api,
        "my-app",
        baseline=7,
        expected_source_id=malformed_source,
    ) is False

    output = capsys.readouterr().out
    assert "Deployment evidence unavailable: expected source identity required" in output
    assert malformed_source not in output


@pytest.mark.parametrize("source_id", [SOURCE_SHA, SOURCE_FINGERPRINT])
def test_verify_deploy_accepts_changed_generation_with_pinned_source_without_claiming_health(
    capsys, source_id
):
    api = _VerificationAPI(_deployment_definition(version=8, source_id=source_id))

    assert cd.verify_deploy(
        api, "my-app", baseline=7, expected_source_id=source_id
    ) is True

    output = capsys.readouterr().out
    assert "application health not proven" in output
    assert "registry.example" not in output
    assert "app:8" not in output


def test_verify_deploy_requires_matching_expected_source_identity(capsys):
    definition = _deployment_definition(version=8)
    api = _VerificationAPI(definition)

    assert cd.verify_deploy(
        api,
        "my-app",
        baseline=7,
        expected_source_id=SOURCE_SHA,
    ) is True
    assert cd.verify_deploy(
        api,
        "my-app",
        baseline=7,
        expected_source_id="2" * 40,
    ) is False

    output = capsys.readouterr().out
    assert "generation/source not confirmed" in output


def test_verify_deploy_serializes_one_remote_command_and_preserves_template_tab_through_shell(
    monkeypatch,
):
    api = _VerificationAPI(
        _deployment_definition(version=8, instance_count=2, is_legacy=True)
    )
    real_run = cd.subprocess.run
    calls = []

    def run(command, **kwargs):
        remote_command = " ".join(command[2:])
        shell_script = """
docker() {
    printf 'argc=<%s>\\n' "$#" >&2
    for argument do
        printf 'arg=<%s>\\n' "$argument" >&2
    done
    printf 'srv-captain--my-app\\t2/2\\n'
}
""" + remote_command
        completed = real_run(
            ["/bin/sh", "-c", shell_script],
            capture_output=True,
            text=True,
            timeout=kwargs["timeout"],
        )
        calls.append((command, kwargs, completed.stderr.splitlines()))
        return completed

    monkeypatch.setattr(cd.subprocess, "run", run)

    assert cd.verify_deploy(
        api,
        "my-app",
        ssh_cmd=["ssh", "host"],
        baseline=7,
        expected_source_id=SOURCE_SHA,
    ) is True
    assert len(calls) == 1
    command, kwargs, parsed_arguments = calls[0]
    assert command[:2] == ["ssh", "host"]
    assert len(command[2:]) == 1
    assert kwargs == {"capture_output": True, "text": True, "timeout": 15}
    assert parsed_arguments == [
        "argc=<6>",
        "arg=<service>",
        "arg=<ls>",
        "arg=<--filter>",
        "arg=<name=srv-captain--my-app>",
        "arg=<--format>",
        "arg=<{{.Name}}\t{{.Replicas}}>",
    ]


@pytest.mark.parametrize(
    ("is_legacy", "service_name"),
    [(False, "my-app"), (True, "srv-captain--my-app")],
)
def test_verify_deploy_uses_supported_server_service_name(
    monkeypatch, is_legacy, service_name
):
    api = _VerificationAPI(
        _deployment_definition(version=8, instance_count=2, is_legacy=is_legacy)
    )
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=f"{service_name}\t2/2\n")

    monkeypatch.setattr(cd.subprocess, "run", run)

    assert cd.verify_deploy(
        api,
        "my-app",
        ssh_cmd=["ssh", "host"],
        baseline=7,
        expected_source_id=SOURCE_SHA,
    ) is True
    assert len(calls) == 1
    assert len(calls[0][2:]) == 1
    assert f"name={service_name}" in calls[0][2]


@pytest.mark.parametrize(
    ("is_legacy", "service_name"),
    [(False, "my-app"), (True, "srv-captain--my-app")],
)
def test_verify_deploy_accepts_one_healthy_exact_row_with_healthy_prefix_sibling(
    monkeypatch, is_legacy, service_name
):
    api = _VerificationAPI(
        _deployment_definition(version=8, instance_count=2, is_legacy=is_legacy)
    )
    service_rows = f"{service_name}\t2/2\n{service_name}-worker\t2/2\n"
    monkeypatch.setattr(
        cd.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=service_rows),
    )

    assert cd.verify_deploy(
        api,
        "my-app",
        ssh_cmd=["ssh", "host"],
        baseline=7,
        expected_source_id=SOURCE_SHA,
    ) is True


@pytest.mark.parametrize(
    ("is_legacy", "service_name"),
    [(False, "my-app"), (True, "srv-captain--my-app")],
)
@pytest.mark.parametrize(
    "rows",
    [
        "{service_name}-worker\t2/2\n",
        "{service_name}\t2/2\n{service_name}\t2/2\n",
        "{service_name}\t1/2\n{service_name}-worker\t2/2\n",
    ],
    ids=["sibling-only", "duplicate-exact-target", "unhealthy-target-healthy-sibling"],
)
def test_verify_deploy_rejects_prefix_results_without_one_healthy_exact_target(
    monkeypatch, is_legacy, service_name, rows
):
    api = _VerificationAPI(
        _deployment_definition(version=8, instance_count=2, is_legacy=is_legacy)
    )
    monkeypatch.setattr(
        cd.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=rows.format(service_name=service_name),
        ),
    )

    assert cd.verify_deploy(
        api,
        "my-app",
        ssh_cmd=["ssh", "host"],
        baseline=7,
        expected_source_id=SOURCE_SHA,
    ) is False


@pytest.mark.parametrize("legacy_flag", [None, 0, 1, "false", {}, []])
def test_verify_deploy_rejects_missing_or_malformed_legacy_name_flag(
    monkeypatch, legacy_flag
):
    definition = _deployment_definition(version=8, instance_count=2)
    if legacy_flag is None:
        definition.pop("isLegacyAppName")
    else:
        definition["isLegacyAppName"] = legacy_flag
    api = _VerificationAPI(definition)
    calls = []
    monkeypatch.setattr(
        cd.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs))
        or SimpleNamespace(returncode=0, stdout="my-app\t2/2\n"),
    )

    assert cd.verify_deploy(
        api,
        "my-app",
        ssh_cmd=["ssh", "host"],
        baseline=7,
        expected_source_id=SOURCE_SHA,
    ) is False
    assert calls == []


@pytest.mark.parametrize(
    "service_rows",
    [
        "",
        "my-app\t1/2\n",
        "my-app\t3/2\n",
        "my-app\t2/3\n",
        "my-app\t2/2\nmy-app\t2/2\n",
        "my-app-worker\t2/2\n",
    ],
    ids=[
        "zero",
        "partial",
        "excess-running",
        "excess-desired",
        "duplicates",
        "similar-name",
    ],
)
def test_verify_deploy_requires_one_exact_row_matching_instance_count(
    monkeypatch, service_rows
):
    api = _VerificationAPI(_deployment_definition(version=8, instance_count=2))
    monkeypatch.setattr(
        cd.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=service_rows),
    )

    assert cd.verify_deploy(
        api,
        "my-app",
        ssh_cmd=["ssh", "host"],
        baseline=7,
        expected_source_id=SOURCE_SHA,
    ) is False


def test_verify_deploy_rejects_one_of_one_when_two_replicas_are_intended(monkeypatch):
    api = _VerificationAPI(_deployment_definition(version=8, instance_count=2))
    monkeypatch.setattr(
        cd.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="my-app\t1/1\n",
        ),
    )

    assert cd.verify_deploy(
        api,
        "my-app",
        ssh_cmd=["ssh", "host"],
        baseline=7,
        expected_source_id=SOURCE_SHA,
    ) is False


def test_verify_deploy_rejects_zero_intended_replicas_without_ssh(monkeypatch):
    api = _VerificationAPI(_deployment_definition(version=8, instance_count=0))
    monkeypatch.setattr(
        cd.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("SSH must not run for an invalid replica target"),
    )

    assert cd.verify_deploy(
        api,
        "my-app",
        ssh_cmd=["ssh", "host"],
        baseline=7,
        expected_source_id=SOURCE_SHA,
    ) is False


def test_verify_deploy_rejects_failed_ssh_check_without_printing_output(monkeypatch, capsys):
    api = _VerificationAPI(_deployment_definition(version=8, instance_count=2))
    monkeypatch.setattr(
        cd.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=255,
            stdout="SENSITIVE-CANARY",
            stderr="SENSITIVE-CANARY",
        ),
    )

    assert cd.verify_deploy(
        api,
        "my-app",
        ssh_cmd=["ssh", "host"],
        baseline=7,
        expected_source_id=SOURCE_SHA,
    ) is False
    assert "SENSITIVE-CANARY" not in capsys.readouterr().out


def test_verify_deploy_sanitizes_unexpected_exception(capsys):
    class BrokenAPI:
        def get_build_status(self, app_name):
            raise RuntimeError("SENSITIVE-CANARY-token-path")

    assert cd.verify_deploy(
        BrokenAPI(), "my-app", baseline=7, expected_source_id=SOURCE_SHA
    ) is False
    assert "SENSITIVE-CANARY" not in capsys.readouterr().out
