from pathlib import Path


REFERENCE = Path(__file__).resolve().parent.parent / "references" / "agilize-bruno-opencollection.md"


def test_bruno_reference_uses_redaction_first_handoff():
    text = REFERENCE.read_text()

    assert "Ask the user for the DevTools curl" not in text
    assert "sanitized request description" in text
    assert "strip `Authorization`, `Cookie`, `key`" in text
    assert "Never** ask the user to paste a full browser cURL" in text
