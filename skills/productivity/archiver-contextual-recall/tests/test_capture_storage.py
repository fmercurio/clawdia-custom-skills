from __future__ import annotations


import importlib
import json

from pathlib import Path
import sqlite3
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


@pytest.fixture
def modules(tmp_path, monkeypatch):
    monkeypatch.setenv('ARCHIVER_HOME', str(tmp_path / 'archiver'))
    monkeypatch.delenv('ARCHIVER_VAULT', raising=False)
    monkeypatch.delenv('ARCHIVER_DB', raising=False)
    monkeypatch.syspath_prepend(str(SCRIPTS))
    for name in ('archiver_db', 'archiver_extract_context', 'archive_item', 'backfill_link_contexts'):
        monkeypatch.delitem(sys.modules, name, raising=False)
    return tuple(importlib.import_module(name) for name in ('archiver_db', 'archive_item', 'backfill_link_contexts'))


def seed(db):
    con = db.connect()
    db.ensure_schema(con)
    con.execute("INSERT INTO items(id,title,path,created_at,updated_at) VALUES(1,'Fixture','00-inbox/fixture.md','2020','2020')")
    con.execute("INSERT INTO links(id,item_id,url,created_at) VALUES(1,1,'https://source.example/article','2020')")
    con.commit()
    return con


def test_readonly_preserves_bytes_schema_modes_and_blocks_temp_writes(modules, tmp_path):
    db, _, _ = modules
    directory = tmp_path / 'readonly'
    directory.mkdir(mode=0o750)
    path = directory / 'archive ?#%.sqlite3'
    with sqlite3.connect(path) as con:
        con.execute('CREATE TABLE entries(value TEXT)')
        con.execute("INSERT INTO entries VALUES('kept')")
    path.chmod(0o640)
    directory.chmod(0o750)
    before = (path.read_bytes(), path.stat().st_mode, directory.stat().st_mode, sorted(p.name for p in directory.iterdir()))
    cwd = Path.cwd()
    with db.connect_readonly(path) as con:
        assert con.execute('PRAGMA query_only').fetchone() == (1,)
        assert con.execute('SELECT value FROM entries').fetchall() == [('kept',)]
        for statement in ('CREATE TABLE forbidden(x)', 'CREATE TEMP TABLE forbidden(x)', "INSERT INTO entries VALUES('bad')"):
            with pytest.raises(sqlite3.OperationalError):
                con.execute(statement)
    after = (path.read_bytes(), path.stat().st_mode, directory.stat().st_mode, sorted(p.name for p in directory.iterdir()))
    assert after == before
    assert Path.cwd() == cwd


def test_readonly_missing_database_creates_nothing(modules, tmp_path):
    db, _, _ = modules
    absent = tmp_path / 'missing' / 'db.sqlite3'
    with pytest.raises((ValueError, sqlite3.OperationalError)):
        db.connect_readonly(absent)
    assert not absent.parent.exists()


def test_additive_schema_keeps_legacy_rows_and_defaults_unknown(modules):
    db, _, _ = modules
    with seed(db) as con:
        db.upsert_link_context(con, 1, 'https://source.example/article', summary='Legacy annotation', extracted_text='Legacy text', context_status='extracted')
        con.commit()
        before = con.execute('SELECT id,link_id,url,summary,extracted_text,created_at FROM link_contexts').fetchall()
        db.ensure_schema(con)
        db.ensure_schema(con)
        assert con.execute('SELECT id,link_id,url,summary,extracted_text,created_at FROM link_contexts').fetchall() == before
        assert con.execute('SELECT capture_quality,capture_coverage,capture_metadata,user_context,source_summary FROM link_contexts').fetchone() == ('unknown', 'unknown', '{}', None, None)
        assert con.execute('SELECT capabilities,use_cases FROM items').fetchone() == ('[]', '[]')


def test_capture_upsert_persists_separate_layers_and_preserves_optional_fields(modules):
    db, _, _ = modules
    with seed(db) as con:
        db.upsert_link_context(con, 1, 'https://source.example/article', summary='Annotation', user_context='Full user note', source_summary='Prefix only', capture_quality='usable', capture_coverage='truncated', capture_metadata={'schema': 'archiver-capture.v1', 'truncated_text': True})
        db.upsert_link_context(con, 1, 'https://source.example/article', summary='Updated legacy annotation')
        row = con.execute('SELECT summary,user_context,source_summary,capture_quality,capture_coverage,capture_metadata FROM link_contexts').fetchone()
        assert row[:5] == ('Updated legacy annotation', 'Full user note', 'Prefix only', 'usable', 'truncated')
        assert json.loads(row[5])['truncated_text'] is True
        assert con.execute('SELECT count(*) FROM link_contexts').fetchone()[0] == 1
        with pytest.raises(ValueError):
            db.upsert_link_context(con, 1, 'https://source.example/article', capture_quality='tested')


def test_intake_keeps_long_annotation_separate_and_explicit_capabilities(modules, monkeypatch, capsys):
    db, intake, _ = modules
    body = 'User annotation not an automatic source summary. ' * 100
    result = {'title': 'Actual article', 'description': 'Description', 'summary': 'Automatic prefix only', 'extracted_text': 'Visible article text', 'keywords': ['editing'], 'context_status': 'extracted', 'extractor': 'fixture', 'capture_quality': 'limited', 'capture_coverage': 'bounded_text', 'capture_metadata': {'schema': 'archiver-capture.v1', 'summary_method': 'prefix'}, 'error': None}
    monkeypatch.setattr(intake, 'extract_url_context', lambda *_args, **_kwargs: result)
    monkeypatch.setattr(sys, 'argv', ['archive_item.py', '--title', 'Tool reference', '--source', 'https://source.example/Case?version=2#details', '--body', body, '--capability', 'editar vídeos', '--use-case', 'melhorar copy', '--json'])
    assert intake.main() == 0
    output = json.loads(capsys.readouterr().out)
    with sqlite3.connect(db.DB) as con:
        row = con.execute('SELECT user_context,source_summary,summary,capture_quality,capture_coverage,capture_metadata FROM link_contexts').fetchone()
        assert row[:5] == (body.strip(), result['summary'], body.strip(), 'limited', 'bounded_text')
        assert json.loads(row[5])['summary_method'] == 'prefix'
        item = con.execute('SELECT capabilities,use_cases,source FROM items').fetchone()
        assert json.loads(item[0]) == ['editar vídeos']
        assert json.loads(item[1]) == ['melhorar copy']
        assert item[2] == 'https://source.example/Case?version=2#details'
    assert body.strip() in Path(output['path']).read_text()
    assert output['item_id'] > 0
    assert output['extracted_context_count'] == 1


@pytest.mark.parametrize('status,quality,coverage', [('metadata_only', 'metadata_only', 'metadata_only'), ('insufficient_text', 'limited', 'bounded_text'), ('failed', 'unknown', 'none'), ('unsupported_content_type', 'unknown', 'none')])
def test_intake_records_capture_status_without_erasing_annotation(modules, monkeypatch, capsys, status, quality, coverage):
    db, intake, _ = modules
    monkeypatch.setattr(intake, 'extract_url_context', lambda *_args, **_kwargs: {'context_status': status, 'capture_quality': quality, 'capture_coverage': coverage, 'capture_metadata': {'schema': 'archiver-capture.v1'}, 'title': 'Metadata title', 'error': None})
    monkeypatch.setattr(sys, 'argv', ['archive_item.py', '--title', 'Reference', '--source', 'https://source.example/item', '--body', 'Preserved annotation', '--json'])
    assert intake.main() == 0
    payload = json.loads(capsys.readouterr().out)
    with sqlite3.connect(db.DB) as con:
        assert con.execute('SELECT context_status,user_context,capture_quality,capture_coverage FROM link_contexts').fetchone() == (status, 'Preserved annotation', quality, coverage)
    assert payload['extracted_context_count'] == 0


def test_offline_intake_does_not_infer_source_quality(modules, monkeypatch, capsys):
    db, intake, _ = modules
    monkeypatch.setattr(intake, 'extract_url_context', lambda *_args, **_kwargs: pytest.fail('offline intake attempted fetch'))
    monkeypatch.setattr(sys, 'argv', ['archive_item.py', '--title', 'Offline', '--source', 'https://source.example/item', '--body', 'My note', '--no-extract', '--json'])
    assert intake.main() == 0
    capsys.readouterr()
    with sqlite3.connect(db.DB) as con:
        assert con.execute('SELECT context_status,user_context,source_summary,capture_quality,capture_coverage FROM link_contexts').fetchone() == ('body_only', 'My note', None, 'unknown', 'none')


def test_failed_forced_backfill_does_not_replace_good_capture(modules, monkeypatch):
    db, _, backfill = modules
    with seed(db) as con:
        db.upsert_link_context(con, 1, 'https://source.example/article', title='Good title', summary='Local annotation', user_context='User intent', source_summary='Good source summary', extracted_text='Good text', context_status='extracted', extractor='old-parser', capture_quality='usable', capture_coverage='bounded_text', capture_metadata={'schema': 'archiver-capture.v1', 'method': 'old'})
        con.commit()
        before = con.execute('SELECT * FROM link_contexts').fetchall()
        monkeypatch.setattr(backfill, 'extract_url_context', lambda *_args, **_kwargs: {'context_status': 'failed', 'capture_quality': 'unknown', 'capture_coverage': 'none', 'error': 'fixture failure'})
        stats = backfill.extract_existing_contexts(con, dry_run=False, force=True)
        assert con.execute('SELECT * FROM link_contexts').fetchall() == before
        assert stats['failed_contexts'] == 1
        assert stats['preserved_contexts'] == 1


def test_backfill_downgrade_is_preserved_not_counted_as_written_extraction(modules, monkeypatch):
    db, _, backfill = modules
    with seed(db) as con:
        db.upsert_link_context(con, 1, 'https://source.example/article', extracted_text='Good source text', context_status='extracted', capture_quality='usable')
        con.commit()
        before = con.execute('SELECT * FROM link_contexts').fetchall()
        monkeypatch.setattr(backfill, 'extract_url_context', lambda *_args, **_kwargs: {'context_status': 'extracted', 'extracted_text': 'Brief fragment', 'capture_quality': 'limited', 'capture_coverage': 'bounded_text'})
        stats = backfill.extract_existing_contexts(con, dry_run=False, force=True)
        assert con.execute('SELECT * FROM link_contexts').fetchall() == before
        assert stats['preserved_contexts'] == 1
        assert stats['extracted_contexts'] == 0


def test_backfill_unsupported_capture_is_not_counted_as_local_only(modules, monkeypatch):
    db, _, backfill = modules
    with seed(db) as con:
        db.upsert_link_context(con, 1, 'https://source.example/article', summary='Local annotation', context_status='body_only')
        con.commit()
        monkeypatch.setattr(backfill, 'extract_url_context', lambda *_args, **_kwargs: {'context_status': 'unsupported_content_type', 'capture_quality': 'unknown', 'capture_coverage': 'unknown'})
        stats = backfill.extract_existing_contexts(con, dry_run=False, force=False)
        assert stats['body_only_contexts'] == 0
        assert stats['limited_contexts'] == 1
        assert con.execute('SELECT context_status,summary FROM link_contexts').fetchone() == ('unsupported_content_type', 'Local annotation')


def test_backfill_success_preserves_annotation_and_records_new_source_metadata(modules, monkeypatch):
    db, _, backfill = modules
    with seed(db) as con:
        db.upsert_link_context(con, 1, 'https://source.example/article', summary='Local annotation', user_context='User intent', context_status='body_only')
        con.commit()
        monkeypatch.setattr(backfill, 'extract_url_context', lambda *_args, **_kwargs: {'context_status': 'extracted', 'title': 'Source title', 'summary': 'Source prefix', 'extracted_text': 'Source text', 'capture_quality': 'usable', 'capture_coverage': 'truncated', 'capture_metadata': {'schema': 'archiver-capture.v1', 'text_truncated': True}})
        stats = backfill.extract_existing_contexts(con, dry_run=False, force=False)
        assert con.execute('SELECT summary,user_context,source_summary,capture_quality,capture_coverage FROM link_contexts').fetchone() == ('Local annotation', 'User intent', 'Source prefix', 'usable', 'truncated')
        assert stats['extracted_contexts'] == 1


def test_weekly_review_surfaces_insufficient_captures(modules, monkeypatch):
    db, _, _ = modules
    review = importlib.import_module('archive_weekly_review')
    monkeypatch.setattr(review, 'run_subprocess', lambda *_args, **_kwargs: {'returncode': 1, 'stdout': '', 'stderr': ''})
    with seed(db) as con:
        db.upsert_link_context(con, 1, 'https://source.example/article', context_status='metadata_only', capture_quality='metadata_only', capture_coverage='metadata_only')
        con.commit()
        metrics = review.collect_metrics(con, db.BASE, db.VAULT, 'fixture', 30)
        finding = next(item for item in metrics['findings'] if item['id'] == 'attention.insufficient_contexts')
        assert finding['severity'] == 'attention'
        assert len(metrics['insufficient_contexts']) == 1


def test_backup_captures_committed_wal_rows_before_schema_changes(modules, tmp_path):
    _, _, backfill = modules
    path = tmp_path / 'wal.sqlite3'
    with sqlite3.connect(path) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('CREATE TABLE legacy(value TEXT)')
        writer.execute("INSERT INTO legacy VALUES('committed in WAL')")
        writer.commit()
        backup = backfill.add_backup(path)
        assert backup
        with sqlite3.connect(backup) as copied:
            assert copied.execute('SELECT value FROM legacy').fetchall() == [('committed in WAL',)]
        assert Path(backup).stat().st_mode & 0o777 == 0o600
