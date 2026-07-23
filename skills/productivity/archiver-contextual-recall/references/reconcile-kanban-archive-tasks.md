# Reconcile Kanban tasks with Archiver DB

Use this when a user reports a link through Kanban and the current Archiver control plane does not immediately show it.

## Why this exists

Some operational histories may contain links in Kanban task payloads that are not yet reflected in SQLite tables.
Treat Kanban and DB evidence together; do not mark an item missing from Archiver without cross-checking both.

## Control-plane checks

```bash
DB="$ARCHIVER_DB"
sqlite3 "$DB" '.tables'
sqlite3 "$DB" "SELECT id,title,source,path,created_at FROM items WHERE created_at >= '$START' ORDER BY created_at;"
sqlite3 "$DB" "SELECT l.id,l.url,i.path,l.created_at FROM links l JOIN items i ON i.id=l.item_id WHERE l.created_at >= '$START' ORDER BY l.created_at;"
```

Normalize URLs when comparing by URL family:

- protocol changes (`http` ↔ `https`)
- trailing slash normalization
- host canonicalization (`www.` vs bare host)

## Kanban checks

```bash
hermes kanban --board "${ARCHIVER_KANBAN_BOARD:-archive}" show <task_id>
```

If the exact task id is unknown, inspect nearby tasks on the configured board and collect source URLs from task bodies.

## Backfill workflow

- If a missing link is confirmed, run intake-safe backfill/rebuild tools instead of direct file edits:

```bash
python3 .../scripts/backfill_link_contexts.py --dry-run --json
python3 .../scripts/backfill_link_contexts.py --extract-existing --json
```

- Use `--dry-run` first to inspect counts and candidate IDs before writing.

## Outcome classes

- `in_control`: present in `items`/`links` and has a current note path.
- `extracted_only`: present in task trail but absent from `archiver.sqlite3`.
- `note_only`: present in markdown history but missing `links`/`link_contexts`.
- `missing`: no match after checking DB and Kanban evidence.

## Note

Private routing IDs, historical state DB paths, and recovery branches are deployment-specific and are excluded from this package.
