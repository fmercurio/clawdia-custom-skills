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
from types import SimpleNamespace
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


class TestUrlSafety:
    def test_https_url_is_normalized(self):
        assert cd.validate_caprover_url("https://captain.example.com/") == "https://captain.example.com"

    def test_http_url_is_rejected_by_default(self):
        with pytest.raises(CapRoverDeployError) as exc:
            cd.validate_caprover_url("http://captain.example.com")
        assert exc.value.code == "caprover_config_invalid"

    def test_http_url_requires_explicit_insecure_opt_in(self):
        assert (
            cd.validate_caprover_url("http://127.0.0.1:3000", allow_insecure=True)
            == "http://127.0.0.1:3000"
        )

    def test_url_rejects_embedded_credentials(self):
        with pytest.raises(CapRoverDeployError):
            cd.validate_caprover_url("https://admin:secret@captain.example.com")

    def test_expected_host_must_match(self):
        with pytest.raises(CapRoverDeployError):
            cd.validate_caprover_url("https://captain.evil.example", expected_host="captain.example.com")

    def test_playwright_does_not_ignore_tls_by_default(self):
        source = SCRIPT.read_text()
        assert "ignore_https_errors=True" not in source
        assert "ignore_https_errors=args.allow_insecure" in source


class TestSecretSources:
    def test_parser_no_longer_accepts_secret_argv_flags(self):
        parser = cd.build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([
                "--caprover-url", "https://captain.example.com",
                "--app-name", "my-app",
                "--caprover-password", "secret",
            ])
        with pytest.raises(SystemExit):
            parser.parse_args([
                "--caprover-url", "https://captain.example.com",
                "--app-name", "my-app",
                "--github-token", "secret",
            ])

    def test_parser_has_no_secret_attributes(self):
        args = cd.build_arg_parser().parse_args([
            "--caprover-url", "https://captain.example.com",
            "--app-name", "my-app",
        ])
        assert not hasattr(args, "caprover_password")
        assert not hasattr(args, "github_token")

    def test_caprover_password_comes_from_env(self, monkeypatch):
        monkeypatch.setenv("CAPROVER_PASSWORD", "from-env")
        args = SimpleNamespace(keepass_entry=None)
        assert cd.get_password(args) == "from-env"

    def test_keepass_requires_explicit_db_and_key_env(self, monkeypatch, capsys):
        monkeypatch.delenv("CAPROVER_PASSWORD", raising=False)
        monkeypatch.delenv("KEEPASS_DB", raising=False)
        monkeypatch.delenv("KEEPASS_KEY", raising=False)
        args = SimpleNamespace(keepass_entry="/CapRover")

        with pytest.raises(SystemExit) as exc:
            cd.get_password(args)

        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "KEEPASS_DB" in err
        assert "/Users/Shared" not in SCRIPT.read_text()
