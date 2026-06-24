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
