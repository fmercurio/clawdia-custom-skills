from __future__ import annotations

from collections.abc import Callable
import hmac
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


class _StaticBearerTokenVerifier:
    """Verify the per-instance secret without exposing it to the HTTP surface."""

    def __init__(self, token: str) -> None:
        self._token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token, self._token):
            return None
        return AccessToken(
            token="",
            client_id="second-brain-local-client",
            scopes=["second-brain:read"],
        )


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


def create_server(
    core: CompatibilityCore | None = None,
    *,
    bearer_token: str,
    resource_server_url: str = "http://127.0.0.1:8765/mcp",
) -> MCPServer:
    """Create an MCP server exposing only the compatibility tool surface."""

    if core is None:
        core = CompatibilityCore()
    if len(bearer_token) < 32:
        raise ValueError("MCP bearer token must contain at least 32 characters")

    mcp = MCPServer(
        "second-brain-kit",
        auth=AuthSettings(
            issuer_url="https://second-brain.invalid",
            resource_server_url=resource_server_url,
            required_scopes=["second-brain:read"],
        ),
        token_verifier=_StaticBearerTokenVerifier(bearer_token),
    )

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

        if core.proposal_staging_enabled:
            @mcp.tool(name="propose_brain_delta", annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False))
            def propose_brain_delta(
                title: str,
                summary: str,
                proposed_changes: list[dict[str, str]],
                provenance: list[str],
            ) -> dict[str, Any]:
                return _safe_payload(
                    lambda: core.propose_brain_delta(
                        title=title,
                        summary=summary,
                        proposed_changes=proposed_changes,
                        provenance=provenance,
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
