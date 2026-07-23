#!/usr/bin/env python3
"""Populate link_contexts for existing archive notes and links."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sqlite3
from pathlib import Path

from archiver_db import DB, VAULT, connect, connect_readonly, ensure_schema, table_columns, table_exists, upsert_link_context
from archiver_extract_context import extract_url_context

SKIP_PREFIXES = {"90-meta", "attachments"}


def now_iso() -> str:
    return dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def parse_frontmatter(raw: str) -> tuple[dict[str, object], str]:
    data: dict[str, object] = {
        "title": "",
        "source": "",
        "status": "",
        "tags": [],
        "created": "",
    }
    if not raw.startswith("---\n"):
        return data, raw

    lines = raw.splitlines()
    try:
        end = lines[1:].index("---")
    except ValueError:
        return data, "\n".join(lines)

    for line in lines[1 : end + 1]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        if key == "tags":
            if value.startswith("[") and value.endswith("]"):
                inner = value[1:-1].strip()
                data[key] = [item.strip().strip('"').strip("'") for item in inner.split(",") if item.strip()]
            else:
                data[key] = []
            continue
        data[key] = value

    body = "\n".join(lines[end + 2 :])
    return data, body


def item_created_from_meta(meta: dict[str, object]) -> str:
    created = str(meta.get("created", "")).strip()
    if created:
        return created
    return now_iso()


def item_title_from_meta(path: Path, meta: dict[str, object]) -> str:
    title = str(meta.get("title", "")).strip()
    if title:
        return title
    return path.stem


def collect_links_from_text(text: str, source: str) -> list[tuple[str, str]]:
    # Reuse conservative detection from archive_item's DB helper.
    from archiver_db import collect_urls_and_context

    return collect_urls_and_context(text, source)


def merge_summaries(base: str | None, addition: str | None) -> str:
    base = (base or "").strip()
    addition = (addition or "").strip()
    if not addition or addition == base:
        return base
    if not base:
        return addition[:1500]
    return f"{base}\n{addition}"[:1500]


def iter_notes(vault: Path):
    for md_path in vault.rglob("*.md"):
        rel_parts = md_path.relative_to(vault).parts
        if rel_parts and rel_parts[0] in SKIP_PREFIXES:
            continue
        raw = md_path.read_text(encoding="utf-8", errors="ignore")
        meta, body = parse_frontmatter(raw)
        rel_path = str(md_path.relative_to(vault))
        source = str(meta.get("source", "") or "")
        links = collect_links_from_text(body or "", source)
        yield rel_path, meta, links


def add_backup(path: Path) -> str | None:
    if not path.exists():
        return None
    stamp = dt.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.pre-context-{stamp}.bak")
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup)
    return str(backup)


def ensure_item(con, vault: Path, rel_path: str, meta: dict[str, object], created: str) -> tuple[int, bool]:
    row = con.execute("SELECT id FROM items WHERE path = ?", (rel_path,)).fetchone()
    if row:
        return row[0], False

    con.execute(
        """
        INSERT INTO items(title, source, path, tags, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_title_from_meta(vault / rel_path, meta),
            str(meta.get("source", "")),
            rel_path,
            json.dumps(meta.get("tags", []), ensure_ascii=False),
            str(meta.get("status", "inbox") or "inbox"),
            created,
            now_iso(),
        ),
    )
    return con.execute("SELECT id FROM items WHERE path = ?", (rel_path,)).fetchone()[0], True


def ensure_link(
    con,
    item_id: int,
    url: str,
    context: str,
    now: str,
    position: int,
    status: str,
) -> tuple[int, bool]:
    row = con.execute("SELECT id FROM links WHERE item_id = ? AND url = ?", (item_id, url)).fetchone()
    if row:
        return row[0], False

    con.execute(
        """
        INSERT INTO links(item_id, url, title, context, position, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (item_id, url, None, context, position, status, now),
    )
    link_id = con.execute("SELECT id FROM links WHERE item_id = ? AND url = ?", (item_id, url)).fetchone()[0]
    return link_id, True


def extract_existing_contexts(con, *, dry_run: bool, force: bool) -> dict[str, int]:
    link_cols = {column.lower() for column in table_columns(con, "links")} if table_exists(con, "links") else set()
    has_links = {"id", "url", "context"}.issubset(link_cols)
    if not has_links:
        return {
            "extract_candidates": 0,
            "extracted_contexts": 0,
            "failed_contexts": 0,
            "body_only_contexts": 0,
        }

    context_cols = {column.lower() for column in table_columns(con, "link_contexts")} if table_exists(con, "link_contexts") else set()
    has_context = {"link_id"}.issubset(context_cols)

    select_fields = [
        "l.id AS link_id",
        "l.url AS link_url",
        "COALESCE(l.context, '') AS link_context",
    ]
    if has_context:
        select_fields.extend(
            [
                "lc.id AS context_id",
                "COALESCE(lc.title, '') AS existing_title",
                "COALESCE(lc.description, '') AS existing_description",
                "COALESCE(lc.summary, '') AS existing_summary",
                "COALESCE(lc.extracted_text, '') AS existing_text",
                "COALESCE(lc.keywords, '[]') AS existing_keywords",
                "COALESCE(lc.context_status, '') AS existing_context_status",
                "lc.extractor AS existing_extractor",
                "lc.error AS existing_error",
            ]
        )
        join_sql = "LEFT JOIN link_contexts lc ON lc.link_id = l.id"
        where_sql = ""
        if not force:
            where_sql = "WHERE lc.id IS NULL OR COALESCE(lc.context_status, '') IN ('pending', 'body_only', 'failed')"
    else:
        select_fields.extend(
            [
                "NULL AS context_id",
                "'' AS existing_title",
                "'' AS existing_description",
                "'' AS existing_summary",
                "'' AS existing_text",
                "'[]' AS existing_keywords",
                "'' AS existing_context_status",
                "NULL AS existing_extractor",
                "NULL AS existing_error",
            ]
        )
        join_sql = ""
        where_sql = ""

    previous_factory = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            f"""
            SELECT
              {", ".join(select_fields)}
            FROM links l
            {join_sql}
            {where_sql}
            ORDER BY l.id
            """
        ).fetchall()
    finally:
        con.row_factory = previous_factory

    stats = {
        "extract_candidates": len(rows),
        "extracted_contexts": 0,
        "failed_contexts": 0,
        "body_only_contexts": 0,
    }
    if dry_run:
        return stats

    for row in rows:
        link_id = row["link_id"]
        url = row["link_url"]
        link_context = row["link_context"]
        existing_title = row["existing_title"]
        existing_description = row["existing_description"]
        existing_summary = row["existing_summary"]
        existing_text = row["existing_text"]
        existing_keywords = row["existing_keywords"]
        existing_extractor = row["existing_extractor"]

        base_description = existing_description or link_context or "Contexto da mensagem"
        base_summary = existing_summary or link_context or url
        title = existing_title or None
        description = base_description
        extracted_text = existing_text
        summary = base_summary
        keywords: list[str] | str = existing_keywords
        context_status = "body_only"
        extractor = existing_extractor
        error = None

        try:
            result = extract_url_context(url, timeout=5)
            extractor = result.get("extractor") if isinstance(result.get("extractor"), str) else extractor
            error = result.get("error") if isinstance(result.get("error"), str) else None
            status = str(result.get("context_status", "failed"))
            if isinstance(result.get("title"), str):
                title = result["title"]
            if isinstance(result.get("description"), str):
                description = result["description"]
            if isinstance(result.get("extracted_text"), str):
                extracted_text = result["extracted_text"]
            if isinstance(result.get("keywords"), list):
                keywords = result["keywords"]

            if status == "extracted":
                context_status = "extracted"
                summary = merge_summaries(
                    base_summary,
                    result.get("summary") if isinstance(result.get("summary"), str) else None,
                )
                stats["extracted_contexts"] += 1
            elif status == "unsupported_content_type":
                context_status = "body_only"
                stats["body_only_contexts"] += 1
            else:
                context_status = "failed"
                stats["failed_contexts"] += 1
        except Exception as exc:  # pragma: no cover - defensive fallback
            context_status = "failed"
            extractor = "urllib.request"
            error = str(exc)
            stats["failed_contexts"] += 1

        upsert_link_context(
            con,
            link_id,
            url,
            title=title,
            description=description,
            extracted_text=extracted_text,
            summary=summary,
            keywords=keywords,
            context_status=context_status,
            extractor=extractor,
            error=error,
            now=now_iso(),
        )

    return stats


def estimate_backfill_counts(vault: Path) -> tuple[int, int, int]:
    if not DB.exists():
        return _estimate_from_markdown(vault)

    con = None
    try:
        con = connect_readonly(DB)
    except sqlite3.OperationalError:
        return _estimate_from_markdown(vault)

    try:
        has_items = table_exists(con, "items")
        item_cols = {column.lower() for column in table_columns(con, "items")} if has_items else set()
        has_links = table_exists(con, "links")
        link_cols = {column.lower() for column in table_columns(con, "links")} if has_links else set()
        has_contexts = table_exists(con, "link_contexts")
        context_cols = {column.lower() for column in table_columns(con, "link_contexts")} if has_contexts else set()

        has_items_path = has_items and "path" in item_cols
        has_items_id = has_items and "id" in item_cols
        has_links_query = has_links and {"item_id", "url", "id"}.issubset(link_cols)
        has_context_query = has_contexts and {"link_id", "id"}.issubset(context_cols)

        item_ids_by_path: dict[str, int] = {}
        if has_items and has_items_path and has_items_id:
            item_ids_by_path = {
                str(path): int(item_id)
                for path, item_id in con.execute("SELECT path, id FROM items WHERE path IS NOT NULL").fetchall()
            }

        added_items = 0
        added_links = 0
        added_contexts = 0
        for rel_path, _meta, links in iter_notes(vault):
            item_id = item_ids_by_path.get(rel_path) if has_items_path else None
            if (not has_items) or (not has_items_path) or item_id is None:
                added_items += 1

            for url, _context in links:
                if has_links_query and item_id is not None:
                    row = con.execute(
                        "SELECT id FROM links WHERE item_id = ? AND url = ?",
                        (item_id, url),
                    ).fetchone()
                else:
                    row = None

                if row is None:
                    added_links += 1
                    added_contexts += 1
                elif has_context_query:
                    context_row = con.execute("SELECT 1 FROM link_contexts WHERE link_id = ?", (row[0],)).fetchone()
                    if context_row is None:
                        added_contexts += 1
        return added_items, added_links, added_contexts
    finally:
        if con is not None:
            con.close()


def _estimate_from_markdown(vault: Path) -> tuple[int, int, int]:
    item_count = 0
    link_count = 0
    for _rel_path, _meta, links in iter_notes(vault):
        item_count += 1
        link_count += len(links)
    return item_count, link_count, link_count


def run_backfill(dry_run: bool, extract_existing: bool = False, force: bool = False) -> dict[str, object]:
    added_items = 0
    added_links = 0
    added_contexts = 0
    extraction_stats = {
        "extract_candidates": 0,
        "extracted_contexts": 0,
        "failed_contexts": 0,
        "body_only_contexts": 0,
    }
    backup_path: str | None = None

    if not VAULT.exists():
        return {
            "added_items": added_items,
            "added_links": added_links,
            "added_contexts": added_contexts,
            **extraction_stats,
            "backup_path": backup_path,
            "dry_run": dry_run,
            "extract_existing": extract_existing,
            "force": force,
        }

    if dry_run:
        added_items, added_links, added_contexts = estimate_backfill_counts(VAULT)
        con = None
        if DB.exists():
            try:
                con = connect_readonly(DB)
                extraction_stats = extract_existing_contexts(con, dry_run=True, force=force)
            except sqlite3.OperationalError:
                extraction_stats = {
                    "extract_candidates": 0,
                    "extracted_contexts": 0,
                    "failed_contexts": 0,
                    "body_only_contexts": 0,
                }
            finally:
                if con is not None:
                    con.close()

        return {
            "added_items": added_items,
            "added_links": added_links,
            "added_contexts": added_contexts,
            **extraction_stats,
            "backup_path": backup_path,
            "dry_run": dry_run,
            "extract_existing": extract_existing,
            "force": force,
        }

    con = connect(DB)
    ensure_schema(con)
    backup_path = add_backup(DB)

    for rel_path, meta, links in iter_notes(VAULT):
        item_created = item_created_from_meta(meta)
        link_created = now_iso()
        item_id_row = con.execute("SELECT id FROM items WHERE path = ?", (rel_path,)).fetchone()
        if item_id_row:
            item_id = item_id_row[0]
        else:
            item_id, created_now = ensure_item(con, VAULT, rel_path, meta, item_created)
            if created_now:
                added_items += 1

        source = str(meta.get("source", "") or "")
        for position, (url, context) in enumerate(links, start=1):
            link_id, link_added = ensure_link(
                con,
                item_id,
                url,
                context,
                link_created,
                position,
                str(meta.get("status", "inbox") or "inbox"),
            )
            if link_added:
                added_links += 1

            context_exists = con.execute("SELECT 1 FROM link_contexts WHERE link_id = ?", (link_id,)).fetchone()
            if context_exists:
                continue

            upsert_link_context(
                con,
                link_id,
                url,
                description=context,
                summary=context,
                context_status="body_only",
                error=None,
                extractor="backfill",
                now=now_iso(),
            )
            added_contexts += 1

    if extract_existing:
        extraction_stats = extract_existing_contexts(con, dry_run=False, force=force)

    con.commit()
    con.close()

    return {
        "added_items": added_items,
        "added_links": added_links,
        "added_contexts": added_contexts,
        **extraction_stats,
        "backup_path": backup_path,
        "dry_run": dry_run,
        "extract_existing": extract_existing,
        "force": force,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Conta alterações sem alterar o banco")
    parser.add_argument("--extract-existing", action="store_true", help="Reprocessa links existentes com extração de contexto atual")
    parser.add_argument("--force", action="store_true", help="Com --extract-existing, reprocessa todos os links existentes")
    parser.add_argument("--json", action="store_true", help="Exibe saída JSON")
    args = parser.parse_args()

    payload = run_backfill(dry_run=args.dry_run, extract_existing=args.extract_existing, force=args.force)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"Itens adicionados: {payload['added_items']}")
    print(f"Links adicionados: {payload['added_links']}")
    print(f"Contextos adicionados: {payload['added_contexts']}")
    print(f"Candidatos para extração: {payload['extract_candidates']}")
    print(f"Contextos extraídos: {payload['extracted_contexts']}")
    print(f"Falhas de extração: {payload['failed_contexts']}")
    print(f"Dry-run: {payload['dry_run']}")
    print(f"Backup: {payload['backup_path'] or 'não gerado'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
