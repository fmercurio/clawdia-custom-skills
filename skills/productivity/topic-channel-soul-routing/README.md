# Configure Specialist Agents per Topic/Profile

This README is for a user/operator who wants to ask their own agent to turn a Telegram topic, Discord channel/thread, or similar messaging surface into a specialist agent.

You do **not** need to know implementation details such as `SOUL.md`, route registries, thread IDs, or profile overlays before starting. Ask your agent to guide you.

## What you are configuring

You are creating a mapping like this:

```text
A specific topic/channel/thread
→ uses a specific specialist agent identity
→ answers normal messages conversationally
→ creates tasks only when explicitly asked
```

Example:

```text
#research → Research specialist
#product → Product/design specialist
#support → Support specialist
#admin → Operations/admin specialist
```

## Step-by-step: ask your agent

Copy this message to your agent:

```text
I want to make one or more messaging topics/channels into specialist agent spaces.

Please guide me step by step. I want normal messages to stay conversational, and I want tasks/Kanban items to be created only when someone explicitly starts a message with `task:`, `tarefa:`, `kanban:`, `/task`, or `/kanban`.

Start by asking which platform/workspace I want to configure, then help me list the topics/channels, choose or create a specialist profile/soul for each one, define its role/tone/boundaries, and show me a final summary before applying anything.

Do not write config, create active routes, or restart the runtime until I confirm.
Do not store secrets in any profile, SOUL, prompt, or route registry.
```

Then answer your agent’s questions in order.

## Step 1 — Choose the platform/workspace

Tell the agent where this should work:

- Telegram group/forum topics;
- Discord server channels;
- Discord threads;
- Slack channels;
- another platform supported by your runtime.

Useful information:

```text
Platform: Telegram
Workspace/group/server name: Acme HQ
Technical ID: I do not know yet / here is the ID: ...
```

If you do not know the technical ID, say so. The agent should help discover it or leave the route as a draft until it is known.

## Step 2 — List the topics/channels

Send a simple list first:

```text
I want specialist agents for:
- Research
- Product
- Support
- Admin
```

The agent should later map each human name to a stable platform ID before activating routes.

## Step 3 — Decide the specialist for each topic/channel

For each surface, choose one:

1. use an existing profile/soul;
2. create a new specialist profile/soul;
3. reuse the same specialist across multiple surfaces.

Example:

```text
Research should use a new `researcher` specialist.
Product should use a new `product-strategist` specialist.
Admin can reuse the existing `ops-admin` profile.
```

## Step 4 — Define the specialist

For each new specialist, provide:

| Field | What to say | Example |
|---|---|---|
| Name | Short ID | `researcher` |
| Role | What it does | Researches options and recommends next steps |
| Domain | What it knows | Market research, technical evaluation, citations |
| Tone | How it sounds | Direct, critical, source-driven |
| Response style | How replies are shaped | Verdict first, then evidence and trade-offs |
| Boundaries | What needs approval | No purchases, no production changes, no private data access |
| Default board | Where explicit tasks go | `research` |

Example answer:

```text
Name: researcher
Role: finds, compares, and recommends options.
Domain: web research, tools, benchmarks, academic/technical sources.
Tone: direct and critical.
Response style: verdict first, bullets, cite sources when available.
Boundaries: do not buy services, do not contact vendors, do not change production without approval.
Default board/profile: research / researcher.
```

## Step 5 — Confirm conversation vs task behavior

Recommended default:

```text
Normal messages = conversation.
Tasks only when explicit.
```

Use explicit task prefixes like:

```text
task: compare three options and recommend one
/tarefa revisar o onboarding
kanban: create a follow-up for next week
```

Avoid making vague phrases auto-create tasks:

```text
We should improve this someday.
It would be nice to review this.
Maybe someone can check this.
```

Those should remain conversation unless your workspace intentionally has intake-only channels.

## Step 6 — Review the summary before applying

Before your agent writes config, ask it to show something like:

```text
Summary before applying:
- Platform: Telegram
- Workspace: Acme HQ
- Topic/channel: Research
- Specialist: researcher
- Profile: researcher
- Board: research
- Behavior: conversation by default; tasks only with explicit prefixes
- Status: draft/active
```

Only approve if the summary is correct.

## Step 7 — Apply safely

Tell your agent:

```text
Apply this only after backing up the current config.
Validate the route registry before any restart.
If a runtime/bot/gateway restart is needed, ask me first.
```

The agent should not put credentials, tokens, cookies, passwords, private keys, or customer secrets into any profile/soul/route file.

## Step 8 — Test it live

For each configured topic/channel, send two test messages.

### Conversation test

```text
What is your role in this topic/channel?
```

Expected result:

```text
The specialist answers conversationally.
No task is created.
```

### Explicit task test

```text
task: test explicit task creation for this topic
```

Expected result:

```text
One task is created on the configured board/profile.
The agent confirms board, task id, and assignee/profile.
```

## Full copy/paste prompt

Use this if you want a single message:

```text
Please configure specialist agents for my messaging topics/channels.

Requirements:
- normal messages should be conversation;
- task/Kanban creation should happen only with explicit prefixes: `task:`, `tarefa:`, `kanban:`, `/task`, `/kanban`, `criar task:`, `criar tarefa:`;
- each selected topic/channel/thread should map to a specialist profile/soul;
- ask me one step at a time;
- show a final summary before writing anything;
- back up config before changing it;
- do not restart the runtime/gateway without my approval;
- do not store secrets in prompts, SOUL files, profiles, or route registries.

Start by asking which platform/workspace I want to configure.
```

## Safety checklist

- [ ] I know which workspace/platform I am configuring.
- [ ] Each active topic/channel has a stable technical ID.
- [ ] Each specialist has a clear role, tone, boundaries, and default board/profile.
- [ ] Normal message test does not create tasks.
- [ ] Explicit `task:` test creates exactly one task.
- [ ] No secrets are stored in prompts or config.
- [ ] Runtime restart, if needed, was approved by a human operator.
