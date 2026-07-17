# Docs MCP Server Operations

Candidate public skill for deploying and maintaining a shared `@arabold/docs-mcp-server` instance for Hermes, Codex, and other MCP clients.

This package is intentionally generic:

- no customer/project-specific repository names;
- no secrets or credential examples with real values;
- templates use placeholders and example domains;
- scripts read credentials only from environment variables.

## Files

- `SKILL.md` — main operational runbook.
- `references/` — detailed background and decision notes.
- `templates/` — starter Docker/CapRover/docs registry files.
- `scripts/` — deterministic helpers for dependency scanning and docs staleness reports.

## Minimal validation

```bash
python3 ../../../tools/validate_skill.py SKILL.md
python3 -m py_compile scripts/*.py
python3 scripts/check_docs_staleness.py --help
python3 scripts/scan_repo_packages.py --help
```

Do not publish a deployment report without real health, list, search, staleness, and persistence checks.
