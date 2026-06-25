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
import sys
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
        assert (
            cd.validate_caprover_url(
                "https://captain.example.com/",
                expected_host="captain.example.com",
            )
            == "https://captain.example.com"
        )

    def test_non_local_https_url_requires_expected_host(self):
        with pytest.raises(CapRoverDeployError) as exc:
            cd.validate_caprover_url("https://attacker.example/")
        assert exc.value.code == "caprover_config_invalid"
        assert "expected-host" in exc.value.message

    def test_http_url_is_rejected_by_default(self):
        with pytest.raises(CapRoverDeployError) as exc:
            cd.validate_caprover_url("http://captain.example.com", expected_host="captain.example.com")
        assert exc.value.code == "caprover_config_invalid"

    def test_local_http_url_requires_explicit_insecure_opt_in(self):
        assert (
            cd.validate_caprover_url("http://127.0.0.1:3000", allow_insecure=True)
            == "http://127.0.0.1:3000"
        )

    def test_allow_insecure_rejects_remote_http_even_with_expected_host(self):
        with pytest.raises(CapRoverDeployError) as exc:
            cd.validate_caprover_url(
                "http://captain.example.com",
                allow_insecure=True,
                expected_host="captain.example.com",
            )

        assert exc.value.code == "caprover_config_invalid"
        assert "allow-insecure" in exc.value.message

    def test_allow_insecure_rejects_remote_https_tls_bypass(self):
        with pytest.raises(CapRoverDeployError) as exc:
            cd.validate_caprover_url(
                "https://captain.example.com",
                allow_insecure=True,
                expected_host="captain.example.com",
            )

        assert exc.value.code == "caprover_config_invalid"
        assert "allow-insecure" in exc.value.message

    def test_url_rejects_embedded_credentials(self):
        with pytest.raises(CapRoverDeployError):
            cd.validate_caprover_url(
                "https://admin:secret@captain.example.com",
                expected_host="captain.example.com",
            )

    def test_expected_host_must_match(self):
        with pytest.raises(CapRoverDeployError):
            cd.validate_caprover_url("https://captain.evil.example", expected_host="captain.example.com")

    def test_playwright_does_not_ignore_tls_by_default(self):
        source = SCRIPT.read_text()
        assert "ignore_https_errors=True" not in source
        assert "ignore_https_errors=args.allow_insecure" in source

    def test_main_rejects_remote_allow_insecure_before_password_resolution(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", [
            "caprover_deploy.py",
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--allow-insecure",
            "--app-name", "my-app",
        ])
        monkeypatch.setattr(cd, "get_password", lambda args: pytest.fail("password was resolved"))

        with pytest.raises(SystemExit) as exc:
            cd.main()

        assert exc.value.code == 2
        out = capsys.readouterr().out
        assert "caprover_config_invalid" in out
        assert "allow-insecure" in out


class TestRepoSafety:
    def test_github_repo_url_default_host_is_normalized(self):
        assert (
            cd.validate_github_repo_url("https://github.com/org/repo.git/")
            == "https://github.com/org/repo.git"
        )

    def test_repo_url_rejects_attacker_host_before_token_resolution(self):
        with pytest.raises(CapRoverDeployError) as exc:
            cd.validate_github_repo_url("https://attacker.example/org/repo.git")

        assert exc.value.code == "caprover_config_invalid"
        assert "expected-repo-host" in exc.value.message

    def test_repo_url_allows_expected_enterprise_host(self):
        assert (
            cd.validate_github_repo_url(
                "https://git.example.com:8443/org/repo",
                expected_host="git.example.com:8443",
            )
            == "https://git.example.com:8443/org/repo"
        )

    @pytest.mark.parametrize("expected_host", ["git.example.com/path", "user@git.example.com", "git.example.com?x=1"])
    def test_expected_repo_host_must_be_host_only(self, expected_host):
        with pytest.raises(CapRoverDeployError):
            cd.validate_github_repo_url("https://git.example.com/org/repo", expected_host=expected_host)

    @pytest.mark.parametrize(
        "repo",
        [
            "git@github.com:org/repo.git",
            "https://user:secret@github.com/org/repo",
            "https://github.com/org/repo?token=secret",
            "https://github.com/org/repo#secret",
            "https://github.com/org",
            "https://github.com:8443/org/repo",
        ],
    )
    def test_repo_url_rejects_unsafe_shapes(self, repo):
        with pytest.raises(CapRoverDeployError):
            cd.validate_github_repo_url(repo)

    def test_main_validates_repo_before_credential_resolution(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", [
            "caprover_deploy.py",
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--app-name", "my-app",
            "--repo", "https://attacker.example/org/repo",
        ])
        monkeypatch.setattr(cd, "get_password", lambda args: pytest.fail("password was resolved"))
        monkeypatch.setattr(cd, "get_github_creds", lambda args: pytest.fail("GitHub credentials were resolved"))

        with pytest.raises(SystemExit) as exc:
            cd.main()

        assert exc.value.code == 2
        out = capsys.readouterr().out
        assert "caprover_config_invalid" in out
        assert "repo validation" in out

    def test_custom_repo_host_requires_host_specific_token_env(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "generic-github-token")
        args = SimpleNamespace(
            github_user=None,
            repo="https://git.example.com/org/repo",
            repo_token_env=None,
        )

        with pytest.raises(CapRoverDeployError) as exc:
            cd.get_github_creds(args)

        assert exc.value.code == "caprover_config_invalid"
        assert "--repo-token-env" in exc.value.message

    def test_custom_repo_host_rejects_generic_github_token_env(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "generic-github-token")
        args = SimpleNamespace(
            github_user=None,
            repo="https://git.example.com/org/repo",
            repo_token_env="GITHUB_TOKEN",
        )

        with pytest.raises(CapRoverDeployError) as exc:
            cd.get_github_creds(args)

        assert exc.value.code == "caprover_config_invalid"
        assert "host-specific" in exc.value.message

    def test_custom_repo_host_does_not_fallback_to_gh_auth_token(self, monkeypatch):
        def fail_if_gh_auth_is_called(*args, **kwargs):
            pytest.fail("gh auth token was called for a custom repo host")

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setattr(cd.subprocess, "run", fail_if_gh_auth_is_called)
        args = SimpleNamespace(
            github_user=None,
            repo="https://git.example.com/org/repo",
            repo_token_env=None,
        )

        with pytest.raises(CapRoverDeployError) as exc:
            cd.get_github_creds(args)

        assert exc.value.code == "caprover_config_invalid"
        assert "--repo-token-env" in exc.value.message

    def test_custom_repo_host_uses_only_declared_token_env(self, monkeypatch):
        def fail_if_gh_auth_is_called(*args, **kwargs):
            pytest.fail("gh auth token was called for a custom repo host")

        monkeypatch.setattr(cd.subprocess, "run", fail_if_gh_auth_is_called)
        monkeypatch.setenv("GITHUB_TOKEN", "generic-github-token")
        monkeypatch.setenv("GIT_EXAMPLE_TOKEN", "host-specific-token")
        args = SimpleNamespace(
            github_user="alice",
            repo="https://git.example.com/org/repo",
            repo_token_env="GIT_EXAMPLE_TOKEN",
        )

        assert cd.get_github_creds(args) == ("alice", "host-specific-token")

    def test_main_rejects_custom_repo_missing_token_env_before_password_resolution(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "generic-github-token")
        monkeypatch.setattr(sys, "argv", [
            "caprover_deploy.py",
            "--caprover-url", "https://captain.example.com",
            "--expected-host", "captain.example.com",
            "--app-name", "my-app",
            "--repo", "https://git.example.com/org/repo",
            "--expected-repo-host", "git.example.com",
        ])
        monkeypatch.setattr(cd, "get_password", lambda args: pytest.fail("password was resolved"))

        with pytest.raises(SystemExit) as exc:
            cd.main()

        assert exc.value.code == 2
        out = capsys.readouterr().out
        assert "caprover_config_invalid" in out
        assert "repo token validation" in out


class TestCliDeploySafety:
    def test_cli_deploy_binds_target_app_and_password_env(self, monkeypatch):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            if cmd == ["caprover", "--version"]:
                return SimpleNamespace(returncode=0, stdout="2.3.1", stderr="")
            if cmd == ["node", "--version"]:
                return SimpleNamespace(returncode=0, stdout="v24.0.0", stderr="")
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr(cd.subprocess, "run", fake_run)
        monkeypatch.setenv("CAPROVER_CONFIG_FILE", "/tmp/stale.yaml")
        monkeypatch.setenv("CAPROVER_NAME", "stale-machine")
        monkeypatch.setenv("CAPROVER_APP_TOKEN", "stale-token")

        args = SimpleNamespace(
            app_name="my-app",
            branch="main",
            caprover_url="https://captain.example.com",
            tarball=None,
        )

        assert cd.try_cli_deploy(args, "captain-secret") is True

        deploy_cmd, deploy_kwargs = calls[-1]
        assert deploy_cmd == [
            "caprover",
            "deploy",
            "--caproverUrl",
            "https://captain.example.com",
            "--caproverApp",
            "my-app",
            "--branch",
            "main",
        ]
        assert "captain-secret" not in deploy_cmd

        deploy_env = deploy_kwargs["env"]
        assert deploy_env["CAPROVER_PASSWORD"] == "captain-secret"
        assert deploy_env["CAPROVER_URL"] == "https://captain.example.com"
        assert deploy_env["CAPROVER_APP"] == "my-app"
        assert deploy_env["CAPROVER_BRANCH"] == "main"
        assert "CAPROVER_CONFIG_FILE" not in deploy_env
        assert "CAPROVER_NAME" not in deploy_env
        assert "CAPROVER_APP_TOKEN" not in deploy_env


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
            "--expected-host", "captain.example.com",
            "--repo-token-env", "GIT_EXAMPLE_TOKEN",
        ])
        assert args.repo_token_env == "GIT_EXAMPLE_TOKEN"
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
