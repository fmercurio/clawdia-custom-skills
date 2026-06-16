---
name: pull-brain
description: Generic template — recover and load consolidated context from a PARA-first Second Brain vault before acting. Retrieves knowledge in PARA order and separates vault facts from session memory and assumptions. Customize vault path and scope values for each deployment.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [second-brain, knowledge-retrieval, para, template]
    related_skills: [brain-search, push-brain, second-brain-operations, second-brain-knowledge-architecture]
---

# Pull Brain (Generic Template)

> **Customization required.** Replace all `<PLACEHOLDER>` values with deployment-specific paths, names, and scope values. This is a parameterized template, not a ready-to-use skill.

## Overview

`pull-brain` is the context-recovery ritual for a PARA-first Second Brain vault.

Use it to load consolidated knowledge from the Markdown/Git/Obsidian vault before making decisions, continuing a project, answering "what do we know about X?", or operating a domain where durable context matters.

Canonical vault (CUSTOMIZE):

```text
<VAULT_ROOT>/
```

Core principle:

> The Second Brain is the source of truth for durable knowledge. Agent memory and session history are auxiliary recall, not canonical truth when the vault has a relevant note.

## When to Use

Use this skill when the user says or implies:

- "load the brain" / "carrega o cérebro";
- "recover context" / "recupera contexto";
- "pull-brain";
- "what do we know about X?" / "o que sabemos sobre X?";
- "let's continue that project" / "vamos continuar aquele projeto";
- "what was the decision on X?" / "qual era a decisão sobre X?";
- starts a session that depends on vault context.

Do not use for trivial one-off questions where no durable context is needed.

## Source of Truth

Start from the vault, not from memory:

```text
<VAULT_ROOT>/
├── MAPA.md
├── PARA.md
├── HERMES.md
├── 00_Inbox/
├── 10_Projects/
├── 20_Areas/
├── 30_Resources/
├── 40_Archives/
├── _Hermes/
└── _Meta/
```

Key files to know:

- `MAPA.md` — root map and current structure
- `PARA.md` — routing rules and frontmatter contract
- `HERMES.md` — how the agent operates the vault
- `_Hermes/fluxos/pull-brain.md` — canonical flow documentation (if present)

## Retrieval Order

Always retrieve context in PARA order:

1. **Project** — Is there an active project related to the request?
2. **Area** — Which ongoing area owns the topic?
3. **Resource** — Which distilled references inform it?
4. **Archive** — Is historical/inactive context needed?
5. **Brain Search** — use `brain_search.py --query ... --vector` for concept-level search
6. **Inbox/session_search** — only if consolidated context is insufficient

This prevents the agent from drowning in resources before checking the active project and owner area.

## Preferred Search Method

If brain-search is installed, use it instead of raw grep:

```bash
BRAIN_EMBED_MODEL="<EMBED_MODEL_NAME>" \
  python3 <VAULT_ROOT>/scripts/brain_search.py \
  --query "term or concept" --vector --limit 8 --json
```

Benefits: concept-level matching, relevance ranking, chunk-level precision, PARA layer tagging. Falls back gracefully to FTS-only if model server is not running.

## Workflow

### 1. Identify scope

Classify the request by scope (CUSTOMIZE values):

- `<SCOPE_1>` (e.g. personal)
- `<SCOPE_2>` (e.g. company)
- `<SCOPE_3>` (e.g. client)
- `<SCOPE_4>` (e.g. product)
- `<SCOPE_5>` (e.g. hermes/runtime)

If sensitivity might be high (contracts, named money, legal, HR, personal data), treat as restricted and avoid exposing details until confirmed.

### 2. Read root context

Read, at minimum:

- `MAPA.md`
- `PARA.md`
- `HERMES.md` when the request touches agent/runtime operation

### 3. Search the vault

Use file tools and brain-search, not guesses:

- Search `10_Projects/` for active projects
- Search `20_Areas/` for area context, decisions, lessons
- Search `30_Resources/` for methods, references, distilled research
- Search `_Meta/decisoes/` for canonical decisions
- Use `brain_search.py` for concept-level queries

### 4. Read only what is needed

Prefer targeted reads over loading the whole vault. For large files, read sections with offsets or search for headings first.

### 5. Use session_search only as fallback

Use `session_search` when:
- the vault has no canonical note for the subject;
- the user explicitly asks about past conversations;
- a recent conversation likely has not been consolidated yet.

Label these as **recovered from session, not yet consolidated**.

### 6. Return provenance-separated context

```markdown
## Context retrieved

### Consolidated in the Second Brain
- ...

### Active project
- ...

### Owner area
- ...

### Relevant resources
- ...

### Related decisions
- ...

### Recovered from session (not consolidated)
- ...

### Gaps
- ...

### Suggested next action
- ...
```

For quick responses, compress headings but preserve the distinction between vault facts, session recall, and assumptions.

## Sensitivity Routing

Treat the following as restricted until proven otherwise:

- named person + money;
- salary, commission, bonus, pro-labore;
- hiring, firing, conflicts, performance feedback;
- legal, contracts, NDA, litigation, compliance/privacy;
- client secrets, credentials, tokens, `.env` contents;
- strategic negotiations.

If the question touches restricted content, report that the answer may require restricted review and avoid broadcasting details in broad channels.

## Customization Checklist

Before deploying, replace these placeholders:

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `<VAULT_ROOT>` | Absolute path to the vault | `/home/user/my-brain` |
| `<OWNER_NAME>` | Vault owner name | `Jane Doe` |
| `<SCOPE_1..N>` | Scope classification values | `personal`, `company`, `client` |
| `<EMBED_MODEL_NAME>` | Embedding model for brain-search | `text-embedding-nomic-embed-text-v1.5` |

Add deployment-specific starting points (key projects, areas, resources) after customization.

## Common Pitfalls

1. **Answering from memory when the vault has canonical files.** Always read the vault first for durable facts.
2. **Loading resources before active projects.** PARA order matters.
3. **Mixing runtime with the Second Brain.** Runtime lives in `~/.hermes/`; the vault only has bridge notes.
4. **Treating session recall as canonical.** Label as not consolidated.
5. **Over-reading the vault.** Pull only files relevant to the scope.
6. **Ignoring sensitivity.** Use restricted routing for legal, money, named people, contracts.

## Verification Checklist

- [ ] Vault path customized in this skill
- [ ] Root map and PARA/HERMES context read when relevant
- [ ] Active project checked before resources
- [ ] Area owner identified or explicit lacuna reported
- [ ] brain-search used for concept-level queries (if installed)
- [ ] Decisions/resources cited from vault paths
- [ ] Session history used only as fallback and labeled
- [ ] Sensitive content not exposed casually
- [ ] Response distinguishes consolidated fact, session recall, assumption, and lacuna
