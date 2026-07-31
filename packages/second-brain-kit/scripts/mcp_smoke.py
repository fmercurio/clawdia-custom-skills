#!/usr/bin/env python3
"""Run a deterministic MCP smoke check against a URL or injected client object."""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from mcp.client import Client

EXPECTED_READ_ONLY_TOOLS = (
    "brain_status",
    "search_brain",
    "read_brain_note",
    "pull_brain_context",
)


def _annotation_bool(value: object, name: str) -> bool | None:
    aliases = {"readOnlyHint": "read_only_hint", "openWorldHint": "open_world_hint"}
    for candidate in (name, aliases.get(name)):
        if candidate and hasattr(value, candidate):
            return getattr(value, candidate)
        if candidate and isinstance(value, dict) and candidate in value:
            return value[candidate]
    return None


def _result_payload(tools: list[Any]) -> dict:
    found = [tool.name for tool in tools]
    non_read_only = [
        tool.name for tool in tools
        if _annotation_bool(getattr(tool, "annotations", None), "readOnlyHint") is not True
        or _annotation_bool(getattr(tool, "annotations", None), "openWorldHint") is not False
    ]
    return {
        "ok": found == list(EXPECTED_READ_ONLY_TOOLS) and not non_read_only,
        "expected": list(EXPECTED_READ_ONLY_TOOLS),
        "found": found,
        "non_read_only": non_read_only,
    }


async def run_smoke(client: Client) -> dict:
    async with client:
        tools_result = await client.list_tools()
        return _result_payload(list(tools_result.tools))


def _require_url(url: str) -> str:
    if not url:
        raise ValueError("--url is required")
    return url


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        payload = asyncio.run(run_smoke(Client(_require_url(args.url))))
    except Exception as exc:  # noqa: BLE001
        payload = {"ok": False, "error": str(exc), "expected": list(EXPECTED_READ_ONLY_TOOLS), "found": []}
    else:
        if not payload.get("ok"):
            payload["missing"] = [name for name in EXPECTED_READ_ONLY_TOOLS if name not in payload["found"]]
            payload["extra"] = [name for name in payload["found"] if name not in EXPECTED_READ_ONLY_TOOLS]

    output = json.dumps(payload, ensure_ascii=False, indent=2)
    print(output)
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
