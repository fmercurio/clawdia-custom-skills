---
name: topic-channel-soul-routing
description: "Use when configuring Telegram topics, Discord channels/threads, or other messaging surfaces so each one has a specialist agent soul/profile while keeping normal conversation separate from explicit Kanban/task intake."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [topic-routing, profiles, souls, telegram, discord, kanban, tenant-onboarding]
    related_skills: [hermes-agent, github-operations, software-development-workflows]
---

# Topic/Channel Soul Routing

## Overview

This skill turns a messaging workspace into a set of specialist agent surfaces: a Telegram forum topic, Discord channel, Discord thread, or equivalent surface can have its own soul/profile, behavior contract, and default task board.

The core rule is **conversation first, explicit tasks only**. A configured topic/channel should answer in the specialist agent's style for normal messages. It should create Kanban/task items only when the user explicitly asks with prefixes such as `task:`, `tarefa:`, `kanban:`, `/task`, or `/kanban`.

Use this skill as a reusable implementation/runbook for Hermes, ClawdIA tenants, and other agent runtimes that support platform metadata and profile/soul prompt injection.

## When to Use

Use when:

- A user wants a Telegram topic or Discord channel to behave like a specialist agent.
- A tenant needs separate agents for Research, Product, Admin, Support, Engineering, Finance, etc.
- You are designing profile/soul routing, topic-specific prompts, or channel-specific behavior.
- You need to preserve conversational behavior while supporting explicit Kanban intake.
- You are onboarding a non-technical operator who should ask their own agent to configure this.

Do **not** use for:

- A pure task inbox where every message should become a task.
- One-off persona changes inside a single conversation.
- Importing or executing unreviewed external skills.
- Storing secrets, tokens, API keys, or credentials in SOUL/profile files.

## Customization Checklist

Before applying this skill, fill in or discover these values:

| Placeholder | Meaning | Example |
|---|---|---|
| `<PLATFORM>` | Messaging platform | `telegram`, `discord` |
| `<WORKSPACE_NAME>` | Human name of group/server/workspace | `Acme HQ` |
| `<WORKSPACE_ID>` | Stable platform workspace id | `-1001234567890` |
| `<SURFACE_NAME>` | Topic/channel/thread name | `Research` |
| `<SURFACE_ID>` | Stable topic/channel/thread id | `525` |
| `<SURFACE_TYPE>` | Surface kind | `topic`, `channel`, `thread` |
| `<PROJECT_KEY>` | Internal project key | `research` |
| `<BOARD_KEY>` | Kanban/task board | `research` |
| `<PROFILE_NAME>` | Runtime profile/assignee | `researcher` |
| `<SOUL_ID>` | Persona/soul identifier | `researcher` |
| `<SOUL_PATH>` | Optional SOUL/profile file path | `~/.hermes/profiles/researcher/SOUL.md` |

Keep company-specific values in deployment config, not inside the generic skill.

## Operating Principles

1. **Conversation first** — a mapped topic/channel is still a place to talk.
2. **Explicit task intake** — create tasks only for explicit prefixes or commands.
3. **Platform-neutral registry** — represent Telegram and Discord with the same conceptual fields.
4. **Soul/profile separation** — soul describes identity/behavior; profile describes runtime/tool/memory isolation when available.
5. **Read-only discovery before mutation** — inspect current config, profiles, boards, and behavior before edits.
6. **No secrets in souls** — SOULs, registry entries, templates, and examples must never contain credentials.
7. **Human confirmation before applying** — show a summary and ask the operator to confirm before writing config or restarting runtime.

## Data Model

Use a platform-neutral registry. The actual filename depends on the runtime; common examples include `topic_souls.yaml`, `channel_souls.yaml`, or a section inside a larger routing config.

```yaml
topic_souls:
  version: "1"
  entries:
    - platform: "<PLATFORM>"
      workspace_id: "<WORKSPACE_ID>"
      surface_id: "<SURFACE_ID>"
      surface_type: "<SURFACE_TYPE>"
      surface_name: "<SURFACE_NAME>"
      project: "<PROJECT_KEY>"
      board: "<BOARD_KEY>"
      profile: "<PROFILE_NAME>"
      soul_id: "<SOUL_ID>"
      mode: direct
      kanban_intake: explicit
      status: draft
      prompt_summary: >-
        Short description of what this specialist agent does, how it answers,
        and what it must not do without approval.
```

Recommended `status` values:

| Status | Meaning |
|---|---|
| `draft` | Collected but not active; missing IDs or approval |
| `active` | Runtime may route matching messages to this soul/profile |
| `disabled` | Preserved for history but ignored by runtime |

## Wizard Workflow

Run this as a guided wizard. Ask one question at a time unless the user explicitly requests bulk/YAML mode.

### 1. Explain the capability

Use operator-facing wording:

```text
Vamos configurar um agente especialista para um tópico/canal.

Mensagens normais continuam sendo conversa. Tarefas só entram no Kanban quando alguém usar um prefixo explícito como `task:`, `tarefa:`, `kanban:`, `/task` ou `/kanban`.
```

### 2. Choose platform/workspace

Ask:

```text
Qual plataforma e workspace/grupo/servidor você quer configurar?
Se souber o ID técnico, envie também. Se não souber, posso orientar como descobrir.
```

Capture `platform`, `workspace_name`, and `workspace_id`. If the ID is unknown, continue in `draft` mode.

### 3. Choose surfaces

Ask:

```text
Quais tópicos/canais/threads devem ter agentes especialistas?
Pode mandar uma lista com nomes humanos primeiro; depois descobrimos os IDs estáveis.
```

Capture `surface_name`, `surface_type`, and `surface_id` when available.

### 4. Choose or create soul/profile

For each surface, ask:

```text
Para "<SURFACE_NAME>", você quer usar uma soul/profile existente ou criar uma nova especialista?
```

If creating a new specialist, collect:

- short name;
- role/function;
- domain expertise;
- tone;
- response style;
- boundaries/approval rules;
- default board/profile for explicit tasks;
- examples of conversation vs task messages.

### 5. Generate a SOUL/profile prompt

Use this structure:

```markdown
# <SOUL_ID> SOUL

## Role
<What this specialist agent is responsible for.>

## Domain
<Subjects and decisions this agent is strong at.>

## Tone
<Direct, consultative, technical, didactic, critical, creative, etc.>

## Response Style
<How normal replies should be shaped.>

## Boundaries
<What requires explicit approval.>

## Task Intake
Normal messages are conversation. Create tasks only for explicit prefixes:
`task:`, `tarefa:`, `kanban:`, `/task`, `/kanban`, `criar task:`, `criar tarefa:`.

Default board: `<BOARD_KEY>`.
Default profile/assignee: `<PROFILE_NAME>`.
```

### 6. Confirm behavior per surface

Recommended default:

```yaml
mode: direct
kanban_intake: explicit
```

Only use automatic task creation if the operator explicitly says the surface is intake-only.

### 7. Review before writing

Show a summary and ask for confirmation:

```text
Resumo antes de aplicar:
- Platform: <PLATFORM>
- Workspace: <WORKSPACE_NAME> (<WORKSPACE_ID>)
- Surface: <SURFACE_NAME> / <SURFACE_ID>
- Soul: <SOUL_ID>
- Profile: <PROFILE_NAME>
- Board: <BOARD_KEY>
- Behavior: conversa por padrão; Kanban só explícito

Confirmar aplicação?
```

Do not write config until the operator confirms.

### 8. Apply safely

After confirmation:

1. Back up the current routing/profile config.
2. Write or patch registry entries.
3. Create or update SOUL/profile files if the runtime supports them.
4. Validate every `active` entry has platform, workspace id, surface id, profile/soul, and board if task intake is enabled.
5. Run a dry-run resolver or unit tests if available.
6. Ask before restarting gateway/bot/runtime.

## Runtime Behavior Contract

### Normal message

Input:

```text
Qual é sua função neste tópico/canal?
```

Expected behavior:

```text
Load base runtime prompt
+ load platform/chat context
+ load surface-specific route
+ load configured soul/profile prompt
+ answer conversationally
+ do not create a Kanban task
```

### Explicit task message

Input:

```text
task: pesquisar benchmarks para agentes autônomos e documentar recomendações
```

Expected behavior:

```text
Create task on configured board
Assign configured profile/agent
Include surface context in title/body
Return confirmation with board, task id, profile, and dashboard link when available
```

### Supported explicit prefixes

Support at least:

```text
/task ...
/kanban ...
task: ...
kanban: ...
tarefa: ...
criar task: ...
criar tarefa: ...
```

Do not trigger tasks from vague phrases such as “precisamos”, “seria bom”, “vamos fazer”, or “alguém deveria”.

## Validation Checklist

- [ ] Existing config, profiles/souls, boards, and platform metadata inspected before mutation.
- [ ] Every active route has stable workspace and surface IDs.
- [ ] Normal message test answers conversationally and creates no task.
- [ ] Explicit `task:` test creates one task on the configured board/profile.
- [ ] Disabled/draft entries are ignored by runtime.
- [ ] Wrong workspace/surface does not match a route.
- [ ] SOUL/profile files contain no secrets.
- [ ] Runtime restart, if needed, was explicitly approved.
- [ ] Operator-facing README or handoff has been provided for non-technical users.

## Common Pitfalls

1. **Routing every message into Kanban.** Specialist surfaces are conversation-first unless explicitly configured as intake-only.
2. **Using human names as the only routing key.** Always discover stable platform IDs before activating routes.
3. **Mixing secrets into SOUL files.** Store credentials in the runtime’s secret manager/env/KeePass, never in prompts.
4. **Skipping confirmation.** A wizard can draft config, but it must not apply active routes without operator confirmation.
5. **Restarting the bot/gateway too early.** Validate config and ask first; many runtimes can dry-run route resolution without restart.
6. **Duplicating every global skill into every profile.** Prefer profile overlays only for exceptions; use global skill discovery/fallback when available.
7. **Forgetting tenant language.** Product UX should say “configure an agent for this channel”, not “edit SOUL.md and topic_routes”.

## One-Shot Handoff Prompt

Use when asking another implementation agent to configure this capability:

```text
Configure a specialist agent for each selected Telegram topic, Discord channel/thread, or equivalent messaging surface.

Normal messages must remain conversational. Create Kanban/tasks only when the user starts with `/task`, `/kanban`, `task:`, `kanban:`, `tarefa:`, `criar task:` or `criar tarefa:`.

First run a wizard with the operator:
1. choose platform/workspace;
2. collect surface names and stable IDs;
3. choose existing soul/profile or create a new specialist;
4. define role, domain, tone, response style, boundaries, default board/profile;
5. show a summary and ask for confirmation before writing config.

After confirmation, create/update a platform-neutral route registry with platform, workspace_id, surface_id, surface_type, surface_name, project, board, profile, soul_id, mode=direct, kanban_intake=explicit, status.

Validate with two live tests per surface:
- `Qual é sua função neste tópico/canal?` must answer conversationally and create no task.
- `task: teste de criação explícita` must create one task on the configured board/profile.

Do not restart runtime/gateway unless the operator explicitly approves. Do not store secrets in souls or registry.
```
