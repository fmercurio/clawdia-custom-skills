---
name: brain-search
description: Generic template — FTS5 + semantic search engine for a PARA-first Second Brain vault. Use for concept-level queries, keyword search, and vault exploration. Customize vault path and embedding model for each deployment.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [second-brain, search, fts5, embeddings, semantic, knowledge-retrieval, template]
    related_skills: [pull-brain, push-brain, second-brain-operations, second-brain-knowledge-architecture]
---

# Brain Search (Generic Template)

> **Customization required.** Replace all `<PLACEHOLDER>` values with deployment-specific paths, names, and model endpoints. This is a parameterized template, not a ready-to-use skill.

## Overview

`brain-search` provides FTS5 + optional semantic search over a PARA-first Second Brain vault.

It uses a standalone Python script (`brain_search.py`) that builds a SQLite/FTS5 index with optional local embedding model integration for concept-level retrieval.

Embedding egress is localhost-only by default. Remote embedding providers receive vault text and search queries, so they require an explicit `--allow-remote-embeddings` opt-in plus an approved `BRAIN_EMBED_URL`.

Canonical vault (CUSTOMIZE):

```text
<VAULT_ROOT>/
```

Index location:

```text
<VAULT_ROOT>/.brain-index/brain_search.sqlite
```

## When to Use

- **pull-brain** needs to find vault content by concept, not just keyword
- User asks "what do we know about X?" and keyword search misses relevant notes
- Agent needs to explore the vault before a session
- Rebuilding or updating the search index after vault changes

## Commands

### Rebuild full index (with embeddings)

```bash
cd <VAULT_ROOT>
BRAIN_EMBED_MODEL="<EMBED_MODEL_NAME>" \
  python3 scripts/brain_search.py --rebuild --embeddings --json
```

Run when:
- After a push-brain session that added/modified files
- On demand when search seems stale
- Local model server (`<EMBED_ENDPOINT>`) must be running

### Quick rebuild (FTS only, no embeddings)

```bash
cd <VAULT_ROOT>
python3 scripts/brain_search.py --rebuild --json
```

Takes <1s. Good enough for keyword search when embeddings aren't needed.

### Search (FTS only)

```bash
cd <VAULT_ROOT>
python3 scripts/brain_search.py --query "search terms" --limit 8 --json
```

### Search (FTS + semantic)

```bash
cd <VAULT_ROOT>
BRAIN_EMBED_MODEL="<EMBED_MODEL_NAME>" \
  python3 scripts/brain_search.py --query "concept or question" --vector --limit 8 --json
```

Semantic search finds results even when exact keywords don't appear in the vault. Similarity scores above ~0.65 are usually relevant.

### Update a single file

```bash
cd <VAULT_ROOT>
python3 scripts/brain_search.py --update "10_Projects/my-project/Projeto.md" --json
```

### Stats

```bash
cd <VAULT_ROOT>
python3 scripts/brain_search.py --stats --json
```

## How it Works

1. **Chunking**: Markdown files split by headings (##/###). Oversized sections split by paragraphs. Each chunk keeps its heading context.
2. **FTS5**: Full-text search with unicode61 tokenizer (good for accented languages). Matches keywords with relevance ranking.
3. **Embeddings** (optional): Uses a local model server's OpenAI-compatible API. Stores float32 vectors in SQLite. Cosine similarity for semantic ranking.
4. **Combined search**: FTS results first, then unique vector results not already found by FTS. Deduplication by path+heading.
5. **PARA awareness**: Each chunk tagged with its layer (project/area/resource/archive) from path detection and frontmatter.

## Integration with pull-brain

When pull-brain needs to search the vault, prefer brain_search over raw grep:

```bash
# Instead of: search_files(pattern="term", path="<VAULT_ROOT>")
# Use:
BRAIN_EMBED_MODEL="<EMBED_MODEL_NAME>" \
  python3 <VAULT_ROOT>/scripts/brain_search.py \
  --query "term or concept" --vector --limit 8 --json
```

## Integration with push-brain

After push-brain writes files and commits, rebuild the index:

```bash
cd <VAULT_ROOT>
python3 scripts/brain_search.py --rebuild --json
# Or with embeddings:
BRAIN_EMBED_MODEL="<EMBED_MODEL_NAME>" \
  python3 scripts/brain_search.py --rebuild --embeddings --json
```

## Customization Checklist

Before deploying, replace these placeholders:

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `<VAULT_ROOT>` | Absolute path to the vault | `/home/user/my-brain` |
| `<EMBED_MODEL_NAME>` | Local embedding model identifier | `text-embedding-nomic-embed-text-v1.5` |
| `<EMBED_ENDPOINT>` | OpenAI-compatible API endpoint | `http://127.0.0.1:1234/v1/embeddings` |

## Pitfalls

1. **Model server must be running for embeddings.** Check connectivity to `<EMBED_ENDPOINT>`. FTS-only rebuild is always available as fallback.
2. **Remote embeddings are data egress.** The script rejects non-local endpoints unless `--allow-remote-embeddings` or `BRAIN_ALLOW_REMOTE_EMBEDDINGS=1` is set for an approved provider.
3. **Model name mismatch.** Always set `BRAIN_EMBED_MODEL` env var; don't rely on defaults.
4. **Index is cache, not source of truth.** The `.brain-index/` directory is gitignored and can be rebuilt at any time.
5. **Rebuild is cheap.** FTS-only: <1s. With embeddings: ~17s for ~75 files. Don't hesitate to rebuild.
6. **Semantic similarity threshold.** Scores below ~0.60 are usually noise. Above 0.70 is good. Above 0.80 is strong.
7. **Tokenizer limitations.** FTS5 unicode61 handles accents but not stemming (singular ≠ plural won't match without OR).

## Verification Checklist

- [ ] `brain_search.py` placed in `<VAULT_ROOT>/scripts/`
- [ ] `.brain-index/` added to `.gitignore`
- [ ] FTS-only rebuild tested (exit 0, stats show files/chunks)
- [ ] Embedding rebuild tested (requires running model server)
- [ ] Search (FTS) returns relevant results
- [ ] Search (semantic) returns relevant results
- [ ] Skill installed at `~/.hermes/skills/note-taking/brain-search/SKILL.md`
- [ ] `/reload-skills` run after installation
- [ ] Integration with pull-brain tested
- [ ] Integration with push-brain tested
