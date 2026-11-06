#!/usr/bin/env python3
"""Read-only, bounded relevance-ranked recall for Archiver items and notes."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from archiver_db import DB, VAULT, connect_readonly, read_vault_text, table_columns, table_exists

SKIP_PREFIXES = {"90-meta", "attachments"}
WORD_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+")
MAX_QUERY_TOKENS = 12
MAX_TOKEN_CHARS = 48
MAX_SNIPPET_CHARS = 240
FTS_RANK_BONUS_MAX = 240
SHORT_DOMAIN_TOKENS = {"ai", "ia", "ui", "ux"}
STOPWORDS = {
    "a", "ao", "aos", "as", "ate", "com", "como", "de", "da", "das", "do", "dos", "e", "em",
    "entre", "esta", "estas", "este", "estes", "isso", "na", "nas", "nao", "no", "nos", "o", "os",
    "para", "por", "que", "sem", "sobre", "the", "and", "for", "with", "that",
}
EMPTY_STR_SQL = "''"
EMPTY_ARRAY_SQL = "'[]'"
CAPTURE_QUALITIES = {"usable", "limited", "metadata_only", "empty", "unknown"}
CAPTURE_COVERAGES = {"bounded_text", "truncated", "metadata_only", "none", "unknown"}


def _fold(value: object) -> str:
    text = str(value or "")
    return "".join(char for char in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(char))


def _tokenize(value: object) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in WORD_RE.findall(_fold(value)):
        token = raw[:MAX_TOKEN_CHARS]
        if token in seen or token in STOPWORDS:
            continue
        if len(token) <= 2 and token not in SHORT_DOMAIN_TOKENS:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= MAX_QUERY_TOKENS:
            break
    return out


def _field_token_set(value: object) -> set[str]:
    return {
        token
        for token in WORD_RE.findall(_fold(value))
        if len(token) > 2 or token in SHORT_DOMAIN_TOKENS
    }


def _safe_json_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _json_or_text(value: object) -> str:
    values = _safe_json_list(value)
    return " ".join(values) if values else str(value or "")


def parse_iso_datetime(value: str | None) -> dt.datetime | None:
    if not value or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = dt.datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=dt.datetime.now().astimezone().tzinfo) if parsed.tzinfo is None else parsed


def _frontmatter_array(value: str) -> list[str]:
    """Read generated JSON arrays without treating escaped commas as delimiters."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        if not (value.startswith("[") and value.endswith("]")):
            return []
        # Preserve compatibility with old bare-token arrays such as ``[ai, archive]``.
        return [part.strip().strip('"').strip("'") for part in value[1:-1].split(",") if part.strip()]
    return [str(item) for item in parsed if str(item).strip()] if isinstance(parsed, list) else []


def parse_frontmatter(path: Path, text: str = "") -> dict[str, Any]:
    """Parse already-safe vault text; never reread the supplied Markdown path."""
    data: dict[str, Any] = {
        "title": path.stem,
        "source": "",
        "status": "",
        "tags": [],
        "capabilities": [],
        "use_cases": [],
        "created": "",
    }
    if not text.startswith("---\n"):
        return data
    lines = text.splitlines()
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        return data
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key in {"tags", "capabilities", "use_cases"}:
            data[key] = _frontmatter_array(value)
        elif key in data:
            try:
                data[key] = json.loads(value) if value.startswith('"') else value.strip("'")
            except json.JSONDecodeError:
                data[key] = value.strip('"').strip("'")
    return data


def _select_expr(columns: set[str], table: str, column: str, fallback: str) -> str:
    return f"COALESCE({table}.{column}, {fallback})" if column in columns else fallback


def _projection(item_cols: set[str], link_cols: set[str], context_cols: set[str], has_links: bool, has_context: bool) -> tuple[list[str], str, str]:
    item_fields = [
        f"{_select_expr(item_cols, 'i', 'title', EMPTY_STR_SQL)} AS item_title",
        f"{_select_expr(item_cols, 'i', 'source', EMPTY_STR_SQL)} AS item_source",
        f"{_select_expr(item_cols, 'i', 'path', EMPTY_STR_SQL)} AS path",
        f"{_select_expr(item_cols, 'i', 'tags', EMPTY_ARRAY_SQL)} AS item_tags",
        f"{_select_expr(item_cols, 'i', 'status', EMPTY_STR_SQL)} AS status",
        f"{_select_expr(item_cols, 'i', 'created_at', EMPTY_STR_SQL)} AS created_at",
        f"{_select_expr(item_cols, 'i', 'capabilities', EMPTY_ARRAY_SQL)} AS capabilities",
        f"{_select_expr(item_cols, 'i', 'use_cases', EMPTY_ARRAY_SQL)} AS use_cases",
        f"{_select_expr(item_cols, 'i', 'description', EMPTY_STR_SQL)} AS item_description",
        f"{_select_expr(item_cols, 'i', 'summary', EMPTY_STR_SQL)} AS item_summary",
    ]
    order_expr = "COALESCE(i.created_at, '')" if "created_at" in item_cols else "i.rowid"
    if not has_links:
        blanks = ["url", "link_title", "link_context", "ctx_title", "ctx_description", "ctx_summary", "ctx_extracted_text", "ctx_keywords", "context_status", "capture_quality", "capture_coverage", "capture_metadata", "user_context", "source_summary", "context_id"]
        return item_fields + [f"{EMPTY_ARRAY_SQL if name == 'ctx_keywords' else EMPTY_STR_SQL} AS {name}" for name in blanks], "\n    FROM items i", order_expr
    link_fields = [
        f"{_select_expr(link_cols, 'l', 'url', EMPTY_STR_SQL)} AS url",
        f"{_select_expr(link_cols, 'l', 'title', EMPTY_STR_SQL)} AS link_title",
        f"{_select_expr(link_cols, 'l', 'context', EMPTY_STR_SQL)} AS link_context",
    ]
    join = "\n    FROM items i\n    LEFT JOIN links l ON l.item_id = i.id"
    if has_context:
        for column, alias, fallback in (
            ("title", "ctx_title", EMPTY_STR_SQL), ("description", "ctx_description", EMPTY_STR_SQL),
            ("summary", "ctx_summary", EMPTY_STR_SQL), ("extracted_text", "ctx_extracted_text", EMPTY_STR_SQL),
            ("keywords", "ctx_keywords", EMPTY_ARRAY_SQL), ("context_status", "context_status", EMPTY_STR_SQL),
            ("capture_quality", "capture_quality", EMPTY_STR_SQL), ("capture_coverage", "capture_coverage", EMPTY_STR_SQL),
            ("capture_metadata", "capture_metadata", EMPTY_STR_SQL), ("user_context", "user_context", EMPTY_STR_SQL),
            ("source_summary", "source_summary", EMPTY_STR_SQL), ("id", "context_id", EMPTY_STR_SQL),
        ):
            link_fields.append(f"{_select_expr(context_cols, 'lc', column, fallback)} AS {alias}")
        join += "\n    LEFT JOIN link_contexts lc ON lc.link_id = l.id"
    else:
        link_fields.extend([f"{EMPTY_ARRAY_SQL if name == 'ctx_keywords' else EMPTY_STR_SQL} AS {name}" for name in ["ctx_title", "ctx_description", "ctx_summary", "ctx_extracted_text", "ctx_keywords", "context_status", "capture_quality", "capture_coverage", "capture_metadata", "user_context", "source_summary", "context_id"]])
    return item_fields + link_fields, join, order_expr


def _safe_fts_terms(tokens: list[str]) -> str:
    # Tokens come only from WORD_RE, then are bounded; quote each term and bind it.
    return " AND ".join(f'"{token}"' for token in tokens[:MAX_QUERY_TOKENS])


def _fts_context_ranks(con: sqlite3.Connection, tokens: list[str]) -> tuple[dict[str, int], str]:
    """Return a bounded, monotonic FTS ranking bonus without excluding lexical rows."""
    if not tokens or not table_exists(con, "link_contexts_fts"):
        return {}, "missing"
    try:
        rows = con.execute(
            "SELECT rowid FROM link_contexts_fts WHERE link_contexts_fts MATCH ? "
            "ORDER BY bm25(link_contexts_fts)",
            (_safe_fts_terms(tokens),),
        ).fetchall()
        return {
            str(row[0]): max(1, FTS_RANK_BONUS_MAX - rank)
            for rank, row in enumerate(rows)
        }, "ok"
    except sqlite3.Error:
        # Missing/stale/corrupt indexes never suppress lexical recall and are never rebuilt here.
        return {}, "error"


def _is_urlish(value: str) -> bool:
    return value.startswith(("http://", "https://")) or ("/" in value and " " not in value)


def _snippet(text: object, tokens: list[str], query_folded: str) -> str:
    value = " ".join(str(text or "").split())
    if not value:
        return ""
    folded = _fold(value)
    start = folded.find(query_folded) if query_folded else -1
    if start < 0:
        for token in tokens:
            start = folded.find(token)
            if start >= 0:
                break
    if start < 0:
        start = 0
    left = max(0, start - 70)
    prefix = "…" if left else ""
    # Reserve space for a possible trailing ellipsis before selecting content.
    content_budget = MAX_SNIPPET_CHARS - len(prefix) - 1
    right = min(len(value), left + max(0, content_budget))
    suffix = "…" if right < len(value) else ""
    content_budget = MAX_SNIPPET_CHARS - len(prefix) - len(suffix)
    right = min(len(value), left + max(0, content_budget))
    suffix = "…" if right < len(value) else ""
    return prefix + value[left:right] + suffix


def _fields(row: dict[str, Any]) -> list[tuple[str, str, object, int]]:
    return [
        ("item_title", "título do item", row.get("item_title"), 11000),
        ("ctx_title", "título do contexto", row.get("ctx_title"), 10500),
        ("link_title", "título do link", row.get("link_title"), 9500),
        ("capabilities", "capacidades", row.get("capabilities"), 8000),
        ("use_cases", "casos de uso", row.get("use_cases"), 7500),
        ("tags", "tags", row.get("item_tags"), 6000),
        ("ctx_keywords", "palavras-chave", row.get("ctx_keywords"), 5500),
        ("item_description", "descrição do item", row.get("item_description"), 5000),
        ("ctx_description", "descrição do contexto", row.get("ctx_description"), 4800),
        ("item_summary", "resumo do item", row.get("item_summary"), 4400),
        ("ctx_summary", "resumo do contexto", row.get("ctx_summary"), 4300),
        ("source_summary", "resumo da fonte", row.get("source_summary"), 4000),
        ("user_context", "contexto do usuário", row.get("user_context"), 3500),
        ("link_context", "contexto do link", row.get("link_context"), 2500),
        ("item_source", "fonte do item", row.get("item_source"), 2200),
        ("url", "URL", row.get("url"), 1800),
        ("path", "caminho", row.get("path"), 1200),
        ("ctx_extracted_text", "texto extraído", row.get("ctx_extracted_text"), 500),
        ("capture_metadata", "metadados de captura", row.get("capture_metadata"), 300),
    ]


def _score_row(
    row: dict[str, Any],
    query: str,
    tokens: list[str],
    *,
    fts_ranks: dict[str, int],
) -> tuple[int, list[str], str, str]:
    query_folded = _fold(query).strip()
    if not query_folded or not tokens:
        return 0, [], "", ""
    matched: list[str] = []
    scored_fields: list[tuple[int, str, str]] = []
    for name, label, raw_value, weight in _fields(row):
        value = _json_or_text(raw_value)
        folded = _fold(value)
        if not folded:
            continue
        field_tokens = _field_token_set(value)
        covered = set(tokens).intersection(field_tokens)
        if not covered:
            continue
        matched.append(name)
        exact_phrase = query_folded in folded and (len(tokens) > 1 or query_folded in field_tokens)
        coverage = len(covered) / len(tokens)
        field_score = max(1, int(weight * coverage))
        if exact_phrase:
            # Exact title/context phrases should beat many copies of generic metadata.
            field_score += weight
        scored_fields.append((field_score, label, value))
    if not scored_fields:
        return 0, [], "", ""
    scored_fields.sort(key=lambda candidate: candidate[0], reverse=True)
    primary_score, primary_label, primary_text = scored_fields[0]
    # Additional fields corroborate a result but cannot swamp field relevance.
    corroboration = min(400, sum(score for score, _, _ in scored_fields[1:]))
    score = primary_score + corroboration + fts_ranks.get(str(row.get("context_id", "")), 0)
    return score, matched, _snippet(primary_text, tokens, query_folded), f"correspondência em {primary_label}"


def _normalize_capture(value: object, allowed: set[str] | None = None) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized and (allowed is None or normalized in allowed) else "unknown"


def _base_result(row: dict[str, Any], *, score: int, match_fields: list[str], snippet: str, why: str, search_method: str) -> dict[str, Any]:
    item_title = str(row.get("item_title") or "")
    context_title = str(row.get("ctx_title") or "")
    title = context_title if context_title and _is_urlish(item_title) else item_title or Path(str(row.get("path") or "item")).name
    created = parse_iso_datetime(str(row.get("created_at") or ""))
    return {
        "source": str(row.get("item_source") or ""), "title": title, "url": str(row.get("url") or ""),
        "tags": _safe_json_list(row.get("item_tags")), "status": str(row.get("status") or ""),
        "path": str(row.get("path") or ""), "created_at": created.isoformat() if created else "", "path_type": "sqlite",
        "why": why, "score": score, "match_fields": match_fields, "snippet": snippet,
        "context_status": _normalize_capture(row.get("context_status")),
        "capture_quality": _normalize_capture(row.get("capture_quality"), CAPTURE_QUALITIES),
        "capture_coverage": _normalize_capture(row.get("capture_coverage"), CAPTURE_COVERAGES), "search_method": search_method,
    }


def _created_timestamp(item: dict[str, Any]) -> float:
    created = parse_iso_datetime(str(item.get("created_at") or ""))
    return created.timestamp() if created else float("-inf")


def _rank(items: Iterable[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    if not query.strip():
        return sorted(items, key=lambda item: (-_created_timestamp(item), item.get("path", ""), item.get("url", "")))
    return sorted(items, key=lambda item: (-int(item.get("score", 0)), -_created_timestamp(item), item.get("path", ""), item.get("url", "")))


def _collect_db_rows(con: sqlite3.Connection, status: str | None) -> tuple[Iterable[sqlite3.Row], bool]:
    if not table_exists(con, "items"):
        return (), False
    item_cols = {name.lower() for name in table_columns(con, "items")}
    link_cols = {name.lower() for name in table_columns(con, "links")} if table_exists(con, "links") else set()
    context_cols = {name.lower() for name in table_columns(con, "link_contexts")} if table_exists(con, "link_contexts") else set()
    has_links = "id" in item_cols and {"id", "item_id", "url"}.issubset(link_cols)
    has_context = has_links and {"id", "link_id"}.issubset(context_cols)
    fields, joins, order_expr = _projection(item_cols, link_cols, context_cols, has_links, has_context)
    where = ""
    params: list[object] = []
    if status and "status" in item_cols:
        where = "WHERE LOWER(i.status) = ?"
        params.append(_fold(status))
    # Do not limit by recency before relevance: old extracted/context titles are candidates too.
    sql = f"SELECT {', '.join(fields)} {joins} {where}"
    return con.execute(sql, params), has_context


def collect_db_results(query: str, limit: int | None, status: str | None) -> list[dict[str, Any]]:
    if not DB.exists():
        return []
    try:
        con = connect_readonly(DB)
    except (OSError, ValueError, sqlite3.Error):
        return []
    try:
        con.row_factory = sqlite3.Row
        rows, has_context = _collect_db_rows(con, status)
        tokens = _tokenize(query)
        fts_ranks, fts_status = _fts_context_ranks(con, tokens) if has_context and query.strip() else ({}, "missing")
        method = {
            "ok": "fts5+lexical",
            "error": "lexical-fallback-error",
            "missing": "lexical",
        }[fts_status]
        results: list[dict[str, Any]] = []
        for row in rows:
            row_dict = dict(row)
            if query.strip():
                score, fields, snippet, why = _score_row(row_dict, query, tokens, fts_ranks=fts_ranks)
                if not score:
                    continue
            else:
                score, fields, snippet, why = 0, [], "", ""
            results.append(_base_result(row_dict, score=score, match_fields=fields, snippet=snippet, why=why, search_method=method))
        ranked = dedupe_keep_newest(results, [], query)
        return ranked if limit is None else ranked[:limit]
    finally:
        con.close()


def collect_note_results(query: str, limit: int | None, status: str | None) -> list[dict[str, Any]]:
    if not VAULT.exists():
        return []
    tokens = _tokenize(query)
    results: list[dict[str, Any]] = []
    for md_path in VAULT.rglob("*.md"):
        try:
            rel = md_path.relative_to(VAULT)
        except ValueError:
            continue
        if rel.parts and rel.parts[0] in SKIP_PREFIXES:
            continue
        text = read_vault_text(VAULT, md_path)
        if text is None:
            continue
        meta = parse_frontmatter(md_path, text)
        if status and _fold(meta.get("status", "")) != _fold(status):
            continue
        row: dict[str, Any] = {
            "item_title": meta.get("title", md_path.stem), "item_source": meta.get("source", ""), "path": str(rel),
            "item_tags": meta.get("tags", []), "status": meta.get("status", ""), "created_at": meta.get("created", ""),
            "capabilities": meta.get("capabilities", []), "use_cases": meta.get("use_cases", []), "item_description": "", "item_summary": "", "url": meta.get("source", ""),
            "link_title": "", "link_context": "", "ctx_title": "", "ctx_description": "", "ctx_summary": "",
            "ctx_extracted_text": text, "ctx_keywords": [], "context_status": "", "capture_quality": "", "capture_coverage": "",
            "capture_metadata": "", "user_context": "", "source_summary": "", "context_id": "",
        }
        if query.strip():
            score, fields, snippet, why = _score_row(row, query, tokens, fts_ranks={})
            if not score:
                continue
        else:
            score, fields, snippet, why = 0, [], "", ""
        result = _base_result(row, score=score, match_fields=fields, snippet=snippet, why=why, search_method="lexical")
        result["path_type"] = "markdown"
        results.append(result)
    ranked = dedupe_keep_newest([], results, query)
    return ranked if limit is None else ranked[:limit]


def dedupe_keep_newest(db_items: list[dict[str, Any]], note_items: list[dict[str, Any]], query: str = "") -> list[dict[str, Any]]:
    """Collapse same-note DB/Markdown representations without collapsing distinct notes sharing a URL."""
    chosen: dict[tuple[str, str], dict[str, Any]] = {}
    for item in db_items + note_items:
        path = str(item.get("path") or "")
        key = ("path", path) if path else ("url", str(item.get("url") or ""))
        existing = chosen.get(key)
        if existing is None:
            chosen[key] = item
            continue
        preferred, alternate = (item, existing) if _rank([item, existing], query)[0] is item else (existing, item)
        merged = dict(preferred)
        merged["tags"] = list(dict.fromkeys([*preferred.get("tags", []), *alternate.get("tags", [])]))
        merged["match_fields"] = list(dict.fromkeys([*preferred.get("match_fields", []), *alternate.get("match_fields", [])]))
        merged["representations"] = list(dict.fromkeys([
            *preferred.get("representations", [preferred.get("path_type", "")]),
            *alternate.get("representations", [alternate.get("path_type", "")]),
        ]))
        for field in ("source", "url", "status"):
            if not merged.get(field):
                merged[field] = alternate.get(field, merged.get(field, ""))
        # Same note is not the same captured source: never borrow another link's
        # extraction status or quality merely because its note path is shared.
        if preferred.get("url") and preferred.get("url") == alternate.get("url"):
            for field in ("context_status", "capture_quality", "capture_coverage"):
                if not merged.get(field) or merged[field] == "unknown":
                    merged[field] = alternate.get(field, merged.get(field, "unknown"))
        chosen[key] = merged
    return _rank(chosen.values(), query)


def collect_all(query: str, limit: int, status: str | None) -> list[dict[str, Any]]:
    # Keep all relevance-filtered source candidates until cross-source same-note dedupe.
    # This honors large requested limits without an arbitrary pre-relevance ceiling.
    return dedupe_keep_newest(
        collect_db_results(query, None, status),
        collect_note_results(query, None, status),
        query,
    )[:limit]


def to_console(results: list[dict[str, Any]], limit: int) -> None:
    if not results:
        print("Nenhum item encontrado.")
        return
    for item in results[:limit]:
        tags = " ".join("#" + str(tag) for tag in item["tags"]) or "sem tags"
        print(item["title"])
        if item.get("url"):
            print(f"URL: {item['url']}")
        if item.get("why"):
            print(f"Por que: {item['why']}")
        if item.get("snippet"):
            print(f"Trecho: {item['snippet']}")
        print(f"Fonte: {item['source'] or 'sem fonte'}")
        print(f"Tags: {tags}")
        print(f"Status: {item['status'] or 'sem status'}")
        print(f"Caminho: {item['path']}")
        print()


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
        print(json.dumps({"count": len(results), "query": args.query, "status": args.status, "results": results}, ensure_ascii=False, indent=2))
        return 0
    to_console(results, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
