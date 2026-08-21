from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import types
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "archiver_extract_context.py"


def load_module():
    spec = importlib.util.spec_from_file_location("archiver_extract_context_security", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, status: int, headers: dict[str, str], body: bytes = b""):
        self.status = status
        self.headers = headers
        self._body = body

    def read(self, _limit: int) -> bytes:
        return self._body


class FakeConnection:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.closed = False

    def request(self, method: str, target: str, headers: dict[str, str]) -> None:
        self.requests.append((method, target, headers))

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


def public_address(host: str, port: int, *_args, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def test_rejects_loopback_before_opening_connection(monkeypatch):
    module = load_module()
    opened = False

    def private_address(host: str, port: int, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    def fail_if_opened(*_args, **_kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("private URL must not be opened")

    monkeypatch.setattr(module.socket, "getaddrinfo", private_address)
    monkeypatch.setattr(module, "_make_connection", fail_if_opened)

    result = module.extract_url_context("http://127.0.0.1/private")

    assert result["context_status"] == "failed"
    assert result["error"] == "unsafe_url:non_public_address"
    assert not opened


def test_pdf_input_budget_is_checked_before_loading_pymupdf(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "import_module", lambda _name: pytest.fail("PDF parser must not load"))

    result = module._extract_pdf_context("https://example.com/report.pdf", b"x" * 5, max_bytes=4)

    assert result["context_status"] == "failed"
    assert result["error"] == "pdf exceeds the 4-byte input limit"


def test_pdf_extraction_uses_limited_worker_and_preserves_success_payload(monkeypatch):
    module = load_module()
    observed = {}
    worker_payload = {
        "url": "",
        "title": "Report",
        "description": None,
        "extracted_text": "Safe text",
        "summary": "Safe text",
        "keywords": ["safe"],
        "context_status": "extracted",
        "extractor": "pymupdf",
        "error": None,
    }

    def run_worker(raw_bytes):
        observed["raw_bytes"] = raw_bytes
        return "ok", json.dumps(worker_payload).encode("utf-8")

    monkeypatch.setattr(module, "_run_pdf_worker", run_worker)

    result = module._extract_pdf_context("https://example.com/report.pdf", b"%PDF-1.7")

    assert observed["raw_bytes"] == b"%PDF-1.7"
    assert result["url"] == "https://example.com/report.pdf"
    assert result["context_status"] == "extracted"
    assert result["extracted_text"] == "Safe text"


def test_pdf_worker_timeout_fails_closed(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "_run_pdf_worker", lambda _raw_bytes: ("timeout", b""))

    result = module._extract_pdf_context("https://example.com/report.pdf", b"%PDF-1.7")

    assert result["context_status"] == "failed"
    assert result["error"] == "pdf_worker_timeout"


def test_pdf_worker_uses_cpu_limit_and_memory_watchdog(monkeypatch):
    module = load_module()
    observed = {}

    class Input:
        def write(self, raw_bytes):
            observed["raw_bytes"] = raw_bytes

        def close(self):
            observed["closed"] = True

    class Output:
        def read(self, _size):
            return b"{}"

    class Process:
        pid = 123
        returncode = 0
        stdin = Input()
        stdout = Output()

        def poll(self):
            return 0

    def popen(command, **kwargs):
        observed["command"] = command
        observed.update(kwargs)
        return Process()

    monkeypatch.setattr(module.subprocess, "Popen", popen)

    status, output = module._run_pdf_worker(b"%PDF-1.7")

    assert status == "ok"
    assert output == b"{}"
    assert observed["command"][-1] == "--pdf-worker"
    assert observed["preexec_fn"] is module._limit_pdf_worker
    assert observed["raw_bytes"] == b"%PDF-1.7"


def test_pdf_worker_memory_limit_fails_closed(monkeypatch):
    module = load_module()

    class Input:
        def write(self, _raw_bytes):
            return None

        def close(self):
            return None

    class Process:
        pid = 123
        stdin = Input()
        stdout = types.SimpleNamespace(read=lambda _size: b"")

        def poll(self):
            return None

        def kill(self):
            return None

        def wait(self):
            return None

    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(module, "_worker_rss_bytes", lambda _pid: module.PDF_WORKER_MAX_MEMORY_BYTES + 1)

    status, output = module._run_pdf_worker(b"%PDF-1.7")

    assert status == "memory_limit"
    assert output == b""


def test_fetch_rejects_response_larger_than_budget(monkeypatch):
    module = load_module()
    response = FakeResponse(200, {"Content-Type": "text/plain"}, b"hello")
    monkeypatch.setattr(module.socket, "getaddrinfo", public_address)
    monkeypatch.setattr(module, "_make_connection", lambda *_args: FakeConnection(response))

    with pytest.raises(ValueError, match="input limit"):
        module._fetch_public_url("https://example.com/article", 5, 4, 8)


def test_rejects_mixed_public_and_private_dns_answers(monkeypatch):
    module = load_module()
    opened = False

    def mixed_addresses(host: str, port: int, *_args, **_kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", port)),
        ]

    def fail_if_opened(*_args, **_kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("mixed DNS answers must not be opened")

    monkeypatch.setattr(module.socket, "getaddrinfo", mixed_addresses)
    monkeypatch.setattr(module, "_make_connection", fail_if_opened)

    result = module.extract_url_context("https://example.com/article")

    assert result["context_status"] == "failed"
    assert result["error"] == "unsafe_url:non_public_address"
    assert not opened


def test_uses_vetted_public_address_for_connection(monkeypatch):
    module = load_module()
    connections: list[tuple[str, str, int, str]] = []
    response = FakeResponse(200, {"Content-Type": "text/plain"}, b"Public content")

    def make_connection(scheme: str, host: str, port: int, address: str, timeout: int):
        connections.append((scheme, host, port, address))
        return FakeConnection(response)

    monkeypatch.setattr(module.socket, "getaddrinfo", public_address)
    monkeypatch.setattr(module, "_make_connection", make_connection)

    result = module.extract_url_context("https://example.com/article")

    assert result["context_status"] == "extracted"
    assert result["extracted_text"] == "Public content"
    assert connections == [("https", "example.com", 443, "93.184.216.34")]


def test_revalidates_redirect_target_before_opening_it(monkeypatch):
    module = load_module()
    calls: list[tuple[str, str, int, str]] = []
    first = FakeResponse(302, {"Location": "http://127.0.0.1/private"})

    def resolver(host: str, port: int, *_args, **_kwargs):
        address = "93.184.216.34" if host == "example.com" else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    def make_connection(scheme: str, host: str, port: int, address: str, timeout: int):
        calls.append((scheme, host, port, address))
        return FakeConnection(first)

    monkeypatch.setattr(module.socket, "getaddrinfo", resolver)
    monkeypatch.setattr(module, "_make_connection", make_connection)

    result = module.extract_url_context("https://example.com/redirect")

    assert result["context_status"] == "failed"
    assert result["error"] == "unsafe_url:non_public_address"
    assert calls == [("https", "example.com", 443, "93.184.216.34")]


def test_rejects_embedded_credentials_without_dns_lookup(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module.socket, "getaddrinfo", lambda *_args, **_kwargs: pytest.fail("unexpected DNS lookup"))

    result = module.extract_url_context("https://user:password@example.com/private")

    assert result["context_status"] == "failed"
    assert result["error"] == "unsafe_url:credentials_not_allowed"
