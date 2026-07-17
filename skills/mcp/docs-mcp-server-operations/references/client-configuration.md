# Client Configuration

`docs-mcp-server` exposes two important paths:

- `/mcp` — MCP client transport endpoint.
- `/api` — API endpoint used by `docs-mcp-server` CLI commands.

Do not confuse them.

## Hermes

```bash
hermes config set mcp_servers.docs-mcp-server.url https://docs-mcp.example.com/mcp
```

If auth headers are required, configure them in Hermes config using the runtime's secure configuration practices. Do not commit real tokens.

After changing MCP config, restart/reload the agent process so MCP tools are rediscovered.

## Codex CLI

```bash
codex mcp add docs-mcp-server --url https://docs-mcp.example.com/mcp
```

If the endpoint requires auth, verify the specific Codex version supports the chosen auth method before making the endpoint public.

## CLI/API Checks

```bash
npx @arabold/docs-mcp-server@2.4.2 list \
  --server-url https://docs-mcp.example.com/api \
  --output json
```

## Auth Compatibility

Before enforcing OAuth/OIDC or custom headers, test with every client that must consume the endpoint. A safe fallback is to keep the endpoint private/tunneled or publish a read-only endpoint.
