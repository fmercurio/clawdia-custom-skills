# Archiver Contextual Recall + Weekly Review

Profile-agnostic Archiver package with deterministic review artifacts and runtime-safe recovery checks.

## Overview (progressive disclosure)

### Install from Hermes Hub

Inspect first, then override only the expected community-source caution findings:

```bash
ARCHIVER_SKILL_ID="skills-sh/fmercurio/clawdia-custom-skills/skills/productivity/archiver-contextual-recall"
hermes skills inspect "${ARCHIVER_SKILL_ID}"
hermes skills install "${ARCHIVER_SKILL_ID}" --force
```

The full bundle is expected to trigger `python_os_environ`, `python_subprocess`, and `persistence_cron` scanner findings because its reviewed runtime behavior reads path configuration, runs local Hermes/git checks, and provides an optional cron wrapper. Do not override additional or `dangerous` findings.

1. **Install and configure environment**
   - Set `ARCHIVER_HOME`, `ARCHIVER_VAULT`, `ARCHIVER_DB` (optional, all have defaults).
   - Default install location is `${HERMES_HOME:-$HOME/.hermes}/skills/archiver-contextual-recall`.
   - Set `ARCHIVER_SKILL_DIR` to the actual skill directory when installed through a named profile, external path, or manual category path.
   - Prefer running with `--json` during validation.
   - Hermes invocation and `skill_view` expose the concrete skill directory for non-default installs.

2. **Create intake and recall workflows**
   - `archive_item.py` to capture links and metadata.
   - `archiver_recall.py` to query structured links, markdown notes, and context.

3. **Run reconciliation**
   - `backfill_link_contexts.py` to add missing DB rows from existing vault files.
   - `archiver_extract_context.py` is used by intake/backfill to generate HTML/text/PDF context.

4. **Run weekly operations**
   - `archive_weekly_review.py` for deterministic health outputs.
   - `archive_weekly_review_cron.py` for Hermes no-agent cron.

## Runtime commands

```bash
ARCHIVER_SKILL_DIR="${HERMES_HOME:-$HOME/.hermes}/skills/archiver-contextual-recall"

python3 "${ARCHIVER_SKILL_DIR}/scripts/archive_item.py" --title "..." --source "https://example.com" --body "..." --json
python3 "${ARCHIVER_SKILL_DIR}/scripts/archiver_recall.py" --query "..." --limit 10 --json
python3 "${ARCHIVER_SKILL_DIR}/scripts/backfill_link_contexts.py" --dry-run --json
python3 "${ARCHIVER_SKILL_DIR}/scripts/archive_weekly_review.py" --days 30 --json
python3 "${ARCHIVER_SKILL_DIR}/scripts/archive_weekly_review_cron.py" --timeout 300 --days 30
```

## Defaults and configuration

- `ARCHIVER_HOME` (default: `~/.hermes/profiles/archiver`)
- `ARCHIVER_VAULT` (default: `${ARCHIVER_HOME}/archive-vault`)
- `ARCHIVER_DB` (default: `${ARCHIVER_VAULT}/90-meta/archiver.sqlite3`)
- `ARCHIVER_KANBAN_BOARD` (default: `archive`)

`ARCHIVER_HOME`, `ARCHIVER_VAULT`, and `ARCHIVER_DB` configure all helper scripts.
`--archiver-home`, `--archiver-vault`, `--archiver-db` only apply to
`archive_weekly_review.py` CLI:

- `--kanban-board` remains available on `archive_weekly_review.py` and pairs with
  `ARCHIVER_KANBAN_BOARD`.

Hermes no-agent cron setup example:

```bash
cp "${ARCHIVER_SKILL_DIR}/scripts/archive_weekly_review_cron.py" \
  "${HERMES_HOME:-$HOME/.hermes}/scripts/archive_weekly_review_cron.py"
chmod +x "${HERMES_HOME:-$HOME/.hermes}/scripts/archive_weekly_review_cron.py"

hermes cron create "15 9 * * 1" \
  --no-agent \
  --script archive_weekly_review_cron.py \
  --deliver origin \
  --name "archive-weekly-review"
```

## Deterministic review artifacts

`archive_weekly_review.py` writes:

- `YYYY-MM-DD.json`
- `YYYY-MM-DD.md`
- `latest.json`
- `latest.md`
- `index.json`

All payloads are stable and written atomically with mode `0600`. Same-day re-runs overwrite only that day’s review entry in `index.json` while keeping the remainder of history intact.

## Runtime safety behavior

- `archiver_recall.py` opens the archive DB in read-only mode and performs no schema migration or writes.
- `backfill_link_contexts.py` with `--dry-run` performs a strict read-only pass only: no DB file is created, no backups are written, and no schema/FTS/trigger changes are performed.
- Escaped/missing item paths are critical findings.
- URL normalization redacts credentials, query strings, and fragments for both schemeless and standard URL forms.
- Kanban board is parameterized through `--kanban-board`/`ARCHIVER_KANBAN_BOARD`.
- Index loading is fail-closed on malformed JSON or schema mismatch unless `--recover-index` is explicitly passed.
- Path, checksum, and size metadata are tracked in `index.json`.

## Governance notes

- The package intentionally includes only public controls and placeholders.
- Deployment routing, chat/group identifiers, private overlays, and historical recovery branches remain in private overlays and are not embedded in public files.

## Verification commands

```bash
python3 tools/validate_skill.py skills/productivity/archiver-contextual-recall/SKILL.md
python3 -m pytest skills/productivity/archiver-contextual-recall/tests/test_archive_weekly_review.py
python3 -m py_compile \
  skills/productivity/archiver-contextual-recall/scripts/*.py \
  skills/productivity/archiver-contextual-recall/tests/test_archive_weekly_review.py
```
