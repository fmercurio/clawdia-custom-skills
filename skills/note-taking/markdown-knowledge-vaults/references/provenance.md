# Provenance and Revalidation

## Package

- Name: `markdown-knowledge-vaults`
- Version: `1.0.0`
- Author: Skills Lab
- License: MIT
- Canonical repo path: `skills/note-taking/markdown-knowledge-vaults/`
- Catalog ID: `markdown-knowledge-vaults`
- Last read-only source review: `2026-07-21`

## Primary internal source

This class-level workflow was synthesized from operating and validating the governed package at `packages/second-brain-kit/`. The last reviewed internal revision affecting that package was:

- Commit: `d01d6079ed32b06bf5e2440d5604abbe658ce450`
- Package license: MIT
- Role: lifecycle boundaries, inspect-first onboarding, dry-run/apply separation, retrieval smoke tests, managed inventory, and vault-preserving rollback.

The package-specific reference `second-brain-kit-rc2.md` is historical operational guidance, not a permanent compatibility promise. Revalidate it against the current package before use.

## Indirect build-time lineage

The governed package used the public Tech Leads Club `skill-architect` methodology selectively at build time. It is not a runtime dependency of this skill.

- Source: [Tech Leads Club — `skill-architect`](https://github.com/tech-leads-club/agent-skills/tree/4beb50707194bc8c7861c7480f80eb756f7983ee/packages/skills-catalog/skills/%28creation%29/skill-architect)
- Original package review revision: `e7ab0caa0c0a055e6b230c72769e75a6cb4cbdb5`
- Current read-only revalidation revision: `4beb50707194bc8c7861c7480f80eb756f7983ee`
- License observed: CC BY 4.0 for skill content; repository code MIT
- Concepts retained indirectly: sequential workflow, context-aware path selection, progressive disclosure, explicit exit criteria, and iterative verification.

No external installer or source script was executed while preparing this candidate.

## Adaptation decisions

### Adopted

- separation of package source, Hermes runtime, and knowledge vault;
- durable source requirement for lifecycle-dependent packages;
- read-only inspection of existing vaults before adaptation;
- explicit dry-run and apply gates;
- profile readiness, retrieval, schema, renderer, inventory, and rollback verification.

### Strengthened

- distinct authorization boundaries for Git initialization, commit, remote configuration, and push;
- explicit privacy gates for remote embeddings, restricted content, rendering, and publication;
- clean-room workaround when installer dry-runs depend on bootstrap-created configuration;
- requirement to validate search and graph/schema conformance independently.

### Rejected

- coupling to one tenant, owner, organization, vault path, or profile;
- treating an optional editor or renderer as mandatory;
- assuming a successful installer exit proves a working deployment;
- implicit cron, remote Git, publication, dependency installation, or gateway restart.

### Deferred

- package-version-specific behavior beyond the reviewed RC reference;
- editor-, renderer-, or operating-system-specific installation recipes not required by the class-level workflow.

## Internal composing skills

- `second-brain-operations`
- `hermes-agent`
- `skills-discovery`

## Revalidation policy

Revalidate when `packages/second-brain-kit/` changes materially, when the external build-time source revision changes, when editing this skill's behavior, or after approximately 90 days.

Read-only procedure:

1. Inspect the current governed package, manifest, lifecycle scripts, tests, and documentation without applying them to a live target.
2. Record the current full internal commit SHA.
3. Inspect the public build-time source at its current revision without running installers or scripts.
4. Compare package boundaries, dry-run semantics, profile lifecycle, retrieval, schema, inventory, and rollback behavior with this skill and its RC reference.
5. Never auto-import changes. Route accepted deltas through review, tests, manifest regeneration, registry update, and pull request approval.
6. Append the result below.

## Revalidation log

- `2026-07-21` — reviewed the governed package through `d01d6079ed32b06bf5e2440d5604abbe658ce450` and revalidated Tech Leads Club `skill-architect` at `4beb50707194bc8c7861c7480f80eb756f7983ee`; retained this generic class-level workflow.
