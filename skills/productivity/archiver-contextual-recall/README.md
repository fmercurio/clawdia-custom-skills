# Archiver Contextual Recall + Weekly Review

This package adds a deterministic Archiver weekly review on top of existing contextual recall behavior.
It only reads archive DB and note paths and writes audit artifacts in local `~/.hermes` paths.

## Overview

The review run writes:

- `YYYY-MM-DD.json`
- `YYYY-MM-DD.md`
- `latest.json`
- `latest.md`
- `index.json`

`index.json` stores checksum registry entries and is the canonical map for persisted artifacts.

## When to Use

Use this package when requesting:

- periodic Archiver operational governance,
- capture integrity checks (missing notes, orphan rows, failed contexts),
- duplicate/normalization signal checks,
- backlog visibility for `inbox` and curation pacing.

## Prerequisites

- Archive home: `~/.hermes/profiles/archiver`
- Archive DB: `~/.hermes/profiles/archiver/archive-vault/90-meta/archiver.sqlite3`
- Installed main script:
  `~/.hermes/skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review.py`
- Cron wrapper copied to: `~/.hermes/scripts/archive_weekly_review_cron.py`

## How to Run

- `--days` must be greater than `0`.
- Default review window is `--days 30`; keep 30 for weekly backlog context.
- No command runs with a shell, only direct process arguments.

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

1. Write full artifacts:

```bash
python3 ~/.hermes/skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review.py \
  --archiver-home ~/.hermes/profiles/archiver \
  --output-dir ~/.hermes/profiles/archiver/reports/archive-reviews \
  --days 30
```

2. Print payload only:

```bash
python3 ~/.hermes/skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review.py --days 30 --json
```

3. Run in inspection mode (no files written):

```bash
python3 ~/.hermes/skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review.py --no-write --days 30
```

4. Copy the wrapper into the Hermes cron script sandbox:

```bash
cp ~/.hermes/skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review_cron.py \
  ~/.hermes/scripts/archive_weekly_review_cron.py
```

5. Create the no-agent job using Hermes cron semantics (not system `crontab`):

```bash
hermes cron create "15 9 * * 1" \
  --no-agent \
  --script archive_weekly_review_cron.py \
  --deliver origin \
  --name "archive-weekly-review"
```

The schedule is Mondays at 09:15 local time (`15 9 * * 1`).

## Pitfalls

- `latest.json` and `latest.md` are byte-identical to the dated files.
- `index.json` is authoritative for SHA-256 and byte sizes of persisted artifacts.
- URL redaction removes query, fragment, and credentials before persistence.
- Kanban lookup failures are reported as info-only and do not force critical status.
- Schema validation failures, foreign key violations, and critical integrity failures are marked critical.

## Verification

- `python3 tools/validate_skill.py skills/productivity/archiver-contextual-recall/SKILL.md`
- `python3 -m pytest skills/productivity/archiver-contextual-recall/tests`
- `python3 -m py_compile $(find skills/productivity/archiver-contextual-recall/scripts -name '*.py')`
- Regenerate and verify `skills/productivity/archiver-contextual-recall/MANIFEST.sha256`
- `git diff --check`
- `git status --short`
