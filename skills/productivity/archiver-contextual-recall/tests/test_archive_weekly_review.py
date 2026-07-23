from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "archive_weekly_review.py"
CRON_PATH = Path(__file__).resolve().parent.parent / "scripts" / "archive_weekly_review_cron.py"
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
ARCHIVE_ITEM_PATH = SCRIPTS_DIR / "archive_item.py"
ARCHIVER_RECALL_PATH = SCRIPTS_DIR / "archiver_recall.py"
BACKFILL_PATH = SCRIPTS_DIR / "backfill_link_contexts.py"
ARCHIVER_DB_PATH = SCRIPTS_DIR / "archiver_db.py"
SKILL_PATH = Path(__file__).resolve().parent.parent / "SKILL.md"

EXPECTED_SUPPORT_LINKS = {
    "scripts/archive_item.py",
    "scripts/archive_weekly_review.py",
    "scripts/archive_weekly_review_cron.py",
    "scripts/archiver_db.py",
    "scripts/archiver_extract_context.py",
    "scripts/archiver_recall.py",
    "scripts/backfill_link_contexts.py",
    "references/pdf-extraction-existing-links.md",
    "references/provenance.md",
    "references/reconcile-kanban-archive-tasks.md",
    "references/weekly-review-operations.md",
    "references/x-twitter-content-extraction.md",
    "templates/archive-weekly-review.md",
}


@pytest.fixture
def module_archive_review():
    spec = importlib.util.spec_from_file_location("archive_weekly_review", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def module_archiver_db():
    spec = importlib.util.spec_from_file_location("archiver_db_for_tests", ARCHIVER_DB_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def module_cron():
    spec = importlib.util.spec_from_file_location("archive_weekly_review_cron", CRON_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def freeze_time(monkeypatch, module, when: str = "2026-07-23T12:00:00+00:00"):
    fixed = datetime.fromisoformat(when)
    monkeypatch.setattr(module, "_utcnow", lambda: fixed)


def run_main(module, args, monkeypatch=None):
    if monkeypatch:
        module.run_subprocess = lambda *_, **__: {"returncode": 1, "stdout": "", "stderr": ""}
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = module.main(args)
    assert code == 0
    return buf.getvalue().strip()


def run_main_error(module, args):
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = module.main(args)
    return code, out.getvalue().strip(), err.getvalue().strip()


def run_script(path: Path, args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    merged = os.environ.copy()
    if env:
        merged.update({key: str(value) for key, value in env.items()})
    return subprocess.run([sys.executable, str(path), *args], capture_output=True, text=True, env=merged)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def support_inventory_targets() -> set[str]:
    text = SKILL_PATH.read_text(encoding="utf-8")
    section = re.search(
        r"### Support files / bundle inventory(.*?)(?:\n### |\n## |\Z)",
        text,
        re.S,
    )
    assert section, "support files / bundle inventory section not found"
    return {
        match.group(1)
        for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", section.group(1))
    }


def write_notes(archive_root: Path, notes, *, vault_root: Path | None = None):
    vault = vault_root if vault_root is not None else archive_root / "archive-vault"
    vault.mkdir(parents=True, exist_ok=True)
    for note in notes:
        full = vault / note
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text("note", encoding="utf-8")


def create_db(
    root: Path,
    with_title: bool = True,
    with_fk: bool = False,
    *,
    db_path: Path | None = None,
):
    db = db_path if db_path is not None else root / "archive-vault" / "90-meta" / "archiver.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db)
    cur = conn.cursor()

    item_columns = ["id INTEGER PRIMARY KEY", "path TEXT"]
    if with_title:
        item_columns.insert(1, "title TEXT")
    item_columns.extend(["status TEXT", "created_at TEXT"])

    link_columns = [
        "id INTEGER PRIMARY KEY",
        "item_id INTEGER NOT NULL",
        "url TEXT",
        "created_at TEXT",
    ]
    if with_fk:
        link_columns[1] = "item_id INTEGER NOT NULL REFERENCES items(id)"

    context_columns = [
        "id INTEGER PRIMARY KEY",
        "link_id INTEGER NOT NULL",
        "context_status TEXT",
        "error TEXT",
    ]
    if with_fk:
        context_columns[1] = "link_id INTEGER NOT NULL REFERENCES links(id)"

    cur.execute(f"CREATE TABLE items({', '.join(item_columns)})")
    cur.execute(f"CREATE TABLE links({', '.join(link_columns)})")
    cur.execute(f"CREATE TABLE link_contexts({', '.join(context_columns)})")
    conn.commit()
    return conn


def test_healthy_review_writes_expected_artifacts(module_archive_review, tmp_path, monkeypatch):
    freeze_time(monkeypatch, module_archive_review)
    home = tmp_path / "archiver"
    conn = create_db(home)
    conn.execute(
        "INSERT INTO items(id, path, title, status, created_at) VALUES(1, ?, 'A', 'done', ?)"
        ,
        ("notes/a.md", "2026-07-23T08:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO links(id, item_id, url, created_at) VALUES(1, 1, ?, ?)"
        ,
        ("https://example.com/a", "2026-07-23T08:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO link_contexts(id, link_id, context_status) VALUES(1, 1, 'extracted')"
    )
    conn.commit()
    conn.close()

    write_notes(home, ["notes/a.md"])

    output_dir = tmp_path / "out"
    stdout = run_main(module_archive_review, ["--archiver-home", str(home), "--output-dir", str(output_dir), "--json", "--days", "30"])
    payload = json.loads(stdout)

    assert payload["schema"] == "archive-weekly-review.v1"
    assert payload["status"] == "healthy"
    assert payload["metrics"]["items_total"] == 1

    expected = [
        f"{payload['date']}.json",
        f"{payload['date']}.md",
        "latest.json",
        "latest.md",
        "index.json",
    ]
    for filename in expected:
        assert (output_dir / filename).exists()

    date_json_bytes = (output_dir / f"{payload['date']}.json").read_bytes()
    latest_json_bytes = (output_dir / "latest.json").read_bytes()
    date_md_bytes = (output_dir / f"{payload['date']}.md").read_bytes()
    latest_md_bytes = (output_dir / "latest.md").read_bytes()
    assert latest_json_bytes == date_json_bytes
    assert latest_md_bytes == date_md_bytes

    on_disk = json.loads(date_json_bytes.decode("utf-8"))
    assert on_disk == payload
    assert on_disk["artifacts"]["index"]["path"] == "index.json"
    assert on_disk["artifacts"]["json"]["path"] == f"{payload['date']}.json"

    idx = read_json(output_dir / "index.json")
    assert payload["date"] in idx["reviews"]
    entry = idx["reviews"][payload["date"]]
    assert entry["json"]["size_bytes"] == len(date_json_bytes)
    assert entry["markdown"]["size_bytes"] == len(date_md_bytes)
    assert entry["json"]["sha256"] == hashlib.sha256(date_json_bytes).hexdigest()
    assert entry["markdown"]["sha256"] == hashlib.sha256(date_md_bytes).hexdigest()
    assert entry["generated_at"] == payload["generated_at"]

    index_bytes = (output_dir / "index.json").read_bytes()
    assert idx.get("latest_date") == payload["date"]
    assert idx["schema"] == "archive-weekly-review.v1-index"
    assert idx["generated_at"] == payload["generated_at"]
    assert entry["json"]["size_bytes"] == len(date_json_bytes)


def test_critical_findings_for_missing_note_orphan_and_missing_context(module_archive_review, tmp_path, monkeypatch):
    freeze_time(monkeypatch, module_archive_review)
    home = tmp_path / "archiver"
    conn = create_db(home)
    conn.execute("INSERT INTO items(id, path, title, status, created_at) VALUES(1, 'notes/missing.md', 'Missing', 'done', '2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO links(id, item_id, url) VALUES(1, 999, 'https://critical.example.com')")
    conn.execute("INSERT INTO links(id, item_id, url) VALUES(2, 1, 'https://critical2.example.com')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status) VALUES(1, 999, 'extracted')")
    conn.commit()
    conn.close()
    # Note intentionally omitted to trigger missing note path finding.

    output_dir = tmp_path / "out"
    stdout = run_main(module_archive_review, ["--archiver-home", str(home), "--output-dir", str(output_dir), "--json"])
    payload = json.loads(stdout)

    assert payload["status"] == "critical"
    findings = {finding["id"] for finding in payload["findings"]}
    assert "critical.orphan_links" in findings
    assert "critical.missing_contexts" in findings
    assert "critical.missing_note_paths" in findings
    assert "critical.foreign_key_violations" not in findings
    assert (output_dir / f"{payload['date']}.json").exists()


def test_attention_findings_include_inbox_backlog_and_dirty_git_and_duplicate_urls(module_archive_review, tmp_path, monkeypatch):
    freeze_time(monkeypatch, module_archive_review)
    home = tmp_path / "archiver"
    conn = create_db(home)
    conn.execute("INSERT INTO items(id, path, title, status, created_at) VALUES(1, 'notes/one.md', 'One', 'inbox', '2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO items(id, path, title, status, created_at) VALUES(2, 'notes/two.md', 'Two', 'done', '2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO links(id, item_id, url, created_at) VALUES(1,1,'https://dup.example.com/page?x=1#top','2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO links(id, item_id, url, created_at) VALUES(2,2,'https://user:pass@dup.example.com/page#section','2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status, error) VALUES(1,1,'failed','timeout')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status, error) VALUES(2,2,'body_only','')")
    conn.commit()

    # leave repository dirty to trigger attention.dirty_git
    subprocess.run(["git", "-C", str(home), "init"], capture_output=True, text=True, check=True)
    write_notes(home, ["notes/one.md", "notes/two.md"])
    (home / "dirty.txt").write_text("dirty", encoding="utf-8")

    output_dir = tmp_path / "out"
    stdout = run_main(module_archive_review, ["--archiver-home", str(home), "--output-dir", str(output_dir), "--json", "--days", "30"])
    payload = json.loads(stdout)

    assert payload["status"] == "attention"
    finding_ids = {f["id"] for f in payload["findings"]}
    assert "attention.failed_contexts" in finding_ids
    assert "attention.body_only_contexts" in finding_ids
    assert "attention.duplicate_urls" in finding_ids
    assert "attention.inbox_backlog" in finding_ids
    assert "attention.dirty_git" in finding_ids
    assert payload["metrics"]["inbox"]["recent"] >= 1
    assert payload["metrics"]["git"]["status"] == "dirty"


def test_url_normalization_and_no_extracted_text(module_archive_review, tmp_path, monkeypatch):
    freeze_time(monkeypatch, module_archive_review)
    home = tmp_path / "archiver"
    conn = create_db(home)
    conn.execute("INSERT INTO items(id, path, title, status) VALUES(1, 'notes/x.md', 'X', 'done')")
    conn.execute("INSERT INTO items(id, path, title, status) VALUES(2, 'notes/y.md', 'Y', 'done')")
    conn.execute("INSERT INTO items(id, path, title, status) VALUES(3, 'notes/z.md', 'Z', 'inbox')")
    conn.execute("INSERT INTO items(id, path, title, status) VALUES(4, 'notes/w.md', 'W', 'done')")
    conn.execute("INSERT INTO links(id, item_id, url) VALUES(1,1,'https://User:Pass@Example.COM/path?u=1#fragment')")
    conn.execute("INSERT INTO links(id, item_id, url) VALUES(2,2,'https://example.com/path')")
    conn.execute("INSERT INTO links(id, item_id, url) VALUES(3,3,'//schemeless.EXAMPLE.net/resource?x=1#frag')")
    conn.execute("INSERT INTO links(id, item_id, url) VALUES(4,3,'//schemeless.example.net/resource')")
    conn.execute("INSERT INTO links(id, item_id, url) VALUES(5,4,'HTTPS://[2001:DB8::1]:8443/a/B?token=1#frag')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status, error) VALUES(1,1,'failed','timeout')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status, error) VALUES(2,2,'body_only','')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status, error) VALUES(3,3,'extracted','')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status, error) VALUES(4,4,'extracted','')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status, error) VALUES(5,5,'extracted','')")
    conn.commit()
    conn.close()

    write_notes(home, ["notes/x.md", "notes/y.md", "notes/z.md", "notes/w.md"])

    output_dir = tmp_path / "out"
    stdout = run_main(module_archive_review, ["--archiver-home", str(home), "--output-dir", str(output_dir), "--json", "--days", "30"])
    payload = json.loads(stdout)
    payload_text = json.dumps(payload)
    markdown = (output_dir / f"{payload['date']}.md").read_text(encoding="utf-8")

    assert payload["status"] == "attention"
    dup = next(f for f in payload["findings"] if f["id"] == "attention.duplicate_urls")
    assert any(example["normalized_url"] == "https://example.com/path" for example in dup["examples"])
    assert any(example["normalized_url"] == "schemeless.example.net/resource" for example in dup["examples"])
    assert "?u=1" not in payload_text
    assert "#fragment" not in payload_text
    assert "User:Pass@example.com" not in payload_text
    assert "User:Pass@" not in payload_text
    assert "?x=1" not in payload_text
    assert "#frag" not in payload_text
    assert "User:pass@" not in markdown
    assert "token=1" not in payload_text
    assert "2001:DB8::1" not in payload_text
    assert module_archive_review.normalize_url("HTTPS://[2001:DB8::1]:8443/a/B?token=1#frag") == "https://[2001:db8::1]:8443/a/B"


def test_index_is_idempotent_for_same_day(module_archive_review, tmp_path, monkeypatch):
    freeze_time(monkeypatch, module_archive_review)
    home = tmp_path / "archiver"
    conn = create_db(home)
    conn.execute("INSERT INTO items(id, path, title, status, created_at) VALUES(1, 'notes/a.md', 'A', 'done', '2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO links(id, item_id, url, created_at) VALUES(1,1,'https://a.com','2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status) VALUES(1,1,'extracted')")
    conn.commit()
    conn.close()
    write_notes(home, ["notes/a.md"])

    output_dir = tmp_path / "out"
    out1 = run_main(module_archive_review, ["--archiver-home", str(home), "--output-dir", str(output_dir), "--json"])
    payload1 = json.loads(out1)
    conn = sqlite3.connect(home / "archive-vault" / "90-meta" / "archiver.sqlite3")
    conn.execute("INSERT INTO links(id, item_id, url) VALUES(2,1,'https://b.com')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status) VALUES(2,2,'extracted')")
    conn.commit()
    conn.close()

    out2 = run_main(module_archive_review, ["--archiver-home", str(home), "--output-dir", str(output_dir), "--json"])
    payload2 = json.loads(out2)

    idx = read_json(output_dir / "index.json")
    assert payload2["date"] == payload1["date"]
    assert idx["latest_date"] == payload1["date"]
    assert len(idx["reviews"]) == 1
    assert idx["reviews"][payload1["date"]]["generated_at"] == payload2["generated_at"]


def test_no_write_mode_creates_nothing(module_archive_review, tmp_path, monkeypatch):
    freeze_time(monkeypatch, module_archive_review)
    home = tmp_path / "archiver"
    conn = create_db(home)
    conn.execute("INSERT INTO items(id, path, title, status, created_at) VALUES(1, 'notes/a.md', 'A', 'done', '2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO links(id, item_id, url, created_at) VALUES(1,1,'https://a.com','2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status) VALUES(1,1,'extracted')")
    conn.commit()
    conn.close()
    write_notes(home, ["notes/a.md"])

    output_dir = tmp_path / "out"
    payload = json.loads(
        run_main(
            module_archive_review,
            ["--archiver-home", str(home), "--output-dir", str(output_dir), "--no-write", "--json"],
        )
    )
    assert payload["status"] in {"healthy", "attention", "critical"}
    assert payload["artifacts"]["json"]["path"].endswith(".json")
    assert payload["artifacts"]["index"]["path"] == "index.json"
    assert not output_dir.exists()


def test_kanban_contract_and_unavailable_info_finding(module_archive_review, tmp_path, monkeypatch):
    freeze_time(monkeypatch, module_archive_review)
    home = tmp_path / "archiver"
    conn = create_db(home)
    conn.execute("INSERT INTO items(id, path, title, status) VALUES(1, 'notes/a.md', 'A', 'done')")
    conn.execute("INSERT INTO links(id, item_id, url) VALUES(1,1,'https://a.com')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status) VALUES(1,1,'extracted')")
    conn.commit()
    conn.close()
    write_notes(home, ["notes/a.md"])

    def fake_run(cmd, capture_output=False, text=False, env=None, check=False, timeout=None):
        return SimpleNamespace(returncode=1, stdout="", stderr="no-hermes")

    monkeypatch.setattr(module_archive_review.subprocess, "run", fake_run)
    stdout = run_main(module_archive_review, ["--archiver-home", str(home), "--json", "--days", "30"])
    payload = json.loads(stdout)

    assert any(f["id"] == "info.kanban_unavailable" for f in payload["findings"])
    assert payload["metrics"]["kanban"]["status"] == "unavailable"
    assert payload["status"] == "healthy"


def test_run_subprocess_timeout_is_non_fatal(module_archive_review):
    def fake_run(*_, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["hermes"], timeout=20)

    with pytest.MonkeyPatch.context() as m:
        m.setattr(module_archive_review.subprocess, "run", fake_run)
        result = module_archive_review.run_subprocess(["hermes"])

    assert result["returncode"] == 124
    assert result["stderr"] == "command timed out"


def test_days_must_be_positive(module_archive_review, tmp_path):
    home = tmp_path / "archiver"
    conn = create_db(home)
    conn.execute("INSERT INTO items(id, path, status) VALUES(1, 'notes/a.md', 'done')")
    conn.execute("INSERT INTO links(id, item_id, url) VALUES(1,1,'https://a.com')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status) VALUES(1,1,'extracted')")
    conn.commit()
    conn.close()

    code, _, err = run_main_error(module_archive_review, ["--archiver-home", str(home), "--days", "0"])
    assert code == 2
    assert "--days must be greater than 0" in err


def test_optional_title_column_is_supported_without_embedded_title(module_archive_review, tmp_path, monkeypatch):
    freeze_time(monkeypatch, module_archive_review)
    home = tmp_path / "archiver"
    conn = create_db(home, with_title=False)
    conn.execute("INSERT INTO items(id, path, status) VALUES(1, 'notes/missing.md', 'done')")
    conn.execute("INSERT INTO links(id, item_id, url) VALUES(1,1,'https://a.com')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status) VALUES(1,1,'extracted')")
    conn.commit()
    conn.close()

    output_dir = tmp_path / "out"
    stdout = run_main(module_archive_review, ["--archiver-home", str(home), "--output-dir", str(output_dir), "--json"])
    payload = json.loads(stdout)

    missing = next(f for f in payload["findings"] if f["id"] == "critical.missing_note_paths")
    assert missing["examples"][0]["title"] == ""


def test_critical_findings_include_sqlite_integrity_and_fk_violations(module_archive_review, tmp_path, monkeypatch):
    freeze_time(monkeypatch, module_archive_review)
    home = tmp_path / "archiver"
    conn = create_db(home, with_fk=True)
    conn.execute("INSERT INTO items(id, path, title, status, created_at) VALUES(1, 'notes/a.md', 'A', 'done', '2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO links(id, item_id, url, created_at) VALUES(1, 1, 'https://a.com', '2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status) VALUES(1, 1, 'extracted')")
    conn.commit()
    conn.close()

    real_connect = module_archive_review.sqlite3.connect

    class ConnProxy:
        def __init__(self, inner):
            self._inner = inner
            self.row_factory = None

        @property
        def row_factory(self):
            return self._inner.row_factory

        @row_factory.setter
        def row_factory(self, value):
            self._inner.row_factory = value

        def execute(self, sql, params=None):
            query = str(sql).strip().upper()
            if query == "PRAGMA INTEGRITY_CHECK":
                return self._inner.execute("SELECT 'corrupt' AS result")
            if query == "PRAGMA FOREIGN_KEY_CHECK":
                return self._inner.execute(
                    'SELECT "links" AS "table", 1 AS "rowid", "items" AS "parent", 1 AS "fkid"'
                )
            if params is None:
                return self._inner.execute(sql)
            return self._inner.execute(sql, params)

        def close(self):
            self._inner.close()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()

    def fake_connect(*args, **kwargs):
        return ConnProxy(real_connect(*args, **kwargs))

    with pytest.MonkeyPatch.context() as m:
        m.setattr(module_archive_review.sqlite3, "connect", fake_connect)
        output_dir = tmp_path / "out"
        stdout = run_main(
            module_archive_review,
            ["--archiver-home", str(home), "--output-dir", str(output_dir), "--json"],
            monkeypatch=True,
        )

    payload = json.loads(stdout)
    assert payload["status"] == "critical"
    ids = {f["id"] for f in payload["findings"]}
    assert "critical.sqlite_integrity" in ids
    assert "critical.foreign_key_violations" in ids


def test_compute_kanban_uses_list_with_board_env(module_archive_review, monkeypatch):
    captured = {}

    def fake_run_subprocess(cmd, env_var=None):
        captured["cmd"] = cmd
        captured["env_var"] = env_var
        return {"returncode": 0, "stdout": "[]", "stderr": ""}

    monkeypatch.setattr(module_archive_review, "run_subprocess", fake_run_subprocess)
    health = module_archive_review.compute_kanban_health("archive")

    assert health["status"] == "available"
    assert captured["cmd"] == ["hermes", "kanban", "list", "--archived", "--json"]
    assert captured["env_var"] == {"HERMES_KANBAN_BOARD": "archive"}


def test_wrapper_uses_installed_script_path(module_cron, tmp_path, monkeypatch):
    home = tmp_path / "home"
    explicit_dir = tmp_path / "explicit-skill"
    flat_dir = home / ".hermes/skills/archiver-contextual-recall"
    legacy_dir = home / ".hermes/skills/productivity/archiver-contextual-recall"

    scripts_dir = explicit_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    fake_script = scripts_dir / "archive_weekly_review.py"
    fake_script.write_text("", encoding="utf-8")
    flat_script = flat_dir / "scripts" / "archive_weekly_review.py"
    flat_script.parent.mkdir(parents=True)
    flat_script.write_text("", encoding="utf-8")
    legacy_script = legacy_dir / "scripts" / "archive_weekly_review.py"
    legacy_script.parent.mkdir(parents=True)
    legacy_script.write_text("", encoding="utf-8")

    captured = {}

    def fake_run(cmd, check=False, text=False, timeout=None):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module_cron.Path, "home", lambda: home)
    monkeypatch.setenv("HERMES_HOME", str(home / ".hermes"))
    monkeypatch.setenv("ARCHIVER_SKILL_DIR", str(explicit_dir))
    monkeypatch.setattr(module_cron.subprocess, "run", fake_run)

    result = module_cron.main(["--days", "30", "--json"])

    assert result == 0
    assert captured["cmd"][0] == sys.executable
    assert captured["cmd"][1] == str(fake_script)
    assert captured["cmd"][2:] == ["--days", "30", "--json"]
    assert all(isinstance(x, str) for x in captured["cmd"])


def test_wrapper_prefers_hermes_home_flat_install(module_cron, tmp_path, monkeypatch):
    home = tmp_path / "home"
    flat_script = (home / ".hermes/skills/archiver-contextual-recall/scripts/archive_weekly_review.py")
    flat_script.parent.mkdir(parents=True)
    flat_script.write_text("", encoding="utf-8")

    legacy_script = (home / ".hermes/skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review.py")
    legacy_script.parent.mkdir(parents=True)
    legacy_script.write_text("", encoding="utf-8")

    captured = {}

    def fake_run(cmd, check=False, text=False, timeout=None):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module_cron.Path, "home", lambda: home)
    monkeypatch.setenv("HERMES_HOME", str(home / ".hermes"))
    monkeypatch.delenv("ARCHIVER_SKILL_DIR", raising=False)
    monkeypatch.setattr(module_cron.subprocess, "run", fake_run)

    result = module_cron.main(["--days", "7"])

    assert result == 0
    assert captured["cmd"][1] == str(flat_script)


def test_wrapper_prefers_legacy_category_path_as_fallback(module_cron, tmp_path, monkeypatch):
    home = tmp_path / "home"
    legacy_script = (home / ".hermes/skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review.py")
    legacy_script.parent.mkdir(parents=True)
    legacy_script.write_text("", encoding="utf-8")

    captured = {}

    def fake_run(cmd, check=False, text=False, timeout=None):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module_cron.Path, "home", lambda: home)
    monkeypatch.setenv("HERMES_HOME", str(home / ".hermes"))
    monkeypatch.delenv("ARCHIVER_SKILL_DIR", raising=False)
    monkeypatch.setattr(module_cron.subprocess, "run", fake_run)

    result = module_cron.main(["--days", "1"])

    assert result == 0
    assert captured["cmd"][1] == str(legacy_script)


def test_wrapper_reports_flat_path_when_no_script_found(module_cron, tmp_path, monkeypatch):
    home = tmp_path / "home"
    missing_dir = tmp_path / "missing"

    monkeypatch.setattr(module_cron.Path, "home", lambda: home)
    monkeypatch.setenv("HERMES_HOME", str(home / ".hermes"))
    monkeypatch.setenv("ARCHIVER_SKILL_DIR", str(missing_dir))
    code, _, err = run_main_error(module_cron, ["--days", "1"])

    expected = f"{home / '.hermes/skills/archiver-contextual-recall/scripts/archive_weekly_review.py'}"
    assert code == 2
    assert f"ERROR: main script not found at {expected}" in err

    monkeypatch.delenv("ARCHIVER_SKILL_DIR")
    code, _, err = run_main_error(module_cron, ["--days", "1"])
    assert code == 2
    assert f"ERROR: main script not found at {expected}" in err


def test_skill_bundle_inventory_includes_exact_support_targets():
    assert support_inventory_targets() == EXPECTED_SUPPORT_LINKS


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("HTTPS://[2001:DB8::1]:8443/a/B?token=1#frag", "https://[2001:db8::1]:8443/a/B"),
        ("https://User:Pass@Example.COM/path?u=1#fragment", "https://example.com/path"),
        ("//schemeless.EXAMPLE.net/resource?x=1#frag", "schemeless.example.net/resource"),
        ("user:pass@Example.COM/path?x=1#frag", "example.com/path"),
        ("foo:bar", "foo:bar"),
        ("example.com:notaport/path", "example.com:notaport/path"),
        ("https://[::1", "https://[::1"),
    ],
)
def test_normalize_url_contracts_and_malformed_inputs_do_not_raise(module_archive_review, value, expected):
    assert module_archive_review.normalize_url(value) == expected


def test_note_path_escape_detects_absolute_relative_and_symlink_paths(module_archive_review, tmp_path, monkeypatch):
    freeze_time(monkeypatch, module_archive_review)
    home = tmp_path / "archiver"
    vault = home / "archive-vault"
    conn = create_db(home)
    conn.execute("INSERT INTO items(id, path, title, status, created_at) VALUES(1, 'notes/ok.md', 'OK', 'done', '2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO links(id, item_id, url, created_at) VALUES(1,1,'https://a.com','2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status) VALUES(1,1,'body_only')")
    conn.execute("INSERT INTO items(id, path, title, status, created_at) VALUES(2, '/etc/passwd', 'ESC', 'done', '2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO links(id, item_id, url, created_at) VALUES(2,2,'https://b.com','2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status) VALUES(2,2,'body_only')")
    conn.execute("INSERT INTO items(id, path, title, status, created_at) VALUES(3, '../outside.md', 'REL', 'done', '2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO links(id, item_id, url, created_at) VALUES(3,3,'https://c.com','2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status) VALUES(3,3,'body_only')")
    conn.execute("INSERT INTO items(id, path, title, status, created_at) VALUES(4, 'notes/escape.md', 'LINK', 'done', '2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO links(id, item_id, url, created_at) VALUES(4,4,'https://d.com','2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status) VALUES(4,4,'body_only')")
    conn.execute("INSERT INTO items(id, path, title, status, created_at) VALUES(5, 'notes/missing.md', 'MISSING', 'done', '2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO links(id, item_id, url, created_at) VALUES(5,5,'https://e.com','2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status) VALUES(5,5,'body_only')")
    conn.commit()
    conn.close()

    escaped_target = tmp_path / "outside.md"
    escaped_target.write_text("x", encoding="utf-8")
    (vault / "notes").mkdir(parents=True, exist_ok=True)
    (vault / "notes").joinpath("escape.md").symlink_to(escaped_target)

    write_notes(home, ["notes/ok.md"], vault_root=vault)

    output_dir = tmp_path / "out"
    payload = json.loads(run_main(module_archive_review, ["--archiver-db", str(home / "archive-vault" / "90-meta" / "archiver.sqlite3"), "--archiver-vault", str(vault), "--output-dir", str(output_dir), "--json"]))
    findings = {finding["id"]: finding for finding in payload["findings"]}

    assert payload["status"] == "critical"
    assert "critical.note_path_escape" in findings
    assert findings["critical.note_path_escape"]["details"]["count"] == 3


def test_missing_required_db_schema_fails_closed_no_mutation_and_no_extracted_text_leak(module_archive_review, tmp_path, monkeypatch):
    freeze_time(monkeypatch, module_archive_review)
    base = tmp_path / "archiver"
    home = base / "missing-table"
    db_path = home / "archive-vault" / "90-meta" / "archiver.sqlite3"
    vault = home / "archive-vault"
    conn = create_db(home)
    conn.execute(
        "INSERT INTO items(id, path, status) VALUES(1, 'notes/a.md', 'done')"
    )
    conn.execute("INSERT INTO links(id, item_id, url) VALUES(1,1,'https://a.com')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status) VALUES(1,1,'extracted')")
    conn.commit()
    conn.close()
    write_notes(home, ["notes/a.md"], vault_root=vault)

    # Fail on missing required table (link_contexts removed).
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE link_contexts")
    conn.commit()
    conn.close()

    baseline = db_path.read_bytes()
    calls = []
    original_connect = module_archive_review.sqlite3.connect

    with pytest.MonkeyPatch.context() as m:
        m.setattr(module_archive_review.sqlite3, "connect", lambda *args, **kwargs: calls.append(args[0]) or original_connect(*args, **kwargs))
        code, _, err = run_main_error(module_archive_review, ["--json", "--archiver-home", str(home)])

    assert code == 2
    assert any("mode=ro" in str(call) for call in calls)
    assert db_path.read_bytes() == baseline
    assert "Missing required DB table" in err

    # Missing-column fail-close on a fresh schema missing note path.
    home = base / "missing-column"
    db_path = home / "archive-vault" / "90-meta" / "archiver.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, title TEXT)")
    conn.execute("CREATE TABLE links(id INTEGER PRIMARY KEY, item_id INTEGER, url TEXT)")
    conn.execute("CREATE TABLE link_contexts(id INTEGER PRIMARY KEY, link_id INTEGER)")
    conn.execute("INSERT INTO items(id, title) VALUES(1, 'no-path')")
    conn.execute("INSERT INTO links(id, item_id, url) VALUES(1,1,'https://a.com')")
    conn.execute("INSERT INTO link_contexts(id, link_id) VALUES(1,1)")
    conn.commit()
    conn.close()

    code, _, err = run_main_error(module_archive_review, ["--json", "--archiver-home", str(home), "--archiver-db", str(db_path)])
    assert code == 2
    assert "Could not resolve note-path column in items table" in err

    # Confirm raw extracted text never appears in emitted payload.
    home = base / "no-leak"
    db_path = home / "archive-vault" / "90-meta" / "archiver.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, title TEXT, path TEXT, status TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE links(id INTEGER PRIMARY KEY, item_id INTEGER, url TEXT)")
    conn.execute(
        "CREATE TABLE link_contexts("
        "id INTEGER PRIMARY KEY, link_id INTEGER, context_status TEXT, extracted_text TEXT)"
    )
    conn.execute("INSERT INTO items(id, title, path, status, created_at) VALUES(1,'Safe','notes/a.md','done','2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO links(id, item_id, url) VALUES(1,1,'https://a.com')")
    conn.execute(
        "INSERT INTO link_contexts(id, link_id, context_status, extracted_text) "
        "VALUES(1,1,'extracted','SECRET_LEAK_SHOULD_NOT_APPEAR')"
    )
    conn.commit()
    conn.close()

    output_dir = tmp_path / "out-healthy"
    stdout = run_main(module_archive_review, ["--archiver-home", str(home), "--output-dir", str(output_dir), "--json", "--no-write"])
    payload = json.loads(stdout)
    rendered = json.dumps(payload)
    assert "SECRET_LEAK_SHOULD_NOT_APPEAR" not in rendered
    assert payload["schema"] == "archive-weekly-review.v1"
    assert "SECRET_LEAK_SHOULD_NOT_APPEAR" not in stdout


def test_index_contracts_for_malformed_payloads_and_recover_mode(module_archive_review, tmp_path, monkeypatch):
    freeze_time(monkeypatch, module_archive_review, "2026-07-23T12:00:00+00:00")
    home = tmp_path / "archiver"
    conn = create_db(home)
    conn.execute("INSERT INTO items(id, path, title, status, created_at) VALUES(1, 'notes/a.md', 'A', 'done', '2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO links(id, item_id, url, created_at) VALUES(1,1,'https://a.com','2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status) VALUES(1,1,'extracted')")
    conn.commit()
    conn.close()
    write_notes(home, ["notes/a.md"])

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    malformed = output_dir / "index.json"
    malformed_bytes = b"{bad json"
    malformed.write_bytes(malformed_bytes)

    code, _, err = run_main_error(module_archive_review, ["--archiver-home", str(home), "--output-dir", str(output_dir), "--json"])
    assert code == 2
    assert "-- json" not in err.lower()
    assert malformed.read_bytes() == malformed_bytes
    assert not (output_dir / "index.json.corrupt").exists()

    wrong = {
        "schema": "archive-weekly-review.v0",
        "generated_at": "2026-07-01T00:00:00+00:00",
        "latest_date": "2026-07-01",
        "reviews": {},
    }
    malformed.write_text(json.dumps(wrong, ensure_ascii=False), encoding="utf-8")
    wrong_bytes = malformed.read_bytes()
    code, _, err = run_main_error(module_archive_review, ["--archiver-home", str(home), "--output-dir", str(output_dir), "--json"])
    assert code == 2
    assert wrong_bytes == malformed.read_bytes()

    malformed.write_bytes(malformed_bytes)
    original = malformed_bytes
    payload = run_main(
        module_archive_review,
        [
            "--archiver-home",
            str(home),
            "--output-dir",
            str(output_dir),
            "--json",
            "--recover-index",
            "--days",
            "30",
        ],
    )
    payload = json.loads(payload)

    assert payload["scope"]["db_path"] == str(home / "archive-vault" / "90-meta" / "archiver.sqlite3")
    assert payload["status"] in {"healthy", "attention", "critical"}

    recover_backup = output_dir / "index.json.corrupt"
    assert recover_backup.exists()
    assert recover_backup.read_bytes() == original
    assert (recover_backup.stat().st_mode & 0o777) == 0o600
    assert malformed.exists()

    recovered = read_json(output_dir / "index.json")
    assert recovered["schema"] == module_archive_review.INDEX_SCHEMA_VERSION


def test_index_same_day_rerun_preserves_history_and_artifacts_permissions(module_archive_review, tmp_path, monkeypatch):
    freeze_time(monkeypatch, module_archive_review, "2026-07-23T12:00:00+00:00")
    home = tmp_path / "archiver"
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    conn = create_db(home)
    conn.execute("INSERT INTO items(id, path, title, status, created_at) VALUES(1, 'notes/a.md', 'A', 'done', '2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO links(id, item_id, url, created_at) VALUES(1,1,'https://a.com','2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status) VALUES(1,1,'extracted')")
    conn.commit()
    conn.close()
    write_notes(home, ["notes/a.md"])

    old_index = output_dir / "index.json"
    old_payload = {
        "schema": module_archive_review.INDEX_SCHEMA_VERSION,
        "generated_at": "2026-07-22T00:00:00+00:00",
        "latest_date": "2026-07-22",
        "reviews": {
            "2026-07-22": {
                "status": "healthy",
                "summary": "legacy",
                "json": {"path": "legacy.json", "size_bytes": 11, "sha256": "a" * 64},
                "markdown": {"path": "legacy.md", "size_bytes": 11, "sha256": "b" * 64},
                "generated_at": "2026-07-22T00:00:00+00:00",
            }
        },
    }
    old_index.write_text(json.dumps(old_payload, ensure_ascii=False), encoding="utf-8")

    first = json.loads(run_main(module_archive_review, ["--archiver-home", str(home), "--output-dir", str(output_dir), "--json"]))
    second = json.loads(
        run_main(module_archive_review, ["--archiver-home", str(home), "--output-dir", str(output_dir), "--json"])
    )

    assert first["date"] == second["date"] == "2026-07-23"
    recovered_index = read_json(output_dir / "index.json")
    assert recovered_index["latest_date"] == "2026-07-23"
    assert set(recovered_index["reviews"].keys()) == {"2026-07-22", "2026-07-23"}
    assert recovered_index["reviews"]["2026-07-23"]["generated_at"] == second["generated_at"]
    assert recovered_index["schema"] == module_archive_review.INDEX_SCHEMA_VERSION

    for name in [f"{first['date']}.json", f"{first['date']}.md", "latest.json", "latest.md", "index.json"]:
        assert (output_dir / name).exists()
        assert (output_dir / name).stat().st_mode & 0o777 == 0o600


def test_cron_wrapper_passes_args_and_propagates_exit_and_timeout(module_cron):
    captured = {}

    def fake_run(cmd, check=False, text=False, timeout=None):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return SimpleNamespace(returncode=7)

    with pytest.MonkeyPatch.context() as m:
        m.setattr(module_cron.subprocess, "run", fake_run)
        rc = module_cron.main(["--timeout", "31", "--days", "30", "--json"])

    assert rc == 7
    assert captured["timeout"] == 31
    assert captured["cmd"][2:] == ["--days", "30", "--json"]

    def fake_run_timeout(cmd, check, text, timeout):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    with pytest.MonkeyPatch.context() as m:
        m.setattr(module_cron.subprocess, "run", fake_run_timeout)
        rc = module_cron.main(["--timeout", "9", "--days", "1"])

    assert rc == 124


def test_configurable_home_vault_db_and_kanban_board_are_honored(module_archive_review, tmp_path, monkeypatch):
    freeze_time(monkeypatch, module_archive_review, "2026-07-23T12:00:00+00:00")
    home = tmp_path / "home"
    vault = home / "custom-vault"
    db = vault / "state.sqlite3"
    conn = create_db(home, db_path=db)
    conn.execute("INSERT INTO items(id, path, title, status, created_at) VALUES(1,'notes/a.md','A','done','2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO links(id, item_id, url, created_at) VALUES(1,1,'https://a.com','2026-07-23T08:00:00+00:00')")
    conn.execute("INSERT INTO link_contexts(id, link_id, context_status) VALUES(1,1,'extracted')")
    conn.commit()
    conn.close()
    write_notes(home, ["notes/a.md"], vault_root=vault)

    captured = {}

    def fake_run_subprocess(cmd, env_var=None):
        captured["env"] = env_var
        return {"returncode": 0, "stdout": "[]", "stderr": ""}

    with pytest.MonkeyPatch.context() as m:
        m.setattr(module_archive_review, "run_subprocess", fake_run_subprocess)
        m.setenv("ARCHIVER_HOME", str(home))
        m.setenv("ARCHIVER_VAULT", str(vault))
        m.setenv("ARCHIVER_DB", str(db))
        m.setenv("ARCHIVER_KANBAN_BOARD", "env-board")
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            rc = module_archive_review.main(["--no-write", "--json", "--days", "30"])
    payload = json.loads(out_buf.getvalue())

    assert rc == 0
    assert payload["scope"]["archiver_home"] == str(home)
    assert payload["scope"]["db_path"] == str(db)
    assert captured["env"] == {"HERMES_KANBAN_BOARD": "env-board"}

    with pytest.MonkeyPatch.context() as m:
        m.setattr(module_archive_review, "run_subprocess", fake_run_subprocess)
        m.setenv("ARCHIVER_HOME", str(home))
        m.setenv("ARCHIVER_VAULT", str(vault))
        m.setenv("ARCHIVER_DB", str(db))
        m.setenv("ARCHIVER_KANBAN_BOARD", "env-board")
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            module_archive_review.main(["--no-write", "--json", "--days", "30", "--kanban-board", "cli-board"])
    payload = json.loads(out_buf.getvalue())
    assert payload["scope"]["db_path"] == str(db)
    assert captured["env"] == {"HERMES_KANBAN_BOARD": "cli-board"}


def test_cli_archiver_vault_overrides_stale_archiver_db_env(tmp_path):
    home = tmp_path / "home"
    env_vault = home / "stale-vault"
    cli_vault = home / "cli-vault"
    stale_db = env_vault / "90-meta" / "archiver.sqlite3"
    cli_db = cli_vault / "90-meta" / "archiver.sqlite3"

    env_conn = create_db(home, db_path=stale_db)
    env_conn.execute(
        "INSERT INTO items(id, path, title, status, created_at) VALUES(1, 'notes/env.md', 'Env DB', 'done', '2026-01-01T08:00:00+00:00')"
    )
    env_conn.execute(
        "INSERT INTO links(id, item_id, url) VALUES(1, 1, 'https://env.example')"
    )
    env_conn.commit()
    env_conn.close()

    cli_conn = create_db(home, db_path=cli_db)
    cli_conn.execute(
        "INSERT INTO items(id, path, title, status, created_at) VALUES(1, 'notes/cli-a.md', 'CLI DB A', 'done', '2026-07-23T08:00:00+00:00')"
    )
    cli_conn.execute(
        "INSERT INTO items(id, path, title, status, created_at) VALUES(2, 'notes/cli-b.md', 'CLI DB B', 'done', '2026-07-23T09:00:00+00:00')"
    )
    cli_conn.execute("INSERT INTO links(id, item_id, url) VALUES(1, 1, 'https://cli-a.example')")
    cli_conn.execute("INSERT INTO links(id, item_id, url) VALUES(2, 2, 'https://cli-b.example')")
    cli_conn.commit()
    cli_conn.close()

    output = run_script(
        SCRIPT_PATH,
        [
            "--no-write",
            "--json",
            "--days",
            "30",
            "--archiver-vault",
            str(cli_vault),
        ],
        env={
            "ARCHIVER_HOME": str(home),
            "ARCHIVER_DB": str(stale_db),
            "ARCHIVER_VAULT": str(env_vault),
            "ARCHIVER_KANBAN_BOARD": "archive",
        },
    )
    assert output.returncode == 0
    payload = json.loads(output.stdout)
    assert payload["scope"]["db_path"] == str(cli_db)
    assert payload["metrics"]["items_total"] == 2


def test_cli_archiver_home_overrides_stale_path_env(tmp_path):
    env_home = tmp_path / "env-home"
    cli_home = tmp_path / "cli-home"
    stale_db = env_home / "archive-vault" / "90-meta" / "archiver.sqlite3"
    cli_db = cli_home / "archive-vault" / "90-meta" / "archiver.sqlite3"

    stale_conn = create_db(env_home, db_path=stale_db)
    stale_conn.execute(
        "INSERT INTO items(id, path, title, status, created_at) VALUES(1, 'notes/stale.md', 'Stale', 'done', '2026-01-01T08:00:00+00:00')"
    )
    stale_conn.commit()
    stale_conn.close()

    cli_conn = create_db(cli_home, db_path=cli_db)
    cli_conn.execute(
        "INSERT INTO items(id, path, title, status, created_at) VALUES(1, 'notes/a.md', 'A', 'done', '2026-07-23T08:00:00+00:00')"
    )
    cli_conn.execute(
        "INSERT INTO items(id, path, title, status, created_at) VALUES(2, 'notes/b.md', 'B', 'done', '2026-07-23T09:00:00+00:00')"
    )
    cli_conn.commit()
    cli_conn.close()

    output = run_script(
        SCRIPT_PATH,
        ["--no-write", "--json", "--days", "30", "--archiver-home", str(cli_home)],
        env={
            "ARCHIVER_HOME": str(env_home),
            "ARCHIVER_VAULT": str(env_home / "archive-vault"),
            "ARCHIVER_DB": str(stale_db),
            "ARCHIVER_KANBAN_BOARD": "archive",
        },
    )
    assert output.returncode == 0
    payload = json.loads(output.stdout)
    assert payload["scope"]["archiver_home"] == str(cli_home)
    assert payload["scope"]["db_path"] == str(cli_db)
    assert payload["metrics"]["items_total"] == 2


def test_archive_item_recall_and_backfill_use_temporary_archiver_home(tmp_path):
    home = tmp_path / "temp-home"
    env = {"ARCHIVER_HOME": str(home)}
    archive_payload = run_script(
        ARCHIVE_ITEM_PATH,
        [
            "--title",
            "Temporary integration note",
            "--source",
            "https://source.example.com",
            "--tags",
            "integration",
            "--body",
            "Temporary integration body",
            "--no-extract",
            "--json",
        ],
        env=env,
    )
    assert archive_payload.returncode == 0
    item = json.loads(archive_payload.stdout)
    assert item["path"].startswith(str(home / "archive-vault"))

    recall_payload = run_script(
        ARCHIVER_RECALL_PATH,
        ["--json", "--query", "Temporary integration note", "--limit", "5"],
        env=env,
    )
    assert recall_payload.returncode == 0
    recall_data = json.loads(recall_payload.stdout)
    assert recall_data["count"] >= 1

    vault = home / "archive-vault"
    source_note = vault / "notes" / "source-only.md"
    source_note.parent.mkdir(parents=True, exist_ok=True)
    source_note.write_text(
        "---\n"
        "title: Source-only note\n"
        "source: https://source.only.example\n"
        "status: done\n"
        "created: 2026-07-23T08:00:00+00:00\n"
        "tags: []\n"
        "---\n",
        encoding="utf-8",
    )

    backfill_payload = run_script(BACKFILL_PATH, ["--json"], env=env)
    assert backfill_payload.returncode == 0
    backfill_result = json.loads(backfill_payload.stdout)
    assert backfill_result["added_items"] >= 1
    assert backfill_result["added_links"] >= 1


def test_archiver_db_legacy_link_contexts_migration_is_idempotent_and_upserts_without_duplicates(module_archiver_db, tmp_path):
    db = tmp_path / "legacy.sqlite3"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, path TEXT)")
    con.execute("CREATE TABLE links (id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, url TEXT NOT NULL)")
    con.execute("CREATE TABLE link_contexts (id INTEGER PRIMARY KEY, link_id INTEGER, extracted_text TEXT)")
    con.execute("INSERT INTO items(id, path) VALUES(1, 'notes/a.md')")
    con.execute("INSERT INTO links(id, item_id, url) VALUES(1, 1, 'https://legacy.example.com/path?a=1#frag')")
    con.execute("INSERT INTO link_contexts(id, link_id, extracted_text) VALUES(1, 1, 'legacy')")
    con.commit()

    module_archiver_db.ensure_schema(con)

    cols = {row[1] for row in con.execute("PRAGMA table_info(link_contexts)").fetchall()}
    assert {"url", "title", "description", "extracted_text", "summary", "keywords", "context_status", "extractor", "error", "created_at", "updated_at"}.issubset(cols)
    url, status, extracted = con.execute("SELECT url, context_status, extracted_text FROM link_contexts WHERE id=1").fetchone()
    assert url == "https://legacy.example.com/path?a=1#frag"
    assert status == "pending"
    assert extracted == "legacy"

    module_archiver_db.ensure_schema(con)
    module_archiver_db.upsert_link_context(con, 1, url, context_status="extracted", summary="first")
    module_archiver_db.upsert_link_context(con, 1, url, context_status="failed", summary="second")
    rows = con.execute("SELECT COUNT(*) FROM link_contexts WHERE link_id=1").fetchone()[0]
    latest = con.execute("SELECT context_status, summary FROM link_contexts WHERE link_id=1").fetchone()
    assert rows == 1
    assert latest == ("failed", "second")
    con.close()


def test_archiver_recall_list_and_query_degrade_safely_on_minimal_and_legacy_schemas(tmp_path):
    home = tmp_path / "archiver"
    db = home / "archive-vault" / "90-meta" / "archiver.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(db)
    con.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, path TEXT)")
    con.execute("CREATE TABLE links(id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, url TEXT NOT NULL)")
    con.execute("INSERT INTO items(id, path) VALUES(1, 'notes/legacy.md')")
    con.execute("INSERT INTO links(id, item_id, url) VALUES(1, 1, 'https://legacy.example.com/path')")
    con.commit()
    con.close()

    env = {"ARCHIVER_HOME": str(home), "ARCHIVER_DB": str(db), "ARCHIVER_VAULT": str(home / "archive-vault")}

    list_result = run_script(ARCHIVER_RECALL_PATH, ["--json", "--limit", "5"], env=env)
    assert list_result.returncode == 0
    payload = json.loads(list_result.stdout)
    assert payload["count"] == 1
    assert payload["results"][0]["title"] == "legacy.md"

    before = db.read_bytes()
    query_result = run_script(ARCHIVER_RECALL_PATH, ["--json", "--limit", "5", "--query", "legacy"], env=env)
    assert query_result.returncode == 0
    assert json.loads(query_result.stdout)["count"] >= 1
    assert db.read_bytes() == before

    con = sqlite3.connect(db)
    con.execute("CREATE TABLE link_contexts(id INTEGER PRIMARY KEY, link_id INTEGER)")
    con.commit()
    con.close()

    before_legacy = db.read_bytes()
    legacy_query = run_script(ARCHIVER_RECALL_PATH, ["--json", "--limit", "5", "--query", "legacy"], env=env)
    assert legacy_query.returncode == 0
    assert json.loads(legacy_query.stdout)["count"] >= 1
    assert db.read_bytes() == before_legacy


def test_archiver_recall_limits_across_sources_and_ranks_newest_markdown_on_full_db_limit(tmp_path):
    home = tmp_path / "archiver"
    db = home / "archive-vault" / "90-meta" / "archiver.sqlite3"
    conn = create_db(home, db_path=db)
    conn.execute(
        "INSERT INTO items(id, path, title, status, created_at) VALUES(1, 'notes/old.md', 'same query older', 'done', '2026-01-01T08:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO links(id, item_id, url, created_at) VALUES(1, 1, 'https://old.example', '2026-01-01T08:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    vault = home / "archive-vault" / "notes"
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "newer.md").write_bytes(
        (
            "---\n"
            "title: same query newer\n"
            "source: https://new.example\n"
            "status: done\n"
            "created: 2026-07-23T08:00:00+00:00\n"
            "tags: []\n"
            "---\n"
            "same query\n"
        ).encode("utf-8")
    )

    payload = run_script(
        ARCHIVER_RECALL_PATH,
        ["--json", "--query", "same query", "--limit", "1"],
        env={"ARCHIVER_HOME": str(home)},
    )
    assert payload.returncode == 0
    data = json.loads(payload.stdout)
    assert data["count"] == 1
    assert data["results"][0]["path"] == "notes/newer.md"
    assert data["results"][0]["path_type"] == "markdown"


def test_archiver_recall_invalid_utf8_markdown_does_not_abort(tmp_path):
    home = tmp_path / "archiver"
    db = create_db(home)
    db.close()

    vault = home / "archive-vault" / "notes"
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "bad-utf8.md").write_bytes(
        (
            "---\n"
            "title: valid note title\n"
            "source: https://note.example\n"
            "status: done\n"
            "created: 2026-07-23T08:00:00+00:00\n"
            "tags: []\n"
            "---\n"
            "needle token\n"
        ).encode("utf-8")
        + b"\xff\xfe"
    )

    payload = run_script(
        ARCHIVER_RECALL_PATH,
        ["--json", "--query", "needle", "--limit", "5"],
        env={"ARCHIVER_HOME": str(home)},
    )
    assert payload.returncode == 0
    data = json.loads(payload.stdout)
    assert data["count"] >= 1
    assert data["results"][0]["path"] == "notes/bad-utf8.md"


def test_backfill_dry_run_and_apply_cover_source_only_url_and_extract_existing_stubbed(tmp_path):
    home = tmp_path / "archiver"
    vault = home / "archive-vault"
    db = vault / "90-meta" / "archiver.sqlite3"
    env = {"ARCHIVER_HOME": str(home)}

    # dry-run should not create a missing DB.
    (vault / "notes").mkdir(parents=True, exist_ok=True)
    note = vault / "notes" / "source-only.md"
    note.write_text(
        "---\n"
        "title: Source only\n"
        "source: https://backfill-source-only.example/path\n"
        "status: done\n"
        "created: 2026-07-23T08:00:00+00:00\n"
        "tags: []\n"
        "---\n"
        "no links in body\n",
        encoding="utf-8",
    )
    dry_payload = run_script(BACKFILL_PATH, ["--dry-run", "--json"], env=env)
    assert dry_payload.returncode == 0
    dry_result = json.loads(dry_payload.stdout)
    assert dry_result["added_items"] == 1
    assert dry_result["added_links"] == 1
    assert dry_result["added_contexts"] == 1
    assert not db.exists()

    # apply should create the DB from the source-only note.
    apply_payload = run_script(BACKFILL_PATH, ["--json"], env=env)
    assert apply_payload.returncode == 0
    apply_result = json.loads(apply_payload.stdout)
    assert apply_result["added_items"] >= 1
    assert apply_result["added_links"] >= 1
    assert apply_result["added_contexts"] >= 1

    # dry-run against existing DB should not mutate bytes.
    before = db.read_bytes()
    dry_existing = run_script(BACKFILL_PATH, ["--dry-run", "--json"], env=env)
    assert dry_existing.returncode == 0
    assert db.read_bytes() == before

    con = sqlite3.connect(db)
    row = con.execute("SELECT url FROM links ORDER BY id LIMIT 1").fetchone()
    assert row and row[0] == "https://backfill-source-only.example/path"
    total_contexts = con.execute("SELECT COUNT(*) FROM link_contexts").fetchone()[0]
    assert total_contexts >= 1
    before_status = con.execute(
        "SELECT context_status, extractor, extracted_text FROM link_contexts WHERE link_id = 1"
    ).fetchone()

    # stubbed extraction with --extract-existing.
    stub_dir = tmp_path / "stub_extract"
    stub_dir.mkdir()
    sitecustomize = stub_dir / "sitecustomize.py"
    sitecustomize.write_text(
        "import sys\n"
        "from types import SimpleNamespace\n"
        "\n"
        "def extract_url_context(url, timeout=None):\n"
        "    return {\n"
        "        'extractor': 'stub-extractor',\n"
        "        'title': 'Extracted Stub Title',\n"
        "        'description': 'Extracted Stub Description',\n"
        "        'summary': 'Extracted Stub Summary',\n"
        "        'extracted_text': 'extracted text body',\n"
        "        'keywords': ['alpha', 'beta'],\n"
        "        'context_status': 'extracted',\n"
        "    }\n"
        "\n"
        "module = SimpleNamespace(extract_url_context=extract_url_context)\n"
        "sys.modules['archiver_extract_context'] = module\n",
        encoding="utf-8",
    )
    stub_module = stub_dir / "archiver_extract_context.py"
    stub_module.write_text(
        "def extract_url_context(url, timeout=None):\n"
        "    return {\n"
        "        'extractor': 'stub-extractor',\n"
        "        'title': 'Extracted Stub Title',\n"
        "        'description': 'Extracted Stub Description',\n"
        "        'summary': 'Extracted Stub Summary',\n"
        "        'extracted_text': 'extracted text body',\n"
        "        'keywords': ['alpha', 'beta'],\n"
        "        'context_status': 'extracted',\n"
        "    }\n",
        encoding="utf-8",
    )
    seed_py_path = os.pathsep.join([str(stub_dir), str(SCRIPTS_DIR)])
    ext_env = {"ARCHIVER_HOME": str(home), "PYTHONPATH": seed_py_path}

    extract_result = run_script(
        BACKFILL_PATH,
        ["--extract-existing", "--json", "--force"],
        env=ext_env,
    )
    assert extract_result.returncode == 0
    extract_payload = json.loads(extract_result.stdout)
    assert extract_payload["extract_candidates"] >= 1

    after = con.execute(
        "SELECT context_status, extractor, extracted_text FROM link_contexts WHERE link_id = 1"
    ).fetchone()
    assert after[0] == "extracted"
    assert after[1] == "stub-extractor"
    assert after[2] == "extracted text body"
    assert after != before_status
    con.close()
