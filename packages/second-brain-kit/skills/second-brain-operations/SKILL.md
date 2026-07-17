---
name: second-brain-operations
description: Bootstrap, connect, diagnose, and maintain a Hermes-native Second Brain. Use for a new vault, an existing vault connection, health checks, optional cron, rollback, or package lifecycle work. Do not use for a one-off lookup or a single note save.
version: 0.1.0-rc1
author: Skills Lab
license: MIT
metadata:
  hermes:
    tags: [second-brain, bootstrap, operations, doctor, lifecycle]
    related_skills: [pull-brain, push-brain, brain-search]
---

# Second Brain Operations

Operate the installable `second-brain-kit` without assuming this is the only loaded skill.

## Triggers

Use for “quero criar meu Segundo Cérebro”, “conecte este vault”, “rode o doctor”, health-check, install, rollback, uninstall, or optional cron setup.

## Anti-triggers

- A concept lookup belongs to `brain-search` or `pull-brain`.
- A durable save belongs to `push-brain`.
- Do not reorganize an existing vault automatically.

## Sequential workflow

1. Collect owner, optional organization, vault path, profile, mode, scopes, and sensitivity policy.
2. Select **new** or **existing** context.
3. For existing vaults, run read-only audit first and produce an adaptation manifest. No physical moves.
4. Run `bootstrap.py` with explicit arguments; use `--apply` only after reviewing the plan.
5. Run `install.py`; install into the configured profile and explicit `HERMES_HOME`.
6. Run `doctor.py --smoke` and fix deterministic failures.
7. Test a representative push, rebuild, pull, and health check.
8. Offer cron only when explicitly authorized. Never restart the gateway.

## Safety and optional capabilities

FTS5 is the minimum. Embeddings, OKF, Obsidian, Git remote, and cron are optional. Remote embeddings and restricted-content publication require explicit opt-in. Keep vault data, Hermes runtime, and backups separate.

OKF 1.6 static rendering is available only through the explicit adapter. A rendered page is a frozen snapshot; rebuild it after bundle changes. Large bundles produce large HTML files.

## Exit criteria

- Config validates and contains no secrets.
- Bootstrap is idempotent.
- Four skills are installed in the intended profile.
- FTS5 rebuild and representative query pass.
- Health check is silent when healthy.
- Optional missing dependencies are reported as graceful degradation.
- Rollback inventory exists; uninstall preserves vault data.

Read `references/workflow.md`, `references/knowledge-contracts.md`, and package-root documentation for details.
