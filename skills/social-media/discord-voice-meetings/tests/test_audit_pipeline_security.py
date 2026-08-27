import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "audit-meeting-pipeline.py"
HELPERS = ROOT / "scripts" / "audit_helpers.py"
TROUBLESHOOTING = ROOT / "references" / "troubleshooting.md"
ENV_EXAMPLE = ROOT / "templates" / "env.example"
SKILL = ROOT / "SKILL.md"


def load_helpers(monkeypatch):
    module_name = "audit_helpers_under_test"
    spec = importlib.util.spec_from_file_location(module_name, HELPERS)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load audit helpers")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def test_probe_uses_a_bounded_in_process_request_with_bearer_header(monkeypatch):
    module = load_helpers(monkeypatch)
    observed = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size):
            observed["read_size"] = size
            return b'{"choices": []}'

    class Opener:
        def open(self, request, timeout):
            observed["authorization"] = request.get_header("Authorization")
            observed["timeout"] = timeout
            return Response()

    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *_handlers: Opener())

    assert module.probe_zai_endpoint("https://api.example.test/v1", "test-token", timeout=7) == '{"choices": []}'
    assert observed["authorization"] == "Bearer test-token"
    assert observed["timeout"] == 7
    assert observed["read_size"] == module.MAX_PROBE_RESPONSE_BYTES + 1


def test_log_summary_redacts_secret_assignments_and_transcript_content(monkeypatch):
    module = load_helpers(monkeypatch)
    line = "2026-08-27T12:00:00Z voice token=sentinel-secret private transcript words"

    summary = module.summarize_log_line(line)

    assert "sentinel-secret" not in summary
    assert "private transcript words" not in summary
    assert "voice" in summary
    assert f"chars={len(line)}" in summary


def test_private_env_reader_rejects_broad_permissions_before_returning_value(monkeypatch, tmp_path):
    module = load_helpers(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("GLM_API_KEY=private-test-value\n", encoding="utf-8")
    env_file.chmod(0o600)

    assert module.load_private_env_value(env_file, "GLM_API_KEY") == ("private-test-value", "ok")

    env_file.chmod(0o644)
    assert module.load_private_env_value(env_file, "GLM_API_KEY") == (None, "broad_permissions")


def test_private_env_reader_rejects_symlinked_ancestor_without_returning_value(monkeypatch, tmp_path):
    module = load_helpers(monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / ".env"
    target.write_text("GLM_API_KEY=private-test-value\n", encoding="utf-8")
    target.chmod(0o600)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)

    assert module.load_private_env_value(linked_parent / ".env", "GLM_API_KEY") == (None, "unreadable")


def test_audit_entrypoint_redacts_gateway_log_content(monkeypatch, tmp_path):
    home = tmp_path / "home"
    gateway_log = home / ".hermes" / "logs" / "gateway.log"
    gateway_log.parent.mkdir(parents=True)
    gateway_log.write_text(
        "2026-08-27T12:00:00Z voice token=sentinel-secret private transcript words\n",
        encoding="utf-8",
    )
    (home / ".hermes" / "hermes-agent").mkdir(parents=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    commands = {
        "git": "#!/bin/sh\nexit 0\n",
        "systemctl": "#!/bin/sh\nexit 0\n",
        "pgrep": "#!/bin/sh\nexit 1\n",
        "tail": "#!/bin/sh\n/usr/bin/tail \"$@\"\n",
    }
    for name, body in commands.items():
        command = fake_bin / name
        command.write_text(body, encoding="utf-8")
        command.chmod(command.stat().st_mode | stat.S_IXUSR)
    env = {**os.environ, "HOME": str(home), "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=SCRIPT.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "sentinel-secret" not in result.stdout
    assert "private transcript words" not in result.stdout
    assert "voice log line (chars=" in result.stdout


def test_env_docs_require_private_permissions():
    assert "chmod 600 .env" in ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "chmod 600 .env" in SKILL.read_text(encoding="utf-8")
    assert "audit-meeting-pipeline.py" in TROUBLESHOOTING.read_text(encoding="utf-8")
