"""Real Chromium coverage for the Force Build request/response boundary."""

import importlib.util
import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "caprover_deploy.py"
spec = importlib.util.spec_from_file_location("caprover_deploy_browser", SCRIPT)
cd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cd)

APP = "fixture-app"
TOKEN = "synthetic-approved-webhook-token"
TRIGGER_PATH = (
    "/api/v2/user/apps/webhooks/triggerbuild"
    f"?token={TOKEN}&namespace=captain"
)


def _dashboard_html():
    return f"""<!doctype html>
<html><body>
  <input type="password">
  <button id="login">Login</button>
  <div>Deployment</div>
  <button id="force">Force Build</button>
  <script>
    document.querySelector('#login').addEventListener('click', () => {{
      document.querySelector('input[type=password]').remove();
    }});
    document.querySelector('#force').addEventListener('click', () => {{
      fetch({json.dumps(TRIGGER_PATH)}, {{method: 'POST'}});
    }});
  </script>
</body></html>"""


class _BrowserFixture(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, mode):
        self.mode = mode
        self.post_count = 0
        self.response_completed = threading.Event()
        super().__init__(("127.0.0.1", 0), _BrowserHandler)


class _BrowserHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        return

    def do_GET(self):
        body = _dashboard_html().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.server.post_count += 1
        assert self.path == TRIGGER_PATH
        status = 100 if self.server.mode != "rejected" else 1108
        body = json.dumps({"status": status, "data": {}}).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.flush()
            if self.server.mode == "body_timeout":
                time.sleep(2)
            elif self.server.mode == "accepted":
                time.sleep(0.25)
            self.wfile.write(body)
            self.wfile.flush()
            self.server.response_completed.set()
        except (BrokenPipeError, ConnectionResetError):
            pass


@contextmanager
def _server(mode):
    server = _BrowserFixture(mode)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _args(server):
    return SimpleNamespace(
        caprover_url=f"http://127.0.0.1:{server.server_port}",
        app_name=APP,
        allow_insecure=True,
        timeout=1,
        playwright_trigger_token=TOKEN,
    )


def _require_chromium():
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser.close()
    except Exception as error:
        pytest.fail(f"mandatory isolated Chromium prerequisite unavailable: {type(error).__name__}")


def test_force_build_waits_for_delayed_exact_acceptance_before_browser_cleanup():
    _require_chromium()
    with _server("accepted") as server:
        assert cd.deploy_via_playwright(_args(server), "synthetic-password", "", "") is True
        assert server.post_count == 1
        assert server.response_completed.is_set()


def test_force_build_server_rejection_is_inconclusive_and_not_retried():
    _require_chromium()
    with _server("rejected") as server:
        with pytest.raises(cd.CapRoverDeployError) as exc:
            cd.deploy_via_playwright(_args(server), "synthetic-password", "", "")

        assert exc.value.code == "reconcile_required"
        assert server.post_count == 1


def test_force_build_body_timeout_after_immediate_headers_is_inconclusive_and_not_retried():
    _require_chromium()
    with _server("body_timeout") as server:
        with pytest.raises(cd.CapRoverDeployError) as exc:
            cd.deploy_via_playwright(_args(server), "synthetic-password", "", "")

        assert exc.value.code == "reconcile_required"
        assert server.post_count == 1
