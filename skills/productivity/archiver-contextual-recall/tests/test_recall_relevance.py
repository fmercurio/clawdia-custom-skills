from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest


PACKAGE = Path(__file__).resolve().parents[1]
SCRIPTS = PACKAGE / "scripts"
SCRIPT = SCRIPTS / "archiver_recall.py"


@pytest.fixture
def recall_module():
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location("archiver_recall_relevance", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


def make_db(tmp_path: Path, *, fts: bool = False) -> tuple[Path, sqlite3.Connection]:
    db = tmp_path / "archive.sqlite3"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE items(
          id INTEGER PRIMARY KEY, title TEXT, source TEXT, path TEXT, tags TEXT,
          status TEXT, created_at TEXT, capabilities TEXT, use_cases TEXT,
          description TEXT, summary TEXT
        );
        CREATE TABLE links(
          id INTEGER PRIMARY KEY, item_id INTEGER, url TEXT, title TEXT, context TEXT
        );
        CREATE TABLE link_contexts(
          id INTEGER PRIMARY KEY, link_id INTEGER, url TEXT, title TEXT, description TEXT,
          summary TEXT, extracted_text TEXT, keywords TEXT, context_status TEXT,
          capture_quality TEXT, capture_coverage TEXT, capture_metadata TEXT,
          user_context TEXT, source_summary TEXT
        );
        """
    )
    if fts:
        con.execute(
            "CREATE VIRTUAL TABLE link_contexts_fts USING fts5("
            "url, title, description, summary, extracted_text, keywords, "
            "content='link_contexts', content_rowid='id')"
        )
    return db, con


def configure(recall_module, tmp_path: Path, db: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    recall_module.DB = db
    recall_module.VAULT = vault
    return vault


def add_row(con, *, item_id=1, title="item", path="notes/item.md", created="2026-01-01T00:00:00+00:00", tags="[]", capabilities="[]", use_cases="[]", description="", summary="", url="https://example.test", link_title="", context="", ctx_title="", ctx_description="", ctx_summary="", extracted="", keywords="[]", status="done", quality=None, coverage=None, user_context="", source_summary=""):
    con.execute(
        "INSERT INTO items(id,title,source,path,tags,status,created_at,capabilities,use_cases,description,summary) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (item_id, title, "", path, tags, status, created, capabilities, use_cases, description, summary),
    )
    con.execute("INSERT INTO links(id,item_id,url,title,context) VALUES(?,?,?,?,?)", (item_id, item_id, url, link_title, context))
    con.execute(
        "INSERT INTO link_contexts(id,link_id,url,title,description,summary,extracted_text,keywords,context_status,capture_quality,capture_coverage,capture_metadata,user_context,source_summary) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (item_id, item_id, url, ctx_title, ctx_description, ctx_summary, extracted, keywords, "extracted", quality, coverage, "{}", user_context, source_summary),
    )


def test_ctx_title_tags_keywords_and_optional_arrays_rank_with_evidence(recall_module, tmp_path):
    db, con = make_db(tmp_path)
    configure(recall_module, tmp_path, db)
    add_row(con, title="https://example.test/opaque", ctx_title="Guia de IA aplicada", tags='["produto"]', keywords='["busca", "relevância"]', capabilities='["semantic retrieval"]', use_cases='["rank search results"]', quality="usable", coverage="bounded_text")
    con.commit()
    con.close()

    by_title = recall_module.collect_db_results("ia aplicada", 5, None)
    assert by_title[0]["title"] == "Guia de IA aplicada"
    assert "ctx_title" in by_title[0]["match_fields"]
    assert by_title[0]["snippet"]
    assert by_title[0]["capture_quality"] == "usable"
    assert by_title[0]["capture_coverage"] == "bounded_text"

    by_tags = recall_module.collect_db_results("produto", 5, None)
    assert "tags" in by_tags[0]["match_fields"]
    by_keywords = recall_module.collect_db_results("relevancia", 5, None)
    assert "ctx_keywords" in by_keywords[0]["match_fields"]
    by_capability = recall_module.collect_db_results("semantic retrieval", 5, None)
    assert "capabilities" in by_capability[0]["match_fields"]


def test_exact_title_beats_newer_weak_body_and_merge_preserves_relevance(recall_module, tmp_path):
    db, con = make_db(tmp_path)
    vault = configure(recall_module, tmp_path, db)
    add_row(
        con,
        item_id=1,
        title="Firecracker microVM",
        path="notes/same.md",
        created="2026-01-01T00:00:00+00:00",
        quality="usable",
        coverage="bounded_text",
    )
    add_row(con, item_id=2, title="new generic", path="notes/generic.md", created="2026-12-01T00:00:00+00:00", extracted="a weak firecracker body mention")
    con.commit()
    con.close()
    (vault / "notes").mkdir()
    (vault / "notes" / "same.md").write_text("---\ntitle: Firecracker microVM\nsource: https://example.test\nstatus: done\ncreated: 2026-11-01T00:00:00+00:00\ntags: []\n---\nFirecracker microVM", encoding="utf-8")

    results = recall_module.collect_all("firecracker microvm", 5, None)
    assert results[0]["path"] == "notes/same.md"
    assert len([row for row in results if row["path"] == "notes/same.md"]) == 1
    assert results[0]["score"] > results[1]["score"]
    assert results[0]["capture_quality"] == "usable"
    assert results[0]["capture_coverage"] == "bounded_text"
    assert set(results[0]["representations"]) == {"sqlite", "markdown"}


def test_accents_short_ia_and_malformed_fts_query_are_safe(recall_module, tmp_path):
    db, con = make_db(tmp_path)
    configure(recall_module, tmp_path, db)
    add_row(con, ctx_description="Pesquisa de inteligência artificial para IA")
    con.commit()
    con.close()

    assert recall_module.collect_db_results("inteligencia artificial", 5, None)
    assert recall_module.collect_db_results("IA", 5, None)
    assert recall_module.collect_db_results('IA OR "* : (', 5, None)


def test_fts_match_is_bound_and_stale_or_missing_index_falls_back(recall_module, tmp_path, monkeypatch):
    db, con = make_db(tmp_path, fts=True)
    configure(recall_module, tmp_path, db)
    add_row(con, ctx_title="FTS assisted recall", extracted="fallback proof")
    con.execute("INSERT INTO link_contexts_fts(link_contexts_fts) VALUES('rebuild')")
    con.commit()
    con.close()

    traces = []
    original = sqlite3.connect
    def traced_connect(_path):
        connection = original(db)
        connection.set_trace_callback(traces.append)
        return connection
    monkeypatch.setattr(recall_module, "connect_readonly", traced_connect)
    found = recall_module.collect_db_results("assisted recall", 5, None)
    assert found and found[0]["search_method"] == "fts5+lexical"
    assert any("MATCH" in statement.upper() for statement in traces)
    assert not any(repr(statement).upper().startswith(("'CREATE", "'ALTER", "'DROP", "'REINDEX", "'INSERT", "'UPDATE", "'DELETE")) for statement in traces)

    stale = sqlite3.connect(db)
    stale.execute("DELETE FROM link_contexts_fts")
    stale.commit()
    stale.close()
    monkeypatch.setattr(recall_module, "connect_readonly", lambda _path: original(db))
    fallback = recall_module.collect_db_results("fallback proof", 5, None)
    assert fallback and fallback[0]["search_method"] == "fts5+lexical"


@pytest.mark.parametrize('quality,coverage', [('tested', 'full'), ('reviewed', 'complete')])
def test_invalid_capture_labels_do_not_claim_review_or_complete_coverage(recall_module, tmp_path, quality, coverage):
    db, con = make_db(tmp_path)
    configure(recall_module, tmp_path, db)
    add_row(con, title='Unverified reference', quality=quality, coverage=coverage)
    con.commit()
    con.close()
    result = recall_module.collect_db_results('unverified reference', 1, None)[0]
    assert result['capture_quality'] == 'unknown'
    assert result['capture_coverage'] == 'unknown'


def test_no_evidence_returns_no_result_and_empty_query_is_newest_first(recall_module, tmp_path):
    db, con = make_db(tmp_path)
    configure(recall_module, tmp_path, db)
    add_row(con, item_id=1, title="older", created="2026-01-01T00:00:00+00:00")
    add_row(con, item_id=2, title="newer", path="notes/newer.md", created="2026-02-01T00:00:00+00:00")
    con.commit(); con.close()

    assert recall_module.collect_db_results("absent evidence", 5, None) == []
    assert recall_module.collect_db_results("", 1, None)[0]["title"] == "newer"


def test_legacy_schema_status_limit_and_unknown_capture_values(recall_module, tmp_path):
    db = tmp_path / "legacy.sqlite3"
    con = sqlite3.connect(db)
    con.executescript("CREATE TABLE items(id INTEGER PRIMARY KEY, path TEXT, status TEXT, created_at TEXT, title TEXT); CREATE TABLE links(id INTEGER PRIMARY KEY, item_id INTEGER, url TEXT);")
    con.execute("INSERT INTO items VALUES(1,'notes/a.md','done','2026-02-01T00:00:00+00:00','Legacy needle')")
    con.execute("INSERT INTO links VALUES(1,1,'https://legacy.test')")
    con.commit(); con.close()
    configure(recall_module, tmp_path, db)

    result = recall_module.collect_db_results("needle", 1, "done")
    assert len(result) == 1
    assert result[0]["capture_quality"] == "unknown"
    assert result[0]["capture_coverage"] == "unknown"
    assert result[0]["context_status"] == "unknown"
    assert recall_module.collect_db_results("needle", 1, "inbox") == []


def test_markdown_is_read_once_and_returns_transparent_fields(recall_module, tmp_path, monkeypatch):
    db, con = make_db(tmp_path)
    con.close()
    vault = configure(recall_module, tmp_path, db)
    note = vault / "note.md"
    note.write_text("---\ntitle: Única leitura IA\nsource: https://note.test\nstatus: done\ncreated: 2026-01-01T00:00:00+00:00\ntags: [ai]\n---\nConteúdo", encoding="utf-8")
    calls = []
    actual = recall_module.read_vault_text
    def read_once(root, path):
        calls.append(path)
        return actual(root, path)
    monkeypatch.setattr(recall_module, "read_vault_text", read_once)

    result = recall_module.collect_note_results("IA", 5, None)
    assert len(calls) == 1
    assert "item_title" in result[0]["match_fields"]
    assert result[0]["search_method"] == "lexical"
    assert result[0]["context_status"] == "unknown"


@pytest.mark.parametrize("fts", [False, True])
def test_old_context_title_survives_more_than_250_newer_db_rows(recall_module, tmp_path, fts):
    db, con = make_db(tmp_path, fts=fts)
    configure(recall_module, tmp_path, db)
    add_row(
        con,
        item_id=1,
        title="opaque archive record",
        path="notes/old-context.md",
        created="2020-01-01T00:00:00+00:00",
        ctx_title="Oldest unique context title",
    )
    for item_id in range(2, 253):
        add_row(
            con,
            item_id=item_id,
            title=f"unrelated newer record {item_id}",
            path=f"notes/newer-{item_id}.md",
            created=f"2026-10-{(item_id % 28) + 1:02d}T00:00:00+00:00",
        )
    if fts:
        con.execute("INSERT INTO link_contexts_fts(link_contexts_fts) VALUES('rebuild')")
    con.commit()
    con.close()

    results = recall_module.collect_db_results("oldest unique context", 5, None)

    assert [result["path"] for result in results] == ["notes/old-context.md"]
    assert results[0]["search_method"] == ("fts5+lexical" if fts else "lexical")


def test_markdown_scan_keeps_late_strongest_match_after_200_candidates(recall_module, tmp_path):
    db, con = make_db(tmp_path)
    con.close()
    vault = configure(recall_module, tmp_path, db)
    notes = vault / "notes"
    notes.mkdir()
    for index in range(250):
        (notes / f"{index:03d}-weak.md").write_text(
            "---\n"
            f"title: weak {index}\n"
            "status: done\n"
            "created: 2026-01-01T00:00:00+00:00\n"
            "tags: []\n"
            "---\n"
            "firecracker\n",
            encoding="utf-8",
        )
    (notes / "zzz-strong.md").write_text(
        "---\n"
        "title: Firecracker microVM\n"
        "status: done\n"
        "created: 2026-12-01T00:00:00+00:00\n"
        "tags: []\n"
        "---\n"
        "complete title match\n",
        encoding="utf-8",
    )

    results = recall_module.collect_note_results("firecracker microvm", 1, None)

    assert results[0]["path"] == "notes/zzz-strong.md"


def test_snippet_honors_the_total_character_bound(recall_module):
    text = "prefix " * 40 + "needle" + " suffix" * 40
    snippet = recall_module._snippet(text, ["needle"], "needle")
    assert "needle" in snippet
    assert len(snippet) <= recall_module.MAX_SNIPPET_CHARS


def test_markdown_frontmatter_json_metadata_is_ranked_without_a_second_read(recall_module, tmp_path, monkeypatch):
    db, con = make_db(tmp_path)
    con.close()
    vault = configure(recall_module, tmp_path, db)
    note = vault / "metadata.md"
    note.write_text(
        "---\n"
        "title: Metadata note\n"
        "status: done\n"
        "created: 2026-01-01T00:00:00+00:00\n"
        "tags: [\"plain tag\"]\n"
        "capabilities: [\"semantic retrieval\", \"escaped \\\"quote\\\"\"]\n"
        "use_cases: [\"rank search results\"]\n"
        "---\n"
        "body without the capability phrase\n",
        encoding="utf-8",
    )
    assert recall_module.parse_frontmatter(note, note.read_text(encoding="utf-8"))["capabilities"] == [
        "semantic retrieval",
        'escaped "quote"',
    ]
    reads = []
    actual = recall_module.read_vault_text
    monkeypatch.setattr(recall_module, "read_vault_text", lambda root, path: reads.append(path) or actual(root, path))

    capability = recall_module.collect_note_results("semantic retrieval", 5, None)
    use_case = recall_module.collect_note_results("rank search", 5, None)

    assert "capabilities" in capability[0]["match_fields"]
    assert capability[0]["why"] == "correspondência em capacidades"
    assert "use_cases" in use_case[0]["match_fields"]
    assert use_case[0]["why"] == "correspondência em casos de uso"
    assert reads == [note, note]


def test_exact_title_beats_repeated_generic_metadata(recall_module, tmp_path):
    db, con = make_db(tmp_path)
    configure(recall_module, tmp_path, db)
    add_row(
        con,
        item_id=1,
        title="Firecracker microVM",
        path="notes/exact-title.md",
        created="2020-01-01T00:00:00+00:00",
    )
    repeated = "Firecracker microVM generic reference"
    add_row(
        con,
        item_id=2,
        title="new generic record",
        path="notes/repeated.md",
        created="2026-12-01T00:00:00+00:00",
        tags=json.dumps([repeated]),
        capabilities=json.dumps([repeated]),
        use_cases=json.dumps([repeated]),
        description=repeated,
        summary=repeated,
        ctx_description=repeated,
        ctx_summary=repeated,
        extracted=repeated,
        keywords=json.dumps([repeated]),
    )
    con.commit()
    con.close()

    results = recall_module.collect_db_results("firecracker microvm", 2, None)

    assert results[0]["path"] == "notes/exact-title.md"


def test_many_link_rows_for_one_note_do_not_crowd_distinct_notes(recall_module, tmp_path):
    db, con = make_db(tmp_path)
    configure(recall_module, tmp_path, db)
    con.execute(
        "INSERT INTO items(id,title,source,path,tags,status,created_at,capabilities,use_cases,description,summary) VALUES(1,?,?,?,?,?,?,?,?,?,?)",
        ("needle", "", "notes/one.md", "[]", "done", "2026-01-01T00:00:00+00:00", "[]", "[]", "", ""),
    )
    for link_id in range(1, 17):
        con.execute("INSERT INTO links(id,item_id,url,title,context) VALUES(?,?,?, '', '')", (link_id, 1, f"https://same.example/{link_id}"))
        con.execute(
            "INSERT INTO link_contexts(id,link_id,url,title,description,summary,extracted_text,keywords,context_status,capture_quality,capture_coverage,capture_metadata,user_context,source_summary) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (link_id, link_id, f"https://same.example/{link_id}", "", "", "", "needle", "[]", "extracted", "", "", "{}", "", ""),
        )
    add_row(con, item_id=20, title="needle", path="notes/two.md", url="https://same.example/shared")
    add_row(con, item_id=21, title="needle", path="notes/three.md", url="https://same.example/shared")
    con.commit()
    con.close()

    results = recall_module.collect_db_results("needle", 3, None)

    assert {result["path"] for result in results} == {"notes/one.md", "notes/two.md", "notes/three.md"}
    assert len(results) == 3


def test_same_note_different_links_do_not_share_capture_evidence(recall_module, tmp_path):
    db, con = make_db(tmp_path)
    configure(recall_module, tmp_path, db)
    add_row(con, title='General source note', ctx_title='Needle target', url='https://first.example', quality=None, coverage=None)
    con.execute("INSERT INTO links(id,item_id,url,title,context) VALUES(2,1,'https://second.example','','needle')")
    con.execute("INSERT INTO link_contexts(id,link_id,url,extracted_text,context_status,capture_quality,capture_coverage) VALUES(2,2,'https://second.example','needle','extracted','usable','bounded_text')")
    con.commit()
    con.close()
    result = recall_module.collect_db_results('needle target', 5, None)
    assert len(result) == 1
    assert result[0]['url'] == 'https://first.example'
    assert result[0]['capture_quality'] == 'unknown'
    assert result[0]['capture_coverage'] == 'unknown'


def test_fts_errors_are_labeled_as_lexical_fallback(recall_module, tmp_path, monkeypatch):
    db, con = make_db(tmp_path, fts=True)
    configure(recall_module, tmp_path, db)
    add_row(con, title="fallback needle")
    con.commit()
    con.close()
    monkeypatch.setattr(recall_module, "_fts_context_ranks", lambda _con, _tokens: ({}, "error"))

    results = recall_module.collect_db_results("fallback needle", 5, None)

    assert results[0]["search_method"] == "lexical-fallback-error"


def test_requested_limit_above_200_is_not_silently_capped(recall_module, tmp_path):
    db, con = make_db(tmp_path)
    configure(recall_module, tmp_path, db)
    for item_id in range(1, 206):
        add_row(
            con,
            item_id=item_id,
            title=f"needle {item_id}",
            path=f"notes/{item_id}.md",
            created=f"2026-01-{(item_id % 28) + 1:02d}T00:00:00+00:00",
        )
    con.commit()
    con.close()

    results = recall_module.collect_db_results("needle", 205, None)

    assert len(results) == 205
