---
name: archiver-contextual-recall
description: Contextual recall plus weekly Archiver integrity reviews.
version: 1.1.0
author: Felippe M. and Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [archiver, recall, links, context, telegram, second-brain, weekly-review, governance, ops]
    related_skills: [hermes-agent, hermes-runtime-ops, github-operations]
---

# Archiver Contextual Recall

Use this skill for contextual link memory and operational governance in the Archiver profile.
It preserves the existing recall/intake/reconciliation behavior and adds weekly deterministic
review artifacts for capture health and curation backlog.

## When to Use

Use this skill when the request is about:

- contextual recall of saved links and notes;
- direct link intake in Archive Telegram;
- auditing whether shared links are truly in Archiver DB/vault;
- reconciling missing historical links through Kanban and session history;
- weekly capture integrity and backlog review.

## Prerequisites

- Profile home: `~/.hermes/profiles/archiver`.
- Archive DB: `~/.hermes/profiles/archiver/archive-vault/90-meta/archiver.sqlite3`.
- Vault root: `~/.hermes/profiles/archiver/archive-vault/`.
- Runtime scripts:
  - `~/.hermes/skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review.py`
  - `~/.hermes/skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review_cron.py`
- Cron wrapper destination: `~/.hermes/scripts/archive_weekly_review_cron.py`.

## How to Run

- Recall: `python3 ~/.hermes/profiles/archiver/scripts/archiver_recall.py --query "<consulta>" --limit 8 --json`
- Weekly review:
  - `python3 ~/.hermes/skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review.py --days 30 --json`
  - `--days` defaults to `30`; must be greater than `0`.
  - `--no-write` keeps inspection-only mode.

## Quick Reference

```bash
python3 ~/.hermes/profiles/archiver/scripts/archiver_recall.py \
  --query "firecracker container runtime" --limit 8 --json
```

```bash
python3 ~/.hermes/skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review.py \
  --days 30 --json
```

```bash
python3 ~/.hermes/scripts/archive_weekly_review_cron.py --days 30
```

```bash
hermes cron create "15 9 * * 1" \
  --no-agent \
  --script archive_weekly_review_cron.py \
  --deliver origin \
  --name "archive-weekly-review"
```

## Procedure

### Contextual recall

Primary recall command:

```bash
python3 ~/.hermes/profiles/archiver/scripts/archiver_recall.py --query "<consulta>" --limit 8 --json
```

If the recall result is empty, rerun with 2–3 query variants/synonyms before concluding absence.
For infrastructure/runtime questions, include class and ecosystem synonyms in the retry set:
`microVM`, `micro-vm`, `lightweight VM`, `KVM`, `sandbox`, `serverless`, `Lambda`, `Fargate`,
`Firecracker`, `Kata Containers`, `gVisor`, `Cloud Hypervisor`, `Podman`, `LXD`,
`Incus`, `containerd`, `Nomad`, and `Kubernetes`.

Response format:

- keep a shortlist only;
- cite saved URL and local note path when available;
- explain why each result matched the question;
- return the top 5–8 and offer refinement when there are many matches;
- if confidence is weak, label as candidates instead of facts.

Use archived context first. Do not browse or refresh external pages unless Felippe asks.

If the query is likely corrected by user feedback, rerun immediately with the exact term and
synonyms, then answer whether Archiver has context versus only general memory.

If recall has no hits, query Markdown as fallback (without mutating state):

```bash
python3 - <<'PY'
from pathlib import Path

q = "<query>".lower()
root = Path.home() / ".hermes/profiles/archiver/archive-vault"
for p in root.rglob("*.md"):
    if "90-meta" in p.parts or "attachments" in p.parts:
        continue
    t = p.read_text(encoding="utf-8", errors="ignore").lower()
    if q in t:
        print(p)
PY
```

### Direct archive intake

Use `archive_item.py` for link-only Telegram intake:

```bash
python3 ~/.hermes/profiles/archiver/scripts/archive_item.py \
  --title "<title>" \
  --source "https://..." \
  --tags "inbox,link,archive" \
  --body "<message/body>" \
  --json
```

Use JSON output, not raw note paths, when confirming success to the user.
Gateway/direct archive responses should summarize title/context and counts; avoid sending only
`/...md` paths.

The intake contract is additive-safe:

- always create item/link rows (`items`, `links`);
- store contextual rows in `link_contexts`;
- do not fail archive creation if extraction fails;
- keep body/Telegram-derived context in `body_only`;
- set `extracted` when fetch+parse succeeds.

New archives attempt bounded extraction by default: `urllib.request` for HTML/plain text and
optional PyMuPDF (`fitz`) for PDFs, always with bounded timeout and byte limits. Successful PDF
rows use `extractor='pymupdf'`. If the content type is unsupported, PyMuPDF is unavailable, or
fetching fails, keep the body-derived context and record extraction status/error without aborting
archival. Use `--no-extract` for deterministic tests or intentionally offline intake.

Backfill existing rows:

```bash
python3 ~/.hermes/profiles/archiver/scripts/backfill_link_contexts.py --dry-run --json
python3 ~/.hermes/profiles/archiver/scripts/backfill_link_contexts.py --json
```

Reprocess links through current extraction schema (enriching `body_only`/`failed` and missing
contexts only):

```bash
python3 ~/.hermes/profiles/archiver/scripts/backfill_link_contexts.py --dry-run --extract-existing --json
python3 ~/.hermes/profiles/archiver/scripts/backfill_link_contexts.py --extract-existing --json
```

`--force` with `--extract-existing` is only for intentional full re-fetching and may re-touch
already-good rows.
Backfill creates a timestamped DB backup under `90-meta/`.
Before any backfill mutation, confirm the JSON response includes a `backup_path` under `90-meta/`.
Blocked or 404 pages can remain `failed`; this is an extraction result, not an archival failure.

`link_contexts.context_status` includes:

- `extracted`: content/title/summary/context captured;
- `body_only`: archive-local context persisted without successful extraction;
- `failed`: extraction failed after capture;
- extractor-specific statuses like `unsupported_content_type`.

### Shared-link audit

Always audit against official Archiver data first, not Obsidian notes alone:

- DB tables: `items`, `links`, `link_contexts`;
- Vault notes: `~/.hermes/profiles/archiver/archive-vault/`;
- ad-hoc note paths are evidence only and are not proof of Archiver registration.

Collect links from the current/past session, including Telegram reply context and GitHub shorthand
such as `Owner/repo: description` when the message clearly identifies a repository.

Run normalization before compare:

- drop trailing slash;
- prefer `https` when comparing;
- canonicalize owner/repo case for GitHub-style links.

If a shared link is missing from Archiver DB but appears in note artifacts, backfill with
`archive_item.py` and then re-check official tables.

After any backfill, re-query SQLite and report each link as `consta` or `não consta`, including its
canonical note path and `context_status` when available. A note path outside the Archiver vault is
non-authoritative evidence only.

When you inspect links at the topic level, include Telegram reply context and worker provenance
when available.

### Topic routing and runtime pitfalls

If links stop entering Archiver after posting in Archive topic:

- inspect recent routing evidence with `search_files` against `~/.hermes/logs/gateway.log` for
  `Routing topic message`; compare the last match with the most recent Hermes update;
- remember that `topic_routes` in config can survive an update while the implementation in
  `gateway/run.py` is overwritten;

- inspect `gateway/run.py` with `search_files` for
  `Routing topic message|_resolve_kanban_topic_route`.

If that search returns no matches, the routing patch is likely gone and should be restored following
`hermes-runtime-ops`, using the preserved `felippe/local-patches-*` branch when applicable.

If `search_files` finds `Enfileirado no Kanban: Archive` in recent topic/gateway evidence and links
still miss capture, routing is working. In that case inspect:

- Kanban `archive` board task status and payload;
- archive worker logs and `archive` task execution;
- worker script/runtime failure rather than topic router.

### Weekly review

`archive_weekly_review.py` emits schema `archive-weekly-review.v1` and keeps the same profile
operational contract as v1.1:

- DB is opened read-only for this review path;
- URLs are normalized and redacted (`query`, `fragment`, credentials).

Command to write canonical artifacts:

```bash
python3 ~/.hermes/skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review.py \
  --archiver-home ~/.hermes/profiles/archiver \
  --output-dir ~/.hermes/profiles/archiver/reports/archive-reviews \
  --days 30
```

Outputs are deterministic in:

- `~/.hermes/profiles/archiver/reports/archive-reviews/YYYY-MM-DD.json`
- `~/.hermes/profiles/archiver/reports/archive-reviews/YYYY-MM-DD.md`
- `~/.hermes/profiles/archiver/reports/archive-reviews/latest.json`
- `~/.hermes/profiles/archiver/reports/archive-reviews/latest.md`
- `~/.hermes/profiles/archiver/reports/archive-reviews/index.json`

`latest.*` must be byte-identical to the corresponding dated artifact.
`index.json` is the checksum/size authority for persisted artifacts.

Status policy is:

- `critical`: SQLite integrity not ok, FK violations, missing note paths, orphan links/contexts,
  or missing context rows.
- `attention`: `failed`/`body_only` contexts, duplicate URLs, inbox backlog, dirty git tree.
- `info`: Kanban check unavailable.

Schedule wrapper/copy path:

```bash
cp ~/.hermes/skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review_cron.py \
  ~/.hermes/scripts/archive_weekly_review_cron.py

hermes cron create "15 9 * * 1" \
  --no-agent \
  --script archive_weekly_review_cron.py \
  --deliver origin \
  --name "archive-weekly-review"
```

The cron wrapper must stay under `~/.hermes/scripts/`; the installed script is the canonical
execution target.

### Reconciliation when current DB is empty

When a link is remembered but absent from current Archiver DB/vault, check:

- `items`, `links`, and `link_contexts` in Archiver DB;
- `archive` Kanban board history for tasks around the date;
- `~/.hermes/profiles/archiver/state.db` session transcripts;
- worker/tool output that includes extracted URLs and metadata.

Classification to report:

- `in_control`;
- `extracted_only`;
- `note_only`;
- `missing`.

For `extracted_only` or `note_only`, recommend controlled backfill preserving provenance (`platform`,
`chat`, `thread`, `user`, `message_id`, `task_id`, archived date).

### Maintenance

Reference notes in `references/`:

- `references/pdf-extraction-existing-links.md`
- `references/reconcile-kanban-archive-tasks.md`
- `references/x-twitter-content-extraction.md`
- `references/weekly-review-operations.md`

## Pitfalls

- Don’t treat ad-hoc Obsidian notes as Archiver registration.
- A previous quick-capture flow wrote `ComposioHQ/composio` and `@andreprado/agentkit` under a
  general Obsidian `00 Inbox`; those notes looked saved but did not create official Archiver rows.
- Keep a strict difference between gateway routing failures and worker/script failures.
- If extraction fails, use the `body_only` path and keep the item archived.
- An npm/blocked page can be archived from body context even when extraction remains `failed`.
- Review status should not be downgraded by noisy non-critical operational findings.
- Preserve old recall semantics and only add weekly review side-effects.

## Verification

Run through `terminal`, from the custom-skills repository root:

```bash
python3 tools/validate_skill.py skills/productivity/archiver-contextual-recall/SKILL.md
python3 -m pytest -q skills/productivity/archiver-contextual-recall/tests
python3 tools/generate_catalog.py --check
PYTHONPYCACHEPREFIX=/tmp python3 -m py_compile \
  skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review.py \
  skills/productivity/archiver-contextual-recall/scripts/archive_weekly_review_cron.py
git diff --check
git status --short
```

Also verify every `MANIFEST.sha256` digest and every registry `size_bytes` value against the
actual package files before commit or runtime sync.
