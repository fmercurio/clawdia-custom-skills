#!/usr/bin/env python3
"""Create a Markdown archive item and register it in the Archiver SQLite index.

Usage:
  python archive_item.py --title "..." --source "https://..." --tags hermes,ai-agents --body "..."
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

from archiver_db import (
    DB,
    VAULT,
    capture_context_fields,
    collect_urls_and_context,
    connect,
    ensure_private_directory,
    ensure_schema,
    restrict_sqlite_permissions,
    upsert_link_context,
    write_private_text_exclusive,
)
from archiver_extract_context import extract_url_context

INBOX = VAULT / "00-inbox"

def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\u00c0-\u024f]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:80] or "item"


def yaml_list(tags: list[str]) -> str:
    return "[" + ", ".join(json.dumps(t, ensure_ascii=False) for t in tags) + "]"


def _context_from_link(url: str, body: str, source: str, context: str) -> tuple[str, str]:
    if context and context != "source":
        return context, context
    if body.strip():
        return "Contexto da mensagem", body.strip()
    if source:
        return f"Fonte: {source}", source
    return "Contexto da mensagem", url


def _explicit_labels(values: list[str]) -> list[str]:
    labels = list(dict.fromkeys(value.strip() for value in values if value.strip()))
    if len(labels) > 32 or any(len(value) > 256 for value in labels):
        raise ValueError("At most 32 labels of 256 characters are allowed per field")
    return labels


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--source", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--body", default="")
    parser.add_argument("--status", default="inbox")
    parser.add_argument("--capability", action="append", default=[], help="Explicit capability; repeatable, not inferred")
    parser.add_argument("--use-case", action="append", default=[], help="Explicit use case; repeatable, not inferred")
    parser.add_argument("--no-extract", action="store_true", help="Desativa extração automática de contexto de links")
    parser.add_argument("--json", action="store_true", help="Emite saída JSON")
    args = parser.parse_args()

    now = dt.datetime.now().astimezone().replace(microsecond=0).isoformat()
    tags = [t.strip().lstrip("#") for t in args.tags.split(",") if t.strip()]
    if not tags:
        tags = ["inbox"]

    stem = f"{dt.date.today().isoformat()}-{slugify(args.title)}"
    body = args.body.strip() or "_Sem corpo ainda._"
    try:
        links = collect_urls_and_context(body, args.source)
        capabilities = _explicit_labels(args.capability)
        use_cases = _explicit_labels(args.use_case)
    except ValueError as exc:
        parser.error(str(exc))

    ensure_private_directory(VAULT)
    ensure_private_directory(INBOX)
    ensure_private_directory(DB.parent)
    content = f"""---
title: {json.dumps(args.title, ensure_ascii=False)}
created: {json.dumps(now)}
source: {json.dumps(args.source, ensure_ascii=False)}
tags: {yaml_list(tags)}
capabilities: {yaml_list(capabilities)}
use_cases: {yaml_list(use_cases)}
status: {json.dumps(args.status)}
---

# {args.title}

## Resumo
{body}

## Fonte
{args.source or '_Sem fonte informada._'}
"""
    counter = 1
    while True:
        suffix = "" if counter == 1 else f"-{counter}"
        path = INBOX / f"{stem}{suffix}.md"
        try:
            write_private_text_exclusive(path, content)
            break
        except FileExistsError:
            counter += 1

    con = connect(DB)
    ensure_schema(con)
    cur = con.execute(
        "INSERT INTO items(title, source, path, tags, status, created_at, updated_at, capabilities, use_cases) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (args.title, args.source, str(path.relative_to(VAULT)), json.dumps(tags, ensure_ascii=False), args.status, now, now, json.dumps(capabilities, ensure_ascii=False), json.dumps(use_cases, ensure_ascii=False)),
    )
    item_id = cur.lastrowid
    context_count = 0
    extracted_context_count = 0

    for position, (url, context) in enumerate(links, start=1):
        con.execute(
            """
            INSERT INTO links(item_id, url, title, context, position, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (item_id, url, None, context, position, "captured", now),
        )
        link_id = con.execute("SELECT id FROM links WHERE item_id = ? AND url = ?", (item_id, url)).fetchone()
        if not link_id:
            continue
        context_title, summary = _context_from_link(url, body, args.source, context)
        context_status = "body_only"
        extractor = None
        extracted_title = None
        extracted_text = None
        error = None
        keywords: list[str] = []
        description = context_title
        capture = capture_context_fields({
            "capture_quality": "unknown",
            "capture_coverage": "none",
            "capture_metadata": {"schema": "archiver-capture.v1", "method": "not_requested"},
        })

        if not args.no_extract:
            try:
                result = extract_url_context(url, timeout=5)
                capture = capture_context_fields(result)
                extractor = result.get("extractor")
                extracted_title = result.get("title") if isinstance(result.get("title"), str) else None
                extracted_text = result.get("extracted_text") if isinstance(result.get("extracted_text"), str) else None
                keywords = result.get("keywords") if isinstance(result.get("keywords"), list) else []
                error = result.get("error")
                status = str(result.get("context_status", "failed"))
                context_status = status if status in {"extracted", "metadata_only", "insufficient_text", "failed", "unsupported_content_type", "empty"} else "failed"
                description = result.get("description") if isinstance(result.get("description"), str) else context_title
                if status == "extracted":
                    extracted_context_count += 1
            except Exception as exc:  # pragma: no cover - defensive fallback
                context_status = "failed"
                extractor = "urllib.request"
                error = str(exc)
                capture = capture_context_fields({"capture_quality": "unknown", "capture_coverage": "none", "capture_metadata": {"schema": "archiver-capture.v1", "method": "failed"}})

        upsert_link_context(
            con,
            link_id[0],
            url,
            title=extracted_title,
            description=description,
            summary=summary,
            extracted_text=extracted_text,
            context_status=context_status,
            extractor=extractor,
            error=error,
            keywords=keywords,
            user_context=args.body.strip(),
            **capture,
        )
        context_count += 1

    con.execute(
        "INSERT INTO events(item_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
        (item_id, "created", json.dumps({"path": str(path)}, ensure_ascii=False), now),
    )
    con.commit()
    con.close()
    restrict_sqlite_permissions(DB)

    if args.json:
        print(json.dumps({
            "item_id": item_id,
            "title": args.title,
            "source": args.source,
            "tags": tags,
            "capabilities": capabilities,
            "use_cases": use_cases,
            "status": args.status,
            "path": str(path),
            "created_at": now,
            "link_count": len(links),
            "context_count": context_count,
            "extracted_context_count": extracted_context_count,
        }, ensure_ascii=False))
        return 0

    print(f"Arquivado: {args.title}")
    print(f"Tags: {', '.join('#' + t for t in tags)}")
    print(f"Destino: {path}")
    print(f"Links: {len(links)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
