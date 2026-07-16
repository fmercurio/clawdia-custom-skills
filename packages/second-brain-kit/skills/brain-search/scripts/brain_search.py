#!/usr/bin/env python3
"""Deterministic SQLite FTS5 search for a Markdown vault."""
from __future__ import annotations
import argparse
import json
import re
import sqlite3
from pathlib import Path

SKIP_DIRS = {".git", ".obsidian", ".brain-index", "node_modules", "__pycache__"}


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    meta = {}
    for line in text[4:end].splitlines():
        if ":" in line and not line.lstrip().startswith("-"):
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip("'\"")
    return meta, text[end + 5:]


def db_path(vault: Path) -> Path:
    return vault / ".brain-index" / "brain_search.sqlite"


def connect(vault: Path) -> sqlite3.Connection:
    target = db_path(vault)
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target)
    con.row_factory = sqlite3.Row
    con.executescript("""
      CREATE TABLE IF NOT EXISTS notes(path TEXT PRIMARY KEY, title TEXT, para TEXT, sensitivity TEXT, body TEXT);
      CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(path UNINDEXED, title, body, tokenize='unicode61');
    """)
    return con


def iter_notes(vault: Path):
    for path in sorted(vault.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.relative_to(vault).parts):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        yield path


def rebuild(vault: Path, include_restricted: bool = False) -> dict:
    con = connect(vault)
    con.execute("DELETE FROM notes")
    con.execute("DELETE FROM notes_fts")
    indexed = skipped_restricted = 0
    for path in iter_notes(vault):
        text = path.read_text(encoding="utf-8", errors="replace")
        meta, body = parse_frontmatter(text)
        sensitivity = meta.get("sensitivity", "internal").lower()
        if sensitivity == "restricted" and not include_restricted:
            skipped_restricted += 1
            continue
        rel = path.relative_to(vault).as_posix()
        title = meta.get("title") or next((line[2:].strip() for line in body.splitlines() if line.startswith("# ")), path.stem)
        para = meta.get("para", "")
        con.execute("INSERT INTO notes VALUES(?,?,?,?,?)", (rel, title, para, sensitivity, body))
        con.execute("INSERT INTO notes_fts(path,title,body) VALUES(?,?,?)", (rel, title, body))
        indexed += 1
    con.commit(); con.close()
    return {"ok": True, "files_indexed": indexed, "restricted_skipped": skipped_restricted, "db": str(db_path(vault))}


def search(vault: Path, query: str, limit: int = 8) -> list[dict]:
    if not db_path(vault).exists():
        raise FileNotFoundError("search index missing; run --rebuild explicitly")
    con = connect(vault)
    terms = re.findall(r"[\wÀ-ÿ]+", query, flags=re.UNICODE)
    if not terms:
        con.close(); return []
    expression = " OR ".join('"' + term.replace('"', '') + '"' for term in terms)
    rows = con.execute("""
      SELECT n.path,n.title,n.para,n.sensitivity,
             snippet(notes_fts,2,'>>>','<<<','…',24) AS snippet, bm25(notes_fts) AS rank
      FROM notes_fts JOIN notes n ON n.path=notes_fts.path
      WHERE notes_fts MATCH ? ORDER BY rank LIMIT ?
    """, (expression, limit)).fetchall()
    con.close()
    return [dict(row) for row in rows]


def stats(vault: Path) -> dict:
    if not db_path(vault).exists():
        return {"files": 0, "db": str(db_path(vault)), "exists": False}
    con = connect(vault)
    count = con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    restricted = con.execute("SELECT COUNT(*) FROM notes WHERE sensitivity='restricted'").fetchone()[0]
    con.close()
    return {"files": count, "restricted_indexed": restricted, "db": str(db_path(vault)), "exists": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--rebuild", action="store_true")
    action.add_argument("--query")
    action.add_argument("--stats", action="store_true")
    parser.add_argument("--include-restricted", action="store_true")
    parser.add_argument("--vector", action="store_true", help="Request semantic search; RC1 degrades to FTS when embeddings are unavailable")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        print(json.dumps({"ok": False, "error": "vault not found"})); return 2
    if args.rebuild:
        result = rebuild(vault, args.include_restricted)
    elif args.query is not None:
        try:
            results = search(vault, args.query, args.limit)
        except FileNotFoundError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
            return 2
        result = {"ok": True, "query": args.query, "results": results, "semantic": "fts-fallback" if args.vector else "disabled"}
    else:
        result = {"ok": True, **stats(vault)}
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
