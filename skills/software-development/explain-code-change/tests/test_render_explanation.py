import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "render_explanation.py"


def _base_spec():
    questions = [
        {"id": "q1", "prompt": "Question one?", "options": ["A", "B", "C", "D"], "correct_index": 0, "explanation": "Because A is true."},
        {"id": "q2", "prompt": "Question two?", "options": ["B", "C", "D", "A"], "correct_index": 2, "explanation": "Because D is true."},
        {"id": "q3", "prompt": "Question three?", "options": ["A", "B", "C", "D"], "correct_index": 1, "explanation": "Because B is true."},
        {"id": "q4", "prompt": "Question four?", "options": ["A", "B", "C", "D"], "correct_index": 3, "explanation": "Because D is true."},
        {"id": "q5", "prompt": "Question five?", "options": ["A", "B", "C", "D"], "correct_index": 0, "explanation": "Because A is true."},
    ]
    return {
        "metadata": {
            "title": "Explain change deterministic test",
            "artifact_slug": "deterministic-test",
            "change_id": "change-test-001",
            "base_ref": "main",
            "target_ref": "feature/test",
            "seed": 1337,
        },
        "sections": [
            {"id": "background", "title": "Background", "blocks": [
                {"type": "paragraph", "text": "Base behavior and target behavior differ."},
                {"type": "list", "ordered": False, "items": ["item one", "item two"]},
            ]},
            {"id": "intuition", "title": "Intuition", "blocks": [
                {"type": "paragraph", "text": "The change routes all callers to one resolver."},
            ]},
            {"id": "code", "title": "Code", "blocks": [
                {"type": "code", "language": "python", "code": "print('hello')"},
            ]},
            {"id": "quiz", "title": "Quiz", "questions": questions},
        ],
    }


def _run(spec, tmp_path, *, output=None, args=None, env=None):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    cmd = [sys.executable, str(SCRIPT), str(spec_path)]
    if output is not None:
        cmd += ["--output", str(output)]
    if args:
        cmd += args
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def test_successful_render(tmp_path):
    output = tmp_path / "artifact.html"
    result = _run(_base_spec(), tmp_path, output=output)
    assert result.returncode == 0
    text = output.read_text(encoding="utf-8")
    assert text.lower().startswith("<!doctype html>")
    assert all(f"id='{section}'" in text for section in ("background", "intuition", "code", "quiz"))
    assert "table-of-contents" in text


def test_escaping_of_body_and_quiz_text(tmp_path):
    spec = _base_spec()
    spec["sections"][0]["blocks"][0]["text"] = '<script>alert("x")</script>'
    question = spec["sections"][3]["questions"][0]
    question["prompt"] = '<b>Which "path"?</b>'
    question["options"][0] = "<script>unsafe()</script>"
    question["explanation"] = "A & B </script> remain text"
    output = tmp_path / "artifact.html"
    result = _run(spec, tmp_path, output=output)
    assert result.returncode == 0
    text = output.read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in text
    assert "&lt;b&gt;Which &quot;path&quot;?&lt;/b&gt;" in text
    assert "&amp;lt;b&amp;gt;" not in text
    assert "&lt;script&gt;unsafe()&lt;/script&gt;" in text
    assert "A & B <\\/script> remain text" in text


def test_exact_five_questions_validation(tmp_path):
    spec = _base_spec()
    spec["sections"][3]["questions"] = spec["sections"][3]["questions"][:4]
    result = _run(spec, tmp_path, output=tmp_path / "artifact.html")
    assert result.returncode != 0
    assert "exactly five" in result.stderr.lower()


def test_deterministic_and_balanced_quiz(tmp_path):
    spec = _base_spec()
    first, second = tmp_path / "a.html", tmp_path / "b.html"
    assert _run(spec, tmp_path, output=first, args=["--seed", "5555"]).returncode == 0
    assert _run(spec, tmp_path, output=second, args=["--seed", "5555"]).returncode == 0
    assert first.read_text() == second.read_text()
    match = re.search(r"const QUIZ_DATA = (\[[\s\S]*?\]);", first.read_text())
    assert match
    counts = Counter(item["correct_index"] for item in json.loads(match.group(1)))
    assert len(counts) == 4
    assert max(counts.values()) - min(counts.values()) <= 1


def test_strict_quiz_leakage_failure(tmp_path):
    spec = _base_spec()
    spec["sections"][3]["questions"][0]["options"] = [
        "Duplicated option", "Duplicated option", "Different one", "Different two"
    ]
    result = _run(spec, tmp_path, output=tmp_path / "artifact.html", args=["--strict"])
    assert result.returncode != 0
    assert "strict mode" in result.stderr.lower()


def test_no_external_assets_inline_handlers_and_pre_wrap(tmp_path):
    output = tmp_path / "artifact.html"
    result = _run(_base_spec(), tmp_path, output=output)
    assert result.returncode == 0
    text = output.read_text(encoding="utf-8")
    assert "<script src=" not in text
    assert "https://" not in text and "http://" not in text
    assert re.search(r"\son\w+\s*=", text, flags=re.IGNORECASE) is None
    assert "white-space: pre-wrap" in text


def test_output_mode_0600(tmp_path):
    output = tmp_path / "artifact.html"
    assert _run(_base_spec(), tmp_path, output=output).returncode == 0
    assert output.stat().st_mode & 0o777 == 0o600


def test_default_output_path_uses_home_override(tmp_path):
    home = tmp_path / "home"
    result = _run(_base_spec(), tmp_path, env={**os.environ, "HOME": str(home)})
    assert result.returncode == 0
    output = Path(result.stdout.strip().splitlines()[-1])
    assert output.parent == home / ".hermes" / "artifacts" / "explain-code-change"
    assert re.match(r"\d{4}-\d{2}-\d{2}-.*\.html", output.name)


def test_invalid_metadata_seed_warns_and_uses_default(tmp_path):
    spec = _base_spec()
    spec["metadata"]["seed"] = "not-an-integer"
    output = tmp_path / "artifact.html"
    result = _run(spec, tmp_path, output=output)
    assert result.returncode == 0
    assert "metadata.seed should be an integer" in result.stderr
    assert output.exists()


def test_invalid_json_reports_clean_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), str(bad)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "not valid JSON" in result.stderr
    assert "Traceback" not in result.stderr
