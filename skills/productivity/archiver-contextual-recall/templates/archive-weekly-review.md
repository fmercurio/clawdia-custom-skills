# Archiver Weekly Review {{date}}

- **Schema:** {{schema}}
- **Generated:** {{generated_at}}
- **Status:** {{status}}
- **Window:** {{window_days}} days
- **Home:** `{{archiver_home}}`
- **Report DB:** `{{db_path}}`

## Summary

{{summary}}

## Metrics

- Items: `{{items_total}}`
- Links: `{{links_total}}`
- Link contexts: `{{contexts_total}}`
- Missing note paths: `{{missing_note_paths}}`
- Orphan links: `{{orphan_links}}`
- Orphan contexts: `{{orphan_contexts}}`
- Links with missing contexts: `{{missing_contexts}}`
- Duplicate URL groups: `{{duplicate_url_groups}}`
- Failed contexts: `{{failed_contexts}}`
- Body-only contexts: `{{body_only_contexts}}`
- Recent items: `{{recent_items}}`
- Recent links: `{{recent_links}}`
- Inbox backlog: `{{inbox_backlog}}`
- Markdown notes: `{{markdown_notes}}`
- Git: `{{git_status}}`
- Kanban: `{{kanban_status}}`

## Findings

{{findings_markdown}}

## Artifact metadata

- `{{date}}.json`: written to the review folder and mirrored by `latest.json`.
- `{{date}}.md`: written to the review folder and mirrored by `latest.md`.
- `index.json`: contains canonical registry entries for date artifacts, including their byte sizes and SHA-256 checksums.
