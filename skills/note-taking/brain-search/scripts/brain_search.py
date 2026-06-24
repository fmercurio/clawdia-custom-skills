#!/usr/bin/env python3
"""
brain_search.py — FTS5 + optional semantic search over the Second Brain vault.

Standalone script (zero Hermes internals dependency).
Index: FTS5 SQLite under <vault>/.brain-index/
Chunking: by Markdown headings (##/###), fallback to paragraph splits.

Usage:
  python3 brain_search.py --rebuild              # Build/rebuild full index
  python3 brain_search.py --query "termos"        # Lexical FTS search
  python3 brain_search.py --query "termos" --vector  # + semantic embeddings
  python3 brain_search.py --query "termos" --limit 10
  python3 brain_search.py --update "path/to/file.md"  # Reindex one file
  python3 brain_search.py --stats                 # Index statistics
  python3 brain_search.py --list                  # List indexed files

Embeddings (optional):
  Uses OpenAI-compatible API (LM Studio / Ollama).
  Set env vars or defaults apply:
    BRAIN_EMBED_URL  — default http://127.0.0.1:1234/v1/embeddings
    BRAIN_EMBED_MODEL — default nomic-embed-text

Design choices:
  - Markdown headings (## / ###) as chunk boundaries
  - FTS5 unicode61 tokenizer (good for Portuguese)
  - Chunks include: heading context, content, PARA layer, tags from frontmatter
  - Embeddings stored in separate table, cosine similarity search
  - Graceful degradation: works fully without embeddings endpoint
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

VAULT_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = VAULT_ROOT / ".brain-index"
DB_PATH = DB_DIR / "brain_search.sqlite"

# Embedding config
EMBED_URL = os.environ.get("BRAIN_EMBED_URL", "http://127.0.0.1:1234/v1/embeddings")
EMBED_MODEL = os.environ.get("BRAIN_EMBED_MODEL", "nomic-embed-text")
LOOPBACK_EMBED_HOSTS = {"localhost", "127.0.0.1", "::1"}
REMOTE_EMBED_OPT_IN_ENV = "BRAIN_ALLOW_REMOTE_EMBEDDINGS"

# File scanning
SUPPORTED_EXTS = {".md", ".txt", ".yaml", ".yml"}
SKIP_DIRS = {".git", ".obsidian", ".trash", ".brain-index", "node_modules", "__pycache__", ".indices"}

# Chunking
MAX_CHUNK_CHARS = 800
MIN_CHUNK_CHARS = 50


class EmbeddingEndpointError(ValueError):
    """Raised when embedding egress would leave the trusted local boundary."""


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def validate_embed_url(raw_url: str, allow_remote: bool = False) -> str:
    """Return a normalized embedding URL, fail-closed for remote endpoints by default."""
    parsed = urllib.parse.urlsplit((raw_url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise EmbeddingEndpointError("embedding endpoint must include http(s) scheme and host")
    if parsed.username or parsed.password:
        raise EmbeddingEndpointError("embedding endpoint must not contain credentials")
    if parsed.query or parsed.fragment:
        raise EmbeddingEndpointError("embedding endpoint must not include query or fragment")
    hostname = (parsed.hostname or "").lower()
    if not allow_remote and hostname not in LOOPBACK_EMBED_HOSTS:
        raise EmbeddingEndpointError(
            "embedding endpoint must be localhost by default; pass --allow-remote-embeddings "
            f"or set {REMOTE_EMBED_OPT_IN_ENV}=1 only for an approved remote provider"
        )
    path = parsed.path or ""
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def resolve_embed_url(allow_remote: bool = False) -> str:
    return validate_embed_url(
        EMBED_URL,
        allow_remote=allow_remote or _env_flag(REMOTE_EMBED_OPT_IN_ENV),
    )


def ensure_vault_file(path: Path) -> Path:
    """Return a resolved in-vault, supported file path or raise ValueError."""
    vault_root = VAULT_ROOT.resolve()
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(vault_root)
    except ValueError:
        raise ValueError("path escapes vault root")

    if any(part in SKIP_DIRS for part in rel.parts):
        raise ValueError("path is inside a skipped directory")
    if resolved.suffix.lower() not in SUPPORTED_EXTS:
        raise ValueError(f"unsupported file extension: {resolved.suffix or '<none>'}")
    return resolved


def resolve_update_path(raw_path: str) -> Path:
    """Resolve a CLI --update path while enforcing the vault boundary."""
    value = (raw_path or "").strip()
    if not value:
        raise ValueError("--update path is empty")

    requested = Path(value)
    if requested.is_absolute():
        raise ValueError("--update requires a relative path inside the vault")
    return ensure_vault_file(VAULT_ROOT / requested)


# ---------------------------------------------------------------------------
# Database schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    relpath TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    layer TEXT DEFAULT '',
    title TEXT DEFAULT '',
    para_tag TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    indexed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    heading TEXT DEFAULT '',
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    heading,
    title,
    layer,
    tags,
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id INTEGER PRIMARY KEY,
    embedding BLOB,
    model TEXT DEFAULT '',
    FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_files_relpath ON files(relpath);
CREATE INDEX IF NOT EXISTS idx_chunks_file_id ON chunks(file_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_chunk_id ON embeddings(chunk_id);
"""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and return (meta, body)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end].strip()
    body = text[end + 3:].strip()
    meta = {}
    for line in raw.split("\n"):
        line = line.strip()
        if ":" in line and not line.startswith("-"):
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if v:
                meta[k] = v
    return meta, body


def detect_layer(relpath: str) -> str:
    """Detect PARA layer from path."""
    parts = Path(relpath).parts
    layer_map = {
        "00_Inbox": "inbox",
        "10_Projects": "project",
        "20_Areas": "area",
        "30_Resources": "resource",
        "40_Archives": "archive",
        "50_Templates": "template",
        "_Hermes": "hermes",
        "_Meta": "meta",
    }
    for part in parts:
        if part in layer_map:
            return layer_map[part]
    return ""


def chunk_markdown(text: str, title: str = "") -> list[dict]:
    """Split markdown into chunks by headings, with fallback to paragraphs."""
    chunks = []
    # Split by headings (## or ###)
    heading_pattern = re.compile(r'^(#{1,4})\s+(.+)$', re.MULTILINE)
    sections = []
    last_end = 0
    heading_stack = []  # Track heading hierarchy for context

    for m in heading_pattern.finditer(text):
        if m.start() > last_end:
            content = text[last_end:m.start()].strip()
            if content:
                h_context = " > ".join(h for h in heading_stack) if heading_stack else title
                sections.append({"heading": h_context, "content": content})
        heading_stack = [m.group(2).strip()]
        last_end = m.start()

    # Remaining text after last heading
    if last_end < len(text):
        content = text[last_end:].strip()
        if content:
            h_context = " > ".join(h for h in heading_stack) if heading_stack else title
            sections.append({"heading": h_context, "content": content})

    # If no sections found, treat entire text as one chunk
    if not sections and text.strip():
        sections.append({"heading": title, "content": text.strip()})

    # Split oversized sections into smaller chunks
    for sec in sections:
        content = sec["content"]
        heading = sec["heading"]
        if len(content) <= MAX_CHUNK_CHARS:
            chunks.append({"heading": heading, "content": content})
        else:
            # Split by double newline (paragraphs)
            paragraphs = re.split(r'\n\s*\n', content)
            current = ""
            for para in paragraphs:
                if len(current) + len(para) + 2 > MAX_CHUNK_CHARS and current:
                    if len(current) >= MIN_CHUNK_CHARS:
                        chunks.append({"heading": heading, "content": current.strip()})
                    current = para
                else:
                    current = current + "\n\n" + para if current else para
            if current.strip() and len(current) >= MIN_CHUNK_CHARS:
                chunks.append({"heading": heading, "content": current.strip()})

    return chunks


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def init_db() -> sqlite3.Connection:
    """Initialize or open the database."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    # Add .brain-index to .gitignore if not already there
    gitignore = VAULT_ROOT / ".gitignore"
    if gitignore.exists():
        gi = gitignore.read_text()
        if ".brain-index" not in gi:
            gi = gi.rstrip() + "\n.brain-index/\n"
            gitignore.write_text(gi)
    else:
        gitignore.write_text(".brain-index/\n")

    con = sqlite3.connect(str(DB_PATH))
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    return con


def file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def index_file(
    path: Path,
    con: sqlite3.Connection,
    embeddings: bool = False,
    allow_remote_embeddings: bool = False,
) -> dict:
    """Index a single file into the database."""
    try:
        path = ensure_vault_file(path)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    relpath = str(path.relative_to(VAULT_ROOT.resolve()))

    # Read and parse
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"ok": False, "error": str(e)}

    stat = path.stat()
    sha = file_hash(path)
    meta, body = parse_frontmatter(text)

    title = meta.get("title", path.stem)
    para_tag = meta.get("para", "")
    tags = meta.get("tags", "")
    # Clean tags: remove brackets, quotes
    tags_clean = re.sub(r'[\[\]\'"]', '', tags)
    layer = detect_layer(relpath)

    # Delete existing entries for this file
    existing = con.execute("SELECT id FROM files WHERE relpath=?", (relpath,)).fetchone()
    if existing:
        fid = existing[0]
        chunk_ids = [r[0] for r in con.execute("SELECT id FROM chunks WHERE file_id=?", (fid,))]
        for cid in chunk_ids:
            try:
                con.execute("DELETE FROM chunks_fts WHERE rowid=?", (cid,))
            except sqlite3.DatabaseError:
                pass
        con.execute("DELETE FROM embeddings WHERE chunk_id IN (SELECT id FROM chunks WHERE file_id=?)", (fid,))
        con.execute("DELETE FROM chunks WHERE file_id=?", (fid,))
        con.execute("DELETE FROM files WHERE id=?", (fid,))

    # Insert file record
    con.execute(
        """INSERT INTO files (relpath, filename, layer, title, para_tag, tags, mtime, size, sha256, indexed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (relpath, path.name, layer, title, para_tag, tags_clean, stat.st_mtime, stat.st_size, sha,
         datetime.now(timezone.utc).isoformat())
    )
    file_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Chunk the body
    chunks = chunk_markdown(body, title)
    chunk_texts_for_embed = []

    for i, chunk in enumerate(chunks):
        con.execute(
            """INSERT INTO chunks (file_id, heading, chunk_index, content, char_count)
               VALUES (?, ?, ?, ?, ?)""",
            (file_id, chunk["heading"], i, chunk["content"], len(chunk["content"]))
        )
        chunk_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

        # FTS index — include metadata for richer search
        fts_content = f'{chunk["content"]}'
        fts_heading = chunk["heading"]
        con.execute(
            "INSERT INTO chunks_fts (rowid, content, heading, title, layer, tags) VALUES (?, ?, ?, ?, ?, ?)",
            (chunk_id, fts_content, fts_heading, title, layer, tags_clean)
        )

        if embeddings:
            chunk_texts_for_embed.append((chunk_id, fts_content))

    con.commit()

    # Optional embeddings
    embed_count = 0
    if embeddings and chunk_texts_for_embed:
        embed_count = _store_embeddings(
            con,
            chunk_texts_for_embed,
            allow_remote_embeddings=allow_remote_embeddings,
        )

    return {
        "ok": True,
        "file": relpath,
        "chunks": len(chunks),
        "embeddings": embed_count,
        "action": "updated" if existing else "indexed"
    }


def _store_embeddings(
    con: sqlite3.Connection,
    items: list[tuple[int, str]],
    allow_remote_embeddings: bool = False,
) -> int:
    """Generate and store embeddings via OpenAI-compatible API."""
    try:
        import urllib.request
    except ImportError:
        return 0

    embed_url = resolve_embed_url(allow_remote=allow_remote_embeddings)
    count = 0
    batch_size = 20
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        texts = [t for _, t in batch]
        ids = [cid for cid, _ in batch]

        payload = json.dumps({
            "model": EMBED_MODEL,
            "input": texts
        }).encode("utf-8")

        req = urllib.request.Request(
            embed_url,
            data=payload,
            headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            for j, emb_data in enumerate(result.get("data", [])):
                vec = emb_data.get("embedding", [])
                if vec:
                    blob = _floats_to_blob(vec)
                    con.execute(
                        "INSERT OR REPLACE INTO embeddings (chunk_id, embedding, model) VALUES (?, ?, ?)",
                        (ids[j], blob, EMBED_MODEL)
                    )
                    count += 1
            con.commit()
        except Exception:
            # Graceful: skip this batch if embedding endpoint is down
            continue

    return count


def _floats_to_blob(floats: list[float]) -> bytes:
    """Convert float list to compact binary blob (float32 array)."""
    import struct
    return struct.pack(f'{len(floats)}f', *floats)


def _blob_to_floats(blob: bytes) -> list[float]:
    """Convert binary blob back to float list."""
    import struct
    n = len(blob) // 4
    return list(struct.unpack(f'{n}f', blob))


def rebuild_index(
    con: sqlite3.Connection,
    embeddings: bool = False,
    allow_remote_embeddings: bool = False,
) -> dict:
    """Full rebuild of the index."""
    start = time.time()
    # Clear all tables
    con.execute("DELETE FROM chunks_fts")
    con.execute("DELETE FROM embeddings")
    con.execute("DELETE FROM chunks")
    con.execute("DELETE FROM files")
    con.commit()

    files_scanned = 0
    files_indexed = 0
    total_chunks = 0
    total_embeddings = 0
    errors = []

    for path in _walk_vault():
        files_scanned += 1
        result = index_file(
            path,
            con,
            embeddings=embeddings,
            allow_remote_embeddings=allow_remote_embeddings,
        )
        if result.get("ok"):
            files_indexed += 1
            total_chunks += result.get("chunks", 0)
            total_embeddings += result.get("embeddings", 0)
        else:
            errors.append({"file": str(path), "error": result.get("error", "unknown")})

    elapsed = time.time() - start
    return {
        "ok": True,
        "action": "rebuild",
        "files_scanned": files_scanned,
        "files_indexed": files_indexed,
        "total_chunks": total_chunks,
        "total_embeddings": total_embeddings,
        "errors": len(errors),
        "elapsed_seconds": round(elapsed, 2),
        "error_details": errors[:5] if errors else []
    }


def _walk_vault():
    """Walk vault and yield supported files."""
    for p in VAULT_ROOT.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in SUPPORTED_EXTS:
            continue
        yield p


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_fts(con: sqlite3.Connection, query: str, limit: int = 10) -> list[dict]:
    """FTS5 lexical search."""
    # Escape FTS5 special characters
    safe_query = re.sub(r'[^\w\s]', ' ', query).strip()
    if not safe_query:
        return []

    # Build FTS query: all words must appear (AND mode)
    terms = safe_query.split()
    fts_query = " AND ".join(f'"{t}"' if len(t) > 2 else t for t in terms)

    try:
        rows = con.execute("""
            SELECT
                f.relpath, f.filename, f.layer, f.title, f.para_tag, f.tags,
                c.heading, c.content, c.char_count,
                snippet(chunks_fts, 0, '>>>', '<<<', '…', 32) as snippet,
                rank
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            JOIN files f ON f.id = c.file_id
            WHERE chunks_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (fts_query, limit)).fetchall()
    except sqlite3.OperationalError:
        # Fallback: try simpler query
        fts_query = " OR ".join(f'"{t}"' for t in terms)
        rows = con.execute("""
            SELECT
                f.relpath, f.filename, f.layer, f.title, f.para_tag, f.tags,
                c.heading, c.content, c.char_count,
                snippet(chunks_fts, 0, '>>>', '<<<', '…', 32) as snippet,
                rank
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            JOIN files f ON f.id = c.file_id
            WHERE chunks_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (fts_query, limit)).fetchall()

    results = []
    for r in rows:
        results.append({
            "path": r[0],
            "filename": r[1],
            "layer": r[2],
            "title": r[3],
            "para": r[4],
            "tags": r[5],
            "heading": r[6],
            "content": r[7],
            "chars": r[8],
            "snippet": r[9],
            "rank": r[10],
        })
    return results


def search_vector(
    con: sqlite3.Connection,
    query: str,
    limit: int = 10,
    allow_remote_embeddings: bool = False,
) -> list[dict]:
    """Semantic search via embeddings + cosine similarity."""
    import urllib.request
    embed_url = resolve_embed_url(allow_remote=allow_remote_embeddings)

    payload = json.dumps({
        "model": EMBED_MODEL,
        "input": [query]
    }).encode("utf-8")

    req = urllib.request.Request(
        embed_url,
        data=payload,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return [{"error": f"Embedding endpoint unavailable: {e}"}]

    query_vec = result["data"][0]["embedding"]
    if not query_vec:
        return []

    # Compare against stored embeddings
    rows = con.execute("""
        SELECT e.chunk_id, e.embedding, e.model,
               c.heading, c.content,
               f.relpath, f.title, f.layer, f.tags
        FROM embeddings e
        JOIN chunks c ON c.id = e.chunk_id
        JOIN files f ON f.id = c.file_id
    """).fetchall()

    if not rows:
        return []

    scored = []
    for r in rows:
        vec = _blob_to_floats(r[1])
        sim = _cosine_similarity(query_vec, vec)
        scored.append((sim, r))

    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for sim, r in scored[:limit]:
        results.append({
            "path": r[5],
            "title": r[6],
            "layer": r[7],
            "tags": r[8],
            "heading": r[3],
            "content": r[4],
            "similarity": round(sim, 4),
        })
    return results


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def search_combined(
    con: sqlite3.Connection,
    query: str,
    limit: int = 8,
    vector: bool = False,
    allow_remote_embeddings: bool = False,
) -> dict:
    """Combined search: FTS + optional vector, deduplicated."""
    fts_results = search_fts(con, query, limit=limit)

    result = {
        "query": query,
        "fts_count": len(fts_results),
        "fts_results": fts_results,
    }

    if vector:
        vec_results = search_vector(
            con,
            query,
            limit=limit,
            allow_remote_embeddings=allow_remote_embeddings,
        )
        if vec_results and "error" not in vec_results[0]:
            # Deduplicate: prefer FTS, add vector-only results
            fts_paths = {r["path"] + ":" + r.get("heading", "") for r in fts_results}
            unique_vec = [r for r in vec_results
                          if r["path"] + ":" + r.get("heading", "") not in fts_paths]
            result["vector_count"] = len(vec_results)
            result["vector_unique"] = len(unique_vec)
            result["vector_results"] = unique_vec
        elif vec_results and "error" in vec_results[0]:
            result["vector_error"] = vec_results[0]["error"]

    return result


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def get_stats(con: sqlite3.Connection) -> dict:
    """Return index statistics."""
    file_count = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    chunk_count = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    embed_count = con.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]

    layers = {}
    for row in con.execute("SELECT layer, COUNT(*) FROM files GROUP BY layer ORDER BY COUNT(*) DESC"):
        layers[row[0] or "(sem layer)"] = row[1]

    last_indexed = con.execute("SELECT MAX(indexed_at) FROM files").fetchone()[0]

    return {
        "vault": str(VAULT_ROOT),
        "db": str(DB_PATH),
        "files": file_count,
        "chunks": chunk_count,
        "embeddings": embed_count,
        "layers": layers,
        "last_indexed": last_indexed,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Second Brain search engine")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild full index")
    parser.add_argument("--query", type=str, help="Search query")
    parser.add_argument("--update", type=str, help="Reindex a single file (relative path)")
    parser.add_argument("--stats", action="store_true", help="Show index statistics")
    parser.add_argument("--list", action="store_true", help="List indexed files")
    parser.add_argument("--vector", action="store_true", help="Enable semantic search (requires embedding endpoint)")
    parser.add_argument("--embeddings", action="store_true", help="Generate embeddings during rebuild")
    parser.add_argument(
        "--allow-remote-embeddings",
        action="store_true",
        help="Allow sending vault text/query text to a non-local embedding endpoint",
    )
    parser.add_argument("--limit", type=int, default=8, help="Max results (default 8)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    update_path = None
    if args.update:
        try:
            update_path = resolve_update_path(args.update)
        except ValueError as e:
            print(f"Unsafe update path: {e}", file=sys.stderr)
            sys.exit(2)

    con = init_db()

    if args.rebuild:
        try:
            result = rebuild_index(
                con,
                embeddings=args.embeddings,
                allow_remote_embeddings=args.allow_remote_embeddings,
            )
        except EmbeddingEndpointError as e:
            con.close()
            print(f"Unsafe embedding endpoint: {e}", file=sys.stderr)
            sys.exit(2)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"🧠 Índice reconstruído: {result['files_indexed']} arquivos, {result['total_chunks']} chunks em {result['elapsed_seconds']}s")
            if result["errors"]:
                print(f"   ⚠️  {result['errors']} erro(s)")
        con.close()
        return

    if args.update:
        path = update_path
        if not path.exists():
            print(f"Arquivo não encontrado: {args.update}")
            sys.exit(1)
        try:
            result = index_file(
                path,
                con,
                embeddings=args.embeddings,
                allow_remote_embeddings=args.allow_remote_embeddings,
            )
        except EmbeddingEndpointError as e:
            con.close()
            print(f"Unsafe embedding endpoint: {e}", file=sys.stderr)
            sys.exit(2)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"✅ {result['file']}: {result['chunks']} chunks")
        con.close()
        return

    if args.stats:
        stats = get_stats(con)
        if args.json:
            print(json.dumps(stats, ensure_ascii=False, indent=2))
        else:
            print(f"🧠 Brain Search Index")
            print(f"   Vault: {stats['vault']}")
            print(f"   Arquivos: {stats['files']}")
            print(f"   Chunks: {stats['chunks']}")
            print(f"   Embeddings: {stats['embeddings']}")
            print(f"   Última indexação: {stats['last_indexed']}")
            print(f"   Por layer:")
            for layer, count in stats["layers"].items():
                print(f"     {layer}: {count}")
        con.close()
        return

    if args.list:
        rows = con.execute("SELECT relpath, layer, title, (SELECT COUNT(*) FROM chunks WHERE file_id=files.id) FROM files ORDER BY layer, relpath").fetchall()
        if args.json:
            print(json.dumps([{"path": r[0], "layer": r[1], "title": r[2], "chunks": r[3]} for r in rows], ensure_ascii=False, indent=2))
        else:
            for r in rows:
                print(f"  [{r[1] or '—':10s}] {r[0]} ({r[3]} chunks)")
        con.close()
        return

    if args.query:
        try:
            result = search_combined(
                con,
                args.query,
                limit=args.limit,
                vector=args.vector,
                allow_remote_embeddings=args.allow_remote_embeddings,
            )
        except EmbeddingEndpointError as e:
            con.close()
            print(f"Unsafe embedding endpoint: {e}", file=sys.stderr)
            sys.exit(2)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"🔍 \"{args.query}\" — {result['fts_count']} resultado(s) FTS")
            for r in result["fts_results"]:
                print(f"\n  📄 {r['title']}")
                print(f"     {r['path']}")
                print(f"     {r['layer'] or '—'} › {r['heading']}")
                snippet = r.get("snippet", r["content"][:120])
                print(f"     {snippet[:150]}")
            if "vector_results" in result:
                print(f"\n  🎯 +{len(result['vector_results'])} resultado(s) semânticos")
                for r in result["vector_results"]:
                    print(f"     [{r['similarity']:.2f}] {r['title']} › {r['heading']}")
        con.close()
        return

    # No action: show help
    parser.print_help()
    con.close()


if __name__ == "__main__":
    main()
