---
name: second-brain-operations
description: Step-by-step playbook for setting up and operating a PARA-first Second Brain with Hermes — vault creation, semantic search engine, pull/push skills, health-check cron, weekly review, and operational rhythm.
version: 1.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [second-brain, para, obsidian, hermes, operations, playbook]
    related_skills: [second-brain-knowledge-architecture, pull-brain, push-brain, brain-search]
---

# Second Brain Operations

## Overview

Implementation playbook for building and operating a PARA-first Second Brain with Hermes as the operator.

Use this skill when the user wants to:
- Set up a new second brain from scratch;
- Understand the proven vault structure and conventions;
- Create brain-search, pull-brain, and push-brain skills;
- Configure health-check automation;
- Run the weekly review ritual;
- Understand the operational rhythm of a live second brain.

For architecture/design questions (layers, sensitivity routing, multi-agent, fractal patterns), use `second-brain-knowledge-architecture` instead.

## What We Proven

This playbook encodes lessons from the real FMercurio Tech deployment:
- Vault: Markdown + Git + Obsidian
- Operator: Hermes Agent via Telegram
- Method: PARA + CODE (Tiago Forte)
- Health-check: deterministic script, cron, silent-when-healthy
- Search: FTS5 + semantic embeddings (brain_search.py) for concept-level retrieval
- Skills: `brain-search`, `pull-brain`, and `push-brain` as Hermes local skills
- Git-backed: vault commits + pushes to GitHub remote; index rebuild after each push
- Separation: vault (durable knowledge) ≠ runtime (Hermes) ≠ backups

## How to Use This Skill

### Setup (one-time)

The client invokes this skill to start a new second brain:

```
/second-brain-operations
```

Or in natural language: "quero montar um segundo cérebro", "setup second brain", "criar vault PARA".

The agent then follows Phases 1–10 in order, asking the client questions at each phase and implementing as it goes. The client does not need to know Git, Python, YAML, or Hermes internals — the agent handles everything.

**What the client provides:**
- Purpose and scope of the vault
- Owner name
- Sensitivity preferences
- Whether Hermes will be the operator

**What the agent creates:**
- Vault with PARA structure + root files
- Health-check script
- Brain search engine (FTS5 + optional semantic embeddings)
- `brain-search`, `pull-brain`, and `push-brain` skills
- Cron configuration for automated auditing

**What the client receives as commands:**
- `/brain-search` — search the vault by keyword or concept
- `/pull-brain` — load context from the vault
- `/push-brain` — save session output to the vault

### Ongoing use

After setup, the client uses `/brain-search`, `/pull-brain`, and `/push-brain` naturally in their sessions. The agent follows the rituals automatically when these commands are invoked.

## Phase 1: Project Charter

Before creating files, define:

1. **Purpose** — Why does this brain exist?
2. **Scope** — Personal? Company? Client? Which domains?
3. **Owner** — Who is responsible?
4. **Sensitivity model** — What's public, internal, restricted?
5. **Operator** — Hermes? Human-only? Both?
6. **Interface** — Telegram? Obsidian? CLI?

Write a one-paragraph charter and keep it in `README.md`.

## Phase 2: Vault Creation

### Directory structure

```text
vault-name/
├── 00_Inbox/            — raw capture, 30-day max
├── 10_Projects/         — active efforts with outcome + deadline
├── 20_Areas/            — ongoing responsibilities
├── 30_Resources/        — distilled reusable knowledge
├── 40_Archives/         — inactive/concluded/superseded
├── 50_Templates/        — starter files for each note type
├── _Hermes/             — bridge docs (NOT runtime copies)
├── _Meta/               — vault governance + decision log
├── scripts/             — deterministic utilities
├── MAPA.md              — root map
├── PARA.md              — routing rules + frontmatter spec
├── HERMES.md            — how Hermes reads/writes this vault
├── README.md            — human-facing overview
└── .gitignore           — exclude .env, secrets, .obsidian/, backups
```

### Frontmatter PARA contract

Every canonical note must declare:

```yaml
---
para: project          # project | area | resource | archive
scope: personal        # personal | company | client | product | hermes | leadership
status: active         # inbox | active | waiting | paused | complete | archived | distilled
sensitivity: internal  # public | internal | restricted
owner: <name>
created: YYYY-MM-DD
updated: YYYY-MM-DD
review: weekly         # weekly | monthly | quarterly | ad-hoc
related: []
---
```

Root files and changelog are exempt.

### Templates

Create starter templates in `50_Templates/` for: project, area, resource, decision, playbook, client-partner, bridge-note. Each with correct frontmatter pre-filled.

### Git init + Obsidian

```bash
git init && git add . && git commit -m "Initial vault structure"
open -a Obsidian /path/to/vault
```

Add `.obsidian/` and `.brain-index/` to `.gitignore`.

## Phase 3: Health-Check Script

### What to audit

1. Frontmatter compliance — canonical notes with valid `para:`
2. Project staleness — active projects without `updated:` in 14 days
3. Inbox staleness — items older than 30 days
4. Runtime contamination — `.env`, `config.yaml` inside vault
5. Sensitivity routing — `sensitivity: restricted` notes outside restricted areas
6. Overall compliance %

### Design decisions

- **Script-first** — deterministic, zero LLM cost
- **Silent when healthy** — empty stdout; non-empty only for issues
- **Wrapper in profile** — cron resolves scripts relative to profile dir

### Wrapper pattern

```python
#!/usr/bin/env python3
import subprocess, sys
VAULT = "/path/to/vault"
result = subprocess.run(
    [sys.executable, f"{VAULT}/scripts/brain-health-check.py"],
    capture_output=True, text=True, cwd=VAULT
)
if result.returncode != 0:
    print(result.stdout); print(result.stderr, file=sys.stderr); sys.exit(result.returncode)
output = result.stdout.strip()
if output and "saudável" not in output.lower() and "healthy" not in output.lower():
    print(output)
```

## Phase 4: Brain Search Engine

A FTS5 + optional semantic search engine that enables concept-level retrieval across the vault. This is the backbone that makes `pull-brain` effective beyond keyword grep.

### What it does

1. **Chunking** — Markdown files split by headings (##/###). Oversized sections split by paragraphs. Each chunk keeps heading context.
2. **FTS5** — Full-text search with unicode61 tokenizer (handles accented characters). Keyword matching with relevance ranking.
3. **Embeddings** (optional) — Uses a local embedding model (e.g. `nomic-embed-text-v1.5` via LM Studio/Ollama) for semantic similarity. Stores float32 vectors in SQLite. Cosine similarity for concept matching.
4. **Combined search** — FTS results first, then unique vector results not already found by FTS. Deduplication by path+heading.
5. **PARA awareness** — Each chunk tagged with its layer (project/area/resource/archive) from path detection and frontmatter.

### Script: brain_search.py

Create `<vault>/scripts/brain_search.py`. Core operations:

```bash
# Rebuild full index (FTS only — <1s)
python3 scripts/brain_search.py --rebuild --json

# Rebuild with semantic embeddings (~17s for ~75 files)
BRAIN_EMBED_MODEL="text-embedding-nomic-embed-text-v1.5" \
  python3 scripts/brain_search.py --rebuild --embeddings --json

# Keyword search
python3 scripts/brain_search.py --query "termos de busca" --limit 8 --json

# Semantic search (concept-level)
BRAIN_EMBED_MODEL="text-embedding-nomic-embed-text-v1.5" \
  python3 scripts/brain_search.py --query "conceito ou pergunta" --vector --limit 8 --json

# Update a single file (incremental)
python3 scripts/brain_search.py --update "10_Projects/my-project/Projeto.md" --json

# Stats
python3 scripts/brain_search.py --stats --json
```

### Design decisions

- **FTS is always available** — embeddings require a running local model server; FTS works standalone
- **Graceful degradation** — if LM Studio/Ollama is down, search falls back to FTS-only automatically
- **Index is cache, not source** — `.brain-index/` directory is gitignored and can be rebuilt anytime
- **Rebuild is cheap** — FTS-only <1s; with embeddings ~17s for ~75 files

### Skill: brain-search

Create `~/.hermes/skills/note-taking/brain-search/SKILL.md` with:
- Triggers: "search brain", "buscar no cérebro", "o que temos sobre X?"
- Commands: rebuild, search (FTS), search (semantic), update single file, stats
- Integration notes for pull-brain and push-brain
- Pitfalls: model must be running for embeddings; threshold guidance (below ~0.60 = noise)

### Embedding model setup

Requires a local embedding server. Tested with:
- **LM Studio** — load `nomic-embed-text-v1.5`, default endpoint `http://127.0.0.1:1234/v1/embeddings`
- **Ollama** — `ollama pull nomic-embed-text`, endpoint `http://127.0.0.1:11434/v1/embeddings`

The `BRAIN_EMBED_MODEL` env var overrides the model name. If no server is running, FTS-only search is always available.

## Phase 5: Pull-Brain Skill

Create `~/.hermes/skills/note-taking/pull-brain/SKILL.md`.

### Retrieval order (PARA)

1. Project → 2. Area → 3. Resource → 4. Archive → 5. Brain Search → 6. Inbox/session_search

### Brain-search integration

When searching the vault, prefer `brain_search.py` over raw grep:

```bash
BRAIN_EMBED_MODEL="text-embedding-nomic-embed-text-v1.5" \
  python3 /path/to/vault/scripts/brain_search.py \
  --query "termo ou conceito" --vector --limit 8 --json
```

Benefits over grep:
- Concept-level matching (semantic) finds notes without exact keyword match
- Relevance ranking (FTS rank + cosine similarity)
- Chunk-level results instead of file-level (more precise context)
- PARA layer tagging in results

### Key sections

- Triggers and aliases
- Source of truth (vault path + key files)
- Workflow (scope → root → brain-search → read → fallback to session_search)
- Return format (consolidated / session recall / assumptions / gaps)
- Sensitivity routing
- Pitfalls (memory over vault, resources before projects, mixing layers)

## Phase 6: Push-Brain Skill

Create `~/.hermes/skills/note-taking/push-brain/SKILL.md`.

### Classification

| Deliverable in progress? | → Project |
| Ongoing standard? | → Area |
| Reusable knowledge? | → Resource |
| Inactive? | → Archive |
| Raw/uncertain? | → Inbox |
| Governance decision? | → _Meta/decisoes/ |
| Runtime knowledge? | → _Hermes/ bridge |
| Secrets? | → NEVER |

### Workflow

1. Read current state → 2. Choose destination → 3. Write concisely → 4. Update status → 5. Health-check → 6. Commit → 7. Push to remote → 8. Rebuild search index

### Git push to remote

After committing, always push so the vault stays in sync:

```bash
cd /path/to/vault
git push origin HEAD
```

Run `pull-brain` first if the push updates shared state (projects, areas, decisions) that may have changed since the last session.

### Rebuild search index

After pushing, rebuild the brain-search index so FTS5 + embeddings stay current:

```bash
cd /path/to/vault
python3 scripts/brain_search.py --rebuild --json
# Or with embeddings if local model is running:
BRAIN_EMBED_MODEL="text-embedding-nomic-embed-text-v1.5" \
  python3 scripts/brain_search.py --rebuild --embeddings --json
```

### URL archiving (optional quick-archive)

When the user sends a URL with no other instruction, it's a quick-archive request — fetch, extract, write a structured note to `40_Archives/` or a dedicated archive area. This is lighter than a full push-brain consolidation.

Archive note structure:
- Source URL and fetch date
- Title, author, publication date
- Key points extracted (3-7 bullets)
- Tags / PARA classification
- Full content or summary depending on length

### Key sections

- Triggers and aliases
- Classification table
- PARA destinations
- Sensitivity routing
- Output format (paths, health-check, commit hash, push result, index status, next step)
- Pitfalls (chat dumps, duplicates, forgetting health-check, skipping push)

## Phase 7: Cron Configuration

```yaml
schedule: "0 9 * * 1"
script: <wrapper-name>.py
no_agent: true
deliver: origin
profile: <profile-name>
workdir: /path/to/vault
```

### Critical pitfall

`script:` resolves relative to **profile's** `scripts/` directory. Put wrapper in `~/.hermes/profiles/<profile>/scripts/`, not in vault or global scripts.

### Test sequence

1. Test wrapper directly (exit 0, empty stdout when healthy)
2. Create cron
3. Trigger once with `cronjob(action='run')`
4. Verify `last_status: ok`

## Phase 8: Weekly Review

### Checklist

1. Projects — still active? stalled? archive?
2. Areas — context current? decisions/lessons to add?
3. Resources — distill, update, or archive?
4. Inbox — promote, archive, or discard (items > 30 days)
5. Decisions — reflected in area/project files?
6. Gaps — what's missing?
7. Health-check — manual run
8. Brain search index — rebuild after review changes
9. Git — commit and push all

### Output

Save to `_Meta/revisoes-semanais/YYYY-MM-DD.md`:
- Executive summary
- Projects/areas reviewed
- Inbox processed
- Decisions made
- Gaps identified
- Next priorities

## Phase 9: Operational Rhythm

| Cadence | Actions |
|---------|---------|
| Daily | Capture to inbox; push-brain after meaningful sessions |
| Weekly | Health-check cron + manual review + inbox processing |
| Monthly | Review areas; archive inactive; update contexts |
| Quarterly | Review structure; consider splitting vaults |

## Phase 10: Client Offering

### Deliverables

1. Vault template (PARA folders + templates)
2. Health-check script (drop-in)
3. Brain search engine (drop-in)
4. Setup guide (this skill as reference)
5. Training session (search/pull/push walkthrough)
6. Optional: Hermes operator (skills + cron)

### Pricing tiers

| Tier | Included |
|------|----------|
| DIY | Template + guide + health-check + brain-search scripts |
| Assisted | Template + setup + first 4 weekly reviews |
| Managed | Full setup + Hermes operator + ongoing support |

## Common Pitfalls

1. Over-engineering before operating — start minimal, grow by use
2. Mixing layers — vault ≠ runtime ≠ backups
3. Forgetting the push — knowledge in chat dies
4. Over-reading on pull — PARA order prevents drowning
5. Ignoring sensitivity — route before writing
6. No health-check — frontmatter decays without auditing
7. Obsidian as source — vault + Git is source of truth
8. Saving everything — classify first, only durable knowledge enters
9. **brain-health-check.py VAULT_ROOT hardcoded** — the script uses `Path(__file__).resolve().parent.parent` as default vault root. Always pass `--vault /path/to/vault` when running from outside, or use the wrapper pattern which sets `cwd=VAULT`.
10. **Missing sensitivity routing check** — add `check_sensitivity_routing()` to detect `sensitivity: restricted` notes outside designated restricted areas.
11. **Stale search index** — after vault changes (push-brain, weekly review), rebuild brain_search index. Semantic search on a stale index misses new content. Rebuild is cheap (<1s FTS, ~17s with embeddings).
12. **Git push without pull on shared state** — when pushing updates to shared project/area/decision files, pull first if state may have changed since the last session. Health-check catches structural issues but not semantic staleness.
13. **Embedding model name mismatch** — LM Studio loads it as `text-embedding-nomic-embed-text-v1.5`, not `nomic-embed-text`. Always set `BRAIN_EMBED_MODEL` env var.

## Verification Checklist

- [ ] Vault created with PARA structure
- [ ] Root files exist (MAPA, PARA, HERMES, README)
- [ ] Frontmatter PARA contract defined
- [ ] Templates created
- [ ] Health-check script created and tested
- [ ] Brain search engine created and tested (FTS + optional embeddings)
- [ ] Pull-brain skill created and tested (with brain-search integration)
- [ ] Push-brain skill created and tested (with git push + index rebuild)
- [ ] `/reload-skills` run after skill creation
- [ ] Skills tested as `/` commands in gateway
- [ ] Cron configured and triggered once
- [ ] Weekly review ritual defined
- [ ] First real session consolidated via push-brain
- [ ] Git initialized with initial commit + remote configured
- [ ] `.gitignore` protects secrets, `.obsidian/`, and `.brain-index/`
