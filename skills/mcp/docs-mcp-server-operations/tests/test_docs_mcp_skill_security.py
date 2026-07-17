from __future__ import annotations

import importlib.util
import json
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
