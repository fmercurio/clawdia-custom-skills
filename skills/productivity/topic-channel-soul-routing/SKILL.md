---
name: topic-channel-soul-routing
description: "Use when configuring Telegram topics, Discord channels/threads, or other messaging surfaces so each one has a specialist agent soul/profile while keeping normal conversation separate from explicit Kanban/task intake."
version: 1.0.0
author: Skills Lab
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

Use this skill as a reusable implementation/runbook for any agent runtime that supports platform metadata and profile/soul prompt injection.

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
| `<TENANT_KEY>` | Runtime tenant/account/project scope | `tenant-alpha` |
| `<ENVIRONMENT>` | Runtime environment | `dev`, `staging`, `prod` |
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
Treat real tenant keys, workspace IDs, surface IDs, user IDs, and message links as operational metadata. Use placeholders in reusable docs, examples, tickets, screenshots, and public reports.

## Operating Principles

1. **Conversation first** — a mapped topic/channel is still a place to talk.
2. **Explicit task intake** — create tasks only for explicit prefixes or commands.
3. **Platform-neutral registry** — represent Telegram and Discord with the same conceptual fields.
4. **Soul/profile separation** — soul describes identity/behavior; profile describes runtime/tool/memory isolation when available.
5. **Read-only discovery before mutation** — inspect current config, profiles, boards, and behavior before edits.
6. **No secrets in souls** — SOULs, registry entries, templates, and examples must never contain credentials.
7. **Human confirmation before applying** — show a summary and ask the operator to confirm before writing config or restarting runtime.
8. **Tenant-scoped routing** — in multi-tenant runtimes, match routes by tenant/account/project scope plus platform/workspace/surface IDs, never by surface name alone.
9. **Minimal source references** — task creation should store a compact source reference, not raw message metadata, transcripts, permalinks, or user profile data by default.
10. **Policy before prompt** — route lookup, authorization, and task-prefix detection are policy decisions; a SOUL/profile prompt must not grant itself tools, secrets, broader route scope, or automatic task intake.

## Data Model

Use a platform-neutral registry. The actual filename depends on the runtime; common examples include `topic_souls.yaml`, `channel_souls.yaml`, or a section inside a larger routing config.

```yaml
topic_souls:
  version: "1"
  entries:
    - tenant_key: "<TENANT_KEY>"
      environment: "<ENVIRONMENT>"
      platform: "<PLATFORM>"
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
      source_reference_policy: minimal
      include_permalink: false
      actor_reference: hashed
      status: draft
      activation:
        requires_human_confirmation: true
        approved_by: null
        approved_at: null
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

`active` entries must have a complete tenant/scope key when the runtime serves more than one tenant, account, project, or customer. If the runtime is intentionally single-tenant, document that assumption in the deployment config.

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

Do not paste real workspace IDs, private channel IDs, or message links into shared issue trackers or reusable examples. Keep them in the runtime configuration surface with the same access controls as other operational metadata.

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

### Route resolution and policy order

The runtime should resolve policy before loading surface-specific prompt text:

```text
Normalize tenant/account scope
+ normalize platform/workspace/surface IDs
+ match active route by tenant scope + platform + workspace_id + surface_id
+ verify route activation and operator approval
+ detect explicit task prefix
+ load base runtime prompt
+ load configured SOUL/profile as behavior context only
```

The SOUL/profile can shape tone, domain focus, and response format. It must not expand route scope, grant tools, bypass tenant isolation, read secrets, switch task intake to automatic, or override human-approval requirements.

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
+ load configured soul/profile prompt as behavior context only
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
Include minimal surface context in title/body
Return confirmation with board, task id, profile, and dashboard link when available
```

Store a minimal source reference with the task:

```yaml
source_ref:
  platform: "<PLATFORM>"
  tenant_key: "<TENANT_KEY>"
  workspace_id: "<WORKSPACE_ID>"
  surface_id: "<SURFACE_ID>"
  message_id: "<MESSAGE_ID>"
  actor_ref: "<HASHED_OR_INTERNAL_ACTOR_REF>"
```

Do not include raw message metadata, user profile data, transcripts, or private permalinks unless the deployment has an explicit retention and access-control policy for that data.

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
- [ ] Multi-tenant runtimes include tenant/account/project scope in route matching.
- [ ] Every active route has stable workspace and surface IDs.
- [ ] Active routes require operator approval and cannot be activated by prompt text alone.
- [ ] Normal message test answers conversationally and creates no task.
- [ ] Explicit `task:` test creates one task on the configured board/profile.
- [ ] Disabled/draft entries are ignored by runtime.
- [ ] Wrong workspace/surface does not match a route.
- [ ] Wrong tenant/account/project scope does not match a route.
- [ ] Task source references are minimized and do not store raw private metadata by default.
- [ ] SOUL/profile prompt cannot grant tools, secrets, route scope, or automatic intake.
- [ ] SOUL/profile files contain no secrets.
- [ ] Runtime restart, if needed, was explicitly approved.
- [ ] Operator-facing README or handoff has been provided for non-technical users.

## Common Pitfalls

1. **Routing every message into Kanban.** Specialist surfaces are conversation-first unless explicitly configured as intake-only.
2. **Using human names as the only routing key.** Always discover stable platform IDs before activating routes.
3. **Skipping tenant scope.** Workspace IDs can be stable platform identifiers, but they are not tenant authorization boundaries.
4. **Copying private metadata into tasks.** Store compact source references by default; avoid raw permalinks, transcripts, and user profile data.
5. **Letting prompt text change policy.** SOUL/profile text cannot grant tools, secrets, route scope, or automatic task creation.
6. **Mixing secrets into SOUL files.** Store credentials in the runtime’s secret manager/env/KeePass, never in prompts.
7. **Skipping confirmation.** A wizard can draft config, but it must not apply active routes without operator confirmation.
8. **Restarting the bot/gateway too early.** Validate config and ask first; many runtimes can dry-run route resolution without restart.
9. **Duplicating every global skill into every profile.** Prefer profile overlays only for exceptions; use global skill discovery/fallback when available.
10. **Forgetting operator language.** Product UX should say “configure an agent for this channel”, not “edit SOUL.md and topic_routes”.

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

After confirmation, create/update a platform-neutral route registry with tenant/account scope when applicable, platform, workspace_id, surface_id, surface_type, surface_name, project, board, profile, soul_id, mode=direct, kanban_intake=explicit, status, source_reference_policy=minimal, and human activation metadata.

Validate with two live tests per surface:
- `Qual é sua função neste tópico/canal?` must answer conversationally and create no task.
- `task: teste de criação explícita` must create one task on the configured board/profile.

Do not restart runtime/gateway unless the operator explicitly approves. Do not store secrets, raw private message metadata, or public report examples with real IDs in souls or registry.
```
