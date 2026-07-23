# Weekly Review Operations: Archiver Contextual Recall

## Overview

`archive_weekly_review.py` emits `archive-weekly-review.v1` artifacts for weekly operational governance.

## Review schema

- `schema`: `archive-weekly-review.v1`
- `generated_at`: ISO8601 timestamp
- `date`: report date (`YYYY-MM-DD`)
- `scope`: operational boundaries used for the run
- `status`: `healthy|attention|critical`
- `summary`
- `metrics`
- `findings`
- `artifacts`

The dated JSON and markdown artifacts are canonical outputs.
`latest.json` and `latest.md` are mirrors of those artifacts.
`index.json` stores deterministic registry metadata (paths, sizes, hashes).

## Metrics contract

- `items_total`, `links_total`, `link_contexts_total`
- `item_status_counts`
- `context_status_counts`
- `missing_note_paths`
- `orphan_links`
- `orphan_contexts`
- `missing_contexts`
- `duplicate_urls`
- `failed_contexts`
- `body_only_contexts`
- `recent` (bounded by `--days`)
- `markdown_notes`
- `git`
- `kanban`

Rows without parseable timestamps are counted as `unparseable`.

## Finding policy

- `critical`
  - SQLite integrity not `ok`
  - foreign key violations
  - missing note paths
  - orphan links
  - orphan contexts
  - links with missing context rows
- `attention`
  - failed/body_only context statuses
  - duplicate normalized URLs
  - inbox backlog in review window
  - dirty git worktree
- `info`
  - Kanban unavailable

Critical dominates attention. Info does not affect run status.

## URL normalization

- Lowercases scheme and hostname, preserving normalized ports.
- Strips credentials, query params, fragments.
- Uses conservative stripping for schemeless URL-like values without leaking query/fragment/userinfo.

## Cron scheduling

Use Hermes cron semantics, not system `crontab`.

Wrapper path at runtime:

`~/.hermes/scripts/archive_weekly_review_cron.py`

No-agent jobs should run:

```bash
~/.hermes/scripts/archive_weekly_review_cron.py --days 30
```

Recommended schedule example (local time):

```
15 9 * * 1
```

Scripts used by Hermes cron jobs must live under `~/.hermes/scripts/`.

Create the no-agent job with:

```bash
hermes cron create "15 9 * * 1" \
  --no-agent \
  --script archive_weekly_review_cron.py \
  --deliver origin \
  --name "archive-weekly-review"
```

Only the wrapper is copied to `~/.hermes/scripts/`; it executes the main script
from the installed skill package through `sys.executable` without a shell.

## Command contract

Kanban status check uses:

```bash
hermes kanban list --archived --json
```

with `HERMES_KANBAN_BOARD=archive`.

## Review command contract and recoverability

Use explicit recovery only when intentional:

```bash
python3 .../archive_weekly_review.py --recover-index --days 30 --json
```

Private runtime routing and profile IDs should remain in deployment overlays.
