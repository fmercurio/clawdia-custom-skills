from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "audit-meeting-pipeline.py"
TROUBLESHOOTING = Path(__file__).resolve().parent.parent / "references" / "troubleshooting.md"
ENV_EXAMPLE = Path(__file__).resolve().parent.parent / "templates" / "env.example"
SKILL = Path(__file__).resolve().parent.parent / "SKILL.md"


def test_audit_helper_does_not_put_bearer_token_in_curl_argv():
    source = SCRIPT.read_text()

    assert '["curl"' not in source
    assert "Authorization: Bearer {glm_key}" not in source
    assert "probe_zai_endpoint" in source
    assert "urllib.request.Request" in source


def test_troubleshooting_does_not_recommend_curl_with_bearer_token():
    text = TROUBLESHOOTING.read_text()

    assert "curl -s https://api.z.ai" not in text
    assert "Authorization: Bearer" not in text
    assert "audit-meeting-pipeline.py" in text


def test_audit_helper_summarizes_recent_logs_without_raw_content():
    source = SCRIPT.read_text()

    assert "summarize_log_line" in source
    assert "SECRET_ASSIGNMENT_RE" in source
    assert "line.strip()[:120]" not in source
    assert "log line (chars=" in source


def test_audit_helper_does_not_shell_out_to_dump_process_environment():
    source = SCRIPT.read_text()

    assert "process_has_env_value" in source
    assert '["cat", f"/proc/{pid}/environ"]' not in source
    assert "environ_result" not in source
    assert "capture_output=True, text=True\n    )\n    if \"LD_LIBRARY_PATH=" not in source


def test_troubleshooting_does_not_dump_full_proc_environment():
    text = TROUBLESHOOTING.read_text()

    assert "cat /proc/$(pgrep -f 'hermes_cli.main gateway')/environ" not in text
    assert "| tr '\\0' '\\n' | grep LD_LIBRARY" not in text
    assert "Should print only: LD_LIBRARY_PATH=" in text


def test_audit_helper_requires_private_env_before_key_probe():
    source = SCRIPT.read_text()

    assert "load_private_env_value" in source
    assert "stat.S_IRWXG | stat.S_IRWXO" in source
    assert "GLM_API_KEY file permissions are too broad" in source
    assert "ENV_FILE.read_text().splitlines()" not in source


def test_audit_helper_does_not_print_zai_error_body():
    source = SCRIPT.read_text()

    assert "returned error response (chars=" in source
    assert "returned unexpected response (chars=" in source
    assert "resp[:100]" not in source
    assert "resp[:80]" not in source


def test_env_docs_require_private_permissions():
    assert "chmod 600 .env" in ENV_EXAMPLE.read_text()
    assert "chmod 600 .env" in SKILL.read_text()
