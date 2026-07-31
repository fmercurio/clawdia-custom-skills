from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = RUNTIME_ROOT.parent
SCRIPT = PACKAGE / "scripts" / "brain_policy_check.py"


def run_policy(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)


def test_policy_cli_accepts_a_local_v02_policy() -> None:
    result = run_policy(PACKAGE / "runtime/policies/policy.example.json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["schema_version"] == "v0.2"
    assert payload["contract_version"] == "v0.2"


def test_policy_cli_fails_closed_for_invalid_local_json() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        invalid = Path(tmp) / "invalid.json"
        invalid.write_text("{}", encoding="utf-8")
        result = run_policy(invalid)
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "error" in payload
