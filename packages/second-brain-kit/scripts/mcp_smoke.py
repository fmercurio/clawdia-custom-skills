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
PROPOSAL_STAGING_TOOL = "propose_brain_delta"
EXPECTED_PROPOSAL_STAGING_TOOLS = (*EXPECTED_READ_ONLY_TOOLS, PROPOSAL_STAGING_TOOL)


def _annotation_bool(value: object, name: str) -> bool | None:
    aliases = {"readOnlyHint": "read_only_hint", "openWorldHint": "open_world_hint"}
    for candidate in (name, aliases.get(name)):
        if candidate and hasattr(value, candidate):
            return getattr(value, candidate)
        if candidate and isinstance(value, dict) and candidate in value:
            return value[candidate]
    return None


def _expected_tools(expect_proposal_staging: bool) -> tuple[str, ...]:
    if expect_proposal_staging:
        return EXPECTED_PROPOSAL_STAGING_TOOLS
    return EXPECTED_READ_ONLY_TOOLS


def _annotations_match(tool: Any, *, read_only: bool) -> bool:
    annotations = getattr(tool, "annotations", None)
    return (
        _annotation_bool(annotations, "readOnlyHint") is read_only
        and _annotation_bool(annotations, "openWorldHint") is False
    )


def _result_payload(tools: list[Any], *, expect_proposal_staging: bool = False) -> dict:
    expected = _expected_tools(expect_proposal_staging)
    found = [tool.name for tool in tools]
    non_read_only = [
        tool.name for tool in tools
        if _annotation_bool(getattr(tool, "annotations", None), "readOnlyHint") is not True
        or _annotation_bool(getattr(tool, "annotations", None), "openWorldHint") is not False
    ]
    annotation_mismatches = []
    intentional_non_read_only = []
    unexpected_non_read_only = []

    for tool in tools:
        is_proposal_tool = expect_proposal_staging and tool.name == PROPOSAL_STAGING_TOOL
        expected_read_only = not is_proposal_tool
        annotations_match = _annotations_match(tool, read_only=expected_read_only)
        if tool.name in expected and not annotations_match:
            annotation_mismatches.append(tool.name)
        if tool.name in non_read_only:
            if is_proposal_tool and annotations_match:
                intentional_non_read_only.append(tool.name)
            else:
                unexpected_non_read_only.append(tool.name)

    return {
        "ok": found == list(expected) and not annotation_mismatches and not unexpected_non_read_only,
        "expected": list(expected),
        "expected_profile": "proposal_staging" if expect_proposal_staging else "readonly",
        "found": found,
        "non_read_only": non_read_only,
        "intentional_non_read_only": intentional_non_read_only,
        "unexpected_non_read_only": unexpected_non_read_only,
        "annotation_mismatches": annotation_mismatches,
    }


async def run_smoke(client: Client, *, expect_proposal_staging: bool = False) -> dict:
    async with client:
        tools_result = await client.list_tools()
        return _result_payload(
            list(tools_result.tools),
            expect_proposal_staging=expect_proposal_staging,
        )


def _require_url(url: str) -> str:
    if not url:
        raise ValueError("--url is required")
    return url


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument(
        "--expect-proposal-staging",
        action="store_true",
        help="require the opt-in private propose_brain_delta tool after the four read-only tools",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    expected = _expected_tools(args.expect_proposal_staging)

    try:
        payload = asyncio.run(
            run_smoke(
                Client(_require_url(args.url)),
                expect_proposal_staging=args.expect_proposal_staging,
            )
        )
    except Exception as exc:  # noqa: BLE001
        payload = {
            "ok": False,
            "error": str(exc),
            "expected": list(expected),
            "expected_profile": "proposal_staging" if args.expect_proposal_staging else "readonly",
            "found": [],
        }
    else:
        if not payload.get("ok"):
            payload["missing"] = [name for name in expected if name not in payload["found"]]
            payload["extra"] = [name for name in payload["found"] if name not in expected]

    output = json.dumps(payload, ensure_ascii=False, indent=2)
    print(output)
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
