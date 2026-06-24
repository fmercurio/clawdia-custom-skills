import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "SKILL.md"
README = ROOT / "README.md"
TEMPLATE = ROOT / "templates" / "config.example.yaml"
PRIVACY = ROOT / "references" / "privacy-and-redaction.md"


def read_all() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in (SKILL, README, TEMPLATE, PRIVACY)
    )


def test_private_config_permissions_are_documented():
    text = read_all()

    assert "chmod 600" in text
    assert "0600" in text
    assert "0700" in text
    assert "outside the reusable skill package" in text
    assert "Do not commit real taxpayer IDs" in TEMPLATE.read_text(encoding="utf-8")


def test_draft_only_safety_stop_is_preserved():
    skill = SKILL.read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")

    assert "draft_only" in template
    assert "Never emit automatically" in skill
    assert "Stop. Do not click **Emitir NFS-e**." in skill
    assert "final issue/emit button" in skill


def test_evidence_and_shared_reports_are_redacted():
    text = read_all()

    assert "private run directory" in text
    assert "raw evidence" in text
    assert "redacted summaries" in text
    assert "counts, booleans, configured customer keys, draft states, and redacted labels" in text
    assert "Do not paste real CNPJ/CPF" in text


def test_package_examples_do_not_include_real_taxpayer_or_email_values():
    text = read_all()

    assert "<CUSTOMER_CNPJ_OR_CPF_DIGITS>" in text
    assert "<YOUR_COMPANY_CNPJ_OR_CPF_DIGITS>" in text
    assert not re.search(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b", text)
    assert not re.search(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", text)
    assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
