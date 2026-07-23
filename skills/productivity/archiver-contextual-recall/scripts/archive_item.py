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

from archiver_db import DB, VAULT, connect, collect_urls_and_context, ensure_schema, upsert_link_context
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


def _merge_summaries(base: str, addition: str | None) -> str:
    base = base.strip()
    if not addition:
        return base
    addition = addition.strip()
    if not addition or addition == base:
        return base
    if not base:
        return addition[:1500]
    return f"{base}\n{addition}"[:1500]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--source", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--body", default="")
    parser.add_argument("--status", default="inbox")
    parser.add_argument("--no-extract", action="store_true", help="Desativa extração automática de contexto de links")
    parser.add_argument("--json", action="store_true", help="Emite saída JSON")
    args = parser.parse_args()

    now = dt.datetime.now().astimezone().replace(microsecond=0).isoformat()
    tags = [t.strip().lstrip("#") for t in args.tags.split(",") if t.strip()]
    if not tags:
        tags = ["inbox"]

    INBOX.mkdir(parents=True, exist_ok=True)
    DB.parent.mkdir(parents=True, exist_ok=True)

    stem = f"{dt.date.today().isoformat()}-{slugify(args.title)}"
    path = INBOX / f"{stem}.md"
    counter = 2
    while path.exists():
        path = INBOX / f"{stem}-{counter}.md"
        counter += 1

    body = args.body.strip() or "_Sem corpo ainda._"
    content = f"""---
title: {json.dumps(args.title, ensure_ascii=False)}
created: {json.dumps(now)}
source: {json.dumps(args.source, ensure_ascii=False)}
tags: {yaml_list(tags)}
status: {json.dumps(args.status)}
---

# {args.title}

## Resumo
{body}

## Fonte
{args.source or '_Sem fonte informada._'}
"""
    path.write_text(content, encoding="utf-8")

    con = connect(DB)
    ensure_schema(con)
    cur = con.execute(
        "INSERT INTO items(title, source, path, tags, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (args.title, args.source, str(path.relative_to(VAULT)), json.dumps(tags, ensure_ascii=False), args.status, now, now),
    )
    item_id = cur.lastrowid
    links = collect_urls_and_context(body, args.source)
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

        if not args.no_extract:
            try:
                result = extract_url_context(url, timeout=5)
                extractor = result.get("extractor")
                extracted_title = result.get("title") if isinstance(result.get("title"), str) else None
                extracted_text = result.get("extracted_text") if isinstance(result.get("extracted_text"), str) else None
                keywords = result.get("keywords") if isinstance(result.get("keywords"), list) else []
                error = result.get("error")
                status = str(result.get("context_status", "failed"))
                if status == "extracted":
                    context_status = "extracted"
                    summary = _merge_summaries(summary, result.get("summary") if isinstance(result.get("summary"), str) else None)
                    description = result.get("description") if isinstance(result.get("description"), str) else context_title
                    extracted_context_count += 1
                elif status == "unsupported_content_type":
                    context_status = "body_only"
                else:
                    context_status = "failed"
            except Exception as exc:  # pragma: no cover - defensive fallback
                context_status = "failed"
                extractor = "urllib.request"
                error = str(exc)

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
        )
        context_count += 1

    con.execute(
        "INSERT INTO events(item_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
        (item_id, "created", json.dumps({"path": str(path)}, ensure_ascii=False), now),
    )
    con.commit()
    con.close()

    if args.json:
        print(json.dumps({
            "title": args.title,
            "source": args.source,
            "tags": tags,
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
