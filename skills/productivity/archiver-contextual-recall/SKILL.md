---
name: archiver-contextual-recall
description: Deterministic weekly Archiver capture and recall review.
version: 1.1.0
author: Felippe M. and Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [archiver, recall, archive, weekly-review, governance, ops]
    related_skills: [hermes-agent, github-operations, hermes-runtime-ops]
---

# Archiver Contextual Recall

Use this skill for Felippe’s contextual link recall and weekly operational governance in
the Hermes Archiver profile.

## Overview

The skill keeps recall behavior intact and adds a deterministic weekly review that audits:

- capture integrity (`items`, `links`, `link_contexts` relations),
- extraction quality (`failed`/`body_only` contexts, duplicate links),
- curation pressure (`inbox` backlog),
- repo and Kanban health.

The review payload schema is `archive-weekly-review.v1`.

## When to Use

Use this skill when the request is about:

- periodic Archiver hygiene checks,
- capture failures, missing notes, duplicates, or invalid relations,
- curation backlog and weekly context retention,
- operational health review for Archiver profile.

## Prerequisites

- Archiver profile: `~/.hermes/profiles/archiver`
- Archive DB: `~/.hermes/profiles/archiver/archive-vault/90-meta/archiver.sqlite3`
- Vault root: `~/.hermes/profiles/archiver/archive-vault`
- Installed package script:
  `~/.hermes/skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review.py`
- Cron wrapper copied to: `~/.hermes/scripts/archive_weekly_review_cron.py`

## How to Run

- Main command: `archive_weekly_review.py`
- `--days` defaults to `30` and **must** be greater than `0`.
- `--no-write` keeps inspection-only mode.
- `--json` prints payload to stdout.

## Quick Reference

```bash
python3 ~/.hermes/skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review.py --days 30 --json
```

```bash
python3 ~/.hermes/skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review.py --days 30 --no-write
```

```bash
python3 ~/.hermes/scripts/archive_weekly_review_cron.py --days 30
```

## Procedure

1. Run review in write mode to refresh artifacts.

```bash
python3 ~/.hermes/skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review.py \
  --archiver-home ~/.hermes/profiles/archiver \
  --output-dir ~/.hermes/profiles/archiver/reports/archive-reviews \
  --days 30
```

2. Confirm artifacts:

- `YYYY-MM-DD.json`
- `YYYY-MM-DD.md`
- `latest.json`
- `latest.md`
- `index.json`

`latest.json` and `latest.md` must be byte-identical to their dated counterparts.

3. Copy the packaged wrapper into the Hermes cron script sandbox:

```bash
cp ~/.hermes/skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review_cron.py \
  ~/.hermes/scripts/archive_weekly_review_cron.py
```

4. Configure a no-agent Hermes cron job:

```bash
hermes cron create "15 9 * * 1" \
  --no-agent \
  --script archive_weekly_review_cron.py \
  --deliver origin \
  --name "archive-weekly-review"
```

The wrapper must live under `~/.hermes/scripts/`; the main implementation remains
inside the installed skill package. With no arguments, the main script uses the
30-day review window by default.

## Artifacts and schema notes

`archive_weekly_review.py` emits:

- `schema`
- `generated_at`
- `date`
- `scope`
- `status` (`healthy|attention|critical`)
- `summary`
- `metrics`
- `findings`
- `artifacts`

`artifacts` includes canonical paths and points to `index.json` as the checksum registry.

## Status policy

- `critical`: SQLite integrity issues, foreign-key violations, missing paths, orphaned rows,
  or missing link contexts.
- `attention`: failed/body-only extraction signals, duplicate URLs, inbox backlog,
  dirty git worktree.
- `info`: Kanban unavailable.

Info findings do not change `critical`/`healthy` status.

## Pitfalls

1. Distinguish capture integrity from operational backlog.
   - Integrity signals indicate possible corruption or schema drift.
   - Inbox backlog is operational backlog, not immediate corruption.
2. URL normalization redacts query params, fragments, and credentials.
3. Do not include raw extracted text in findings.
4. `~/.hermes/scripts` is the Hermes cron sandbox for scheduled scripts.
5. Do not run live DB mutations during review.

## Verification

- `python3 tools/validate_skill.py skills/productivity/archiver-contextual-recall/SKILL.md`
- `python3 -m pytest skills/productivity/archiver-contextual-recall/tests`
- `python3 -m py_compile` on package scripts
- regenerate `MANIFEST.sha256` and verify checksums
- `git diff --check`
- `git status --short`
