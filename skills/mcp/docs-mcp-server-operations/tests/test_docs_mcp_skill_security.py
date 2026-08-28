from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BANNED_TERMS = [
    "Fel" + "ippe",
    "F" + "Mercurio",
    "Nuc" + "lia",
    "Nú" + "cleo",
    "C" + "lawdIA",
    "volt" + "datalab",
    "pack" + "em",
    "Soci" + "cam",
    "OPENAI_API_KEY=" + "lm-studio",
    "localhost:" + "1234",
]


def iter_public_text_files():
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".md", ".yaml", ".yml", ".json", ".py", ""}:
            yield path


def test_no_internal_names_or_local_embedding_defaults():
    combined = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in iter_public_text_files())
    for term in BANNED_TERMS:
        assert term not in combined


def test_scripts_compile():
    scripts = sorted((ROOT / "scripts").glob("*.py"))
    assert scripts
    subprocess.run([sys.executable, "-m", "py_compile", *map(str, scripts)], check=True)


def test_container_defaults_to_read_only_http_api():
    dockerfile = (ROOT / "templates" / "Dockerfile").read_text(encoding="utf-8")

    assert '"--read-only"' in dockerfile


def test_staleness_script_accepts_list_json(tmp_path):
    sample = [
        {
            "name": "vite",
            "status": "completed",
            "documentCount": 3,
            "uniqueUrlCount": 1,
            "sourceUrl": "https://www.npmjs.com/package/vite",
            "indexedAt": "2999-01-01T00:00:00Z",
        }
    ]
    list_file = tmp_path / "list.json"
    list_file.write_text(json.dumps(sample), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_docs_staleness.py"), "--list-json", str(list_file), "--skip-registry", "--output", "json"],
        text=True,
        capture_output=True,
        check=True,
    )
    rows = json.loads(result.stdout)
    assert rows[0]["library"] == "vite"
    assert "low-document-count" in rows[0]["quality_flags"]
    assert "single-source-url" in rows[0]["quality_flags"]
    assert "package-registry-source" in rows[0]["quality_flags"]


def test_staleness_script_rejects_unapproved_npx_package_before_execution():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_docs_staleness.py"),
            "--docs-mcp-package",
            "untrusted-package@1.0.0",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    assert "approved pinned package" in result.stderr


def test_staleness_npx_uses_an_isolated_canonical_registry(monkeypatch):
    script = ROOT / "scripts" / "check_docs_staleness.py"
    spec = importlib.util.spec_from_file_location("check_docs_staleness_test", script)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return type("Result", (), {"returncode": 0, "stdout": "[]"})()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    assert module.load_indexed_libraries("http://127.0.0.1:6280", module.DEFAULT_PACKAGE, None) == []

    assert captured["cwd"] != os.getcwd()
    assert captured["env"]["NPM_CONFIG_REGISTRY"] == "https://registry.npmjs.org/"
    assert captured["env"]["NPM_CONFIG_USERCONFIG"] == os.devnull
    assert "--registry" in captured["command"]


SCAN_SCRIPT = ROOT / "scripts" / "scan_repo_packages.py"
SCAN_SPEC = importlib.util.spec_from_file_location("scan_repo_packages_test", SCAN_SCRIPT)
if SCAN_SPEC is None or SCAN_SPEC.loader is None:
    raise RuntimeError("Could not load scan_repo_packages module")
SCAN_MODULE = importlib.util.module_from_spec(SCAN_SPEC)
SCAN_SPEC.loader.exec_module(SCAN_MODULE)


def parse_pyproject(text: str) -> list[str]:
    return SCAN_MODULE.parse_pyproject(text)["dependencies"]


def test_parse_pyproject_ignores_metadata_and_quoted_text():
    pyproject = """
[project]
name = "docs-server"
description = "This string contains requests and numpy"
readme = "README.md"
dependencies = ["requests >=2.0", "urllib3 == 2.0"]
[project.optional-dependencies]
test = ["pytest>=8"]
"""
    assert parse_pyproject(pyproject) == ["pytest", "requests", "urllib3"]


def test_parse_pyproject_collects_pep621_and_dependency_groups():
    pyproject = """
[project]
name = "docs-server"
description = "ignore me"
readme = "README.md"
dependencies = [
  "Django[auth] >=5.0; python_version >= '3.11'",
  "fastapi @ git+https://github.com/tiangolo/fastapi",
]
[dependency-groups]
lint = ["ruff == 0.1", "black"]
"""
    assert parse_pyproject(pyproject) == ["black", "django", "fastapi", "ruff"]


def test_parse_pyproject_collects_poetry_dependencies_and_groups():
    pyproject = """
[tool.poetry.dependencies]
python = "^3.12"
requests = "^2.30"
PyYAML = "^6.0"

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
ruff = "^0.5"
"""
    assert parse_pyproject(pyproject) == ["pytest", "pyyaml", "requests", "ruff"]


def test_parse_pyproject_invalid_toml_is_safe():
    assert parse_pyproject("[project\nname = 'broken'") == []


def test_dependency_reports_are_owner_only_and_reject_symlink_targets(tmp_path):
    outdir = tmp_path / "reports"
    written = SCAN_MODULE.write_private_report(outdir, "dependency-scan.json", "{}")

    assert written.read_text(encoding="utf-8") == "{}\n"
    assert stat.S_IMODE(outdir.stat().st_mode) == 0o700
    assert stat.S_IMODE(written.stat().st_mode) == 0o600

    target = tmp_path / "target.json"
    target.write_text("sentinel\n", encoding="utf-8")
    (outdir / "dependency-scan.md").symlink_to(target)
    try:
        SCAN_MODULE.write_private_report(outdir, "dependency-scan.md", "report")
    except ValueError as exc:
        assert "regular file" in str(exc)
    else:
        raise AssertionError("symlink report target must be rejected")
    assert target.read_text(encoding="utf-8") == "sentinel\n"


def test_dependency_reports_reject_symlinked_output_ancestor_without_writing(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)

    try:
        SCAN_MODULE.write_private_report(linked_parent / "reports", "dependency-scan.json", "{}")
    except ValueError as exc:
        assert "symlink" in str(exc)
    else:
        raise AssertionError("symlinked report ancestor must be rejected")

    assert sentinel.read_text(encoding="utf-8") == "keep\n"
    assert not (outside / "reports" / "dependency-scan.json").exists()
