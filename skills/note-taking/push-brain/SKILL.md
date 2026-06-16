---
name: push-brain
description: Generic template — save, consolidate, and sync a PARA-first Second Brain vault after a meaningful session. Classifies session output into PARA destinations, writes durable knowledge, runs health-check, commits, pushes, and rebuilds search index.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [second-brain, knowledge-consolidation, para, push, template]
    related_skills: [brain-search, pull-brain, second-brain-operations, second-brain-knowledge-architecture]
---

# Push Brain (Generic Template)

> **Customization required.** Replace all `<PLACEHOLDER>` values with deployment-specific paths, names, and scope values. This is a parameterized template, not a ready-to-use skill.

## Overview

`push-brain` is the session-closing and consolidation ritual for a PARA-first Second Brain vault.

Use it when a conversation, investigation, decision, project update, research result, or operational change should survive beyond chat history and agent short memory.

Canonical vault (CUSTOMIZE):

```text
<VAULT_ROOT>/
```

Core principle:

> Do not save everything. Classify first. Only durable knowledge enters the Second Brain.

## When to Use

Use this skill when the user says or implies:

- "save this to the brain" / "salva isso no cérebro";
- "push-brain";
- "sync" / "fecha sessão";
- "update the brain" / "atualiza o cérebro";
- "consolidate this" / "consolida isso";
- "register this decision" / "registra essa decisão";
- "let's wrap up" after a meaningful session;
- after completing a non-trivial vault, project, or runtime task.

Do not use to dump raw chat logs, secrets, transient task progress, or content without durable value.

## Source of Truth and Destinations

Vault root:

```text
<VAULT_ROOT>/
```

Primary destinations:

```text
00_Inbox/       — raw/uncertain/review-needed captures
10_Projects/    — active efforts with result and completion criterion
20_Areas/       — ongoing responsibilities and operational DNA
30_Resources/   — distilled reusable knowledge
40_Archives/    — inactive/concluded/superseded history
50_Templates/   — reusable templates
_Hermes/        — bridge docs and flows, not runtime copies
_Meta/          — vault governance, decisions, reviews, changelog
```

Never place runtime or backups in the vault:
- Runtime: `~/.hermes/` (profiles, skills, config, crons, sessions, logs)
- Backups: `~/.hermes/backups/` or equivalent
- Secrets: never save `.env`, tokens, API keys, passwords

## Classification First

Before writing, classify every candidate item:

1. **Session summary** — what happened, if worth preserving
2. **Decisions** — durable choices with consequence
3. **Project updates** — status, next actions, completion criteria
4. **Area updates** — ongoing responsibilities, context, decisions, lessons
5. **Resources** — distilled reusable references or research
6. **Playbooks/procedures** — reusable process knowledge
7. **Templates** — reusable structures
8. **Pending items** — unresolved next steps
9. **Sensitive items** — restricted routing or human confirmation
10. **Discard** — chatty, stale, redundant, or no durable value

Then assign PARA:

```text
Has a defined deliverable/current movement?  → Project
Maintains an ongoing standard?              → Area
Reusable/distilled knowledge?               → Resource
Inactive/concluded/superseded?              → Archive
Raw/uncertain but potentially useful?        → Inbox
Transversal vault governance decision?       → _Meta/decisoes/
Runtime knowledge?                           → _Hermes/ bridge doc
Actual runtime file?                         → ~/.hermes/ only, not the vault
Secrets?                                     → NEVER
```

## Workflow

### 1. Inspect current canonical state

Before writing, read the relevant current files so you patch rather than duplicate. Run `pull-brain` first if updating shared state that may have changed since the last session.

### 2. Choose exact destination files

Prefer updating existing canonical files. Create new files only when the current structure has no suitable home.

### 3. Write concise durable knowledge

Do not copy the full conversation. Extract: the decision, why it matters, consequences, current state, next action, provenance, review cadence.

Every canonical note should have frontmatter:

```yaml
---
para: project|area|resource|archive
scope: <SCOPE_VALUE>
status: active|waiting|paused|complete|archived|distilled
sensitivity: public|internal|restricted
owner: <OWNER_NAME>
created: YYYY-MM-DD
updated: YYYY-MM-DD
review: weekly|monthly|quarterly|ad-hoc
related: []
---
```

### 4. Update project status when appropriate

If the session advanced an active project, update the project's living document. For project artifacts (PRDs, specs, plans), use `status: complete` once done. Keep only living project docs as `status: active` so health checks don't overcount.

### 5. Run health check

```bash
cd <VAULT_ROOT>
python3 scripts/brain-health-check.py
```

Fix issues before finishing unless intentional and reported.

### 6. Commit changes

```bash
cd <VAULT_ROOT>
git status --short
git add <changed-files>
git commit -m "Concise commit message"
```

### 7. Push to remote

After committing, always push so the vault stays in sync:

```bash
cd <VAULT_ROOT>
git push origin HEAD
```

### 8. Rebuild search index

After pushing, rebuild the brain-search index:

```bash
cd <VAULT_ROOT>
python3 scripts/brain_search.py --rebuild --json
# Or with embeddings if model server is running:
BRAIN_EMBED_MODEL="<EMBED_MODEL_NAME>" \
  python3 scripts/brain_search.py --rebuild --embeddings --json
```

## URL Archiving (optional)

When the user sends a URL with no other instruction, it's a quick-archive request — fetch, extract, write a structured note to `40_Archives/`. This is lighter than a full push-brain consolidation.

Archive note structure:
- Source URL and fetch date
- Title, author, publication date
- Key points extracted (3-7 bullets)
- Tags / PARA classification
- Full content or summary depending on length

## Output Format to User

After completing the push, report:

```markdown
## Push-brain complete

- Files updated:
  - ...
- Decisions registered:
  - ...
- Project/area updated:
  - ...
- Verification:
  - health-check: ...
  - commit: ...
  - push: ...
  - index rebuild: ...
- Suggested next step:
  - ...
```

## Sensitivity Routing

Before writing, gate restricted content.

Restricted triggers:
- salary, commission, bonus, pro-labore;
- named person + money;
- hiring/firing/conflict/performance feedback;
- legal, contracts, NDA, litigation, compliance/privacy;
- client secrets;
- credentials, tokens, `.env`;
- strategic negotiation terms.

Rules:
- Never save secrets
- If sensitivity is unclear, ask before writing details
- For restricted but durable knowledge, use `sensitivity: restricted` and authorized area only after confirmation
- Operational summaries may mention that a restricted item exists without exposing details

## Customization Checklist

Before deploying, replace these placeholders:

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `<VAULT_ROOT>` | Absolute path to the vault | `/home/user/my-brain` |
| `<OWNER_NAME>` | Vault owner name | `Jane Doe` |
| `<SCOPE_VALUE>` | Default scope for frontmatter | `personal` or `company` |
| `<EMBED_MODEL_NAME>` | Embedding model for index rebuild | `text-embedding-nomic-embed-text-v1.5` |

## Common Pitfalls

1. **Dumping chat history.** Push-brain extracts durable knowledge; it does not archive raw conversations.
2. **Skipping classification.** Every item needs a PARA destination or a discard decision.
3. **Creating duplicate notes.** Read current canonical files before creating new ones.
4. **Saving runtime into the vault.** Profiles, SOULs, crons, configs, and backups stay in `~/.hermes/`.
5. **Committing Obsidian UI state.** `.obsidian/` stays gitignored.
6. **Counting artifacts as active projects.** Use `status: complete` for done artifacts.
7. **Forgetting verification.** Always run health-check, commit, push, and rebuild index.
8. **Pushing without pull on shared state.** Run pull-brain first when updating shared files that may have changed.
9. **Forgetting index rebuild.** Semantic search on a stale index misses new content.

## Verification Checklist

- [ ] Relevant current vault files read before edits
- [ ] Pull-brain run first if updating shared state
- [ ] Session items classified into PARA destinations or discarded
- [ ] Sensitive content routed or withheld safely
- [ ] Canonical notes have valid PARA frontmatter
- [ ] Project/area status updated when changed
- [ ] `brain-health-check.py` run and issues resolved or reported
- [ ] Git status inspected
- [ ] Changes committed with clear message
- [ ] Changes pushed to remote (`git push origin HEAD`)
- [ ] Search index rebuilt
- [ ] Final response includes paths, health-check, commit hash, push result, index status, and next step
