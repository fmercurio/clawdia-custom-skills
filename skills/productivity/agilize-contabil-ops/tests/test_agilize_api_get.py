import importlib.util
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
