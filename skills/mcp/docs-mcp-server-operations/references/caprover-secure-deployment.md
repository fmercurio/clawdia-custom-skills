# CapRover Secure Deployment for Docs MCP Server

This reference describes a safe CapRover-style deployment for `@arabold/docs-mcp-server`. The same rules apply to any Docker hosting platform.

## Goal

Run a persistent docs MCP server with:

- app port `6280`;
- persistent store at `/data`;
- optional embeddings;
- private write/admin operations;
- read-only or authenticated public access.

## Files

Use these templates as a starting point:

- `templates/Dockerfile`
- `templates/captain-definition.json`
- `templates/docs-projects.example.yaml`

## CapRover Settings

| Setting | Value |
|---|---|
| App port | `6280` |
| Persistent directory path in app | `/data` |
| Domain | optional; prefer private first |
| HTTPS | enable only after the app is stable |
| WebSocket | enable if required by the MCP transport/client |

## Environment Variables

Minimum:

```bash
NODE_ENV=production
DOCS_MCP_TELEMETRY=false
```

OpenAI embeddings:

```bash
OPENAI_API_KEY=<set-in-platform-secret-store>
```

OpenAI-compatible embeddings:

```bash
OPENAI_API_BASE=https://embedding.example.com/v1
OPENAI_API_KEY=<set-in-platform-secret-store>
```

GitHub scanning:

```bash
GITHUB_TOKEN=<read-only-token>
```

Never commit these values.

## Start Commands

Private/admin-capable deployment:

```bash
docs-mcp-server server \
  --protocol http \
  --host 0.0.0.0 \
  --port 6280 \
  --store-path /data \
  --resume \
  --telemetry=false
```

Public read-only deployment:

```bash
docs-mcp-server server \
  --protocol http \
  --host 0.0.0.0 \
  --port 6280 \
  --store-path /data \
  --resume \
  --telemetry=false \
  --read-only
```

If using embeddings, append:

```bash
--embedding-model openai:text-embedding-3-small
```

Use the model string that matches your provider.

## Verification Commands

From inside the container or through a private tunnel:

```bash
BASE="http://127.0.0.1:6280"

curl -fsS "$BASE/web/stats"

npx @arabold/docs-mcp-server@2.4.2 list \
  --server-url "$BASE/api" \
  --output json
```

Index and search a canary library:

```bash
npx @arabold/docs-mcp-server@2.4.2 scrape vite https://vite.dev/guide/ \
  --server-url "$BASE/api" \
  --output json

npx @arabold/docs-mcp-server@2.4.2 search vite "import.meta.env" \
  --server-url "$BASE/api" \
  --output json
```

Persistence check:

```bash
npx @arabold/docs-mcp-server@2.4.2 list --server-url "$BASE/api" --output json > /tmp/before.json
# restart app/container
npx @arabold/docs-mcp-server@2.4.2 list --server-url "$BASE/api" --output json > /tmp/after.json
jq length /tmp/before.json /tmp/after.json
```

## Emergency Response: Admin Exposed Publicly

If a public endpoint can scrape/refresh/remove without auth:

1. Remove the public route or switch to `--read-only` immediately.
2. Rotate any tokens that may have appeared in logs or config.
3. Review access logs for unexpected scrape/fetch activity.
4. Re-enable access only after auth or read-only mode is validated.
