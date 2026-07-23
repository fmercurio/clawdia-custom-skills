#!/usr/bin/env python3
"""Read-only recall tool for Archiver items and markdown notes."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from archiver_db import DB, VAULT, connect_readonly, table_columns, table_exists

SKIP_PREFIXES = {"90-meta", "attachments"}
URL_PREFIX_RE = re.compile(r"\bhttps?://[^\s<>'\"`\]\[(){}]+")
WORD_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+")
EXACT_MATCH_BONUS = 1000
STOPWORDS = {
    "a",
    "à",
    "ao",
    "aos",
    "as",
    "até",
    "com",
    "como",
    "de",
    "da",
    "das",
    "do",
    "dos",
    "e",
    "em",
    "entre",
    "esta",
    "estes",
    "esta",
    "este",
    "isso",
    "na",
    "nas",
    "não",
    "no",
    "nos",
    "o",
    "os",
    "para",
    "por",
    "que",
    "sem",
    "sobre",
    "the",
    "and",
    "for",
    "with",
    "that",
}
EMPTY_STR_SQL = "''"
EMPTY_ARRAY_SQL = "'[]'"


def parse_iso_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        if text.endswith("Z"):
            try:
                parsed = dt.datetime.fromisoformat(text[:-1] + "+00:00")
            except ValueError:
                return None
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
    return parsed


def parse_frontmatter(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {
        "title": path.stem,
        "source": "",
        "status": "",
        "tags": [],
        "created": "",
    }
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not text.startswith("---\n"):
        return data
    lines = text.splitlines()
    try:
        end = lines[1:].index("---")
    except ValueError:
        return data
    for line in lines[1 : end + 1]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip().strip().strip('"').strip("'")
        if key == "tags":
            if value.startswith("[") and value.endswith("]"):
                inner = value[1:-1].strip()
                data[key] = [item.strip().strip('"').strip("'") for item in inner.split(",") if item.strip()]
            else:
                data[key] = []
        else:
            data[key] = value
    data["created"] = data.get("created", "")
    return data


def _normalize_status(value: str) -> str:
    return value.strip().lower()


def _select_expr(columns: set[str], table: str, column: str, fallback: str) -> str:
    if column in columns:
        return f"COALESCE({table}.{column}, {fallback})"
    return fallback


def _resolve_item_projection(item_cols: set[str]) -> tuple[list[str], str]:
    fields = [
        f"{_select_expr(item_cols, 'i', 'title', EMPTY_STR_SQL)} AS item_title",
        f"{_select_expr(item_cols, 'i', 'source', EMPTY_STR_SQL)} AS item_source",
        f"{_select_expr(item_cols, 'i', 'path', EMPTY_STR_SQL)} AS path",
        f"{_select_expr(item_cols, 'i', 'tags', EMPTY_ARRAY_SQL)} AS item_tags",
        f"{_select_expr(item_cols, 'i', 'status', EMPTY_STR_SQL)} AS status",
        f"{_select_expr(item_cols, 'i', 'created_at', EMPTY_STR_SQL)} AS created_at",
    ]
    order_expr = "COALESCE(i.created_at, '')" if "created_at" in item_cols else "i.rowid"
    return fields, order_expr


def _safe_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except json.JSONDecodeError:
        pass
    return []


def _path_basename_fallback(path_str: str) -> str:
    return Path(path_str).name if path_str else "item"


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    tokens = []
    seen = set()
    for token in WORD_RE.findall(text.lower()):
        token = token.strip()
        if len(token) <= 2 or token in STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def _to_token_set(value: object) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, list):
        text = " ".join(str(item) for item in value)
    elif isinstance(value, str) and value.strip().startswith("[") and value.strip().endswith("]"):
        parsed = _safe_json_list(value)
        text = " ".join(str(item) for item in parsed) if parsed else value
    else:
        text = str(value)
    return set(_tokenize(text))


def _text_matches(query: str, *candidates: object) -> bool:
    if not query:
        return False
    token = query.lower()
    for value in candidates:
        if not value:
            continue
        text = str(value).lower()
        if token in text:
            return True
    return False


def _link_exact_fields(row: sqlite3.Row) -> list[tuple[str, object]]:
    return [
        ("título do item", row["item_title"]),
        ("fonte do item", row["item_source"]),
        ("caminho", row["path"]),
        ("tags", row["item_tags"]),
        ("status", row["status"]),
        ("url", row["url"]),
        ("título do link", row["link_title"]),
        ("contexto do link", row["link_context"]),
        ("descrição do contexto", row["ctx_description"]),
        ("resumo do contexto", row["ctx_summary"]),
        ("texto extraído do contexto", row["ctx_extracted_text"]),
        ("palavras-chave do contexto", row["ctx_keywords"]),
    ]


def _link_token_fields(row: sqlite3.Row) -> list[tuple[str, object]]:
    return [
        ("título do item", row["item_title"]),
        ("fonte do item", row["item_source"]),
        ("url", row["url"]),
        ("contexto do link", row["link_context"]),
        ("resumo do contexto", row["ctx_summary"]),
        ("texto extraído do contexto", row["ctx_extracted_text"]),
        ("tags", _safe_json_list(row["item_tags"])),
    ]


def _compute_link_row_score(query: str, query_tokens: list[str], row: sqlite3.Row) -> tuple[int, str]:
    q = query.lower().strip()
    if not q:
        return 0, ""

    for label, value in _link_exact_fields(row):
        if _text_matches(q, value):
            return EXACT_MATCH_BONUS, f"correspondência exata em {label}"

    score = 0
    why = ""
    for token in query_tokens:
        for label, value in _link_token_fields(row):
            if token in _to_token_set(value):
                score += 1
                if not why:
                    why = f"correspondência por token em {label}"
    if score:
        if not why:
            why = "correspondência por token"
        return score, why
    return 0, ""


def _reason_for_link_row(query: str, row: sqlite3.Row, query_tokens: list[str]) -> str:
    _, why = _compute_link_row_score(query, query_tokens, row)
    return why or ""


def _collect_links_rows(con: sqlite3.Connection, query: str, limit: int, status: str | None) -> list[sqlite3.Row]:
    if not table_exists(con, "items"):
        return []

    item_cols = {column.lower() for column in table_columns(con, "items")}
    link_cols = {column.lower() for column in table_columns(con, "links")} if table_exists(con, "links") else set()
    context_cols = {column.lower() for column in table_columns(con, "link_contexts")} if table_exists(con, "link_contexts") else set()

    params: list[object] = []
    where_sql = ""
    if status and "status" in item_cols:
        where_sql = "AND LOWER(i.status) = ?"
        params.append(_normalize_status(status))

    has_links = "id" in item_cols and {"id", "item_id", "url"}.issubset(link_cols)
    has_context = has_links and "link_id" in context_cols

    item_fields, order_expr = _resolve_item_projection(item_cols)
    if has_links:
        link_fields = [
            f"{_select_expr(link_cols, 'l', 'url', EMPTY_STR_SQL)} AS url",
            f"{_select_expr(link_cols, 'l', 'title', EMPTY_STR_SQL)} AS link_title",
            f"{_select_expr(link_cols, 'l', 'context', EMPTY_STR_SQL)} AS link_context",
        ]
        link_order = "COALESCE(l.id, -1)"
        join_sql = "\n    FROM items i\n    LEFT JOIN links l ON l.item_id = i.id"
        if has_context:
            link_fields.extend([
                f"{_select_expr(context_cols, 'lc', 'title', EMPTY_STR_SQL)} AS ctx_title",
                f"{_select_expr(context_cols, 'lc', 'description', EMPTY_STR_SQL)} AS ctx_description",
                f"{_select_expr(context_cols, 'lc', 'summary', EMPTY_STR_SQL)} AS ctx_summary",
                f"{_select_expr(context_cols, 'lc', 'extracted_text', EMPTY_STR_SQL)} AS ctx_extracted_text",
                f"{_select_expr(context_cols, 'lc', 'keywords', EMPTY_ARRAY_SQL)} AS ctx_keywords",
            ])
            join_sql += "\n    LEFT JOIN link_contexts lc ON lc.link_id = l.id"
        else:
            link_fields.extend([
                "'' AS ctx_title",
                "'' AS ctx_description",
                "'' AS ctx_summary",
                "'' AS ctx_extracted_text",
                "'[]' AS ctx_keywords",
            ])
    else:
        link_fields = [
            "'' AS url",
            "'' AS link_title",
            "'' AS link_context",
            "'' AS ctx_title",
            "'' AS ctx_description",
            "'' AS ctx_summary",
            "'' AS ctx_extracted_text",
            "'[]' AS ctx_keywords",
        ]
        link_order = "i.rowid"
        join_sql = "\n    FROM items i"

    select_fields = item_fields + link_fields
    query_tokens = _tokenize(query)
    order_expr = f"{order_expr}, {link_order}"

    select_sql = ",\n      ".join(select_fields)
    sql = f"""
    SELECT
      {select_sql}
    {join_sql}
    WHERE 1 = 1
      {where_sql}
    ORDER BY {order_expr}
    """

    rows = con.execute(sql, params).fetchall()

    scored: list[tuple[int, int, sqlite3.Row]] = []
    for idx, row in enumerate(rows):
        score, _ = _compute_link_row_score(query, query_tokens, row)
        if score:
            scored.append((score, -idx, row))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [row for _, _, row in scored][:limit]


def collect_db_results(query: str, limit: int, status: str | None) -> list[dict[str, Any]]:
    if not DB.exists():
        return []
    try:
        con = connect_readonly(DB)
    except sqlite3.OperationalError:
        return []

    con.row_factory = sqlite3.Row
    out: list[dict[str, Any]] = []
    if not table_exists(con, "items"):
        con.close()
        return out

    item_cols = {column.lower() for column in table_columns(con, "items")}

    if not query:
        params: list[object] = []
        if status and "status" in item_cols:
            status_sql = "WHERE LOWER(i.status) = ?"
            params.append(_normalize_status(status))
        else:
            status_sql = ""

        select_fields, order_expr = _resolve_item_projection(item_cols)
        select_sql = ",\n          ".join(select_fields)
        sql = f"""
        SELECT
          {select_sql}
        FROM items i
        {status_sql}
        ORDER BY {order_expr} DESC
        LIMIT ?
        """
        params.append(limit)

        rows = con.execute(sql, params).fetchall()
        for row in rows:
            created_raw = row["created_at"] or ""
            created_at = parse_iso_datetime(created_raw)
            out.append({
                "source": row["item_source"] or "",
                "title": row["item_title"] or _path_basename_fallback(row["path"]),
                "url": "",
                "tags": _safe_json_list(row["item_tags"]),
                "status": row["status"] or "",
                "path": row["path"] or "",
                "created_at": created_at.isoformat() if created_at else "",
                "path_type": "sqlite",
                "why": "",
            })
        con.close()
        return out

    query_l = query.lower()
    query_tokens = _tokenize(query_l)
    rows = _collect_links_rows(con, query_l, limit, status)
    for row in rows:
        created_raw = row["created_at"] or ""
        created_at = parse_iso_datetime(created_raw)
        why = _reason_for_link_row(query_l, row, query_tokens)
        out.append({
            "source": row["item_source"] or "",
            "title": row["item_title"] or _path_basename_fallback(row["path"]),
            "url": row["url"] or "",
            "tags": _safe_json_list(row["item_tags"]),
            "status": row["status"] or "",
            "path": row["path"] or "",
            "created_at": created_at.isoformat() if created_at else "",
            "path_type": "sqlite",
            "why": why,
        })

    con.close()
    return out


def collect_note_results(query: str, limit: int, status: str | None) -> list[dict[str, Any]]:
    if not VAULT.exists():
        return []
    out = []
    query_l = query.lower()
    query_tokens = _tokenize(query_l)
    for md_path in VAULT.rglob("*.md"):
        rel_parts = md_path.relative_to(VAULT).parts
        if rel_parts and rel_parts[0] in SKIP_PREFIXES:
            continue
        text = md_path.read_text(encoding="utf-8", errors="ignore")
        meta = parse_frontmatter(md_path)
        if status and _normalize_status(meta.get("status", "")) != _normalize_status(status):
            continue
        source = meta.get("source", "")
        title = meta.get("title", md_path.stem)
        tags = meta.get("tags", [])
        if not isinstance(tags, list):
            tags = []

        lower_text = text.lower()
        lower_title = str(title).lower()
        lower_source = str(source).lower()
        lower_tags = " ".join(str(x).lower() for x in tags)
        lower_path = str(md_path.relative_to(VAULT)).lower()

        if query:
            haystack = "\n".join([lower_title, lower_source, lower_tags, lower_path, lower_text])
            if query_l not in haystack:
                note_tokens = set(_tokenize(haystack))
                if not any(token in note_tokens for token in query_tokens):
                    continue

        created = parse_iso_datetime(meta.get("created", ""))
        why = ""
        if query:
            if query_l in lower_title:
                why = "correspondência no título da nota"
            elif query_l in lower_source:
                why = "correspondência na fonte"
            elif query_l in lower_tags:
                why = "correspondência nas etiquetas da nota"
            elif query_l in lower_path:
                why = "correspondência no caminho da nota"
            elif query_l in lower_text:
                why = "correspondência no conteúdo da nota"
            else:
                field_tokens = {
                    "título da nota": _to_token_set(lower_title),
                    "fonte da nota": _to_token_set(lower_source),
                    "etiquetas da nota": _to_token_set(lower_tags),
                    "caminho da nota": _to_token_set(lower_path),
                    "conteúdo da nota": _to_token_set(lower_text),
                }
                for label, values in field_tokens.items():
                    if any(token in values for token in query_tokens):
                        why = f"correspondência por token em {label}"
                        break
                if not why:
                    why = "correspondência no item"

        out.append({
            "source": source,
            "title": title,
            "url": source,
            "tags": [str(x) for x in tags if str(x).strip()],
            "status": meta.get("status", ""),
            "path": str(md_path.relative_to(VAULT)),
            "created_at": created.isoformat() if created else "",
            "path_type": "markdown",
            "why": why,
        })
    out.sort(key=lambda item: item["created_at"], reverse=True)
    return out[:limit]


def _created_at_sort_key(item: dict[str, Any]) -> tuple[float, str, str, str]:
    created = parse_iso_datetime(item.get("created_at"))
    ts = created.timestamp() if created else float("-inf")
    return (
        -ts,
        item.get("path", ""),
        item.get("url", ""),
        item.get("source", ""),
    )


def dedupe_keep_newest(db_items: list[dict[str, Any]], note_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    merged = []
    for item in db_items + note_items:
        key = (item["path"], item.get("url", ""))
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    merged.sort(key=_created_at_sort_key)
    return merged


def to_console(results: list[dict[str, Any]], limit: int) -> None:
    if not results:
        print("Nenhum item encontrado.")
        return
    for item in results[:limit]:
        tags = " ".join("#" + str(tag) for tag in item["tags"]) or "sem tags"
        print(f"{item['title']}")
        if item.get("url"):
            print(f"URL: {item['url']}")
        if item.get("why"):
            print(f"Por que: {item['why']}")
        print(f"Fonte: {item['source'] or 'sem fonte'}")
        print(f"Tags: {tags}")
        print(f"Status: {item['status'] or 'sem status'}")
        print(f"Caminho: {item['path']}")
        print()


def collect_all(query: str, limit: int, status: str | None) -> list[dict[str, Any]]:
    db_items = collect_db_results(query, limit, status)
    note_items = collect_note_results(query, limit, status)
    return dedupe_keep_newest(db_items, note_items)[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Consulta itens do Archiver sem escrever no banco.")
    parser.add_argument("--query", default="", help="Termo de busca")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--status")
    parser.add_argument("--json", action="store_true", help="Emite saída JSON")
    args = parser.parse_args()

    if args.limit <= 0:
        print("--limit deve ser maior que 0.")
        return 1

    results = collect_all(args.query.strip(), args.limit, args.status)
    if args.json:
        print(json.dumps({
            "count": len(results),
            "query": args.query,
            "status": args.status,
            "results": results,
        }, ensure_ascii=False, indent=2))
        return 0

    to_console(results, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
