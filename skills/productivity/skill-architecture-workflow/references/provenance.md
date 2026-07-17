# Provenance and Upstream Revalidation

This ledger records the external source behind `skill-architecture-workflow`, the exact revision reviewed, the adaptation boundary, and the safe process for revisiting upstream changes.

## Primary source

| Field | Value |
|---|---|
| Upstream project | Tech Leads Club `agent-skills` |
| Upstream skill | `skill-architect` by Felipe Rodrigues |
| Catalog page | https://agent-skills.techleads.club/skills/skill-architect/ |
| Repository | https://github.com/tech-leads-club/agent-skills |
| Revision reviewed | `6663279cd659b60cecb3e8d2dcc13162c88a8b7a` |
| License | CC-BY-4.0 |
| Initial review | 2026-07-15 |

## Adaptation boundary

### Adopted conceptually

- decide whether a recurring need deserves a skill before authoring it;
- define architecture, trigger and anti-trigger contracts;
- use progressive disclosure across `SKILL.md`, references, templates, scripts, and tests;
- validate structure, safety, activation, and promotion criteria.

### Strengthened for Hermes/ClawdIA

- distinguish skills from SOULs, prompts, project instructions, MCPs, scripts, and subagents;
- use the governed custom-skills registry and explicit runtime promotion;
- require security gates, representative validation, profile intent, and source traceability;
- prefer source-level catalog records plus per-skill governance entries.

### Rejected or removed

- external `npx` installation flow;
- assumptions about Claude/Cursor/OpenCode-specific directories and tools;
- automatic import or execution of upstream scripts;
- promotion to runtime without explicit evidence and approval.

No upstream installer was executed. This package is a selective Hermes-native adaptation with attribution retained under CC-BY-4.0.

## Canonical internal locations

- Governed source: `fmercurio/clawdia-custom-skills/skills/productivity/skill-architecture-workflow/`
- Initial PR: https://github.com/fmercurio/clawdia-custom-skills/pull/13
- Runtime: not installed while status is `candidate`

## Revalidation policy

Revalidate read-only when either condition is true:

1. upstream revision changes; or
2. the derived skill is materially edited and the last comparison is more than 90 days old.

During revalidation:

1. inspect the current upstream repository and exact revision without running installers;
2. compare capabilities rather than filenames;
3. classify deltas as already covered, useful improvement, incompatible, or rejected;
4. record the decision here and in the Skills Lab catalog/registry;
5. route accepted improvements through validation, manifest regeneration, registry update, and PR review;
6. never auto-import upstream changes.

## Revalidation log

| Date | Upstream revision | Result |
|---|---|---|
| 2026-07-15 | `6663279cd659b60cecb3e8d2dcc13162c88a8b7a` | Initial selective adaptation; external installer and non-Hermes assumptions removed. |
