# Provenance and Attribution

## Package

- Name: `autonomous-context-to-spec`
- Version: `1.0.1`
- Author: Skills Lab
- Package license: CC BY 4.0
- Canonical repo path: `skills/productivity/autonomous-context-to-spec/`
- Catalog ID: `autonomous-context-to-spec`
- Last read-only source review: `2026-07-21`

This is a Hermes-native synthesis. External skills are conceptual sources and optional composition points, not install-time dependencies. No upstream installer or source script was executed during review or adaptation.

## Public sources reviewed

| Source | Role in this synthesis | Reviewed revision | Observed license |
|---|---|---|---|
| [Addy Osmani — `idea-refine`](https://github.com/addyosmani/agent-skills/tree/2fbfa004a0192529bc997d103fc12f19a3804aab/skills/idea-refine) | Primary ideation/refinement source | `2fbfa004a0192529bc997d103fc12f19a3804aab` | MIT at repository level; the reviewed `SKILL.md` declares no separate license |
| [Matt Pocock — skills repository](https://github.com/mattpocock/skills/tree/ed37663cc5fbef691ddfecd080dff42f7e7e350d) | Sibling methods for grilling, specification, handoff, architecture, testing, and task shaping | `ed37663cc5fbef691ddfecd080dff42f7e7e350d` | MIT |
| [Tech Leads Club — `the-fool`](https://github.com/tech-leads-club/agent-skills/tree/4beb50707194bc8c7861c7480f80eb756f7983ee/packages/skills-catalog/skills/%28decision-making%29/the-fool) | Critical challenge, evidence audit, pre-mortem, and red team | `4beb50707194bc8c7861c7480f80eb756f7983ee` | CC BY 4.0 for skill content |
| [Tech Leads Club — `tlc-spec-driven`](https://github.com/tech-leads-club/agent-skills/tree/4beb50707194bc8c7861c7480f80eb756f7983ee/packages/skills-catalog/skills/%28development%29/tlc-spec-driven) | Specification depth, traceability, and verification gates | `4beb50707194bc8c7861c7480f80eb756f7983ee` | CC BY 4.0 for skill content |
| [Tech Leads Club — `create-rfc`](https://github.com/tech-leads-club/agent-skills/tree/4beb50707194bc8c7861c7480f80eb756f7983ee/packages/skills-catalog/skills/%28creation%29/create-rfc) | Decision criteria, alternatives, status quo, rationale, and rollback | `4beb50707194bc8c7861c7480f80eb756f7983ee` | CC BY 4.0 for skill content |

The Tech Leads Club repository code is MIT; maintained skill content defaults to CC BY 4.0 unless an individual skill states otherwise. This package therefore remains CC BY 4.0.

### Matt Pocock sibling artifacts considered

At the reviewed revision, the relevant current paths were:

- `skills/productivity/grilling/`
- `skills/productivity/grill-me/`
- `skills/productivity/handoff/`
- `skills/engineering/to-spec/`
- `skills/engineering/tdd/`
- `skills/engineering/codebase-design/`
- `skills/engineering/improve-codebase-architecture/`
- `skills/engineering/to-tickets/`

## Adaptation decisions

### Adopted

- divergent and convergent idea refinement;
- explicit assumptions, validation methods, and “not doing” boundaries;
- steelmanning, evidence audit, dialectic, pre-mortem, and red team;
- requirement closure with visible `HITL`, blocked, assumed, and deferred states;
- decision/RFC gate with criteria defined before options;
- vertical slices with observable verification;
- context-to-decision-to-requirement-to-evidence traceability.

### Strengthened

- explicit run modes separating refinement, specification, planning, execution, and evaluation;
- authorization boundaries for code, trackers, publication, installation, deployment, and production;
- safe clean-room installation stewardship for configuration-dependent dry-runs;
- business-model refinement that separates mechanism, deliverable, benefit, observable outcome, and commercial promise;
- durable ideation through a canonical artifact and meaningful deltas instead of raw transcript capture.

### Rejected

- automatic installation or publication;
- direct dependence on any external skill or installer;
- decomposition primarily by files or architecture layers;
- unconditional micro-commit policies;
- target mutation merely to make a dry-run succeed;
- tenant-, company-, person-, or project-specific examples.

### Deferred

- UI-specific interaction formats tied to one agent host;
- tracker-specific publication behavior;
- non-governed implementation variants not required for standalone use.

## Internal composing skills

When present, this package can compose with these Hermes capabilities while retaining a complete standalone fallback:

- `interactive-grilling`
- `llm-council`
- `writing-plans`
- `software-development-workflows`
- `interface-design-options`
- `afk-issue-triage`
- `autonomous-agent-workflows`
- `agent-handoff`

## Revalidation policy

Revalidate when an upstream revision changes, when materially editing this package, or after approximately 90 days without review.

Read-only procedure:

1. Fetch or clone each repository into a temporary inspection directory without running installers or scripts.
2. Record the new full commit SHA and inspect the exact source paths above.
3. Compare behavior and licensing against this ledger; map renames, splits, deprecations, and meaningful deltas.
4. Never auto-import. Route accepted changes through normal review, tests, manifest regeneration, registry update, and pull request approval.
5. Append a dated entry below with the revisions reviewed and the decision.

## Revalidation log

- `2026-07-21` — reviewed Addy Osmani `2fbfa004a0192529bc997d103fc12f19a3804aab`, Matt Pocock `ed37663cc5fbef691ddfecd080dff42f7e7e350d`, and Tech Leads Club `4beb50707194bc8c7861c7480f80eb756f7983ee`; retained the selective Hermes-native synthesis with no automatic imports.
