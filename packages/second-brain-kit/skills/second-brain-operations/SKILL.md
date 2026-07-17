---
name: second-brain-operations
description: Bootstrap, connect, diagnose, and maintain a Hermes-native Second Brain. Use for a new vault, an existing vault connection, health checks, optional cron, rollback, or package lifecycle work. Do not use for a one-off lookup or a single note save.
version: 0.1.0-rc2
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

1. If the task is setup/installation and package source is available, open `docs/agent-guided-setup.md` and follow it verbatim.
2. Collect owner, optional organization, vault path, profile, mode, scopes, and sensitivity policy.
3. Select **new** or **existing** context.
4. For existing vaults, run read-only audit first and produce an adaptation manifest. No physical moves.
5. Run `bootstrap.py` with explicit arguments; use `--apply` only after reviewing the plan.
6. Run `install.py`; install into the configured profile and explicit `HERMES_HOME`.
7. Run `doctor.py --smoke --check-optional` and fix deterministic failures.
8. Test rebuild, representative search/pull, and health check. Run a disposable push probe only for a new empty vault after authorization; never write to an existing vault during onboarding without separate approval.
9. Offer cron only when explicitly authorized. Never restart the gateway.
10. Ask one blocking question at a time and always include a recommended default plus reason, including during post-install changes.

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

## Setup interview mode

Use when this package is being onboarded by another agent.
- Start from `docs/agent-guided-setup.md`.
- Preserve the one-question-at-a-time pattern with defaults and reasons through setup and any follow-up deployment-safe adjustments.
- Never ask for environment details that are already available from files or process state.
