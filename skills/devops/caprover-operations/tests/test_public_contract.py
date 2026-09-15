from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_skill_frontmatter_and_requested_public_files() -> None:
    expected = {
        "SKILL.md", "README.md",
        "references/cli-session-and-auth.md",
        "references/safe-app-definition-updates.md",
        "references/deployment-provenance-and-rollback.md",
        "references/app-lifecycle-and-retirement.md",
        "references/provenance.md",
        "templates/targets.example.json", "templates/operation-report.md",
        "scripts/probe.py", "scripts/readonly_guard.cjs",
        "tests/test_probe.py", "tests/test_public_contract.py",
    }
    assert expected.issubset({str(path.relative_to(ROOT)) for path in ROOT.rglob("*") if path.is_file()})
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(text.split("---", 2)[1])
    assert frontmatter["name"] == "caprover-operations"
    assert frontmatter["description"].startswith("Use when")
    assert frontmatter["license"] == "MIT"


def test_public_target_example_has_no_credentials() -> None:
    value = json.loads((ROOT / "templates" / "targets.example.json").read_text(encoding="utf-8"))
    serialized = json.dumps(value).lower()
    assert value["version"] == 1
    assert "example" in serialized
    assert not any(word in serialized for word in ("token", "password", "secret", "session"))


def test_probe_contract_is_neutral_and_read_only() -> None:
    source = (ROOT / "scripts" / "probe.py").read_text(encoding="utf-8")
    guard = (ROOT / "scripts" / "readonly_guard.cjs").read_text(encoding="utf-8")
    assert '"GET"' in source and '"/user/system/info"' in source
    assert '"POST"' not in source
    assert "CAPROVER_PASSWORD" not in source
    assert "followRedirect: false" in guard
    assert "strictSSL: true" in guard
