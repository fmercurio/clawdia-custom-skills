---
name: archiver-contextual-recall
description: Use when you need generic Archiver intake, contextual recall, and deterministic weekly health reviews.
version: 1.2.1
author: Felippe M. and Skills Lab
license: MIT
metadata:
  hermes:
    tags: [archiver, recall, links, context, weekly-review, governance]
    related_skills: [hermes-agent, github-operations]
---

# Archiver Contextual Recall

Use this skill when you need a public, company-agnostic workflow for Archiver intake, recall, and periodic control-plane health checks.

## Use this when

- You need deterministic intake with structured link/context persistence.
- You need queryable recall over SQLite + markdown results.
- You need weekly integrity, drift, and extraction health signals.
- You need safe reconciliation tooling for existing vault markdown history.

## Overview

### Hub installation

Use the full skills.sh identifier and inspect the bundle before overriding the community-source caution policy:

```bash
ARCHIVER_SKILL_ID="skills-sh/fmercurio/clawdia-custom-skills/skills/productivity/archiver-contextual-recall"
hermes skills inspect "${ARCHIVER_SKILL_ID}"
hermes skills install "${ARCHIVER_SKILL_ID}" --force
```

The complete executable bundle currently receives an expected `CAUTION` verdict because it reads runtime environment variables, invokes subprocesses for Hermes/git checks, and includes an optional cron wrapper. `--force` is appropriate only after inspection confirms those expected `python_os_environ`, `python_subprocess`, and `persistence_cron` findings and no additional or `dangerous` finding. Do not use `--yes` for a human-operated install unless non-interactive confirmation is intentional.

### Progressive disclosure

1. **Configure runtime paths**
- Set `ARCHIVER_SKILL_DIR="${HERMES_HOME:-$HOME/.hermes}/skills/archiver-contextual-recall"` for the default Hub layout.
- Set `ARCHIVER_SKILL_DIR` to the actual install directory for named profiles, external install dirs, or manual category installs (for example `.../skills/productivity/archiver-contextual-recall` or an external path).
- Set `ARCHIVER_HOME`, `ARCHIVER_VAULT`, and `ARCHIVER_DB` (all parameterizable) for all helper scripts (`archive_item.py`, `archiver_recall.py`, `backfill_link_contexts.py`, etc.).
- Provide `--archiver-home`, `--archiver-vault`, `--archiver-db` only for `archive_weekly_review.py` when explicit overrides are needed.
- `hermes` invocation surfaces the actual runtime skill directory for non-default installations; set `ARCHIVER_SKILL_DIR` accordingly.

2. **Intake**

- Use `archive_item.py` for new notes/links.
- Use `--no-extract` for deterministic ingestion in restricted environments.

3. **Recall**

- Use `archiver_recall.py` for query-based retrieval.
- Recall is read-only: `archiver_recall.py` opens the archive DB in read-only mode, performs dynamic column/table checks, and never mutates schema.

4. **Review**

- Run `archive_weekly_review.py` for daily/weekly deterministic health reviews.
- Run `archive_weekly_review_cron.py` for Hermes no-agent schedules.

5. **Reconcile**

- Use `backfill_link_contexts.py` to repair missing `links` / `link_contexts` rows from markdown history.
- `backfill_link_contexts.py --dry-run` is read-only: no database creation, backups, schema migration, FTS/trigger changes, or writes.

## Command contract

### Support files / bundle inventory

Hermes Hub bundles are allowlisted by direct path references. The runtime support set is:

- [archive_item.py](scripts/archive_item.py)
- [archive_weekly_review.py](scripts/archive_weekly_review.py)
- [archive_weekly_review_cron.py](scripts/archive_weekly_review_cron.py)
- [archiver_db.py](scripts/archiver_db.py)
- [archiver_extract_context.py](scripts/archiver_extract_context.py)
- [archiver_recall.py](scripts/archiver_recall.py)
- [backfill_link_contexts.py](scripts/backfill_link_contexts.py)
- [pdf-extraction-existing-links.md](references/pdf-extraction-existing-links.md)
- [provenance.md](references/provenance.md)
- [reconcile-kanban-archive-tasks.md](references/reconcile-kanban-archive-tasks.md)
- [weekly-review-operations.md](references/weekly-review-operations.md)
- [x-twitter-content-extraction.md](references/x-twitter-content-extraction.md)
- [archive-weekly-review.md](templates/archive-weekly-review.md)

### Prerequisites

- Python 3.10+
- SQLite schema includes `items`, `links`, `link_contexts`.
- Optional `hermes` CLI for kanban status checks.

### Defaults (overridable)

- `ARCHIVER_HOME` (default: `~/.hermes/profiles/archiver`)
- `ARCHIVER_VAULT` (default: `${ARCHIVER_HOME}/archive-vault`)
- `ARCHIVER_DB` (default: `${ARCHIVER_VAULT}/90-meta/archiver.sqlite3`)
- `ARCHIVER_KANBAN_BOARD` (default: `archive`)

### Intake

```bash
ARCHIVER_SKILL_DIR="${HERMES_HOME:-$HOME/.hermes}/skills/archiver-contextual-recall"
python3 "${ARCHIVER_SKILL_DIR}/scripts/archive_item.py" \
  --title "<title>" \
  --source "https://..." \
  --body "<message/context>" \
  --tags "tag1,tag2" \
  --json
```

### Recall

```bash
python3 "${ARCHIVER_SKILL_DIR}/scripts/archiver_recall.py" \
  --query "<search term>" \
  --limit 10 \
  --json
```

### Review

```bash
python3 "${ARCHIVER_SKILL_DIR}/scripts/archive_weekly_review.py" \
  --archiver-home /path/to/profile \
  --archiver-vault /path/to/profile/archive-vault \
  --archiver-db /path/to/archiver.sqlite3 \
  --days 30 \
  --json
```

### Cron wrapper

```bash
cp "${ARCHIVER_SKILL_DIR}/scripts/archive_weekly_review_cron.py" \
  "${HERMES_HOME:-$HOME/.hermes}/scripts/archive_weekly_review_cron.py"
chmod +x "${HERMES_HOME:-$HOME/.hermes}/scripts/archive_weekly_review_cron.py"

hermes cron create "15 9 * * 1" \
  --no-agent \
  --script archive_weekly_review_cron.py \
  --deliver origin \
  --name "archive-weekly-review"

python3 "${HERMES_HOME:-$HOME/.hermes}/scripts/archive_weekly_review_cron.py" --timeout 180 --days 30
```

### Reconciliation

```bash
python3 "${ARCHIVER_SKILL_DIR}/scripts/backfill_link_contexts.py" --dry-run --json
python3 "${ARCHIVER_SKILL_DIR}/scripts/backfill_link_contexts.py" --extract-existing --json
```

## Hardening model

- `archive_weekly_review.py` opens the archive DB read-only for review.
- `archiver_recall.py` is read-only and safe on partial/missing schema via optional-column defaults.
- `backfill_link_contexts.py --dry-run` performs a non-mutating estimate only (no DB file creation, backups, or schema changes).
- Input paths are rejected as `critical` when resolved note paths escape configured vault root.
- URL normalization covers schemeless and `://` inputs; credentials, query string, and fragment are removed.
- Index loading is fail-closed for malformed JSON or invalid schema unless `--recover-index` is explicitly set.
- All artifacts are deterministic and written atomically with mode `0600` where applicable.
- Same-day reruns replace only same-day review entries in `index.json`.

## Public/private boundary

- Deployment-specific routing, chat/group IDs, private recovery history, and branch references are intentionally excluded from this package.
- Keep those values in private overlays and include them only in deployment runtime configuration.
- See `references/provenance.md` for baseline source attribution.
