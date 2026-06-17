"""
Tests for the CapRover deploy sanitized preflight.

Covers:
- happy path (auth OK, app visible)
- auth blocked (401/403)
- network blocked (status -1)
- config invalid (app not found)
- fail() exits with correct code and sanitized message
"""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "caprover_deploy.py"
spec = importlib.util.spec_from_file_location("caprover_deploy", SCRIPT)
cd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cd)

CapRoverAPI = cd.CapRoverAPI
CapRoverDeployError = cd.CapRoverDeployError


def make_api(system_status=100, app_exists=True):
    api = CapRoverAPI("https://captain.example.com")

    def fake_request(method, path, payload=None):
        if path == "/api/v2/user/system/info/":
            return {"status": system_status, "data": {"ok": True}}
        if path == "/api/v2/user/apps/appDefinitions/":
            defs = [{"appName": "my-app"}] if app_exists else []
            return {"data": {"appDefinitions": defs}}
        return {}

    api._request = fake_request
    return api


class TestPreflight:
    def test_happy_path(self):
        api = make_api(system_status=100, app_exists=True)
        assert api.preflight("my-app") is True

    def test_auth_blocked_401(self):
        api = make_api(system_status=401, app_exists=True)
        with pytest.raises(CapRoverDeployError) as exc:
            api.preflight("my-app")
        assert exc.value.code == "caprover_auth_blocked"

    def test_auth_blocked_403(self):
        api = make_api(system_status=403, app_exists=True)
        with pytest.raises(CapRoverDeployError) as exc:
            api.preflight("my-app")
        assert exc.value.code == "caprover_auth_blocked"

    def test_network_blocked(self):
        api = make_api(system_status=-1, app_exists=True)
        with pytest.raises(CapRoverDeployError) as exc:
            api.preflight("my-app")
        assert exc.value.code == "caprover_network_blocked"

    def test_config_invalid_unexpected_status(self):
        api = make_api(system_status=500, app_exists=True)
        with pytest.raises(CapRoverDeployError) as exc:
            api.preflight("my-app")
        assert exc.value.code == "caprover_config_invalid"

    def test_config_invalid_app_missing(self):
        api = make_api(system_status=100, app_exists=False)
        with pytest.raises(CapRoverDeployError) as exc:
            api.preflight("my-app")
        assert exc.value.code == "caprover_config_invalid"


class TestFail:
    def test_fail_exits_with_code_1(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cd.fail("caprover_build_failed", "Build failed", detail="test")
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "caprover_build_failed" in out
        assert "Build failed" in out

    def test_fail_no_message(self, capsys):
        with pytest.raises(SystemExit):
            cd.fail("caprover_auth_blocked")
        out = capsys.readouterr().out
        assert "caprover_auth_blocked" in out

    def test_fail_does_not_leak_secrets(self, capsys):
        with pytest.raises(SystemExit):
            cd.fail("caprover_auth_blocked", "Auth blocked", detail="login failed")
        out = capsys.readouterr().out.lower()
        for s in ["gho_", "token", "password", "captain."]:
            assert s not in out, f"Potential secret '{s}' found in output"


class TestSanitization:
    def test_error_message_is_sanitized(self):
        err = CapRoverDeployError("caprover_auth_blocked")
        assert err.code == "caprover_auth_blocked"
        assert "token" not in str(err).lower()
        assert "password" not in str(err).lower()
