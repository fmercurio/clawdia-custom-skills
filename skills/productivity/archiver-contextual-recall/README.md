# Archiver Contextual Recall + Weekly Review

Profile-agnostic Archiver package with deterministic review artifacts and runtime-safe recovery checks.

**v1.3.0 source candidate — not an instruction to deploy or migrate a live archive.**

## Capture and recall foundation

- HTML capture ignores executable/style/template and structural navigation noise while retaining visible technical code. Metadata-only/insufficient pages are not reported as useful extracted text. Plain text is not parsed as HTML.
- Capture reports `capture_quality`, `capture_coverage`, and versioned `capture_metadata` with observed bounds/provenance. These are deterministic parser heuristics, not human review or factual validation. `extracted` alone on an old row does not prove useful content.
- The automatic summary is a **prefix**, not an LLM or curated synthesis. New intake stores it as `source_summary`; `user_context` preserves the supplied annotation separately. Legacy mixed `summary` values remain unchanged and are not retroactively assigned authorship.
- `--capability` and `--use-case` are repeatable explicit labels, stored on the item and in Markdown frontmatter. They are never inferred from keywords or treated as verified practical capabilities.
- Recall searches titles (including the extracted title), descriptions, tags, keywords, annotations, source text and explicit labels. It uses the existing FTS5 index where available with a lexical fallback for old/missing indexes. It does not rebuild an index during search.
- Query results keep relevance through SQLite/Markdown merging and expose matched fields, a bounded snippet and score. Empty-query listing remains chronological. Legacy capture quality/coverage stays `unknown`.
- Search is lexical, accent-insensitive, and optionally assisted by FTS5/BM25; it is not semantic retrieval or automatic PT/EN translation. Up to 12 meaningful query tokens of 48 characters participate; snippets are at most 240 characters. The small-vault implementation scans eligible rows/notes before ranking instead of excluding old matches, so scan cost grows with the archive. Output honors the requested positive limit. Same-note results never borrow capture quality from a different source URL.
- Read-only connections use SQLite URI `mode=ro` plus `query_only`, with no schema migration or chmod on read/close. These CLI helpers retain the existing descriptor-pinned connection lifecycle, which changes the process working directory until close; they are not a thread-safe connection-pool API. SQLite WAL reader coordination is not a promise of immutable live sidecar bytes.
- Explicit re-extraction preserves an existing successful source capture if a new attempt fails or drops known quality. Weekly review flags metadata-only/insufficient/unsupported source captures. Backfill snapshots committed SQLite state, including WAL data, **before** adding schema columns.

### Additive storage contract

The writer adds `items.capabilities` / `use_cases` (JSON arrays), plus
`link_contexts.user_context`, `source_summary`, `capture_quality`,
`capture_coverage`, and `capture_metadata` (JSON object). New fields on legacy
rows default to empty/unknown; migration does not re-fetch or fabricate evidence.
The legacy `items`, `links`, `link_contexts`, IDs, URLs and notes remain.

`capture_quality`: `usable`, `limited`, `metadata_only`, `empty`, `unknown`.
`capture_coverage`: `bounded_text`, `truncated`, `metadata_only`, `none`, `unknown`.
The metadata schema is `archiver-capture.v1`. It describes observed transport,
parser method and truncation; it does not claim the entire page/site/video was
read. Keep capture status separate from editorial review and evaluation/adoption.

HTML capture is a static-parser heuristic, not a rendered-browser or CSS-cascade
inspection. Obvious hidden ancestors remain excluded, even around a nested
`main`/`article`; malformed wrappers are not guessed visible. Preferred empty
regions fall back to other visible text. Visible text below 200 characters is
`limited`, while known exact loading/JavaScript placeholders are
`insufficient_text`. JavaScript execution, OCR, video inspection and full-site
coverage are not provided. Invalid legacy quality/coverage labels return
`unknown`, not review/adoption or complete-coverage claims.

Example for an **isolated**, explicitly selected archive:

```bash
ARCHIVER_HOME=/path/to/disposable-archive \
python3 "$ARCHIVER_SKILL_DIR/scripts/archive_item.py" \
  --title "Video editing reference" --source "https://example.com/editor" \
  --body "Potential candidate; not installed or tested." \
  --capability "video editing" --use-case "improve a draft video" \
  --no-extract --json
```

### Deliberately outside this slice

No automatic duplicate merging, source-identity migration, append-only capture
ledger, concurrent resend idempotency, embeddings, bulk refresh, runtime sync,
or deployment. Intake still creates one item per invocation; check for an
existing source before calling it. Distinct documentation/repository notes can
legitimately reference the same product. Filesystem+database intake is not a
cross-resource atomic transaction; operational recovery remains necessary after
an interrupted writer. Do not present a source candidate as production-ready
without a separately authorized backup/restore and promotion rehearsal.

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
python3 -m pytest -q skills/productivity/archiver-contextual-recall/tests
python3 -m py_compile \
  skills/productivity/archiver-contextual-recall/scripts/*.py \
  skills/productivity/archiver-contextual-recall/tests/*.py
python3 tools/generate_catalog.py --check
```
