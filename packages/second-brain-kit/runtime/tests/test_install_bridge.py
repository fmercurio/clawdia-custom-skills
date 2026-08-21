from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


RUNTIME_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = RUNTIME_ROOT.parent
SCRIPTS = PACKAGE / "scripts"
PYTHON = sys.executable


def run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run([PYTHON, str(SCRIPTS / script), *args], capture_output=True, text=True)
    assert result.returncode == 0, f"{script} failed: {result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    return result


def bootstrap(home: Path, vault: Path, profile: str = "second-brain") -> None:
    run(
        "bootstrap.py",
        "--hermes-home", str(home), "--profile", profile,
        "--vault", str(vault), "--owner", "Example Owner", "--apply", "--json",
    )


def test_default_install_has_no_mcp_runtime_artifacts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        home, vault = root / "hermes", root / "vault"
        bootstrap(home, vault)
        report = json.loads(run("install.py", "--hermes-home", str(home), "--profile", "second-brain", "--apply", "--json").stdout)
        assert report["ok"] is True
        config = json.loads((home / "second-brain-kit/profiles/second-brain/config.yaml").read_text(encoding="utf-8"))
        assert config["mcp_readonly"]["enabled"] is False
        assert not (home / "second-brain-kit/instances").exists()
        assert not (home / "second-brain-kit/bin/mcp_smoke.py").exists()
        assert not (home / "second-brain-kit/bin/brain_policy_check.py").exists()


def test_enable_mcp_renders_inert_external_instance_and_uninstalls_cleanly() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        home, vault, profile = root / "hermes", root / "vault", "second-brain"
        bootstrap(home, vault, profile)
        before_vault = sorted(path.relative_to(vault).as_posix() for path in vault.rglob("*"))

        dry = json.loads(run("install.py", "--hermes-home", str(home), "--profile", profile, "--enable-mcp", "--json").stdout)
        assert dry["dry_run"] is True
        assert dry["instance"] == "second-brain-readonly"
        assert not (home / "second-brain-kit/instances").exists()

        applied = json.loads(run("install.py", "--hermes-home", str(home), "--profile", profile, "--enable-mcp", "--apply", "--json").stdout)
        assert applied["ok"] is True
        instance = home / "second-brain-kit/instances/second-brain-readonly"
        runtime_config, policy, access_token = instance / "runtime-config.json", instance / "policy.json", instance / "access-token"
        assert {item.name for item in instance.iterdir()} == {"runtime-config.json", "policy.json", "access-token"}
        assert stat.S_IMODE(instance.stat().st_mode) == 0o700
        for artifact in (runtime_config, policy, access_token):
            assert artifact.is_file()
            assert stat.S_IMODE(artifact.stat().st_mode) == 0o600
        assert len(access_token.read_text(encoding="utf-8").strip()) >= 32
        assert json.loads(runtime_config.read_text(encoding="utf-8"))["auth_token_path"] == "access-token"
        token_before_reinstall = access_token.read_text(encoding="utf-8")
        reinstalled = json.loads(run("install.py", "--hermes-home", str(home), "--profile", profile, "--enable-mcp", "--apply", "--json").stdout)
        assert reinstalled["ok"] is True
        assert access_token.read_text(encoding="utf-8") == token_before_reinstall
        assert sorted(path.relative_to(vault).as_posix() for path in vault.rglob("*")) == before_vault
        assert (home / "second-brain-kit/bin/mcp_smoke.py").is_file()
        assert (home / "second-brain-kit/bin/brain_policy_check.py").is_file()
        doctor = json.loads(run("doctor.py", "--hermes-home", str(home), "--profile", profile, "--check-optional", "--json").stdout)
        assert doctor["ok"] is True
        mcp_check = next(item for item in doctor["checks"] if item["name"] == "mcp_readonly")
        assert mcp_check["ok"] is True

        removed = json.loads(run("uninstall.py", "--hermes-home", str(home), "--profile", profile, "--apply").stdout)
        assert removed["ok"] is True
        assert not instance.exists()
        assert vault.is_dir()
        assert sorted(path.relative_to(vault).as_posix() for path in vault.rglob("*")) == before_vault
