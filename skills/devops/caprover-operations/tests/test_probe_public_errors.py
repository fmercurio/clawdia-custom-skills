from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
PROBE = SKILL_ROOT / "scripts" / "probe.py"
SYNTHETIC_ORIGIN = "https://captain.example.invalid"


def clean_env() -> dict[str, str]:
    return {
        "CI": "1",
        "LANG": "C",
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def protected_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def local_validation_args(tmp_path: Path) -> list[str]:
    targets = tmp_path / "targets.json"
    registry = tmp_path / "registry.json"
    protected_json(
        targets,
        {"version": 1, "targets": [{"alias": "fixture", "origin": SYNTHETIC_ORIGIN}]},
    )
    protected_json(
        registry,
        {
            "CapMachines": [
                {
                    "name": "fixture",
                    "baseUrl": SYNTHETIC_ORIGIN,
                    "authToken": "synthetic-token",
                }
            ]
        },
    )
    return [
        "--targets",
        str(targets),
        "--target",
        "fixture",
        "--registry",
        str(registry),
        "--cli-root",
        str(tmp_path / "unused-cli"),
        "--node",
        sys.executable,
    ]


def invoke_probe(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PROBE), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=clean_env(),
        timeout=10,
        check=False,
    )


def invoke_with_injection(
    args: list[str], injection: str
) -> subprocess.CompletedProcess[str]:
    source = f"""
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("probe_under_test", {str(PROBE)!r})
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
{injection}
raise SystemExit(probe.main(sys.argv[1:]))
"""
    return subprocess.run(
        [sys.executable, "-c", source, *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=clean_env(),
        timeout=10,
        check=False,
    )


def assert_sanitized_internal_error(
    completed: subprocess.CompletedProcess[str], marker: str
) -> None:
    assert completed.stdout, completed.stderr
    result = json.loads(completed.stdout)
    assert completed.returncode != 0
    assert result["status"] == "inconclusive"
    assert result["reason"] == "internal_error"
    assert marker not in completed.stdout
    assert marker not in completed.stderr
    assert "Traceback" not in completed.stderr


def test_deep_json_failure_is_sanitized_at_public_boundary(tmp_path: Path) -> None:
    marker = "deep-json-private-marker"
    args = local_validation_args(tmp_path)
    private_path = tmp_path / marker
    deeply_nested = b"[" * 10_000 + b"0" + b"]" * 10_000
    assert len(deeply_nested) == 20_001
    private_path.write_bytes(deeply_nested)
    private_path.chmod(0o600)
    args[1] = str(private_path)

    completed = invoke_probe(*args)

    assert_sanitized_internal_error(completed, marker)


@pytest.mark.parametrize("resolution", ["cli_root", "node"])
def test_symlink_cycle_failure_is_sanitized_at_public_boundary(
    tmp_path: Path, resolution: str
) -> None:
    marker = f"private-{resolution}-cycle-marker"
    args = local_validation_args(tmp_path)
    cycle = tmp_path / marker
    cycle.symlink_to(cycle.name)
    injection = ""
    if resolution == "cli_root":
        args[7] = str(cycle)
    else:
        cli_root = tmp_path / "synthetic-cli"
        cli_root.mkdir()
        protected_json(
            cli_root / "package.json",
            {"name": "caprover", "version": "2.4.4"},
        )
        args[7] = str(cli_root)
        args[9] = str(cycle)
        injection = "probe.LAYOUT_HASHES = {}"

    completed = (
        invoke_with_injection(args, injection) if injection else invoke_probe(*args)
    )

    assert_sanitized_internal_error(completed, marker)


def test_unexpected_local_validation_failure_is_sanitized_at_public_boundary(
    tmp_path: Path,
) -> None:
    marker = "synthetic-sensitive-validation-marker"
    args = local_validation_args(tmp_path)
    completed = invoke_with_injection(
        args,
        f"""
def fail_validation(*_args):
    raise RuntimeError({marker!r})
probe.exact_origin = fail_validation
""",
    )

    assert_sanitized_internal_error(completed, marker)


def test_probe_error_reason_and_exit_code_remain_explicit(tmp_path: Path) -> None:
    args = local_validation_args(tmp_path)
    completed = invoke_with_injection(
        args,
        """
def fail_domain(*_args):
    raise probe.ProbeError("registry_schema_error", 7)
probe.preflight = fail_domain
""",
    )

    assert completed.returncode == 7
    assert json.loads(completed.stdout)["reason"] == "registry_schema_error"
    assert completed.stderr == ""


def test_keyboard_interrupt_remains_inconclusive_with_exit_130(tmp_path: Path) -> None:
    args = local_validation_args(tmp_path)
    completed = invoke_with_injection(
        args,
        """
def interrupt(*_args):
    raise KeyboardInterrupt
probe.preflight = interrupt
""",
    )

    assert completed.returncode == 130
    result = json.loads(completed.stdout)
    assert result["status"] == "inconclusive"
    assert result["reason"] == "interrupted"
    assert completed.stderr == ""


def test_system_exit_from_execution_boundary_still_propagates(tmp_path: Path) -> None:
    args = local_validation_args(tmp_path)
    completed = invoke_with_injection(
        args,
        """
def exit_directly(*_args):
    raise SystemExit(23)
probe.preflight = exit_directly
""",
    )

    assert completed.returncode == 23
    assert completed.stdout == ""
    assert completed.stderr == ""


def test_other_base_exception_still_propagates(tmp_path: Path) -> None:
    args = local_validation_args(tmp_path)
    completed = invoke_with_injection(
        args,
        """
class DeliberateBaseException(BaseException):
    pass
def stop(*_args):
    raise DeliberateBaseException
probe.preflight = stop
""",
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "DeliberateBaseException" in completed.stderr
