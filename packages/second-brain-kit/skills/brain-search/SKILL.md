---
name: brain-search
description: Search a configured Second Brain with SQLite FTS5 and optional semantic fallback. Use for keyword or concept retrieval, index rebuilds, and search diagnostics. Do not use to mutate canonical notes or expose restricted content.
version: 0.1.0-rc1
author: Skills Lab
license: MIT
metadata:
  hermes:
    tags: [second-brain, search, sqlite, fts5]
    related_skills: [pull-brain, push-brain, second-brain-operations]
---

# Brain Search

FTS5 is mandatory and local. Embeddings are optional; RC1 degrades to FTS when unavailable. Restricted notes are excluded from the default index.

## Commands

```bash
python3 ${KIT_BIN}/brain_search.py --vault ${VAULT_ROOT} --rebuild --json
python3 ${KIT_BIN}/brain_search.py --vault ${VAULT_ROOT} --query "decision context" --json
python3 ${KIT_BIN}/brain_search.py --vault ${VAULT_ROOT} --stats --json
```

Use `--include-restricted` on both rebuild and query only inside an explicitly authorized restricted workflow. A restricted-capable index still excludes restricted results from ordinary queries. A remote embedding endpoint is invalid unless config explicitly enables data egress.

## Exit criteria

- Rebuild succeeds on first use.
- Query results cite relative paths and snippets.
- Default stats show zero restricted notes indexed.
- Missing embedding services do not break FTS.
