from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "audit-meeting-pipeline.py"
TROUBLESHOOTING = Path(__file__).resolve().parent.parent / "references" / "troubleshooting.md"


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
