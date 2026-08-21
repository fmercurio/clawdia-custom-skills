#!/usr/bin/env python3
"""Deterministic SQLite FTS5 search for a Markdown vault."""
from __future__ import annotations
import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

try:
    from kitlib import config_path, hermes_home, load_config, private_directory, require_capability
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
    from kitlib import config_path, hermes_home, load_config, private_directory, require_capability

SKIP_DIRS = {".git", ".obsidian", ".brain-index", "node_modules", "__pycache__"}
KNOWN_SENSITIVITY = {"public", "internal", "restricted"}
RESTRICTED_SEARCH_CAPABILITY = "brain.restricted-search"


def parse_yaml_scalar(value: str) -> str:
    value = value.strip()
    quote = None
    escaped = False
    for index, char in enumerate(value):
        if quote:
            if quote == '"' and char == "\\" and not escaped:
                escaped = True
                continue
            if char == quote and not escaped:
                quote = None
            escaped = False
            continue
        if char in {"'", '"'} and index == 0:
            quote = char
        elif char == "#" and index > 0 and value[index - 1].isspace():
            value = value[:index].rstrip()
            break
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


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
            meta[key.strip()] = parse_yaml_scalar(value)
    return meta, text[end + 5:]


def db_path(vault: Path) -> Path:
    return vault / ".brain-index" / "brain_search.sqlite"


def connect(vault: Path) -> sqlite3.Connection:
    index_dir = private_directory(vault, Path(".brain-index"))
    target = index_dir / "brain_search.sqlite"
    if target.is_symlink():
        raise ValueError("symlinked search database is not allowed")
    old_umask = os.umask(0o077)
    try:
        con = sqlite3.connect(target)
    finally:
        os.umask(old_umask)
    target.chmod(0o600)
    con.row_factory = sqlite3.Row
    con.executescript("""
      CREATE TABLE IF NOT EXISTS notes(path TEXT PRIMARY KEY, title TEXT, para TEXT, sensitivity TEXT, body TEXT);
      CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(path UNINDEXED, title, body, tokenize='unicode61');
    """)
    return con


def harden_index_permissions(vault: Path) -> None:
    directory = db_path(vault).parent
    directory.chmod(0o700)
    for path in directory.glob("brain_search.sqlite*"):
        if path.is_symlink() or not path.is_file():
            raise ValueError("unsafe search database sidecar")
        path.chmod(0o600)


def iter_notes(vault: Path):
    for path in sorted(vault.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.relative_to(vault).parts):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        yield path


def _restricted_search_capabilities(
    vault: Path,
    *,
    requested: bool,
    hermes_home_value: str | None,
    profile: str,
) -> frozenset[str]:
    """Grant restricted search only from the owner-controlled profile for this vault."""
    if not requested:
        return frozenset()
    cfg = load_config(config_path(hermes_home(hermes_home_value), profile))
    configured_vault = Path(cfg.get("vault_path", "")).expanduser().resolve()
    if configured_vault != vault.resolve():
        raise PermissionError("restricted search profile does not authorize this vault")
    sensitivity = cfg.get("sensitivity")
    if not isinstance(sensitivity, dict) or sensitivity.get("restricted_search") is not True:
        raise PermissionError("restricted search requires owner policy sensitivity.restricted_search: true")
    return frozenset({RESTRICTED_SEARCH_CAPABILITY})


def rebuild(vault: Path, capabilities: frozenset[str] = frozenset()) -> dict:
    con = connect(vault)
    con.execute("DELETE FROM notes")
    con.execute("DELETE FROM notes_fts")
    indexed = skipped_restricted = 0
    for path in iter_notes(vault):
        text = path.read_text(encoding="utf-8", errors="replace")
        meta, body = parse_frontmatter(text)
        sensitivity = meta.get("sensitivity", "internal").lower()
        if sensitivity not in KNOWN_SENSITIVITY:
            skipped_restricted += 1
            continue
        if sensitivity == "restricted":
            try:
                require_capability(RESTRICTED_SEARCH_CAPABILITY, capabilities)
            except PermissionError:
                skipped_restricted += 1
                continue
        rel = path.relative_to(vault).as_posix()
        title = meta.get("title") or next((line[2:].strip() for line in body.splitlines() if line.startswith("# ")), path.stem)
        para = meta.get("para", "")
        con.execute("INSERT INTO notes VALUES(?,?,?,?,?)", (rel, title, para, sensitivity, body))
        con.execute("INSERT INTO notes_fts(path,title,body) VALUES(?,?,?)", (rel, title, body))
        indexed += 1
    con.commit(); harden_index_permissions(vault); con.close()
    return {"ok": True, "files_indexed": indexed, "restricted_skipped": skipped_restricted, "db": str(db_path(vault))}


def search(vault: Path, query: str, limit: int = 8, capabilities: frozenset[str] = frozenset()) -> list[dict]:
    if not db_path(vault).exists():
        raise FileNotFoundError("search index missing; run --rebuild explicitly")
    con = connect(vault)
    terms = re.findall(r"[\wÀ-ÿ]+", query, flags=re.UNICODE)
    if not terms:
        con.close(); return []
    expression = " OR ".join('"' + term.replace('"', '') + '"' for term in terms)
    include_restricted = RESTRICTED_SEARCH_CAPABILITY in capabilities
    rows = con.execute("""
      SELECT n.path,n.title,n.para,n.sensitivity,
             snippet(notes_fts,2,'>>>','<<<','…',24) AS snippet, bm25(notes_fts) AS rank
      FROM notes_fts JOIN notes n ON n.path=notes_fts.path
      WHERE notes_fts MATCH ? AND (? OR n.sensitivity != 'restricted')
      ORDER BY rank LIMIT ?
    """, (expression, include_restricted, limit)).fetchall()
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
    parser.add_argument("--hermes-home", help="profile root used to authorize --include-restricted")
    parser.add_argument("--profile", default="second-brain", help="owner-controlled profile used to authorize --include-restricted")
    parser.add_argument("--vector", action="store_true", help="Request semantic search; RC1 degrades to FTS when embeddings are unavailable")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        print(json.dumps({"ok": False, "error": "vault not found"})); return 2
    try:
        capabilities = _restricted_search_capabilities(
            vault,
            requested=args.include_restricted,
            hermes_home_value=args.hermes_home,
            profile=args.profile,
        )
        if args.rebuild:
            result = rebuild(vault, capabilities)
        elif args.query is not None:
            results = search(vault, args.query, args.limit, capabilities)
            result = {"ok": True, "query": args.query, "results": results, "semantic": "fts-fallback" if args.vector else "disabled"}
        else:
            result = {"ok": True, **stats(vault)}
    except (FileNotFoundError, OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
