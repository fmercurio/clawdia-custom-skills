from __future__ import annotations

import asyncio
import sys
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from mcp import Client
from mcp.types import Tool

from brain_mcp.core import COMPAT_TOOL_NAMES, V02Core
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


def policy_data() -> dict:
    return {
        "schema_version": "v0.2",
        "contract_version": "v0.2",
        "policy_id": "server-policy",
        "policy_version": "policy-001",
        "allowed_domains": ["engineering", "research", "product"],
        "allowed_classifications": ["public", "internal"],
        "allowed_sensitivities": ["low", "medium"],
        "default_decision": "allow",
    }


def records() -> list[dict]:
    return [
        {
            "frontmatter": {
                "id": "alpha-note",
                "title": "Alpha Note",
                "domain": "engineering",
                "classification": "public",
                "sensitivity": "low",
            },
            "content": "alpha planning update for server context tests",
        },
        {
            "frontmatter": {
                "id": "pii-note",
                "title": "PII Note",
                "domain": "engineering",
                "classification": "public",
                "sensitivity": "low",
            },
            "content": "contact analyst@example.com with details",
        },
    ]


def test_v02_mcp_server_exposes_four_readonly_tools() -> None:
    async def inspect() -> None:
        server = create_server(core=V02Core(policy_data(), records()), bearer_token="t" * 32)
        async with Client(server) as client:
            tools_result = await client.list_tools()
            tools = tools_result.tools
            names = [tool.name for tool in tools]
            assert names == list(COMPAT_TOOL_NAMES)
            assert len(names) == 4
            for tool in tools:
                annotations = tool_annotations(tool)
                assert annotation_bool(annotations, "readOnlyHint") is True
                assert annotation_bool(annotations, "openWorldHint") is False

    asyncio.run(inspect())


def test_v02_mcp_server_structured_v02_payloads() -> None:
    async def inspect() -> None:
        server = create_server(core=V02Core(policy_data(), records()), bearer_token="t" * 32)
        async with Client(server) as client:
            search = await client.call_tool(
                "search_brain",
                {
                    "query": "alpha",
                    "limit": 5,
                    "domains": ["engineering"],
                    "classifications": ["public"],
                },
            )
            payload = search.structured_content
            assert payload["status"] == "ok"
            assert payload["contract_version"] == "v0.2"
            assert payload["classification"] == "public"
            assert payload["state"] == "ok"
            assert payload["confidence"] in {"explicit", "inferred"}
            assert payload["selected_because"] == "search_query_match"
            assert payload["results"][0]["note_id"] == "alpha-note"
            assert payload["results"][0]["canonical_ref"] == "alpha-note"
            assert payload["citations"][0]["canonical_ref"] == "alpha-note"
            assert "note_id" not in payload["citations"][0]
            assert "path" not in payload["results"][0]
            assert "path" not in payload["citations"][0]

            read = await client.call_tool("read_brain_note", {"note_id": "alpha-note", "max_chars": 100})
            read_payload = read.structured_content
            assert read_payload["status"] == "ok"
            assert read_payload["results"][0]["note_id"] == "alpha-note"
            assert read_payload["results"][0]["canonical_ref"] == "alpha-note"
            assert read_payload["results"][0]["classification"] == "public"
            assert read_payload["results"][0]["state"] == "ok"
            assert read_payload["results"][0]["confidence"] in {"explicit", "inferred", "unknown"}
            assert "section_ref" not in read_payload["results"][0]
            assert "path" not in read_payload
            assert "path" not in read_payload["citations"][0]
            assert read_payload["citations"][0]["canonical_ref"] == "alpha-note"

            pull = await client.call_tool("pull_brain_context", {"query": "alpha", "intent": "summary", "max_results": 3})
            pull_payload = pull.structured_content
            assert pull_payload["status"] == "ok"
            assert pull_payload["resolved_intent"] == "summary"
            assert pull_payload["classification"] == "public"
            assert pull_payload["state"] == "ok"
            assert pull_payload["confidence"] in {"explicit", "inferred"}
            assert pull_payload["selected_because"] == "pull_query_match"
            assert pull_payload["citations"]
            assert all("canonical_ref" in item for item in pull_payload["citations"])
            assert all("classification" in item for item in pull_payload["citations"])
            assert all("state" in item for item in pull_payload["citations"])
            assert all("confidence" in item for item in pull_payload["citations"])

    asyncio.run(inspect())
