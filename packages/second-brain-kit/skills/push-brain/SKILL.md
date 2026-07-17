---
name: push-brain
description: Consolidate durable session knowledge into a configured Second Brain. Use for “salva isso no cérebro”, “fecha sessão”, “sync”, a lasting decision, or a meaningful project update. Do not use to dump raw chat, secrets, or temporary task progress.
version: 0.1.0-rc2
author: Skills Lab
license: MIT
metadata:
  hermes:
    tags: [second-brain, consolidation, provenance, sensitivity]
    related_skills: [pull-brain, brain-search, second-brain-operations]
---

# Push Brain

Resolve the deployment through config. This skill composes with other skills and never assumes exclusive control of the session.

## Brain Delta workflow

1. Pull current canonical state before changing shared knowledge.
2. Extract only durable deltas: decisions, project state, area lessons, reusable resources, or unresolved questions.
3. Classify by intent/type; use PARA as the physical fallback.
4. Add provenance and sensitivity. Never write credentials or raw private transcripts.
5. Prefer patching an existing canonical note over creating a duplicate.
6. Run health-check, rebuild FTS5, and run a representative query.
7. Commit or push only according to configured Git policy; remote push is never assumed.

Restricted writes require an authorized destination and explicit confirmation when scope is unclear.

## Exit criteria

- Every saved delta has a destination, provenance, and sensitivity.
- No secrets or transient logs were written.
- Health check and index rebuild pass.
- The final report lists changed paths and verification results.
