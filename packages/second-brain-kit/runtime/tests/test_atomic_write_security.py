from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    script = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_security", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("module_name", "writer", "payload"),
    [
        ("activate_cron", "_write_atomic_json", {"cron_registered": True}),
        ("uninstall", "_write_atomic_bytes", b"restored"),
    ],
)
def test_atomic_writers_refuse_preplanted_temp_symlink(tmp_path: Path, module_name: str, writer: str, payload: object) -> None:
    module = _load(module_name)
    target = tmp_path / "inventory.json"
    outside = tmp_path / "outside"
    outside.write_text("sentinel", encoding="utf-8")
    target.with_name(f".{target.name}.tmp").symlink_to(outside)

    with pytest.raises(OSError):
        getattr(module, writer)(target, payload)

    assert outside.read_text(encoding="utf-8") == "sentinel"
    assert not target.exists()
