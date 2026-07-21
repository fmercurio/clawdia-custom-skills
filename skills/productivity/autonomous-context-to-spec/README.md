# Autonomous Context-to-Spec — Portable Agent Skill

A portable Agent Skills package for turning an existing context into a refined, stress-tested, traceable concept, specification, vertical-slice plan, or explicitly authorized implementation.

## What it does

```text
Context intake
  → divergent/convergent idea refinement
  → critical stress-test
  → requirement closure gate
  → optional RFC/decision memo
  → specification
  → vertical slices
  → optional authorized implementation
  → evidence-backed verification
```

The skill is standalone. If companion skills such as `idea-refine`, `interactive-grilling`, `the-fool`, `project-context-grilling`, `llm-council`, or `afk-issue-triage` are available, it can use them. If they are absent, the package contains complete fallback instructions.

## Package contents

```text
autonomous-context-to-spec/
├── SKILL.md
├── README.md
├── references/
│   ├── full-workflow.md
│   ├── business-model-refinement.md
│   ├── safe-installation-stewardship.md
│   └── provenance.md
├── templates/
│   ├── context-input.md
│   └── result.md
└── MANIFEST.sha256
```

## Installation

Copy the complete `autonomous-context-to-spec/` directory into the skills directory supported by your agent.

Examples:

- Hermes Agent: place under `~/.hermes/skills/<category>/autonomous-context-to-spec/`.
- Repository-local Agent Skills setups: place under the agent's documented project skill directory.

Do not copy only `SKILL.md`; the workflow and templates are linked supporting files.

No dependency installation or script execution is required.

## Usage

### Refine context into a specification

```text
Use autonomous-context-to-spec in refine-and-spec mode.
Context: <paste text or provide paths/URLs>.
Write the final Markdown artifact to <path>.
Do not modify product code or publish anything externally.
```

### Produce an implementation plan without coding

```text
Use autonomous-context-to-spec in plan mode against <project/context>.
Inspect the repository before asking questions.
Produce vertical slices classified AFK/HITL/Blocked.
Do not modify code, commit, create issues, or deploy.
```

### Execute after explicit authorization

```text
Use autonomous-context-to-spec in execute mode against <repo/path>.
Code changes are authorized only inside <scope>.
No deploy or production changes.
Implement one vertical slice at a time and report actual test output.
```

### Evaluate an implementation against its spec

```text
Use autonomous-context-to-spec in evaluate mode.
Spec: <path>.
Implementation: <repo/commit/diff>.
Remain read-only over the evaluated subject and cite file:line evidence.
```

## Input template

Start from `templates/context-input.md`. Explicit permissions matter: autonomy to analyze does not imply permission to write code, create tracker items, publish, install dependencies, or deploy.

## Safety model

Default permissions:

- read authorized context: allowed;
- write the requested local Markdown artifact: allowed when explicitly requested;
- modify product code: denied;
- create GitHub/Linear/Kanban items: denied;
- publish externally: denied;
- install packages/plugins/skills: denied;
- deploy or touch production: denied.

The skill records low-risk reversible assumptions and proceeds, but stops for consequential HITL decisions or missing authorization.

## Compatibility

The package follows the common `SKILL.md` format and uses no executable helper scripts. Agent-specific tool names are avoided in the core protocol. When a preferred companion skill or tool is unavailable, the embedded fallback is authoritative.

## License and attribution

Package license: **CC BY 4.0**.

See `references/provenance.md` for conceptual sources and attribution. External source names do not authorize automatic installation or execution of their packages.
