from __future__ import annotations

import re
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = RUNTIME_ROOT.parent

TARGETS = (
    PACKAGE / "README.md",
    PACKAGE / "docs/architecture.md",
    PACKAGE / "docs/decisions-requiring-human-confirmation.md",
    PACKAGE / "templates/config/config.example.yaml",
    PACKAGE / "scripts/brain_policy_check.py",
    PACKAGE / "scripts/mcp_smoke.py",
    PACKAGE / "runtime/policies/policy.example.json",
)
FORBIDDEN = ("fm" + "ercurio", "biz" + "zadd", "fernando" + "-import", "fel" + "ippe")
MACHINE_PATHS = (
    re.compile(r"/" + r"Users/", re.IGNORECASE),
    re.compile(r"/" + r"home/", re.IGNORECASE),
    re.compile(r"[A-Za-z]:\\\\"),
)


def test_g4_sources_and_docs_are_tenant_neutral() -> None:
    for path in TARGETS:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        assert all(marker not in lowered for marker in FORBIDDEN), path
        assert not any(pattern.search(text) for pattern in MACHINE_PATHS), path
