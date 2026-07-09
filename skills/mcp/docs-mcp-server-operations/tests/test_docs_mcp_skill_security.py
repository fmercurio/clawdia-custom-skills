from __future__ import annotations

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
