---
name: second-brain-operations
description: Step-by-step playbook for setting up and operating a PARA-first Second Brain with Hermes — vault creation, pull/push skills, health-check cron, weekly review, and operational rhythm.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [second-brain, para, obsidian, hermes, operations, playbook]
    related_skills: [second-brain-knowledge-architecture, pull-brain, push-brain]
---

# Second Brain Operations

## Overview

Implementation playbook for building and operating a PARA-first Second Brain with Hermes as the operator.

Use this skill when the user wants to:
- Set up a new second brain from scratch;
- Understand the proven vault structure and conventions;
- Create pull-brain and push-brain skills;
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
- Skills: `pull-brain` and `push-brain` as Hermes local skills
- Separation: vault (durable knowledge) ≠ runtime (Hermes) ≠ backups

## How to Use This Skill

### Setup (one-time)

The client invokes this skill to start a new second brain:

```
/second-brain-operations
```

Or in natural language: "quero montar um segundo cérebro", "setup second brain", "criar vault PARA".

The agent then follows Phases 1–7 in order, asking the client questions at each phase and implementing as it goes. The client does not need to know Git, Python, YAML, or Hermes internals — the agent handles everything.

**What the client provides:**
- Purpose and scope of the vault
- Owner name
- Sensitivity preferences
- Whether Hermes will be the operator

**What the agent creates:**
- Vault with PARA structure + root files
- Health-check script
- `pull-brain` and `push-brain` skills
- Cron configuration for automated auditing

**What the client receives as commands:**
- `/pull-brain` — load context from the vault
- `/push-brain` — save session output to the vault

### Ongoing use

After setup, the client uses `/pull-brain` and `/push-brain` naturally in their sessions. The agent follows the rituals automatically when these commands are invoked.

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

Add `.obsidian/` to `.gitignore`.

## Phase 3: Health-Check Script

### What to audit

1. Frontmatter compliance — canonical notes with valid `para:`
2. Project staleness — active projects without `updated:` in 14 days
3. Inbox staleness — items older than 30 days
4. Runtime contamination — `.env`, `config.yaml` inside vault
5. Overall compliance %

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

## Phase 4: Pull-Brain Skill

Create `~/.hermes/skills/note-taking/pull-brain/SKILL.md`.

### Retrieval order (PARA)

1. Project → 2. Area → 3. Resource → 4. Archive → 5. Inbox/session_search

### Key sections

- Triggers and aliases
- Source of truth (vault path + key files)
- Workflow (scope → root → search → read → fallback)
- Return format (consolidated / session recall / assumptions / gaps)
- Sensitivity routing
- Pitfalls (memory over vault, resources before projects, mixing layers)

## Phase 5: Push-Brain Skill

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

1. Read current state → 2. Choose destination → 3. Write concisely → 4. Update status → 5. Health-check → 6. Commit

### Key sections

- Triggers and aliases
- Classification table
- PARA destinations
- Sensitivity routing
- Output format (paths, health-check, commit, next step)
- Pitfalls (chat dumps, duplicates, forgetting health-check)

## Phase 6: Cron Configuration

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

## Phase 7: Weekly Review

### Checklist

1. Projects — still active? stalled? archive?
2. Areas — context current? decisions/lessons to add?
3. Resources — distill, update, or archive?
4. Inbox — promote, archive, or discard (items > 30 days)
5. Decisions — reflected in area/project files?
6. Gaps — what's missing?
7. Health-check — manual run
8. Git — commit all

### Output

Save to `_Meta/revisoes-semanais/YYYY-MM-DD.md`:
- Executive summary
- Projects/areas reviewed
- Inbox processed
- Decisions made
- Gaps identified
- Next priorities

## Phase 8: Operational Rhythm

| Cadence | Actions |
|---------|---------|
| Daily | Capture to inbox; push-brain after meaningful sessions |
| Weekly | Health-check cron + manual review + inbox processing |
| Monthly | Review areas; archive inactive; update contexts |
| Quarterly | Review structure; consider splitting vaults |

## Phase 9: Client Offering

### Deliverables

1. Vault template (PARA folders + templates)
2. Health-check script (drop-in)
3. Setup guide (this skill as reference)
4. Training session (pull/push walkthrough)
5. Optional: Hermes operator (skills + cron)

### Pricing tiers

| Tier | Included |
|------|----------|
| DIY | Template + guide + health-check script |
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

## Verification Checklist

- [ ] Vault created with PARA structure
- [ ] Root files exist (MAPA, PARA, HERMES, README)
- [ ] Frontmatter PARA contract defined
- [ ] Templates created
- [ ] Health-check script created and tested
- [ ] Pull-brain skill created and tested
- [ ] Push-brain skill created and tested
- [ ] `/reload-skills` run after skill creation
- [ ] Skills tested as `/` commands in gateway
- [ ] Cron configured and triggered once
- [ ] Weekly review ritual defined
- [ ] First real session consolidated via push-brain
- [ ] Git initialized with initial commit
- [ ] `.gitignore` protects secrets and `.obsidian/`
