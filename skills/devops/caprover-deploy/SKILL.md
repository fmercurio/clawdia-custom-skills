---
name: caprover-deploy
description: "Deploy apps to CapRover with a sanitized preflight and method selection (CLI → API → Playwright). Handles app creation, GitHub repo setup, build triggering, HTTPS/WebSocket config, and post-deploy verification. Generic — no instance-specific data."
version: 1.0.0
author: FMercurio Tech
license: MIT
metadata:
  hermes:
    tags: [caprover, deploy, docker, ci-cd, automation, playwright]
    related_skills: [caprover-operations]
---

# CapRover Deploy

## Overview

Automated CapRover deployment that tries three methods in order of preference:

1. **CapRover CLI** (`caprover deploy`) — fastest, works when CLI is installed and not broken
2. **REST API v2** — programmatic, good for creating apps and setting config
3. **Playwright** — browser automation, most reliable for Force Build + HTTPS toggles

The deploy script (`scripts/caprover_deploy.py`) handles the full lifecycle:

```
authenticate → create app (if needed) → configure GitHub repo →
trigger build → poll until done → enable HTTPS + WebSocket → verify
```

## When to Use

- Deploy a new app to CapRover from a GitHub repo
- Force rebuild an existing app after pushing code
- Enable HTTPS / WebSocket on an app
- Automate CapRover deploy in CI/CD or from an agent

## Prerequisites

- **CapRover URL** (e.g. `https://captain.example.com`)
- **CapRover password** — via env var, KeePass, or interactive prompt; never CLI args
- **Git repo token** — `github.com` uses `GITHUB_TOKEN` or `gh auth token`; non-`github.com` hosts require a protected exact host-to-token binding
- **Python 3.9+** with `requests` (or `urllib` fallback)
- **Playwright** (optional, for method 3) — `pip install playwright && playwright install chromium`

## Quick Start

```bash
# Bind the reusable credential to this exact remote origin in the protected environment.
export CAPROVER_CREDENTIAL_ORIGIN=https://captain.example.com
# Bind each non-github.com host in the protected job environment, not the CLI.
export CAPROVER_REPO_TOKEN_BINDINGS='{"git.example.com":"GIT_EXAMPLE_TOKEN"}'

# Full deploy from GitHub repo
python3 scripts/caprover_deploy.py \
  --caprover-url https://captain.example.com \
  --expected-host captain.example.com \
  --app-name my-app \
  --repo https://github.com/org/repo \
  --branch main

# Full deploy from a trusted GitHub Enterprise/custom host
python3 scripts/caprover_deploy.py \
  --caprover-url https://captain.example.com \
  --expected-host captain.example.com \
  --app-name my-app \
  --repo https://git.example.com/org/repo \
  --expected-repo-host git.example.com \
  --branch main

# Force rebuild existing app
python3 scripts/caprover_deploy.py \
  --caprover-url https://captain.example.com \
  --expected-host captain.example.com \
  --app-name my-app \
  --rebuild-only

# Deploy tarball (no GitHub)
python3 scripts/caprover_deploy.py \
  --caprover-url https://captain.example.com \
  --expected-host captain.example.com \
  --app-name my-app \
  --tarball ./project.tar
```

## Authentication

The script tries these in order:

1. `CAPROVER_PASSWORD` env var
2. `--keepass-entry "/Caprover - MyOrg"` (requires `KEEPASS_DB` and `KEEPASS_KEY`)
3. Interactive prompt

GitHub token for `github.com` repos:

1. `GITHUB_TOKEN` env var
2. `gh auth token` (if GitHub CLI is installed)

Git token for non-`github.com` repos:

1. Pass `--expected-repo-host git.example.com`
2. Set `CAPROVER_REPO_TOKEN_BINDINGS` in the protected job environment, for example `{"git.example.com":"GIT_EXAMPLE_TOKEN"}`
3. Export the referenced host-specific token environment variable before running the script

The CLI cannot select a token environment variable. `--repo-token-env` is optional only as an assertion that must match the protected binding. The script does not use generic `GITHUB_TOKEN` or `gh auth token` for custom Git hosts.

Do not pass passwords or tokens through CLI arguments; process arguments are visible to local process inspection on many systems.

## URL Safety

- Use `https://` CapRover dashboard URLs by default.
- Pass `--expected-host captain.example.com` for every non-local target. Include the port in `--expected-host` when the CapRover URL uses a non-default port.
- Set `CAPROVER_CREDENTIAL_ORIGIN` in the protected job or secret environment to the exact origin associated with the CapRover credential, for example `https://captain.example.com` (or the exact local `http://127.0.0.1:port` development origin). The script checks this binding before resolving the password; a matching CLI `--expected-host` alone is not sufficient.
- Git repo URLs default to `https://github.com/org/repo`. For GitHub Enterprise or another trusted Git host, pass `--expected-repo-host git.example.com` before using `--repo`. Include the port in `--expected-repo-host` when the repo URL uses one.
- Git credentials are resolved only after the repo URL host is validated. Non-`github.com` repo hosts must have an exact protected `CAPROVER_REPO_TOKEN_BINDINGS` entry; `GITHUB_TOKEN` and `gh auth token` are reserved for `github.com`.
- `--allow-insecure` is only for local/dev targets and makes Playwright tolerate certificate errors for that run.

## CLI Safety

- CLI deployments pass the validated `--caproverUrl`, `--caproverApp`, and `--branch`/`--tarFile` explicitly.
- CapRover passwords are provided through `CAPROVER_PASSWORD` in the subprocess environment, never through CLI arguments.
- Ambient CapRover CLI config such as `CAPROVER_CONFIG_FILE`, saved machine names, app tokens, stale app names, or stale branches is ignored for the deploy subprocess.

## Method Selection

| Scenario | Best method |
|---|---|
| CLI installed, Node.js < 26 | CLI (`caprover deploy`) |
| Headless / no browser | API v2 (limited — see pitfalls) |
| API returns errors, need Force Build | Playwright |
| CI/CD pipeline | API for config + Playwright for build |

The script auto-detects and falls back. Override with `--method cli|api|playwright|auto`.

## Key Pitfalls (learned the hard way)

1. **CLI crashes on Node.js 26** — `ERR_USE_AFTER_CLOSE` on all interactive commands. Use API/Playwright.
2. **API `appData/{app}/` returns 500** for tarball/inline deploy on CapRover 1.14.x. Use Playwright Force Build.
3. **Git repo config requires credentials** even for public repos — `repoInfo` needs `user` + `password` (PAT). For non-`github.com` hosts, use a host-specific token env var. Without credentials: `status=1110`.
4. **`{gitHash: ""}` does NOT trigger a Git build** via API — only tarball/Dockerfile inline work. Use dashboard "Force build".
5. **Ant Design buttons** in the dashboard may not respond to standard clicks. Playwright with `locator().click()` works; browser automation tools may need JS fallback.
6. **HTTPS provisioning takes 10-30s** (Let's Encrypt cert generation). The script waits automatically.

## Nginx Reverse Proxy Template

If deploying an Nginx reverse proxy app, see `templates/nginx-proxy.conf` for a battle-tested template with:
- WebSocket support
- Self-signed upstream SSL
- Proper buffer sizes for ERP/large responses
- Healthcheck endpoint with correct Content-Type

## Reference

- `references/api-v2-endpoints.md` — CapRover REST API v2 quick reference
- `references/playwright-deploy-pattern.md` — Playwright dashboard automation details

## Verification Checklist

- [ ] App exists in CapRover dashboard
- [ ] Build completed without errors
- [ ] HTTPS enabled (if needed)
- [ ] WebSocket support enabled (if needed)
- [ ] App responds to healthcheck (`/healthz` or equivalent)
- [ ] Container shows 1/1 replicas (`docker service ls | grep <app>`)
