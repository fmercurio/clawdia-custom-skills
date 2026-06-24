import importlib.util
import os
import time
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "brain-health-check.py"
spec = importlib.util.spec_from_file_location("brain_health_check_under_test", SCRIPT)
brain_health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brain_health)


def write_active_project(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\npara: project\nstatus: active\nsensitivity: internal\n---\n# Project\n",
        encoding="utf-8",
    )


def make_old(path: Path, days: int = 30) -> None:
    old = time.time() - days * 24 * 60 * 60
    os.utime(path, (old, old))


def test_collect_md_files_skips_symlink_to_outside_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    inside = vault / "10_Projects" / "inside.md"
    write_active_project(inside)

    outside = tmp_path / "outside.md"
    outside.write_text("outside secret", encoding="utf-8")
    link = vault / "linked.md"
    link.symlink_to(outside)

    files = brain_health.collect_md_files(vault)

    assert inside.resolve() in files
    assert outside.resolve() not in files
    assert link not in files


def test_project_staleness_skips_symlinked_outside_notes(tmp_path):
    vault = tmp_path / "vault"
    projects = vault / "10_Projects"
    projects.mkdir(parents=True)

    outside = tmp_path / "outside.md"
    write_active_project(outside)
    make_old(outside)
    (projects / "linked.md").symlink_to(outside)

    assert brain_health.check_projects_stale(vault) == []


def test_project_staleness_still_reports_real_vault_notes(tmp_path):
    vault = tmp_path / "vault"
    note = vault / "10_Projects" / "real.md"
    write_active_project(note)
    make_old(note)

    issues = brain_health.check_projects_stale(vault)

    assert len(issues) == 1
    assert "`10_Projects/real.md`" in issues[0]


def test_runtime_contamination_skips_symlinked_outside_files(tmp_path):
    vault = tmp_path / "vault"
    hermes = vault / "_Hermes"
    hermes.mkdir(parents=True)

    outside_env = tmp_path / ".env"
    outside_env.write_text("TOKEN=secret", encoding="utf-8")
    (hermes / ".env").symlink_to(outside_env)

    assert brain_health.check_runtime_contamination(vault) == []


def test_runtime_contamination_still_reports_real_vault_files(tmp_path):
    vault = tmp_path / "vault"
    hermes = vault / "_Hermes"
    hermes.mkdir(parents=True)
    (hermes / "config.yaml").write_text("runtime: true\n", encoding="utf-8")

    issues = brain_health.check_runtime_contamination(vault)

    assert issues == ["- `_Hermes/config.yaml` — runtime file detected in vault"]
