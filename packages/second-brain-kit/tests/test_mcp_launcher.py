from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent
SCRIPTS = PACKAGE / "scripts"
LAUNCHER = SCRIPTS / "run_mcp.sh"


def _executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_launcher_allows_only_check_or_serve_with_absolute_regular_config() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runtime = root / "runtime"
        runtime.mkdir()
        (runtime / "run_mcp.py").write_text("# fixture\n", encoding="utf-8")
        config = root / "runtime-config.json"
        config.write_text("{}\n", encoding="utf-8")
        capture = root / "argv.txt"
        fake_python = root / "python"
        _executable(fake_python, "#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > \"$CAPTURE_PATH\"\n")
        env = {**os.environ, "SECOND_BRAIN_KIT_RUNTIME": str(runtime), "SECOND_BRAIN_KIT_PYTHON": str(fake_python), "CAPTURE_PATH": str(capture)}

        checked = subprocess.run(["/bin/bash", str(LAUNCHER), "--check", "--config", str(config)], env=env, capture_output=True, text=True)
        assert checked.returncode == 0, checked.stderr
        assert capture.read_text(encoding="utf-8").splitlines() == [str((runtime / "run_mcp.py").resolve()), "--config", str(config), "--check"]

        served = subprocess.run(["/bin/bash", str(LAUNCHER), "--config", str(config)], env=env, capture_output=True, text=True)
        assert served.returncode == 0, served.stderr
        assert capture.read_text(encoding="utf-8").splitlines()[-1] == "--serve"

        linked = root / "config-link.json"
        linked.symlink_to(config)
        for argv in (("--serve", "--config", str(config)), ("--config", "relative.json"), ("--config", str(linked)), ("--config", str(config), "--host", "0.0.0.0")):
            rejected = subprocess.run(["/bin/bash", str(LAUNCHER), *argv], env=env, capture_output=True, text=True)
            assert rejected.returncode == 2


def test_service_plan_defaults_to_checked_shell_launcher() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        config = root / "runtime-config.json"
        config.write_text(json.dumps({"instance_name": "test-readonly", "runtime_schema_version": "v0.2", "mode": "readonly", "transport": "http", "listener": {"host": "127.0.0.1", "port": 6283, "path": "/mcp"}, "policy_path": "policy.json", "projection_manifest_path": "projection-manifest.json"}), encoding="utf-8")
        command = [sys.executable, str(SCRIPTS / "service_plan.py"), "--config", str(config), "--output-dir", str(root / "rendered"), "--runtime-root", str(SCRIPTS), "--service", "launchagent", "--json"]
        rendered = subprocess.run(command, capture_output=True, text=True)
        assert rendered.returncode == 0, rendered.stdout + rendered.stderr
        assert str(LAUNCHER) in json.loads(rendered.stdout)["rendered"]["second-brain-mcp-launchagent.plist"]
        rejected = subprocess.run([*command[:-1], "--launcher", "run_mcp.sh", "--json"], capture_output=True, text=True)
        assert rejected.returncode == 2
        assert "launcher must be an absolute path" in rejected.stdout

        non_executable = root / "not-executable.sh"
        non_executable.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        absolute_rejected = subprocess.run([*command[:-1], "--launcher", str(non_executable), "--json"], capture_output=True, text=True)
        assert absolute_rejected.returncode == 2
        assert "launcher must be executable" in absolute_rejected.stdout

        linked = root / "launcher-link.sh"
        linked.symlink_to(LAUNCHER)
        symlink_rejected = subprocess.run([*command[:-1], "--launcher", str(linked), "--json"], capture_output=True, text=True)
        assert symlink_rejected.returncode == 2
        assert "non-symlink" in symlink_rejected.stdout


def test_service_plan_derives_managed_bin_and_captures_prepared_interpreter() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        kit = root / "hermes" / "second-brain-kit"
        bin_root = kit / "bin"
        bin_root.mkdir(parents=True)
        launcher = bin_root / "run_mcp.sh"
        _executable(launcher, "#!/usr/bin/env bash\nexit 0\n")
        config = kit / "instances" / "test-readonly" / "runtime-config.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"instance_name": "test-readonly", "runtime_schema_version": "v0.2", "mode": "readonly", "transport": "http", "listener": {"host": "127.0.0.1", "port": 6283, "path": "/mcp"}, "policy_path": "policy.json", "projection_manifest_path": "projection-manifest.json"}), encoding="utf-8")
        rendered = subprocess.run([sys.executable, str(SCRIPTS / "service_plan.py"), "--config", str(config), "--output-dir", str(root / "rendered"), "--service", "launchagent", "--json"], capture_output=True, text=True)
        assert rendered.returncode == 0, rendered.stdout + rendered.stderr
        plan = json.loads(rendered.stdout)["rendered"]["second-brain-mcp-launchagent.plist"]
        assert str(launcher) in plan
        assert str(Path(sys.executable)) in plan

        bad_python = subprocess.run([sys.executable, str(SCRIPTS / "service_plan.py"), "--config", str(config), "--output-dir", str(root / "rendered"), "--service", "launchagent", "--runtime-python", "/usr/bin/env python3", "--json"], capture_output=True, text=True)
        assert bad_python.returncode == 2
        assert "absolute executable path" in bad_python.stdout
