#!/usr/bin/env python3
"""Generate bounded weekly Archiver operational reviews.

This script is intentionally read-only with respect to the archive DB and notes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlsplit, urlunsplit

SCHEMA_VERSION = "archive-weekly-review.v1"
INDEX_SCHEMA_VERSION = "archive-weekly-review.v1-index"
DEFAULT_DAYS = 30
DB_RELATIVE_PATH = Path("90-meta/archiver.sqlite3")
DEFAULT_OUTPUT_RELATIVE = Path("reports") / "archive-reviews"
MAX_EXAMPLE_COUNT = 8
INDEX_BACKUP_SUFFIX = ".corrupt"
ARCHIVER_VAULT_DEFAULT_REL = Path("archive-vault")


def _default_archiver_home() -> Path:
    return Path(os.environ.get("ARCHIVER_HOME", str(Path("~/.hermes/profiles/archiver").expanduser())))


def _default_archiver_vault() -> Path:
    return Path(
        os.environ.get("ARCHIVER_VAULT", str(_default_archiver_home() / ARCHIVER_VAULT_DEFAULT_REL))
    ).expanduser()


def _default_archiver_db(vault_root: Path) -> Path:
    return (vault_root / DB_RELATIVE_PATH).expanduser()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_netloc(parsed: Any) -> str:
    hostname = parsed.hostname
    if not hostname:
        return ""

    host = hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    try:
        port = parsed.port
    except ValueError:
        return ""
    if port:
        return f"{host}:{port}"
    return host


def _safe_urlsplit(value: str) -> Any:
    try:
        return urlsplit(value)
    except ValueError:
        return None


def _normalize_path(path: str) -> str:
    if not path:
        return ""
    normalized = path.rstrip("/")
    return normalized or "/"


def _strip_query_and_fragment(value: str) -> str:
    return value.split("#", 1)[0].split("?", 1)[0]


def normalize_url(value: Optional[str]) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""

    if "://" in text:
        parsed = _safe_urlsplit(text)
        if parsed and parsed.scheme and parsed.hostname:
            netloc = _normalize_netloc(parsed)
            if not netloc:
                return _strip_query_and_fragment(text)
            return urlunsplit((parsed.scheme.lower(), netloc, _normalize_path(parsed.path), "", ""))
        return _strip_query_and_fragment(text)

    if text.startswith("//"):
        parsed = _safe_urlsplit(text)
        if parsed and parsed.hostname:
            netloc = _normalize_netloc(parsed)
            if not netloc:
                return _strip_query_and_fragment(text)
            return f"{netloc}{_normalize_path(parsed.path)}"
        return _strip_query_and_fragment(text)

    # Raw schemeless URL-like values (example.com/path, user:pass@example/path).
    parsed = _safe_urlsplit(f"//{text}")
    if parsed and parsed.hostname:
        netloc = _normalize_netloc(parsed)
        if netloc:
            return f"{netloc}{_normalize_path(parsed.path)}"

    # Last resort fallback for non-URL values.
    return _strip_query_and_fragment(text)


def stable_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def write_file_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as tmp:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name
    os.chmod(tmp_name, 0o600)
    Path(tmp_name).replace(path)


def has_table(conn: sqlite3.Connection, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    )


def table_columns(conn: sqlite3.Connection, table: str) -> Dict[str, str]:
    return {row[1]: row[2] for row in conn.execute(f"PRAGMA table_info({table})")}


def select_first(columns: Iterable[str], *candidates: str) -> Optional[str]:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def run_subprocess(cmd: Sequence[str], env_var: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    env = os.environ.copy()
    if env_var:
        env.update(env_var)
    try:
        proc = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=20,
        )
    except FileNotFoundError as exc:
        return {
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc),
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": 124,
            "stdout": "",
            "stderr": "command timed out",
        }
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def compute_git_health(home: Path) -> Dict[str, Any]:
    if not home.exists():
        return {"status": "unavailable", "reason": "missing_home", "uncommitted": 0}

    rev_parse = run_subprocess(["git", "-C", str(home), "rev-parse", "--is-inside-work-tree"])
    if rev_parse["returncode"] != 0:
        return {"status": "unavailable", "reason": "not_a_git_repo", "uncommitted": 0}

    stat = run_subprocess(["git", "-C", str(home), "status", "--porcelain"])
    if stat["returncode"] != 0:
        return {"status": "unavailable", "reason": "git_status_error", "uncommitted": 0}

    entries = [line for line in (stat["stdout"] or "").splitlines() if line.strip()]
    return {
        "status": "dirty" if entries else "clean",
        "reason": "ok",
        "uncommitted": len(entries),
    }


def compute_kanban_health(board: str) -> Dict[str, Any]:
    env = {
        "HERMES_KANBAN_BOARD": board,
    }
    result = run_subprocess(
        ["hermes", "kanban", "list", "--archived", "--json"],
        env_var=env,
    )
    if result["returncode"] != 0:
        return {
            "status": "unavailable",
            "reason": f"hermes_exit_{result['returncode']}",
            "tasks": 0,
        }

    try:
        payload = json.loads(result["stdout"] or "{}")
    except json.JSONDecodeError:
        return {"status": "unavailable", "reason": "invalid_json", "tasks": 0}

    if isinstance(payload, dict):
        if isinstance(payload.get("tasks"), list):
            tasks = payload["tasks"]
        elif isinstance(payload.get("data"), list):
            tasks = payload["data"]
        else:
            return {"status": "unavailable", "reason": "missing_payload", "tasks": 0}
    elif isinstance(payload, list):
        tasks = payload
    else:
        return {"status": "unavailable", "reason": "bad_payload", "tasks": 0}

    status_counts = Counter()
    for task in tasks:
        if not isinstance(task, dict):
            continue
        status_counts[str(task.get("status") or "").lower()] += 1

    return {
        "status": "available",
        "board": board,
        "tasks": len(tasks),
        "status_counts": dict(status_counts),
    }


def parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def append_finding(
    findings: List[Dict[str, Any]],
    severity: str,
    fid: str,
    title: str,
    summary: str,
    details: Dict[str, Any],
    examples: List[Dict[str, Any]],
) -> None:
    findings.append(
        {
            "id": fid,
            "severity": severity,
            "title": title,
            "summary": summary,
            "details": details,
            "examples": examples[:MAX_EXAMPLE_COUNT],
        }
    )


def _to_int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text[:240]


def _path_under_root(root: Path, candidate: Path) -> bool:
    try:
        root_resolved = root.resolve()
        candidate_resolved = candidate.resolve()
        return candidate_resolved.is_relative_to(root_resolved)
    except AttributeError:
        root_str = os.path.normcase(str(root.resolve()))
        candidate_str = os.path.normcase(str(candidate.resolve()))
        return os.path.commonpath([candidate_str, root_str]) == root_str
    except (OSError, ValueError):
        # Resolve can fail on unreadable parts; use string-based fallback.
        root_str = os.path.normcase(str(root.absolute()))
        candidate_str = os.path.normcase(str(candidate.absolute()))
        return os.path.commonpath([candidate_str, root_str]) == root_str


def _normalize_note_path(vault_root: Path, raw: Any) -> tuple[bool, Path | None, str]:
    if raw is None:
        return False, None, ""
    text = str(raw).strip()
    if not text:
        return False, None, ""

    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = vault_root / candidate

    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate

    safe = _path_under_root(vault_root, resolved)
    return safe, resolved, str(resolved)


def collect_metrics(
    conn: sqlite3.Connection,
    archiver_home: Path,
    vault_root: Path,
    kanban_board: str,
    days: int,
) -> Dict[str, Any]:
    conn.row_factory = sqlite3.Row

    for required in ("items", "links", "link_contexts"):
        if not has_table(conn, required):
            raise RuntimeError(f"Missing required DB table: {required}")

    items_cols = table_columns(conn, "items")
    links_cols = table_columns(conn, "links")
    ctx_cols = table_columns(conn, "link_contexts")

    item_note_col = select_first(items_cols.keys(), "path", "note_path", "note_file")
    if item_note_col is None:
        raise RuntimeError("Could not resolve note-path column in items table")
    item_title_col = select_first(items_cols.keys(), "title")
    if "id" not in items_cols or "id" not in links_cols or "id" not in ctx_cols:
        raise RuntimeError("Required ID columns missing in archive tables")
    if "url" not in links_cols:
        raise RuntimeError("links table missing required 'url' column")
    if "item_id" not in links_cols:
        raise RuntimeError("links table missing required 'item_id' column")

    item_status_col = select_first(items_cols.keys(), "status", "state")
    created_item_col = select_first(items_cols.keys(), "created_at", "created")
    created_link_col = select_first(links_cols.keys(), "created_at", "created")
    context_status_col = select_first(ctx_cols.keys(), "context_status", "status", "state")
    context_link_key = select_first(ctx_cols.keys(), "link_id", "item_id")
    if context_link_key is None:
        raise RuntimeError("Could not resolve context FK in link_contexts (link_id/item_id).")

    integrity_rows = [row[0] for row in conn.execute("PRAGMA integrity_check")]
    integrity_ok = all(r == "ok" for r in integrity_rows)
    foreign_key_rows = conn.execute("PRAGMA foreign_key_check").fetchall()

    items_total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    links_total = conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    contexts_total = conn.execute("SELECT COUNT(*) FROM link_contexts").fetchone()[0]

    findings: List[Dict[str, Any]] = []

    def safe_lower(value: Any) -> str:
        return str(value or "").strip().lower()

    item_status_counts = Counter()
    context_status_counts = Counter()
    if item_status_col:
        for row in conn.execute(
            f"SELECT lower(trim({item_status_col})) AS status, COUNT(*) FROM items GROUP BY status"
        ):
            item_status_counts[safe_lower(row[0])] = int(row[1])
    if context_status_col:
        for row in conn.execute(
            f"SELECT lower(trim({context_status_col})), COUNT(*) FROM link_contexts GROUP BY 1"
        ):
            context_status_counts[safe_lower(row[0])] = int(row[1])

    # Critical integrity findings.
    if not integrity_ok:
        append_finding(
            findings,
            "critical",
            "critical.sqlite_integrity",
            "SQLite integrity check failed",
            "SQLite integrity check reported non-OK rows.",
            {"rows_checked": len(integrity_rows), "bad_rows": [r for r in integrity_rows if r != "ok"]},
            [],
        )

    if foreign_key_rows:
        foreign_examples = []
        for row in foreign_key_rows[:MAX_EXAMPLE_COUNT]:
            foreign_examples.append(
                {
                    "table": row["table"],
                    "rowid": _to_int_or_none(row["rowid"]),
                    "parent": row["parent"],
                    "fkid": _to_int_or_none(row["fkid"]),
                }
            )
        append_finding(
            findings,
            "critical",
            "critical.foreign_key_violations",
            "Foreign-key violations detected",
            "SQLite foreign key checks returned one or more violations.",
            {"count": len(foreign_key_rows)},
            foreign_examples,
        )

    # Critical: escaped note path, missing note path.
    title_expr = f"COALESCE({item_title_col}, '') AS title" if item_title_col else "'' AS title"
    missing_note_paths = 0
    escaped_note_paths = 0
    missing_note_examples: List[Dict[str, Any]] = []
    escaped_path_examples: List[Dict[str, Any]] = []
    for row in conn.execute(f"SELECT id, {item_note_col}, {title_expr} FROM items"):
        note_path_raw = row[item_note_col]
        safe, resolved_path, resolved_text = _normalize_note_path(vault_root, note_path_raw)

        exists = False
        if note_path_raw:
            if not safe:
                escaped_note_paths += 1
                if len(escaped_path_examples) < MAX_EXAMPLE_COUNT:
                    escaped_path_examples.append(
                        {
                            "item_id": int(row["id"]),
                            "note_path": str(note_path_raw),
                            "resolved_path": resolved_text,
                            "title": _safe_text(row["title"]),
                        }
                    )
                continue
            exists = bool(resolved_path and resolved_path.exists())

        if not exists:
            missing_note_paths += 1
            if len(missing_note_examples) < MAX_EXAMPLE_COUNT:
                missing_note_examples.append(
                    {
                        "item_id": int(row["id"]),
                        "note_path": str(note_path_raw or ""),
                        "resolved_path": resolved_text,
                        "title": _safe_text(row["title"]),
                    }
                )

    if escaped_note_paths:
        append_finding(
            findings,
            "critical",
            "critical.note_path_escape",
            "Item note path escapes vault root",
            "One or more archived note paths resolve outside the configured vault root.",
            {"count": escaped_note_paths},
            escaped_path_examples,
        )

    if missing_note_paths:
        append_finding(
            findings,
            "critical",
            "critical.missing_note_paths",
            "Missing note paths",
            "One or more items reference missing note files.",
            {"count": missing_note_paths},
            missing_note_examples,
        )

    # Orphan links.
    orphan_links: List[Dict[str, Any]] = []
    for row in conn.execute(
        """
        SELECT l.id AS link_id, l.item_id
        FROM links l
        LEFT JOIN items i ON i.id = l.item_id
        WHERE i.id IS NULL
        ORDER BY l.id
        """
    ):
        orphan_links.append({"link_id": int(row["link_id"]), "item_id": row["item_id"]})
    if orphan_links:
        append_finding(
            findings,
            "critical",
            "critical.orphan_links",
            "Orphan links",
            "Links reference a non-existent item.",
            {"count": len(orphan_links)},
            orphan_links,
        )

    # Orphan contexts.
    if context_link_key == "link_id":
        q_orphan_contexts = """
            SELECT lc.id AS context_id, lc.link_id
            FROM link_contexts lc
            LEFT JOIN links l ON l.id = lc.link_id
            WHERE lc.link_id IS NOT NULL AND l.id IS NULL
            ORDER BY lc.id
        """
    else:
        q_orphan_contexts = """
            SELECT lc.id AS context_id, lc.item_id
            FROM link_contexts lc
            LEFT JOIN items i ON i.id = lc.item_id
            WHERE lc.item_id IS NOT NULL AND i.id IS NULL
            ORDER BY lc.id
        """
    orphan_contexts = [
        {"context_id": int(r["context_id"]), "ref_id": r[context_link_key]}
        for r in conn.execute(q_orphan_contexts)
    ]
    if orphan_contexts:
        append_finding(
            findings,
            "critical",
            "critical.orphan_contexts",
            "Orphan contexts",
            "Context rows reference missing links/items.",
            {"count": len(orphan_contexts)},
            orphan_contexts,
        )

    # Links without contexts.
    if context_link_key == "link_id":
        q_missing_context = """
            SELECT l.id, l.item_id, l.url
            FROM links l
            LEFT JOIN link_contexts lc ON lc.link_id = l.id
            WHERE lc.id IS NULL
            ORDER BY l.id
        """
    else:
        q_missing_context = """
            SELECT l.id, l.item_id, l.url
            FROM links l
            LEFT JOIN link_contexts lc ON lc.item_id = l.item_id
            WHERE lc.id IS NULL
            ORDER BY l.id
        """
    missing_context_rows = list(conn.execute(q_missing_context))
    missing_context_examples = [
        {
            "link_id": int(r["id"]),
            "item_id": r["item_id"],
            "url": normalize_url(r["url"]),
        }
        for r in missing_context_rows[:MAX_EXAMPLE_COUNT]
    ]
    if missing_context_rows:
        append_finding(
            findings,
            "critical",
            "critical.missing_contexts",
            "Missing link contexts",
            "Some links have no context rows.",
            {"count": len(missing_context_rows)},
            missing_context_examples,
        )

    # Duplicate normalized URLs.
    normalized: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in conn.execute("SELECT id, item_id, url FROM links ORDER BY id"):
        norm = normalize_url(row["url"])
        if not norm:
            continue
        normalized[norm].append(
            {
                "link_id": int(row["id"]),
                "item_id": row["item_id"],
                "url": row["url"],
            }
        )
    duplicates = {k: v for k, v in normalized.items() if len(v) > 1}

    if duplicates:
        examples = []
        for norm, rows in list(duplicates.items())[:MAX_EXAMPLE_COUNT]:
            examples.append(
                {
                    "normalized_url": norm,
                    "count": len(rows),
                    "link_ids": [r["link_id"] for r in rows[:3]],
                    "item_ids": [r["item_id"] for r in rows[:3]],
                }
            )
        append_finding(
            findings,
            "attention",
            "attention.duplicate_urls",
            "Duplicate normalized URLs",
            "Multiple links normalize to the same URL.",
            {
                "groups": len(duplicates),
                "total": sum(len(v) for v in duplicates.values()),
            },
            examples,
        )

    # Failed/body_only contexts.
    failed_context_rows: List[Dict[str, Any]] = []
    body_only_context_rows: List[Dict[str, Any]] = []
    if context_status_col:
        q = f"SELECT id, {context_link_key}, {context_status_col} FROM link_contexts"
        for row in conn.execute(q):
            status = safe_lower(row[context_status_col])
            if not row[context_link_key]:
                continue
            if context_link_key == "link_id":
                link_id = int(row[context_link_key])
            else:
                link_ref = conn.execute(
                    "SELECT id FROM links WHERE item_id = ? LIMIT 1",
                    (row[context_link_key],),
                ).fetchone()
                link_id = int(link_ref[0]) if link_ref is not None else None

            if status not in {"failed", "body_only"}:
                continue

            url = conn.execute(
                "SELECT url FROM links WHERE id=?",
                (link_id,),
            ).fetchone()
            entry = {
                "context_id": int(row["id"]),
                "link_id": link_id,
                "context_status": status,
            }
            if url is not None:
                entry["url"] = normalize_url(url[0])
            if status == "failed":
                failed_context_rows.append(entry)
            else:
                body_only_context_rows.append(entry)

    if failed_context_rows:
        append_finding(
            findings,
            "attention",
            "attention.failed_contexts",
            "Failed extraction contexts",
            "Some contexts are marked as failed.",
            {"count": len(failed_context_rows)},
            failed_context_rows,
        )

    if body_only_context_rows:
        append_finding(
            findings,
            "attention",
            "attention.body_only_contexts",
            "Body-only contexts",
            "Some links were only captured from message body.",
            {"count": len(body_only_context_rows)},
            body_only_context_rows,
        )

    # Recent + inbox window counts.
    now = _utcnow()
    window_start = now - timedelta(days=days)

    recent_items = 0
    recent_items_unparseable = 0
    if created_item_col:
        for row in conn.execute(f"SELECT {created_item_col} FROM items"):
            dt = parse_datetime(row[created_item_col])
            if dt is None:
                recent_items_unparseable += 1
                continue
            if dt >= window_start:
                recent_items += 1

    recent_links = 0
    recent_links_unparseable = 0
    if created_link_col:
        for row in conn.execute(f"SELECT {created_link_col} FROM links"):
            dt = parse_datetime(row[created_link_col])
            if dt is None:
                recent_links_unparseable += 1
                continue
            if dt >= window_start:
                recent_links += 1

    inbox_total = 0
    inbox_recent = 0
    if item_status_col:
        inbox_query = (
            f"SELECT {item_status_col}, COALESCE({created_item_col}, '') FROM items"
            if created_item_col
            else f"SELECT {item_status_col}, '' FROM items"
        )
        for row in conn.execute(inbox_query):
            status = safe_lower(row[0])
            if status != "inbox":
                continue
            inbox_total += 1
            if created_item_col:
                dt = parse_datetime(row[1])
                if dt is not None and dt >= window_start:
                    inbox_recent += 1

    # Markdown notes count.
    markdown_notes = 0
    if vault_root.exists():
        for path in vault_root.rglob("*.md"):
            if "90-meta" in path.parts:
                continue
            if path.is_file():
                markdown_notes += 1

    git = compute_git_health(archiver_home)
    kanban = compute_kanban_health(kanban_board)

    if git.get("status") == "dirty":
        append_finding(
            findings,
            "attention",
            "attention.dirty_git",
            "Dirty git worktree",
            "Archiver profile contains uncommitted changes.",
            {"uncommitted": git.get("uncommitted", 0)},
            [],
        )

    if inbox_recent:
        append_finding(
            findings,
            "attention",
            "attention.inbox_backlog",
            "Inbox backlog in review window",
            "Items are queued in inbox within the review window.",
            {"recent": inbox_recent, "total": inbox_total},
            [],
        )

    if kanban.get("status") == "unavailable":
        append_finding(
            findings,
            "info",
            "info.kanban_unavailable",
            "Kanban unavailable",
            "Kanban checks are currently unavailable.",
            {"reason": kanban.get("reason", "unavailable")},
            [],
        )

    return {
        "integrity_ok": integrity_ok,
        "integrity_rows": integrity_rows,
        "foreign_key_failures": len(foreign_key_rows),
        "items_total": items_total,
        "links_total": links_total,
        "contexts_total": contexts_total,
        "item_status_counts": dict(item_status_counts),
        "context_status_counts": dict(context_status_counts),
        "missing_note_paths": missing_note_paths,
        "escaped_note_paths": escaped_note_paths,
        "missing_note_examples": missing_note_examples,
        "orphan_links": orphan_links,
        "orphan_contexts": orphan_contexts,
        "missing_contexts": missing_context_examples,
        "duplicate_groups": duplicates,
        "failed_contexts": failed_context_rows,
        "body_only_contexts": body_only_context_rows,
        "recent_items": {
            "window_days": days,
            "window_start": window_start.isoformat(),
            "count": recent_items,
            "unparseable": recent_items_unparseable,
        },
        "recent_links": {
            "window_days": days,
            "count": recent_links,
            "unparseable": recent_links_unparseable,
        },
        "inbox": {
            "window_days": days,
            "recent": inbox_recent,
            "total": inbox_total,
        },
        "markdown_notes": markdown_notes,
        "findings": findings,
        "git": git,
        "kanban": kanban,
    }


def decide_status(metrics: Dict[str, Any]) -> str:
    has_critical = any(item["severity"] == "critical" for item in metrics["findings"])
    has_attention = any(item["severity"] == "attention" for item in metrics["findings"])

    if has_critical:
        return "critical"
    if has_attention:
        return "attention"
    return "healthy"


def build_summary(status: str, metrics: Dict[str, Any]) -> str:
    if status == "critical":
        return (
            "Critical review state: integrity or relation checks failed. "
            "Fix data correctness before continuing operations."
        )
    if status == "attention":
        return (
            "Review passed with warnings. Archive is usable, but requires attention "
            "for extraction or backlog/hygiene issues."
        )
    return "Review passed with healthy relational and extraction signals."


def findings_markdown(findings: Sequence[Dict[str, Any]]) -> str:
    if not findings:
        return "- No findings."
    lines = []
    for item in findings:
        lines.append(f"- [{item['severity'].upper()}] {item['title']} ({item['id']})")
        lines.append(f"  - {item['summary']}")
        for key, value in item["details"].items():
            lines.append(f"  - {key}: {value}")
        if item["examples"]:
            lines.append("  - examples:")
            for example in item["examples"]:
                lines.append(f"    - {json.dumps(example, ensure_ascii=False, sort_keys=True)}")
    return "\n".join(lines)


def render_markdown(payload: Dict[str, Any]) -> str:
    template = Path(__file__).resolve().parent / "../templates" / "archive-weekly-review.md"
    text = template.resolve().read_text(encoding="utf-8")
    metrics = payload["metrics"]
    replacements = {
        "{{schema}}": payload["schema"],
        "{{date}}": payload["date"],
        "{{generated_at}}": payload["generated_at"],
        "{{status}}": payload["status"],
        "{{summary}}": payload["summary"],
        "{{items_total}}": str(metrics["items_total"]),
        "{{links_total}}": str(metrics["links_total"]),
        "{{contexts_total}}": str(metrics["link_contexts_total"]),
        "{{missing_note_paths}}": str(metrics["missing_note_paths"]),
        "{{orphan_links}}": str(metrics["orphan_links"]),
        "{{orphan_contexts}}": str(metrics["orphan_contexts"]),
        "{{missing_contexts}}": str(metrics["missing_contexts"]),
        "{{duplicate_url_groups}}": str(metrics["duplicate_urls"]),
        "{{failed_contexts}}": str(metrics["failed_contexts"]),
        "{{body_only_contexts}}": str(metrics["body_only_contexts"]),
        "{{recent_items}}": str(metrics["recent"]["items"]),
        "{{recent_links}}": str(metrics["recent"]["links"]),
        "{{inbox_backlog}}": str(metrics["inbox"]["recent"]),
        "{{markdown_notes}}": str(metrics["markdown_notes"]),
        "{{git_status}}": metrics["git"].get("status", "unavailable"),
        "{{kanban_status}}": metrics["kanban"].get("status", "unavailable"),
        "{{findings_markdown}}": findings_markdown(payload["findings"]),
        "{{window_days}}": str(payload["scope"]["days"]),
        "{{archiver_home}}": payload["scope"]["archiver_home"],
        "{{db_path}}": payload["scope"]["db_path"],
    }
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text


def _validate_index_payload(payload: Dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("index payload is not an object")
    if payload.get("schema") != INDEX_SCHEMA_VERSION:
        raise ValueError("index schema mismatch")
    reviews = payload.get("reviews", {})
    if not isinstance(reviews, dict):
        raise ValueError("index.reviews must be an object")
    for date, item in reviews.items():
        if not isinstance(item, dict):
            raise ValueError(f"index entry {date} must be an object")
        json_entry = item.get("json")
        md_entry = item.get("markdown")
        for key, name in ((json_entry, "json"), (md_entry, "markdown")):
            if not isinstance(key, dict):
                raise ValueError(f"index entry {date} missing {name}")
            for field in ("path", "size_bytes", "sha256"):
                if field not in key:
                    raise ValueError(f"index entry {date} missing {name}.{field}")
            if not isinstance(key.get("path"), str):
                raise ValueError(f"index entry {date} {name}.path must be str")
            if not isinstance(key.get("size_bytes"), int):
                raise ValueError(f"index entry {date} {name}.size_bytes must be int")
            if not isinstance(key.get("sha256"), str):
                raise ValueError(f"index entry {date} {name}.sha256 must be str")


def load_index(path: Path, *, recover: bool = False) -> Dict[str, Any]:
    if not path.exists():
        return {
            "schema": INDEX_SCHEMA_VERSION,
            "generated_at": "",
            "latest_date": "",
            "reviews": {},
        }

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        if recover:
            backup_path = path.with_suffix(path.suffix + INDEX_BACKUP_SUFFIX)
            path.replace(backup_path)
            os.chmod(backup_path, 0o600)
            return {
                "schema": INDEX_SCHEMA_VERSION,
                "generated_at": "",
                "latest_date": "",
                "reviews": {},
            }
        raise RuntimeError(f"Malformed index JSON at {path}: {exc}") from exc

    try:
        _validate_index_payload(data)
    except ValueError as exc:
        if recover:
            backup_path = path.with_suffix(path.suffix + INDEX_BACKUP_SUFFIX)
            path.replace(backup_path)
            os.chmod(backup_path, 0o600)
            return {
                "schema": INDEX_SCHEMA_VERSION,
                "generated_at": "",
                "latest_date": "",
                "reviews": {},
            }
        raise RuntimeError(f"Invalid index schema at {path}: {exc}") from exc

    if "reviews" not in data or not isinstance(data["reviews"], dict):
        data["reviews"] = {}
    data.setdefault("schema", INDEX_SCHEMA_VERSION)
    return data


def update_index(path: Path, payload: Dict[str, Any], artifacts: Dict[str, Any]) -> Dict[str, Any]:
    index = load_index(path, recover=False)
    index["schema"] = INDEX_SCHEMA_VERSION
    index["generated_at"] = payload["generated_at"]
    index["latest_date"] = payload["date"]
    index.setdefault("reviews", {})[payload["date"]] = {
        "status": payload["status"],
        "summary": payload["summary"],
        "json": {
            "path": artifacts["json"]["path"],
            "size_bytes": artifacts["json"]["size_bytes"],
            "sha256": artifacts["json"]["sha256"],
        },
        "markdown": {
            "path": artifacts["markdown"]["path"],
            "size_bytes": artifacts["markdown"]["size_bytes"],
            "sha256": artifacts["markdown"]["sha256"],
        },
        "generated_at": payload["generated_at"],
    }
    return index


def gather_payload(
    archiver_home: Path,
    db_path: Path,
    vault_root: Path,
    output_dir: Path,
    days: int,
    kanban_board: str,
    no_write: bool,
    recover_index: bool,
) -> Dict[str, Any]:
    db_path = db_path.expanduser()
    if not db_path.is_absolute():
        db_path = (archiver_home / db_path).resolve()
    if not db_path.exists():
        raise RuntimeError(f"Archive DB missing at {db_path}")

    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            metrics = collect_metrics(
                conn,
                archiver_home=archiver_home,
                vault_root=vault_root,
                kanban_board=kanban_board,
                days=days,
            )
    except sqlite3.OperationalError as exc:
        raise RuntimeError(f"Cannot open archive DB: {exc}")

    now = _utcnow()
    date_str = now.date().isoformat()
    generated_at = now.isoformat(timespec="seconds")

    artifact_paths = {
        "json": {"path": f"{date_str}.json"},
        "markdown": {"path": f"{date_str}.md"},
        "latest_json": {"path": "latest.json"},
        "latest_markdown": {"path": "latest.md"},
        "index": {"path": "index.json"},
    }

    payload: Dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "generated_at": generated_at,
        "date": date_str,
        "scope": {
            "archiver_home": str(archiver_home),
            "db_path": str(db_path),
            "output_dir": str(output_dir),
            "days": days,
            "window_start": metrics["recent_items"]["window_start"],
            "kanban_board": kanban_board,
        },
        "metrics": {
            "items_total": metrics["items_total"],
            "links_total": metrics["links_total"],
            "link_contexts_total": metrics["contexts_total"],
            "item_status_counts": metrics["item_status_counts"],
            "context_status_counts": metrics["context_status_counts"],
            "missing_note_paths": metrics["missing_note_paths"],
            "orphan_links": len(metrics["orphan_links"]),
            "orphan_contexts": len(metrics["orphan_contexts"]),
            "missing_contexts": len(metrics["missing_contexts"]),
            "duplicate_urls": len(metrics["duplicate_groups"]),
            "failed_contexts": len(metrics["failed_contexts"]),
            "body_only_contexts": len(metrics["body_only_contexts"]),
            "recent": {
                "items": metrics["recent_items"]["count"],
                "links": metrics["recent_links"]["count"],
                "unparseable_items": metrics["recent_items"]["unparseable"],
                "unparseable_links": metrics["recent_links"]["unparseable"],
                "window_days": days,
            },
            "inbox": metrics["inbox"],
            "markdown_notes": metrics["markdown_notes"],
            "db_integrity": {
                "ok": metrics["integrity_ok"],
                "rows_checked": len(metrics["integrity_rows"]),
                "foreign_key_failures": metrics["foreign_key_failures"],
            },
            "git": metrics["git"],
            "kanban": metrics["kanban"],
        },
        "findings": metrics["findings"],
        "artifacts": artifact_paths,
    }
    payload["status"] = decide_status(metrics)
    payload["summary"] = build_summary(payload["status"], metrics)
    payload["metrics"]["artifacts"] = artifact_paths

    if no_write:
        return payload

    index_path = output_dir / "index.json"
    index = load_index(index_path, recover=recover_index)
    json_path = output_dir / f"{date_str}.json"
    md_path = output_dir / f"{date_str}.md"
    latest_json_path = output_dir / "latest.json"
    latest_md_path = output_dir / "latest.md"

    json_text = stable_json(payload)
    md_text = render_markdown(payload)

    write_file_atomic(json_path, json_text.encode("utf-8"))
    write_file_atomic(md_path, md_text.encode("utf-8"))
    write_file_atomic(latest_json_path, json_text.encode("utf-8"))
    write_file_atomic(latest_md_path, md_text.encode("utf-8"))

    json_sha = sha256_hex(json_text.encode("utf-8"))
    md_sha = sha256_hex(md_text.encode("utf-8"))
    index = update_index(
        index_path,
        payload,
        {
            "json": {
                "path": f"{date_str}.json",
                "size_bytes": len(json_text.encode("utf-8")),
                "sha256": json_sha,
            },
            "markdown": {
                "path": f"{date_str}.md",
                "size_bytes": len(md_text.encode("utf-8")),
                "sha256": md_sha,
            },
        },
    )
    index_text = stable_json(index)
    write_file_atomic(index_path, index_text.encode("utf-8"))

    return payload


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate Archiver weekly review artifacts.")
    p.add_argument(
        "--archiver-home",
        default=None,
        help="Archiver profile root directory (default: $ARCHIVER_HOME or ~/.hermes/profiles/archiver).",
    )
    p.add_argument(
        "--archiver-vault",
        default=None,
        help="Root directory for archive-vault (default: $ARCHIVER_VAULT or <archiver_home>/archive-vault).",
    )
    p.add_argument(
        "--archiver-db",
        default=None,
        help="Path to archiver.sqlite3 (default derived from --archiver-vault or ARCHIVER_VAULT/ARCHIVER_DB).",
    )
    p.add_argument(
        "--output-dir",
        default="",
        help="Directory for review artifacts (default: <archiver_home>/reports/archive-reviews).",
    )
    p.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Review window in days.")
    p.add_argument("--kanban-board", default=os.environ.get("ARCHIVER_KANBAN_BOARD", "archive"), help="Kanban board for reconciliation checks.")
    p.add_argument("--recover-index", action="store_true", help="Recover from malformed index.json by backing it up and regenerating history.")
    p.add_argument("--json", action="store_true", help="Print JSON payload to stdout.")
    p.add_argument("--no-write", action="store_true", help="Run in inspection mode without writing files.")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.days <= 0:
        print("ERROR: --days must be greater than 0.", file=sys.stderr)
        return 2

    explicit_home = args.archiver_home is not None
    archiver_home = (
        Path(args.archiver_home).expanduser()
        if explicit_home
        else _default_archiver_home().expanduser()
    )
    if args.archiver_vault is not None:
        vault_root = Path(args.archiver_vault).expanduser()
    elif explicit_home:
        vault_root = archiver_home / ARCHIVER_VAULT_DEFAULT_REL
    else:
        vault_root = Path(
            os.environ.get(
                "ARCHIVER_VAULT",
                str(archiver_home / ARCHIVER_VAULT_DEFAULT_REL),
            )
        ).expanduser()

    if args.archiver_db is not None:
        archiver_db = args.archiver_db
    elif args.archiver_vault is not None or explicit_home:
        archiver_db = str(_default_archiver_db(vault_root))
    else:
        env_db = os.environ.get("ARCHIVER_DB", "")
        archiver_db = env_db if env_db else str(_default_archiver_db(vault_root))
    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser()
    else:
        output_dir = archiver_home / DEFAULT_OUTPUT_RELATIVE
    archiver_db = Path(archiver_db).expanduser()

    try:
        payload = gather_payload(
            archiver_home=archiver_home,
            db_path=archiver_db,
            vault_root=vault_root,
            output_dir=output_dir,
            days=args.days,
            kanban_board=args.kanban_board,
            no_write=args.no_write,
            recover_index=args.recover_index,
        )
    except (RuntimeError, ValueError, sqlite3.OperationalError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(stable_json(payload), end="")
        return 0

    status = payload["status"]
    critical_count = len([f for f in payload["findings"] if f["severity"] == "critical"])
    attention_count = len([f for f in payload["findings"] if f["severity"] == "attention"])
    summary_line = (
        f"[{status.upper()}] Weekly review {payload['date']} | "
        f"items={payload['metrics']['items_total']} links={payload['metrics']['links_total']} "
        f"critical={critical_count} attention={attention_count}"
    )
    if not args.no_write:
        summary_line += f" | report={output_dir / 'latest.md'}"
    print(summary_line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
