from __future__ import annotations

import hashlib
import importlib.util
import io
import json
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


@pytest.fixture
def module_archive_review():
    spec = importlib.util.spec_from_file_location("archive_weekly_review", SCRIPT_PATH)
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


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_notes(archive_root: Path, notes):
    vault = archive_root / "archive-vault"
    vault.mkdir(parents=True, exist_ok=True)
    for note in notes:
        full = vault / note
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text("note", encoding="utf-8")


def create_db(root: Path, with_title: bool = True, with_fk: bool = False):
    db = root / "archive-vault" / "90-meta" / "archiver.sqlite3"
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
    health = module_archive_review.compute_kanban_health()

    assert health["status"] == "available"
    assert captured["cmd"] == ["hermes", "kanban", "list", "--archived", "--json"]
    assert captured["env_var"] == {"HERMES_KANBAN_BOARD": "archive"}


def test_wrapper_uses_installed_script_path(module_cron, tmp_path, monkeypatch):
    home = tmp_path / "home"
    scripts_dir = home / ".hermes/skills/productivity/archiver-contextual-recall/scripts"
    scripts_dir.mkdir(parents=True)
    fake_script = scripts_dir / "archive_weekly_review.py"
    fake_script.write_text("", encoding="utf-8")

    captured = {}

    def fake_run(cmd, check, text):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module_cron.Path, "home", lambda: home)
    monkeypatch.setattr(module_cron.subprocess, "run", fake_run)

    result = module_cron.main(["--days", "30", "--json"])

    assert result == 0
    assert captured["cmd"][0] == sys.executable
    assert captured["cmd"][1] == str(fake_script)
    assert captured["cmd"][2:] == ["--days", "30", "--json"]
    assert all(isinstance(x, str) for x in captured["cmd"])
