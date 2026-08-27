import importlib.util
import os
import stat
import sys
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "agilize_login.py"


class FakeResponse:
    status_code = 200
    text = ""
    headers = {}


def load_script(monkeypatch):
    captured = {}
    fake_requests = types.ModuleType("requests")
    fake_requests.Response = FakeResponse

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, *args, **kwargs):
            return FakeResponse()

        def post(self, *args, **kwargs):
            return FakeResponse()

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})
        captured["kwargs"] = kwargs
        return FakeResponse()

    fake_requests.Session = FakeSession
    fake_requests.get = fake_get
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    module_name = "agilize_login_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module, captured


def test_api_get_rejects_external_absolute_url_before_request(monkeypatch):
    module, captured = load_script(monkeypatch)
    token = module.LoginResult("DUMMY_TOKEN", 3600, "Bearer", 0)

    with pytest.raises(SystemExit):
        module.api_get(token, "https://attacker.example/collect", "12345678000199", 5)

    assert captured == {}


def test_api_get_allows_relative_api_path_and_disables_redirects(monkeypatch):
    module, captured = load_script(monkeypatch)
    token = module.LoginResult("DUMMY_TOKEN", 3600, "Bearer", 0)

    module.api_get(token, "api/v1/companies/abc/finance-accounts?count=1", "12345678000199", 5)

    assert captured["url"] == "https://app.agilize.com.br/api/v1/companies/abc/finance-accounts?count=1"
    assert captured["headers"]["Authorization"] == "Bearer DUMMY_TOKEN"
    assert captured["headers"]["key"] == "12345678000199"
    assert captured["kwargs"]["allow_redirects"] is False


def test_api_get_allows_same_origin_api_url(monkeypatch):
    module, captured = load_script(monkeypatch)
    token = module.LoginResult("DUMMY_TOKEN", 3600, "Bearer", 0)

    module.api_get(token, "https://app.agilize.com.br/api/v1/companies/abc", "", 5)

    assert captured["url"] == "https://app.agilize.com.br/api/v1/companies/abc"
    assert "key" not in captured["headers"]


def test_api_get_rejects_same_origin_non_api_path_before_request(monkeypatch):
    module, captured = load_script(monkeypatch)
    token = module.LoginResult("DUMMY_TOKEN", 3600, "Bearer", 0)

    with pytest.raises(SystemExit):
        module.api_get(token, "https://app.agilize.com.br/#/dashboard", "", 5)

    assert captured == {}


def test_auth_form_action_rejects_external_absolute_origin(monkeypatch):
    module, _ = load_script(monkeypatch)

    with pytest.raises(SystemExit):
        module.absolute_action("https://attacker.example/collect", module.AUTH_URL)


def test_oidc_callback_requires_matching_state(monkeypatch, capsys):
    module, _ = load_script(monkeypatch)

    with pytest.raises(SystemExit):
        module.code_from_url("https://app.agilize.com.br/?code=auth-code", expected_state="tx-state")
    assert "state missing or mismatch" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        module.code_from_url("https://app.agilize.com.br/?code=auth-code&state=wrong", expected_state="tx-state")
    assert "state missing or mismatch" in capsys.readouterr().err
    assert module.code_from_url(
        "https://app.agilize.com.br/?code=auth-code&state=tx-state", expected_state="tx-state"
    ) == "auth-code"


def test_auth_form_action_rejects_protocol_relative_origin(monkeypatch):
    module, _ = load_script(monkeypatch)

    with pytest.raises(SystemExit):
        module.absolute_action("//attacker.example/collect", module.AUTH_URL)


def test_auth_form_action_allows_relative_sso_action(monkeypatch):
    module, _ = load_script(monkeypatch)

    assert (
        module.absolute_action("/auth/realms/AgilizeAPPs/login-actions/authenticate", module.AUTH_URL)
        == "https://sso.agilize.com.br/auth/realms/AgilizeAPPs/login-actions/authenticate"
    )


def test_sso_redirect_resolution_rejects_external_origins_and_allows_callback(monkeypatch):
    module, _ = load_script(monkeypatch)

    assert module.resolve_sso_redirect("/auth/continue", module.AUTH_URL, module.DEFAULT_REDIRECT_URI).startswith(module.EXPECTED_SSO_SCHEME)
    assert module.resolve_sso_redirect("https://app.agilize.com.br/?code=auth&state=state", module.AUTH_URL, module.DEFAULT_REDIRECT_URI).startswith(module.DEFAULT_REDIRECT_URI)
    with pytest.raises(SystemExit):
        module.resolve_sso_redirect("https://attacker.example/collect", module.AUTH_URL, module.DEFAULT_REDIRECT_URI)


def test_sso_fetch_disables_automatic_redirects_and_rejects_an_external_hop(monkeypatch):
    module, _ = load_script(monkeypatch)
    calls = []

    class Session:
        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            response = FakeResponse()
            response.status_code = 302
            response.url = url
            response.headers = {"Location": "https://attacker.example/collect"}
            return response

    with pytest.raises(SystemExit):
        module.fetch_sso_page(Session(), module.AUTH_URL, module.DEFAULT_REDIRECT_URI, 5)

    assert calls[0][1]["allow_redirects"] is False


def test_config_file_with_credentials_must_not_be_group_or_world_readable(monkeypatch, tmp_path):
    module, _ = load_script(monkeypatch)
    config = tmp_path / "agilize.json"
    config.write_text('{"username":"user","password":"secret"}', encoding="utf-8")
    config.chmod(0o644)

    with pytest.raises(SystemExit):
        module.load_config_file(str(config))

    config.chmod(0o600)
    assert module.load_config_file(str(config))["username"] == "user"


def test_write_secure_uses_private_mode_and_does_not_follow_symlink(monkeypatch, tmp_path):
    module, _ = load_script(monkeypatch)
    output = tmp_path / "out" / "response.json"

    module.write_secure(str(output), '{"ok":true}')

    assert output.read_text(encoding="utf-8") == '{"ok":true}'
    assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(output.stat().st_mode) == 0o600

    if not hasattr(os, "O_NOFOLLOW"):
        return

    target = tmp_path / "target.json"
    target.write_text("do not overwrite", encoding="utf-8")
    symlink = tmp_path / "out" / "linked.json"
    symlink.symlink_to(target)

    with pytest.raises(OSError):
        module.write_secure(str(symlink), '{"ok":false}')

    assert target.read_text(encoding="utf-8") == "do not overwrite"


def test_write_secure_rejects_symlink_output_dir(monkeypatch, tmp_path):
    module, _ = load_script(monkeypatch)
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    linked_dir = tmp_path / "linked"
    linked_dir.symlink_to(real_dir, target_is_directory=True)

    with pytest.raises(OSError):
        module.write_secure(str(linked_dir / "response.json"), '{"ok":true}')


def test_write_secure_rejects_symlinked_output_ancestor_without_writing(monkeypatch, tmp_path):
    module, _ = load_script(monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.json"
    sentinel.write_text("keep", encoding="utf-8")
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError, match="symlink"):
        module.write_secure(str(linked_parent / "reports" / "response.json"), '{"ok":true}')

    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (outside / "reports" / "response.json").exists()
