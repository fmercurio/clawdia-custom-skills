from __future__ import annotations

from typing import Any

try:
    from mcp.server import MCPServer
    from mcp.types import ToolAnnotations
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "MCP runtime is required for this module. Install dependencies using "
        "the optional runtime project (mcp>=2,<3) before importing brain_mcp.server."
    ) from exc

from .core import COMPAT_TOOL_NAMES, CompatibilityCore


def _safe_payload(generator):
    try:
        return generator()
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc)}


def create_server(core: CompatibilityCore | None = None) -> MCPServer:
    """Create an MCP server exposing only the compatibility tool surface."""

    if core is None:
        core = CompatibilityCore()

    mcp = MCPServer("second-brain-kit")

    @mcp.tool(name=COMPAT_TOOL_NAMES[0], annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def brain_status() -> dict[str, Any]:
        return _safe_payload(core.brain_status)

    @mcp.tool(name=COMPAT_TOOL_NAMES[1], annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def search_brain(query: str, limit: int = 8) -> dict[str, Any]:
        return _safe_payload(lambda: core.search_brain(query=query, limit=limit))

    @mcp.tool(name=COMPAT_TOOL_NAMES[2], annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def read_brain_note(path: str, max_chars: int = 12000) -> dict[str, Any]:
        return _safe_payload(lambda: core.read_brain_note(path=path, max_chars=max_chars))

    @mcp.tool(name=COMPAT_TOOL_NAMES[3], annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def pull_brain_context(query: str, intent: str | None = None, max_results: int = 20) -> dict[str, Any]:
        return _safe_payload(lambda: core.pull_brain_context(query=query, intent=intent, max_results=max_results))

    return mcp
