#!/usr/bin/env python3
"""Infer staleness and quality flags for a docs-mcp-server index.

This script combines docs-mcp-server `list` output with public package registry
metadata. It does not print secrets and accepts a pre-fetched --list-json file
for offline tests or locked-down environments.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PACKAGE = "@arabold/docs-mcp-server@2.4.2"


def fetch_json(url: str, timeout: int = 12):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "docs-mcp-staleness/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def load_indexed_libraries(server_url: str, package: str, list_json: str | None) -> list[dict]:
    if list_json:
        data = json.loads(Path(list_json).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else data.get("libraries", [])
    result = subprocess.run(
        ["npx", package, "list", "--server-url", f"{server_url.rstrip('/')}/api", "--output", "json"],
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode != 0:
        raise SystemExit("docs-mcp-server list failed; check server URL and CLI availability")
    return json.loads(result.stdout or "[]")


def npm_info(name: str) -> dict:
    url = f"https://registry.npmjs.org/{urllib.parse.quote(name, safe='@/')}"
    data = fetch_json(url)
    if not data:
        return {"registry": "npm", "available": False}
    latest = (data.get("dist-tags") or {}).get("latest")
    times = data.get("time") or {}
    published = times.get(latest) if latest else times.get("modified")
    return {"registry": "npm", "available": True, "latest_version": latest, "latest_published": published}


def pypi_info(name: str) -> dict:
    data = fetch_json(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json")
    if not data:
        return {"registry": "pypi", "available": False}
    version = (data.get("info") or {}).get("version")
    files = (data.get("releases") or {}).get(version, []) if version else []
    times = [f.get("upload_time_iso_8601") or f.get("upload_time") for f in files if f.get("upload_time") or f.get("upload_time_iso_8601")]
    return {"registry": "pypi", "available": True, "latest_version": version, "latest_published": max(times) if times else None}


def github_info(source_url: str) -> dict:
    marker = "github.com/"
    if marker not in source_url:
        return {"registry": "github", "available": False}
    repo = source_url.split(marker, 1)[1].strip("/").split("/")[:2]
    if len(repo) != 2:
        return {"registry": "github", "available": False}
    data = fetch_json(f"https://api.github.com/repos/{repo[0]}/{repo[1]}/releases/latest")
    if data and data.get("published_at"):
        return {"registry": "github", "available": True, "latest_version": data.get("tag_name"), "latest_published": data.get("published_at")}
    commits = fetch_json(f"https://api.github.com/repos/{repo[0]}/{repo[1]}/commits?per_page=1")
    if isinstance(commits, list) and commits:
        date = ((commits[0].get("commit") or {}).get("committer") or {}).get("date")
        return {"registry": "github", "available": True, "latest_version": commits[0].get("sha", "")[:8], "latest_published": date}
    return {"registry": "github", "available": False}


def registry_info(library: dict) -> dict:
    name = library_name(library)
    source_url = str(library.get("sourceUrl") or library.get("source_url") or "")
    if "pypi.org" in source_url:
        return pypi_info(name)
    if "github.com" in source_url:
        return github_info(source_url)
    return npm_info(name)


def parse_date(value: str | None):
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    for candidate in (text, text.split(".")[0] + "+00:00" if "." in text else text):
        try:
            dt = datetime.fromisoformat(candidate)
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    return None


def library_name(item: dict) -> str:
    return str(item.get("library") or item.get("name") or item.get("id") or "unknown")


def quality_flags(item: dict) -> list[str]:
    flags: list[str] = []
    doc_count = int(item.get("documentCount") or item.get("document_count") or 0)
    unique_count = int(item.get("uniqueUrlCount") or item.get("unique_url_count") or 0)
    source_url = str(item.get("sourceUrl") or item.get("source_url") or "")
    if doc_count == 0:
        flags.append("zero-docs")
    elif doc_count <= 5:
        flags.append("low-document-count")
    if unique_count == 1:
        flags.append("single-source-url")
    if "npmjs.com/package/" in source_url:
        flags.append("package-registry-source")
    return flags


def infer(item: dict, info: dict) -> dict:
    status = str(item.get("status") or "unknown")
    doc_count = int(item.get("documentCount") or item.get("document_count") or 0)
    indexed_at = item.get("indexedAt") or item.get("indexed_at")
    flags = quality_flags(item)
    if status == "failed" or doc_count == 0:
        verdict = "failed"
        action = "fix source URL and re-scrape"
        urgency = "high"
    elif not info.get("available"):
        verdict = "unknown"
        action = "manual registry/source review"
        urgency = "low"
    else:
        indexed_dt = parse_date(indexed_at)
        registry_dt = parse_date(info.get("latest_published"))
        if indexed_dt and registry_dt and registry_dt > indexed_dt:
            verdict = "stale"
            action = "refresh if source is canonical; otherwise remove and scrape"
            urgency = "medium"
        else:
            verdict = "fresh"
            action = "run quality gate and canary search"
            urgency = "low"
    if flags and verdict == "fresh":
        action = "inspect quality flags; likely remove and scrape official docs"
        urgency = "medium"
    return {"verdict": verdict, "recommended_action": action, "urgency": urgency, "quality_flags": flags}


def analyze(items: list[dict], skip_registry: bool = False) -> list[dict]:
    rows = []
    for item in items:
        info = {"registry": "skipped", "available": False} if skip_registry else registry_info(item)
        result = infer(item, info)
        rows.append({
            "library": library_name(item),
            "status": item.get("status"),
            "documentCount": item.get("documentCount") or item.get("document_count"),
            "uniqueUrlCount": item.get("uniqueUrlCount") or item.get("unique_url_count"),
            "sourceUrl": item.get("sourceUrl") or item.get("source_url"),
            "indexedAt": item.get("indexedAt") or item.get("indexed_at"),
            "registry": info,
            **result,
        })
    return rows


def render_text(rows: list[dict]) -> str:
    lines = []
    for row in rows:
        flags = ",".join(row.get("quality_flags") or []) or "-"
        lines.append(f"{row['library']}: {row['verdict']} [{row['urgency']}] flags={flags} action={row['recommended_action']}")
    return "\n".join(lines)


def render_markdown(rows: list[dict]) -> str:
    lines = ["# Docs MCP Staleness Report", "", "| Library | Verdict | Urgency | Docs | URLs | Quality flags | Action |", "|---|---|---|---:|---:|---|---|"]
    for row in rows:
        flags = ", ".join(row.get("quality_flags") or []) or "-"
        lines.append(f"| `{row['library']}` | `{row['verdict']}` | {row['urgency']} | {row.get('documentCount') or 0} | {row.get('uniqueUrlCount') or 0} | {flags} | {row['recommended_action']} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check docs-mcp-server index staleness and shallow-index flags.")
    parser.add_argument("--server-url", default="http://127.0.0.1:6280", help="Base server URL without /api")
    parser.add_argument("--docs-mcp-package", default=DEFAULT_PACKAGE, help="npx package spec to run")
    parser.add_argument("--list-json", help="Read docs-mcp list JSON from a file instead of calling the server")
    parser.add_argument("--skip-registry", action="store_true", help="Do not call npm/PyPI/GitHub registries; only emit quality flags")
    parser.add_argument("--output", choices=["text", "markdown", "json"], default="text")
    args = parser.parse_args()

    rows = analyze(load_indexed_libraries(args.server_url, args.docs_mcp_package, args.list_json), skip_registry=args.skip_registry)
    if args.output == "json":
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    elif args.output == "markdown":
        print(render_markdown(rows))
    else:
        print(render_text(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
