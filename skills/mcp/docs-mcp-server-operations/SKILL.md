---
name: docs-mcp-server-operations
description: "Use when deploying, operating, or maintaining a shared Docs MCP Server for Hermes, Codex, or other MCP clients — including persistent storage, safe read-only/public exposure, embedding provider decisions, documentation indexing, staleness checks, and quality gates against shallow or broken documentation indexes."
version: 1.0.0
author: Skills Lab
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [mcp, documentation, docker, caprover, embeddings, agent-tools]
    related_skills: [native-mcp, caprover-deploy]
---

# Docs MCP Server Operations

## Overview

Use this skill to deploy and operate a shared documentation MCP server using `@arabold/docs-mcp-server` / `ghcr.io/arabold/docs-mcp-server`.

The goal is not merely to run another MCP endpoint. The goal is to maintain a **living documentation base for agents**:

- documentation sources are canonical and reviewable;
- the index persists across deploys and restarts;
- embeddings are chosen deliberately;
- public access is read-only or authenticated;
- maintenance is based on staleness and quality checks, not blind refreshes;
- clients such as Hermes, Codex, or another MCP-capable agent can search/read docs safely.

The reusable operating principle is:

> A documentation index can be temporally fresh and still useless. Always verify coverage and canary search results before declaring it ready.

## When to Use

Use when:

- A team wants Hermes, Codex, or other agents to share the same indexed documentation.
- You need to host `docs-mcp-server` on Docker, CapRover, a VPS, or an internal platform.
- You need persistent `/data` storage for the server's SQLite/vector index.
- You need a safe public or semi-public MCP endpoint for read-only documentation access.
- You are adding scripts to discover project dependencies and decide what docs to index.
- You are maintaining an existing docs index and need to decide refresh vs reindex.

Do **not** use for:

- A one-off local docs scrape where a persistent server is unnecessary.
- Exposing a write/admin documentation server directly to the public internet without auth.
- Bulk-importing unreviewed URLs, package READMEs, or third-party scripts.
- Storing API keys, bearer tokens, customer names, private repository names, or tenant IDs in examples, reports, skills, or templates.

## Customization Checklist

Before applying this skill, fill in these values in a deployment-specific file or ticket. Keep real values out of public examples.

| Placeholder | Meaning | Example |
|---|---|---|
| `<APP_NAME>` | Container/app name | `docs-mcp` |
| `<PUBLIC_ORIGIN>` | Optional HTTPS origin advertised to clients | `https://docs-mcp.example.com` |
| `<SERVER_URL>` | Base URL without `/api` or `/mcp` | `http://127.0.0.1:6280` |
| `<MCP_URL>` | Client MCP URL | `https://docs-mcp.example.com/mcp` |
| `<API_URL>` | CLI/API URL | `https://docs-mcp.example.com/api` |
| `<STORE_PATH>` | Persistent data path inside container | `/data` |
| `<EMBEDDING_PROVIDER>` | `openai`, `openai-compatible`, or `none` | `openai` |
| `<EMBEDDING_MODEL>` | Embedding model string | `openai:text-embedding-3-small` |
| `<GITHUB_TOKEN_ENV>` | Env var name for read-only GitHub access | `GITHUB_TOKEN` |
| `<DOCS_REGISTRY>` | Project/library registry path | `templates/docs-projects.example.yaml` |

## Recommended Architecture

```text
                         ┌────────────────────────────┐
                         │ docs-mcp-server             │
                         │ protocol: http              │
                         │ host: 0.0.0.0               │
                         │ port: 6280                  │
                         │ store: <STORE_PATH>         │
                         └──────────────┬─────────────┘
                                        │
             ┌──────────────────────────┴─────────────────────────┐
             │                                                    │
     private/admin path                                  public/client path
     tunnel, SSH, job, VPN                               read-only or auth
     scrape / refresh / remove                           MCP search/read
```

Safe defaults:

1. Deploy first with no public domain or behind a trusted tunnel/VPN.
2. Configure persistent storage before indexing anything.
3. Index a small canary set of libraries.
4. Run list/search/staleness/quality checks.
5. Only then connect MCP clients.
6. If exposing publicly, use `--read-only` unless authentication is proven end-to-end with every client.

## Repository Layout

Use this layout for a deployable project or for the skill package itself:

```text
docs-mcp-server-operations/
  SKILL.md
  references/
    caprover-secure-deployment.md
    quality-gate-and-canary-searches.md
    embedding-provider-decisions.md
    client-configuration.md
  templates/
    captain-definition.json
    Dockerfile
    docs-projects.example.yaml
  scripts/
    scan_repo_packages.py
    check_docs_staleness.py
```

A deployment repo can copy the `templates/` and `scripts/` files, customize `docs-projects.example.yaml`, and commit only non-secret configuration.

## Deployment Workflow

### 1. Preflight

Confirm:

- target platform supports Docker and persistent volumes;
- port `6280` can be routed to the container;
- write/admin paths are private or authenticated;
- secrets will be injected as environment variables, not committed;
- embedding provider/model are decided before first indexing;
- the deployment operator can run commands inside the container or through a private tunnel.

### 2. Build the container

Use `templates/Dockerfile` as the baseline. It pins Node 22 and installs `@arabold/docs-mcp-server@2.4.2` plus Python/JQ/Git/Curl for maintenance scripts.

Minimum server command:

```bash
docs-mcp-server server \
  --protocol http \
  --host 0.0.0.0 \
  --port 6280 \
  --store-path /data \
  --resume \
  --telemetry=false
```

For a public endpoint without validated auth, add:

```bash
--read-only
```

Use a private admin route, job, or shell session for `scrape`, `refresh`, and `remove` operations.

### 3. Decide embeddings before indexing

Options:

| Mode | Use when | Notes |
|---|---|---|
| OpenAI embeddings | You want a simple hosted provider | Set `OPENAI_API_KEY`; use a model such as `openai:text-embedding-3-small` |
| OpenAI-compatible endpoint | You run a private embedding service | Set `OPENAI_API_BASE` + `OPENAI_API_KEY`; ensure the container can reach it |
| No embeddings | You need the simplest deployment or must avoid API cost | Keyword search still works, but semantic search quality is lower |

Do **not** reuse an old data volume when changing to an embedding model with a different vector dimension. Start with a clean store or reindex everything.

See `references/embedding-provider-decisions.md`.

### 4. Configure persistent storage

Mount a persistent volume at `/data` or your chosen `<STORE_PATH>`. Without it, every redeploy loses indexed docs.

Verify persistence by indexing one library, restarting the app, and comparing `list` output before/after.

### 5. Seed canonical libraries

Start with a small set of libraries that have known official documentation URLs. Example:

```bash
BASE="http://127.0.0.1:6280"

npx @arabold/docs-mcp-server@2.4.2 scrape react https://react.dev/reference/react \
  --server-url "$BASE/api" \
  --output json

npx @arabold/docs-mcp-server@2.4.2 scrape vite https://vite.dev/guide/ \
  --server-url "$BASE/api" \
  --output json
```

Prefer official docs over npm package pages for major frameworks. Package registry READMEs are often too shallow for agent use.

### 6. Run quality gates

Run both temporal staleness and content quality checks:

```bash
python3 scripts/check_docs_staleness.py \
  --server-url http://127.0.0.1:6280 \
  --output markdown

npx @arabold/docs-mcp-server@2.4.2 search vite "import.meta.env" \
  --server-url http://127.0.0.1:6280/api \
  --output json
```

A `fresh` verdict only means the index timestamp is not older than the registry's known publish time. It does **not** prove the docs are complete or useful.

See `references/quality-gate-and-canary-searches.md`.

### 7. Maintain the index

Routine maintenance:

1. Scan project dependency manifests:
   ```bash
   python3 scripts/scan_repo_packages.py \
     --registry templates/docs-projects.example.yaml \
     --output markdown
   ```
2. Run staleness report:
   ```bash
   python3 scripts/check_docs_staleness.py \
     --server-url http://127.0.0.1:6280 \
     --output markdown
   ```
3. For `failed`, fix the URL and re-scrape.
4. For `stale`, refresh only if the source URL is canonical and high-quality.
5. For shallow `fresh` indexes, remove and scrape from the official docs URL.
6. Re-run canary searches.
7. Publish a short report without secrets.

## Refresh vs Reindex Decision

| Condition | Action |
|---|---|
| Source URL is canonical and coverage was good | `refresh <library>` |
| Source URL is a package registry README for a large framework | `remove <library>` + `scrape` official docs |
| `documentCount == 0` or status failed | fix URL + `scrape` |
| `documentCount <= 5` for a major framework | inspect; likely reindex |
| Canary search returns empty | reindex from better source |
| Embedding model changed dimensions | start clean or reindex all |

## Client Configuration

Hermes HTTP MCP configuration:

```bash
hermes config set mcp_servers.docs-mcp-server.url <MCP_URL>
```

Codex CLI:

```bash
codex mcp add docs-mcp-server --url <MCP_URL>
```

If auth headers are required, configure them in the client runtime's secure config mechanism. Do not commit tokens in repo files, skills, examples, or issue reports.

See `references/client-configuration.md`.

## Deliverable Format

When an implementation agent finishes a deployment, require a report with real command output summaries:

```markdown
## Docs MCP deployment completed

- App: `<APP_NAME>`
- MCP URL: `<MCP_URL>`
- API access: private tunnel / internal URL / protected public URL
- Exposure mode: private / read-only / authenticated
- Store path: `<STORE_PATH>` persistent
- Embeddings: `<EMBEDDING_PROVIDER>/<EMBEDDING_MODEL>`
- Indexed libraries: `<count>`

## Verification

```bash
curl .../web/stats
# summarized result

npx @arabold/docs-mcp-server@2.4.2 list --server-url .../api --output json
# summarized result

npx @arabold/docs-mcp-server@2.4.2 search vite "import.meta.env" --server-url .../api --output json
# summarized result

python3 scripts/check_docs_staleness.py --server-url ... --output text
# summarized result
```

## Risks / follow-up

- ...
```

Never include raw tokens, full private URLs with credentials, or unredacted logs.

## Common Pitfalls

1. **Public write/admin endpoint** — `docs-mcp-server` can fetch external URLs and mutate the index. Public deployments must be read-only or authenticated.
2. **Wrong route for CLI** — MCP clients use `/mcp`; `docs-mcp-server` CLI commands use `/api` via `--server-url`.
3. **Lost index after deploy** — missing persistent volume at `/data`.
4. **Embedding model changed** — vector dimension mismatch can invalidate old indexes.
5. **Registry README as docs** — npm/PyPI package pages are often shallow; use official docs for major libraries.
6. **Blind refresh cron** — refresh can preserve a bad source. Check quality before automating.
7. **Multipart scrape request** — the web job endpoint expects form-encoded data, not multipart form data.
8. **Headless GitHub scan with interactive auth** — server automation should use a read-only token from an environment variable, not an interactive CLI login.
9. **Declaring ready without canary search** — always prove at least one known query returns useful content.

## Verification Checklist

- [ ] App/container is stable and not crash-looping.
- [ ] Server listens on `0.0.0.0:6280` inside the container.
- [ ] Persistent store is mounted at `/data` or configured `<STORE_PATH>`.
- [ ] `curl <SERVER_URL>/web/stats` succeeds from the intended network path.
- [ ] `list --server-url <SERVER_URL>/api --output json` succeeds.
- [ ] At least one canonical docs source was scraped successfully.
- [ ] A canary search returns useful content.
- [ ] `check_docs_staleness.py` runs without server connectivity errors.
- [ ] Public endpoint, if any, is read-only or authenticated.
- [ ] Client MCP configuration was tested with the real client.
- [ ] No tokens, private repository names, customer names, or credentials appear in repo files, logs, reports, or examples.
