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
- **CapRover password** — via env var, KeePass, or argument
- **GitHub token** — via `gh auth token` or env var `GITHUB_TOKEN`
- **Python 3.9+** with `requests` (or `urllib` fallback)
- **Playwright** (optional, for method 3) — `pip install playwright && playwright install chromium`

## Quick Start

```bash
# Full deploy from GitHub repo
python3 scripts/caprover_deploy.py \
  --caprover-url https://captain.example.com \
  --app-name my-app \
  --repo https://github.com/org/repo \
  --branch main

# Force rebuild existing app
python3 scripts/caprover_deploy.py \
  --caprover-url https://captain.example.com \
  --app-name my-app \
  --rebuild-only

# Deploy tarball (no GitHub)
python3 scripts/caprover_deploy.py \
  --caprover-url https://captain.example.com \
  --app-name my-app \
  --tarball ./project.tar
```

## Authentication

The script tries these in order:

1. `--caprover-password` argument
2. `CAPROVER_PASSWORD` env var
3. `--keepass-entry "/Caprover - MyOrg"` (reads from KeePassXC)
4. Interactive prompt

GitHub token:

1. `GITHUB_TOKEN` env var
2. `gh auth token` (if GitHub CLI is installed)
3. `--github-user` + `--github-token` arguments

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
3. **GitHub config requires credentials** even for public repos — `repoInfo` needs `user` + `password` (PAT). Without them: `status=1110`.
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
