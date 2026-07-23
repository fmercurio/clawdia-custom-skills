# Reconcile Archive Kanban tasks with Archiver DB

Use this when Felippe remembers sending a link to the Archive topic on a specific date, but `archiver_recall.py`, `archive-vault` Markdown search, and the current `archiver.sqlite3` tables do not find it.

## Why this exists

Some historical archive-worker runs processed Telegram archive messages through Kanban and wrote/claimed a note outside the current Archiver control plane. In those cases:

- The Archive Kanban task may be `done`.
- The archiver worker transcript may contain the original Telegram body, extracted URLs, and fetched page metadata.
- The current Archiver DB may still have no `items`, `links`, or `link_contexts` rows for those URLs.
- A final note path mentioned by the worker may not exist anymore in the current vault path.

Do not report “not archived” until checking both the control-plane DB and the Kanban/session trail.

## Control-plane checks

```bash
DB="$HOME/.hermes/profiles/archiver/archive-vault/90-meta/archiver.sqlite3"

sqlite3 "$DB" '.tables'
sqlite3 "$DB" "select id,title,source,path,created_at from items where created_at like '2026-05-11%' order by created_at;"
sqlite3 "$DB" "select l.id,l.url,i.path,l.created_at from links l join items i on i.id=l.item_id where l.created_at like '2026-05-11%' order by l.created_at;"
```

For a specific URL, compare normalized forms: strip trailing slash, `http` vs `https`, `www.` vs bare host where appropriate.

## Archive Kanban checks

```bash
hermes kanban --board archive show <task_id>
```

If the task id is unknown, inspect likely archive-board tasks around the remembered date through the Kanban CLI or board DB. The task body often preserves:

- original Telegram text
- all URLs in the message
- chat/thread/user/message_id provenance

## Archiver profile session DB checks

Historical worker transcripts live in the archiver profile state DB:

```bash
STATE="$HOME/.hermes/profiles/archiver/state.db"
```

Search by local date and `http` content:

```bash
python3 - <<'PY'
import sqlite3, datetime, zoneinfo, os, json
p=os.path.expanduser('~/.hermes/profiles/archiver/state.db')
con=sqlite3.connect(p); con.row_factory=sqlite3.Row
tz=zoneinfo.ZoneInfo('America/Sao_Paulo')
start=datetime.datetime(2026,5,11,0,0,tzinfo=tz).timestamp()
end=datetime.datetime(2026,5,12,0,0,tzinfo=tz).timestamp()
rows=con.execute('''
  select m.id,m.session_id,m.role,m.content,m.timestamp,m.platform_message_id,s.source,s.title
  from messages m join sessions s on s.id=m.session_id
  where m.timestamp>=? and m.timestamp<? and m.content like '%http%'
  order by m.timestamp
''',(start,end)).fetchall()
for r in rows:
    d=dict(r)
    d['dt']=datetime.datetime.fromtimestamp(d['timestamp'],tz).isoformat()
    d['content']=(d.get('content') or '')[:1200]
    print(json.dumps(d,ensure_ascii=False))
PY
```

Once you identify the worker session, inspect surrounding messages/tool calls. Useful evidence can appear in:

- the Kanban task payload/tool output containing the task body
- tool outputs from web readers/extractors containing page title/description/url/content
- assistant final message naming the note destination
- `write_file` tool-call arguments containing the note content/path

## Outcome classification

Classify each URL as one of:

- `in_control`: present in `items`/`links` and has a current note path.
- `extracted_only`: appears in worker transcript/tool output but absent from `archiver.sqlite3`.
- `note_only`: appears in a Markdown note but not in `links`/`link_contexts`.
- `missing`: not found in DB, vault, Kanban task, or session transcript.

For `extracted_only`/`note_only`, recommend a backfill into the current Archiver control plane, preserving provenance fields from the Kanban task: platform, chat, thread, user, message_id, task_id, and archived date.

## Reporting pattern

Be explicit that the current recall DB can be correct while still missing historical worker output:

> The current Archiver DB has no Firecrawl rows, but the Archive Kanban task from 2026-05-11 does contain `https://www.firecrawl.dev/`, and the worker transcript extracted its title/description. So the issue is persistence/reconciliation, not user memory.
