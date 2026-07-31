# Agent-Neutral Brain MCP Reference

## Scope

This document describes the canonical read-only reference surface for a generic Brain MCP layer before any tenant-specific policies are attached.

## Layer Model

- **Core layer**: canonical Markdown/Git vault semantics, tool contracts, contract constraints, and query/read invariants.
- **Core/policy layer**: input validation, authorization/sensitivity/path/bounds enforcement, retrieval filtering, and safety gatekeeping.
- **Index layer**: rebuildable projection (preferably outside vault/repo), refreshed by explicit rebuild and used for deterministic search-like retrieval only.
- **Transport layer**: MCP-facing request/response endpoint that exposes only the v0.1 tool contracts.
- **Thin adapter layer**: protocol adaptation only; policy enforcement never lives at the adapter boundary.

## Indexing Model

- Vault content is canonical source.
- Search index is rebuildable and separate from the vault.
- Index rebuild is a separate action and is not part of default read tool behavior.
- Canonical search/pull responses exclude restricted results, and retrieval may additionally filter preexisting restricted index rows at query time.

## Security Posture

- Read-first posture: the v0.1 contract exposes only read operations.
- No generic write APIs are part of this slice.
- No shell execution API is part of this slice.
- No filesystem write API is part of this slice.
- No git write or arbitrary SQL execution API is part of this slice.
- No policy-bypass endpoint is part of this slice.
- Errors stay local; no implicit egress path is introduced by contract behavior.

## Multi-Profile and Deployment Assumption

- Profiles represent configuration profiles only and are not interpreted as physical trust domains.
- Transport and runtime separation is maintained: one MCP layer receives tool calls, the shared core/policy layer enforces contract constraints, and the thin adapter converts to vault-safe operations.
- The model remains local-first with deterministic fixtures and deterministic tests.

## v0.1 Boundaries

- The compatibility surface is intentionally limited to:
  - status signal
  - lexical search
  - bounded note read
  - context pull with typed intent fallback
- Anything not in this surface remains unsupported until explicitly planned.
