from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import Client
from mcp.types import Tool
from starlette.testclient import TestClient

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from brain_mcp.core import COMPAT_TOOL_NAMES
from brain_mcp.server import create_server


def annotation_bool(value, name: str) -> bool | None:
    aliases = {
        "readOnlyHint": "read_only_hint",
        "openWorldHint": "open_world_hint",
    }
    for candidate in (name, aliases.get(name)):
        if candidate and hasattr(value, candidate):
            return getattr(value, candidate)
        if candidate and isinstance(value, dict) and candidate in value:
            return value[candidate]
    return None


def tool_annotations(tool: Tool):
    return getattr(tool, "annotations", {})


def test_core_tool_names_and_annotations_are_exactly_four() -> None:
    async def inspect_tools() -> None:
        server = create_server(bearer_token="t" * 32)
        async with Client(server) as client:
            tools_result = await client.list_tools()
            tools = tools_result.tools
            names = [tool.name for tool in tools]
            assert names == list(COMPAT_TOOL_NAMES)
            assert len(names) == len(set(names))
            for tool in tools:
                annotations = tool_annotations(tool)
                assert annotation_bool(annotations, "readOnlyHint") is True
                assert annotation_bool(annotations, "openWorldHint") is False

    asyncio.run(inspect_tools())


def test_server_tools_return_deterministic_payloads() -> None:
    async def call_tools() -> None:
        server = create_server(bearer_token="t" * 32)
        async with Client(server) as client:
            status = await client.call_tool("brain_status", {})
            assert status.structured_content == {
                "ok": False,
                "error": "compatibility core not configured",
                "notes": "core is intentionally deterministic and read-only until configured",
            }
            search = await client.call_tool("search_brain", {"query": "query", "limit": 3})
            assert search.structured_content["ok"] is False
            assert search.structured_content["query"] == "query"
            assert search.structured_content["canonical_results"] == []
            read = await client.call_tool("read_brain_note", {"path": "notes/readme.md", "max_chars": 42})
            assert read.structured_content["ok"] is False
            assert read.structured_content["path"] == "notes/readme.md"
            pull = await client.call_tool(
                "pull_brain_context",
                {"query": "intent", "intent": "state", "max_results": 6},
            )
            assert pull.structured_content["ok"] is False
            assert pull.structured_content["query"] == "intent"
            assert pull.structured_content["intent"] == "state"

    asyncio.run(call_tools())


def test_streamable_http_requires_the_instance_bearer_token() -> None:
    token = "t" * 32
    app = create_server(bearer_token=token).streamable_http_app()

    with TestClient(app) as client:
        denied = client.post("/mcp")
        allowed = client.post("/mcp", headers={"Authorization": f"Bearer {token}"})

    assert denied.status_code == 401
    # The authenticated request reaches the protocol handler; its empty body
    # is intentionally invalid MCP rather than an authorization failure.
    assert allowed.status_code == 400
