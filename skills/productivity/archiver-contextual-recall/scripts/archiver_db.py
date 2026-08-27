#!/usr/bin/env python3
"""Shared SQLite helpers for Archiver scripts."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import stat
from pathlib import Path
from typing import Literal
from urllib.parse import quote

def _env_path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, str(default))).expanduser()


def _default_archiver_home() -> Path:
    return _env_path("ARCHIVER_HOME", Path.home() / ".hermes" / "profiles" / "archiver")


def _default_vault() -> Path:
    return _env_path("ARCHIVER_VAULT", _default_archiver_home() / "archive-vault")


def _default_db() -> Path:
    return _env_path("ARCHIVER_DB", _default_vault() / "90-meta" / "archiver.sqlite3")


BASE = _default_archiver_home()
VAULT = _default_vault()
DB = _default_db()


def _canonical_private_path(path: Path | str) -> Path:
    """Normalize only macOS's standard temporary-directory aliases.

    ``resolve()`` must not be used for arbitrary input because it would follow an
    attacker-controlled symlink before descriptor-anchored traversal begins.
    """
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    for alias, canonical in ((Path("/var"), Path("/private/var")), (Path("/tmp"), Path("/private/tmp"))):
        try:
            remainder = candidate.relative_to(alias)
        except ValueError:
            continue
        try:
            if alias.is_symlink() and alias.resolve() == canonical:
                return canonical / remainder
        except OSError:
            pass
    return candidate


def _secure_open_flags() -> tuple[int, int]:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise ValueError("secure Archiver path traversal is unavailable on this platform")
    return os.O_RDONLY | nofollow, os.O_RDONLY | directory | nofollow


def _open_private_directory(path: Path | str, *, create: bool) -> tuple[Path, int]:
    """Open ``path`` without following any component and return its descriptor."""
    target = _canonical_private_path(path)
    if target == Path(target.anchor):
        raise ValueError("Archiver private directory must not be a filesystem root")
    file_flags, directory_flags = _secure_open_flags()
    del file_flags
    try:
        current_fd = os.open(target.anchor, directory_flags)
    except OSError as exc:
        raise ValueError(f"Archiver directory is not a real directory: {target}") from exc
    try:
        for component in target.parts[1:]:
            if component in {"", ".", ".."}:
                raise ValueError(f"Archiver directory contains an unsafe component: {target}")
            try:
                next_fd = os.open(component, directory_flags, dir_fd=current_fd)
            except FileNotFoundError as exc:
                if not create:
                    raise ValueError(f"Archiver directory is missing: {target}") from exc
                try:
                    os.mkdir(component, 0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
                try:
                    next_fd = os.open(component, directory_flags, dir_fd=current_fd)
                except OSError as open_exc:
                    raise ValueError(f"Archiver directory must not traverse a symlink: {target}") from open_exc
            except OSError as exc:
                raise ValueError(f"Archiver directory must not traverse a symlink: {target}") from exc
            os.close(current_fd)
            current_fd = next_fd

        directory_stat = os.fstat(current_fd)
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise ValueError(f"Archiver path is not a real directory: {target}")
        if directory_stat.st_uid != os.geteuid():
            raise ValueError(f"Archiver directory must be owned by the effective user: {target}")
        os.fchmod(current_fd, 0o700)
        return target, current_fd
    except Exception:
        os.close(current_fd)
        raise


def ensure_private_directory(path: Path) -> Path:
    """Create a real, owner-only directory without following a symlink chain."""
    target, directory_fd = _open_private_directory(path, create=True)
    os.close(directory_fd)
    return target


def write_private_text_exclusive(path: Path, content: str, *, encoding: str = "utf-8") -> Path:
    """Create owner-only text beneath a descriptor-anchored parent directory."""
    target = _canonical_private_path(path)
    if target.name in {"", ".", ".."}:
        raise ValueError(f"Archiver file name is unsafe: {target}")
    file_flags, _directory_flags = _secure_open_flags()
    parent_path, parent_fd = _open_private_directory(target.parent, create=True)
    try:
        fd = os.open(target.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | file_flags, 0o600, dir_fd=parent_fd)
        with os.fdopen(fd, "w", encoding=encoding) as stream:
            stream.write(content)
            stream.flush()
            os.fchmod(stream.fileno(), 0o600)
            os.fsync(stream.fileno())
    finally:
        os.close(parent_fd)
    return parent_path / target.name


def write_private_bytes_exclusive(path: Path, content: bytes) -> Path:
    """Create owner-only bytes beneath a descriptor-anchored parent directory."""
    target = _canonical_private_path(path)
    if target.name in {"", ".", ".."}:
        raise ValueError(f"Archiver file name is unsafe: {target}")
    file_flags, _directory_flags = _secure_open_flags()
    parent_path, parent_fd = _open_private_directory(target.parent, create=True)
    try:
        fd = os.open(target.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | file_flags, 0o600, dir_fd=parent_fd)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fchmod(stream.fileno(), 0o600)
            os.fsync(stream.fileno())
    finally:
        os.close(parent_fd)
    return parent_path / target.name


def read_vault_text(vault: Path, path: Path, *, errors: str = "ignore") -> str | None:
    """Read a real Markdown file contained by ``vault``; skip unsafe links."""
    try:
        relative = path.relative_to(vault)
        parts = relative.parts
        if not parts:
            return None
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        current_fd = os.open(vault.resolve(strict=True), flags)
    except (OSError, ValueError):
        return None
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        file_fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=current_fd)
        with os.fdopen(file_fd, "r", encoding="utf-8", errors=errors) as stream:
            return stream.read()
    except OSError:
        return None
    finally:
        os.close(current_fd)


def _restrict_sqlite_permissions_at(parent_fd: int, db_name: str) -> None:
    file_flags, _directory_flags = _secure_open_flags()
    for candidate_name in (db_name, f"{db_name}-journal", f"{db_name}-wal", f"{db_name}-shm"):
        try:
            fd = os.open(candidate_name, file_flags, dir_fd=parent_fd)
        except OSError:
            continue
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)


def restrict_sqlite_permissions(db: Path) -> None:
    """Keep a SQLite database and its sidecars owner-readable without path races."""
    target = _canonical_private_path(db)
    _parent_path, parent_fd = _open_private_directory(target.parent, create=True)
    try:
        _restrict_sqlite_permissions_at(parent_fd, target.name)
    finally:
        os.close(parent_fd)


class _PinnedArchiverConnection(sqlite3.Connection):
    """A connection that keeps SQLite's relative path rooted at an open directory."""

    def __init__(self, *args, **kwargs):
        self._archiver_parent_fd = kwargs.pop("archiver_parent_fd")
        self._archiver_restore_fd = kwargs.pop("archiver_restore_fd")
        self._archiver_db_name = kwargs.pop("archiver_db_name")
        super().__init__(*args, **kwargs)

    def _release_directory(self) -> None:
        if self._archiver_restore_fd is not None:
            try:
                os.fchdir(self._archiver_restore_fd)
            finally:
                os.close(self._archiver_restore_fd)
                self._archiver_restore_fd = None
        if self._archiver_parent_fd is not None:
            os.close(self._archiver_parent_fd)
            self._archiver_parent_fd = None

    def close(self) -> None:
        try:
            if self._archiver_parent_fd is not None:
                _restrict_sqlite_permissions_at(self._archiver_parent_fd, self._archiver_db_name)
            super().close()
        finally:
            try:
                if self._archiver_parent_fd is not None:
                    _restrict_sqlite_permissions_at(self._archiver_parent_fd, self._archiver_db_name)
            finally:
                self._release_directory()

    def __exit__(self, exc_type, exc_value, traceback) -> Literal[False]:
        try:
            super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()
        return False


def _connect_anchored(db: Path | str, *, readonly: bool) -> sqlite3.Connection:
    target = _canonical_private_path(db)
    if target.name in {"", ".", ".."}:
        raise ValueError(f"Archiver database name is unsafe: {target}")
    _parent_path, parent_fd = _open_private_directory(target.parent, create=not readonly)
    restore_fd: int | None = None
    try:
        try:
            leaf_stat = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            if readonly:
                raise sqlite3.OperationalError("Archiver database is missing")
        else:
            if not stat.S_ISREG(leaf_stat.st_mode):
                raise ValueError(f"Archiver database must be a regular file: {target}")
            if leaf_stat.st_uid != os.geteuid():
                raise ValueError(f"Archiver database must be owned by the effective user: {target}")

        _file_flags, directory_flags = _secure_open_flags()
        restore_flags = (os.O_RDONLY | directory_flags) & ~getattr(os, "O_NOFOLLOW", 0)
        restore_fd = os.open(".", restore_flags)
        os.fchdir(parent_fd)
        database_name = f"file:{quote(target.name, safe='')}?mode=ro" if readonly else target.name

        class PinnedConnection(_PinnedArchiverConnection):
            def __init__(self, *args, **kwargs):
                super().__init__(
                    *args,
                    archiver_parent_fd=parent_fd,
                    archiver_restore_fd=restore_fd,
                    archiver_db_name=target.name,
                    **kwargs,
                )

        connection = sqlite3.connect(
            database_name,
            uri=readonly,
            factory=PinnedConnection,
        )
        if not readonly:
            _restrict_sqlite_permissions_at(parent_fd, target.name)
        return connection
    except Exception:
        if restore_fd is not None:
            try:
                os.fchdir(restore_fd)
            finally:
                os.close(restore_fd)
        os.close(parent_fd)
        raise


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def table_columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()]


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    db = Path(db_path) if db_path is not None else DB
    return _connect_anchored(db, readonly=False)


def connect_readonly(db_path: Path | str | None = None) -> sqlite3.Connection:
    db = Path(db_path) if db_path is not None else DB
    return _connect_anchored(db, readonly=True)


def now_iso() -> str:
    return dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _ensure_core_tables(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            source TEXT,
            path TEXT NOT NULL UNIQUE,
            tags TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'inbox',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER,
            event_type TEXT NOT NULL,
            payload TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(item_id) REFERENCES items(id)
        );
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            title TEXT,
            context TEXT,
            position INTEGER,
            status TEXT NOT NULL DEFAULT 'captured',
            created_at TEXT NOT NULL,
            FOREIGN KEY(item_id) REFERENCES items(id)
        );
        """
    )


def _ensure_indexes(con: sqlite3.Connection) -> None:
    if table_exists(con, "items"):
        item_cols = {column.lower() for column in table_columns(con, "items")}
        if "created_at" in item_cols:
            con.execute("CREATE INDEX IF NOT EXISTS idx_items_created_at ON items(created_at)")
        if "status" in item_cols:
            con.execute("CREATE INDEX IF NOT EXISTS idx_items_status ON items(status)")

    if table_exists(con, "links"):
        link_cols = {column.lower() for column in table_columns(con, "links")}
        if "item_id" in link_cols:
            con.execute("CREATE INDEX IF NOT EXISTS idx_links_item_id ON links(item_id)")
        if "url" in link_cols:
            con.execute("CREATE INDEX IF NOT EXISTS idx_links_url ON links(url)")

    if table_exists(con, "link_contexts"):
        context_cols = {column.lower() for column in table_columns(con, "link_contexts")}
        if "link_id" in context_cols:
            con.execute("CREATE INDEX IF NOT EXISTS idx_link_contexts_link_id ON link_contexts(link_id)")


def _ensure_link_contexts(con: sqlite3.Connection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS link_contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link_id INTEGER NOT NULL UNIQUE,
            url TEXT NOT NULL,
            title TEXT,
            description TEXT,
            extracted_text TEXT,
            summary TEXT,
            keywords TEXT NOT NULL DEFAULT '[]',
            context_status TEXT NOT NULL DEFAULT 'pending',
            extractor TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(link_id) REFERENCES links(id)
        )
        """
    )


_LEGACY_LINK_CONTEXTS_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("url", "TEXT"),
    ("title", "TEXT"),
    ("description", "TEXT"),
    ("extracted_text", "TEXT"),
    ("summary", "TEXT"),
    ("keywords", "TEXT NOT NULL DEFAULT '[]'"),
    ("context_status", "TEXT NOT NULL DEFAULT 'pending'"),
    ("extractor", "TEXT"),
    ("error", "TEXT"),
    ("created_at", "TEXT"),
    ("updated_at", "TEXT"),
)


def _migrate_legacy_link_contexts(con: sqlite3.Connection) -> None:
    if not table_exists(con, "link_contexts"):
        return

    existing = {c.lower() for c in table_columns(con, "link_contexts")}
    missing_identity = sorted({"id", "link_id"} - existing)
    if missing_identity:
        missing_text = ", ".join(repr(column) for column in missing_identity)
        raise RuntimeError(
            f"Could not migrate link_contexts table: missing required column(s) {missing_text}. "
            "Recreate the table with current schema before rerunning this command."
        )

    duplicate = con.execute(
        """
        SELECT link_id, COUNT(*)
        FROM link_contexts
        WHERE link_id IS NOT NULL
        GROUP BY link_id
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    ).fetchone()
    if duplicate:
        raise RuntimeError(
            "Could not migrate link_contexts table: duplicate link_id values prevent safe UPSERT migration."
        )
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_link_contexts_link_id ON link_contexts(link_id)"
    )

    for column, definition in _LEGACY_LINK_CONTEXTS_MIGRATIONS:
        if column not in existing:
            con.execute(f"ALTER TABLE link_contexts ADD COLUMN {column} {definition}")

    now = now_iso()
    con.execute("UPDATE link_contexts SET context_status='pending' WHERE COALESCE(context_status, '') = ''")
    con.execute("UPDATE link_contexts SET keywords='[]' WHERE COALESCE(keywords, '') = ''")
    con.execute("UPDATE link_contexts SET created_at = ? WHERE created_at IS NULL OR created_at = ''", (now,))
    con.execute("UPDATE link_contexts SET updated_at = ? WHERE updated_at IS NULL OR updated_at = ''", (now,))

    if table_exists(con, "links"):
        link_columns = {c.lower() for c in table_columns(con, "links")}
        if "url" in link_columns and "id" in link_columns:
            con.execute(
                """
                UPDATE link_contexts
                SET url = (
                    SELECT links.url FROM links WHERE links.id = link_contexts.link_id
                )
                WHERE COALESCE(link_contexts.url, '') = ''
                  AND link_contexts.link_id IS NOT NULL
                  AND EXISTS (SELECT 1 FROM links WHERE links.id = link_contexts.link_id)
                """,
            )


def _has_fts5(con: sqlite3.Connection) -> bool:
    try:
        con.execute("CREATE VIRTUAL TABLE temp._fts5_probe USING fts5(x)").close()
        con.execute("DROP TABLE temp._fts5_probe").close()
        return True
    except sqlite3.OperationalError:
        return False


def _fts_table_exists(con: sqlite3.Connection) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='link_contexts_fts'",
    ).fetchone()
    return row is not None


def _trigger_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _trigger_sql(con: sqlite3.Connection, name: str) -> str:
    row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
        (name,),
    ).fetchone()
    return str(row[0] or "") if row else ""


def _ensure_fts_contexts(con: sqlite3.Connection) -> None:
    if not _has_fts5(con):
        return
    created = False
    if not _fts_table_exists(con):
        con.execute(
            """
            CREATE VIRTUAL TABLE link_contexts_fts USING fts5(
                url,
                title,
                description,
                summary,
                extracted_text,
                keywords,
                content='link_contexts',
                content_rowid='id'
            )
            """
        )
        created = True
    trigger_sql = _trigger_sql(con, "trg_link_contexts_au")
    triggers_need_refresh = created or "link_contexts_fts, rowid" not in trigger_sql
    if not triggers_need_refresh:
        return
    con.executescript(
        """
        DROP TRIGGER IF EXISTS trg_link_contexts_ai;
        DROP TRIGGER IF EXISTS trg_link_contexts_ad;
        DROP TRIGGER IF EXISTS trg_link_contexts_au;
        """
    )
    con.executescript(
        """
        CREATE TRIGGER IF NOT EXISTS trg_link_contexts_ai AFTER INSERT ON link_contexts
        BEGIN
            INSERT INTO link_contexts_fts(rowid, url, title, description, summary, extracted_text, keywords)
            VALUES (new.id, new.url, COALESCE(new.title, ''), COALESCE(new.description, ''),
                    COALESCE(new.summary, ''), COALESCE(new.extracted_text, ''), COALESCE(new.keywords, '[]'));
        END;

        CREATE TRIGGER IF NOT EXISTS trg_link_contexts_ad AFTER DELETE ON link_contexts
        BEGIN
            INSERT INTO link_contexts_fts(link_contexts_fts, rowid, url, title, description, summary, extracted_text, keywords)
            VALUES('delete', old.id, old.url, COALESCE(old.title, ''), COALESCE(old.description, ''),
                   COALESCE(old.summary, ''), COALESCE(old.extracted_text, ''), COALESCE(old.keywords, '[]'));
        END;

        CREATE TRIGGER IF NOT EXISTS trg_link_contexts_au AFTER UPDATE ON link_contexts
        BEGIN
            INSERT INTO link_contexts_fts(link_contexts_fts, rowid, url, title, description, summary, extracted_text, keywords)
            VALUES('delete', old.id, old.url, COALESCE(old.title, ''), COALESCE(old.description, ''),
                   COALESCE(old.summary, ''), COALESCE(old.extracted_text, ''), COALESCE(old.keywords, '[]'));
            INSERT INTO link_contexts_fts(rowid, url, title, description, summary, extracted_text, keywords)
            VALUES (new.id, new.url, COALESCE(new.title, ''), COALESCE(new.description, ''),
                    COALESCE(new.summary, ''), COALESCE(new.extracted_text, ''), COALESCE(new.keywords, '[]'));
        END;
        """
    )
    con.execute("INSERT INTO link_contexts_fts(link_contexts_fts) VALUES('rebuild')")


def ensure_schema(con: sqlite3.Connection) -> None:
    _ensure_core_tables(con)
    _ensure_link_contexts(con)
    _migrate_legacy_link_contexts(con)
    _ensure_indexes(con)
    _ensure_fts_contexts(con)
    con.commit()


def _normalize_keywords(keywords: list[str] | tuple[str, ...] | str | None) -> str:
    if keywords is None:
        return "[]"
    if isinstance(keywords, str):
        return keywords
    return json.dumps([str(k) for k in keywords], ensure_ascii=False)


def upsert_link_context(
    con: sqlite3.Connection,
    link_id: int,
    url: str,
    *,
    title: str | None = None,
    description: str | None = None,
    extracted_text: str | None = None,
    summary: str | None = None,
    keywords: list[str] | tuple[str, ...] | str | None = None,
    context_status: str = "pending",
    extractor: str | None = None,
    error: str | None = None,
    now: str | None = None,
) -> None:
    if not now:
        now = now_iso()
    con.execute(
        """
        INSERT INTO link_contexts(
            link_id, url, title, description, extracted_text, summary, keywords,
            context_status, extractor, error, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(link_id) DO UPDATE SET
            url = excluded.url,
            title = excluded.title,
            description = excluded.description,
            extracted_text = excluded.extracted_text,
            summary = excluded.summary,
            keywords = excluded.keywords,
            context_status = excluded.context_status,
            extractor = excluded.extractor,
            error = excluded.error,
            updated_at = excluded.updated_at
        """,
        (
            link_id,
            url,
            title,
            description,
            extracted_text,
            summary,
            _normalize_keywords(keywords),
            context_status,
            extractor,
            error,
            now,
            now,
        ),
    )


URL_RE = re.compile(r"https?://[^\s<>'\"`\]\[(){}]+")
MAX_ARCHIVE_BODY_BYTES = 64 * 1024
MAX_ARCHIVE_SOURCE_BYTES = 8 * 1024
MAX_ARCHIVE_URLS = 25


def collect_urls_and_context(text: str, source: str) -> list[tuple[str, str]]:
    if len(text.encode("utf-8")) > MAX_ARCHIVE_BODY_BYTES:
        raise ValueError(f"archive body byte limit is {MAX_ARCHIVE_BODY_BYTES}")
    if len(source.encode("utf-8")) > MAX_ARCHIVE_SOURCE_BYTES:
        raise ValueError(f"archive source byte limit is {MAX_ARCHIVE_SOURCE_BYTES}")

    def _normalize(url: str) -> str:
        return url.rstrip(").,;:!?>]}\"'`")

    def _extract_from_text(body: str) -> list[tuple[str, str]]:
        out = []
        for line in body.splitlines():
            for match in URL_RE.finditer(line):
                url = _normalize(match.group(0))
                if url:
                    out.append((url, line.strip()))
        return out

    def _dedupe(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for url, ctx in items:
            if url in seen:
                continue
            seen.add(url)
            out.append((url, ctx))
        return out

    source_urls = [(_normalize(match.group(0)), "source") for match in URL_RE.finditer(source)]
    out = _dedupe(_extract_from_text(text) + source_urls)
    if len(out) > MAX_ARCHIVE_URLS:
        raise ValueError(f"archive URL limit is {MAX_ARCHIVE_URLS}")
    return [(url, context) for url, context in out if url]
