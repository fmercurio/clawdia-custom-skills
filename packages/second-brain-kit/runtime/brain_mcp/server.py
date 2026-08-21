from __future__ import annotations

from collections.abc import Callable
from secrets import compare_digest
from typing import Any

from .config import CONTRACT_VERSION, contract_error_payload

try:
    from mcp.server import MCPServer
    from mcp.server.auth.provider import AccessToken
    from mcp.server.auth.settings import AuthSettings
    from mcp.types import ToolAnnotations
except Exception as exc:  # pragma: no cover
    raise RuntimeError(
        "MCP runtime is required for this module. Install dependencies using "
        "the optional runtime project (mcp>=2,<3) before importing brain_mcp.server."
    ) from exc

from .core import COMPAT_TOOL_NAMES, CompatibilityCore, V02Core


class _InstanceTokenVerifier:
    def __init__(self, access_token: str):
        self._access_token = access_token

    async def verify_token(self, token: str) -> AccessToken | None:
        if not compare_digest(token, self._access_token):
            return None
        return AccessToken(token=token, client_id="local-instance", scopes=["brain.read"])


def _safe_payload(generator: Callable[[], dict[str, Any]], core: CompatibilityCore) -> dict[str, Any]:
    try:
        return generator()
    except Exception:  # pragma: no cover
        policy = getattr(core, "policy", None)
        retrieval_mode = getattr(core, "retrieval_mode", "lexical")
        return contract_error_payload(
            resolved_intent="server",
            policy=policy,
            retrieval_mode=retrieval_mode,
            warnings=["tool_execution_error"],
            limits={},
        )


def create_server(core: CompatibilityCore | None = None, access_token: str | None = None) -> MCPServer:
    """Create an MCP server exposing only the compatibility tool surface."""

    if core is None:
        core = CompatibilityCore()

    if access_token is not None and (len(access_token) < 32 or any(char.isspace() for char in access_token)):
        raise ValueError("access token must contain at least 32 non-whitespace characters")

    server_options: dict[str, Any] = {}
    if access_token is not None:
        server_options = {
            "auth": AuthSettings(
                issuer_url="http://127.0.0.1",
                resource_server_url="http://127.0.0.1/mcp",
                required_scopes=["brain.read"],
            ),
            "token_verifier": _InstanceTokenVerifier(access_token),
        }
    mcp = MCPServer("second-brain-kit", **server_options)

    if getattr(core, "contract_version", None) == CONTRACT_VERSION and isinstance(core, V02Core):
        @mcp.tool(name=COMPAT_TOOL_NAMES[0], annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
        def brain_status() -> dict[str, Any]:
            return _safe_payload(core.brain_status, core)

        @mcp.tool(name=COMPAT_TOOL_NAMES[1], annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
        def search_brain(
            query: str,
            limit: int = 8,
            domains: list[str] | None = None,
            classifications: list[str] | None = None,
        ) -> dict[str, Any]:
            return _safe_payload(
                lambda: core.search_brain(
                    query=query,
                    domains=domains,
                    classifications=classifications,
                    limit=limit,
                ),
                core,
            )

        @mcp.tool(name=COMPAT_TOOL_NAMES[2], annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
        def read_brain_note(
            note_id: str,
            section_ref: str | None = None,
            max_chars: int = 12000,
        ) -> dict[str, Any]:
            return _safe_payload(
                lambda: core.read_brain_note(
                    note_id=note_id,
                    section_ref=section_ref,
                    max_chars=max_chars,
                ),
                core,
            )

        @mcp.tool(name=COMPAT_TOOL_NAMES[3], annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
        def pull_brain_context(
            query: str,
            intent: str | None = None,
            max_results: int = 20,
        ) -> dict[str, Any]:
            return _safe_payload(
                lambda: core.pull_brain_context(
                    query=query,
                    intent=intent,
                    max_results=max_results,
                ),
                core,
            )
    else:
        @mcp.tool(name=COMPAT_TOOL_NAMES[0], annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
        def brain_status() -> dict[str, Any]:
            return _safe_payload(core.brain_status, core)

        @mcp.tool(name=COMPAT_TOOL_NAMES[1], annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
        def search_brain(query: str, limit: int = 8) -> dict[str, Any]:
            return _safe_payload(lambda: core.search_brain(query=query, limit=limit), core)

        @mcp.tool(name=COMPAT_TOOL_NAMES[2], annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
        def read_brain_note(path: str, max_chars: int = 12000) -> dict[str, Any]:
            return _safe_payload(lambda: core.read_brain_note(path=path, max_chars=max_chars), core)

        @mcp.tool(name=COMPAT_TOOL_NAMES[3], annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
        def pull_brain_context(query: str, intent: str | None = None, max_results: int = 20) -> dict[str, Any]:
            return _safe_payload(
                lambda: core.pull_brain_context(
                    query=query,
                    intent=intent,
                    max_results=max_results,
                ),
                core,
            )

    return mcp
