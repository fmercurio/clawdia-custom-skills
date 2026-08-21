from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "service_plan.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("service_plan_security", SCRIPT)
service_plan = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(service_plan)


def test_service_plan_rejects_template_syntax_in_instance_name() -> None:
    with pytest.raises(service_plan.ServiceError, match="portable service identifier"):
        service_plan._expected_config_file_fields(
            {
                "instance_name": "valid-{RUNTIME_ROOT}",
                "transport": "http",
                "listener": {"host": "127.0.0.1", "port": 3000, "path": "/mcp"},
                "policy_path": "policy.json",
                "projection_manifest_path": "projection.json",
            }
        )


def test_service_plan_does_not_follow_output_leaf_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside.service"
    outside.write_text("sentinel", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    (output / "second-brain-mcp.service").symlink_to(outside)

    with pytest.raises(service_plan.ServiceError, match="unsafe service artifact destination"):
        service_plan._apply(output, {"second-brain-mcp.service": "[Service]\n"})

    assert outside.read_text(encoding="utf-8") == "sentinel"
