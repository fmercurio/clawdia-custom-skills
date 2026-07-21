# Full Workflow Protocol

This reference expands the phases in `SKILL.md`. Auto-size depth but do not reorder the logic.

## Phase 0 — Intake and evidence map

Read all authorized context. In repositories inspect README/agent instructions, domain context, ADRs, specs, plans, tests, and current state before asking questions.

Produce internally:

```markdown
## Context map
### Facts
- fact + source
### Existing decisions
- decision + reason/source
### Constraints
- ...
### Unknowns
- ...
### Contradictions
- ...
### Initial confidence
- HIGH / MEDIUM / LOW — rationale
```

**Exit:** one sentence states who has which problem, why it matters, and the sought outcome.

## Phase 1 — Diverge and converge

Restate:

```markdown
**Raw idea:**
**Underlying problem:**
**Primary user:**
**Desired outcome:**
**Current constraints:**
```

Generate 3–5 substantive directions. For each:

```markdown
### Direction N — Name
- Core approach:
- User value:
- Key assumption:
- Cost/complexity:
- Main risk:
- Fastest validation:
```

Compare value, evidence, risk, reversibility, cost/time, constraints, learning speed, and maintenance. Recommend one and record what evidence could reopen discarded options.

## Phase 2 — Critical stress-test

Steelman the recommendation first. Select a mode:

| Mode | Trigger |
|---|---|
| assumption-audit | hidden premises dominate |
| evidence-test | claims are stronger than evidence |
| dialectic | viable options conflict |
| pre-mortem | adoption or operational failure dominates |
| red-team | adversaries, abuse, competition, or security dominate |

For each of the strongest 3–5 challenges:

```markdown
### Challenge N — Name
- Claim under challenge:
- Why it may fail:
- Evidence available:
- Evidence missing:
- Consequence if wrong:
- Mitigation or experiment:
```

Synthesize objections incorporated, open trade-offs, riskiest assumption, minimum experiment, and confidence (`HIGH`, `MEDIUM`, `LOW`, `PIVOT`).

## Phase 3 — Requirement closure

Sweep only relevant dimensions: input bounds, failure/partial failure, retry/duplicates, authorization, concurrency/order, data lifecycle, observability, external dependencies, state transitions, adoption/ownership.

Classify every material ambiguity:

| Item | Type | Default/decision | Rationale | Confidence | Invalidated by | Status |
|---|---|---|---|---|---|---|

Statuses: confirmed, assumed, deferred, HITL, blocked, or `N/A — reason`.

## Phase 4 — Decision memo gate

Use only for multiple viable consequential options. Define criteria and weights before options. Include assumptions, status quo when relevant, recommendation tied to criteria, consequences, and rollback. Otherwise record why skipped.

## Phase 5 — Specification

A proportional spec contains:

- executive summary;
- problem and primary user;
- recommended direction;
- goals and non-goals;
- assumptions with validation methods;
- prioritized stories;
- precise observable acceptance criteria;
- edge/failure cases;
- success metrics with baseline/target/measurement;
- security/privacy and operations when relevant;
- deferred ideas;
- HITL/Blocked items.

Prefer: `WHEN [event] THEN [system] SHALL [observable result].`

## Phase 6 — Vertical slices

Each slice is a narrow end-to-end demonstrable outcome:

```markdown
## Slice N — Observable outcome
**Classification:** AFK / HITL / Blocked
**Category:** product / engineering / ops / editorial
**User-visible outcome:**
**Requirements:**
**Blocked by:**
**In scope:**
**Out of scope:**
**Acceptance criteria:**
**Verification:**
**Rollback/safety:**
```

Tests travel with behavior. Dependencies must be real. Do not split primarily by file, component, database, API, UI, and test layers.

## Phase 7 — Execution

Only with explicit mode, scope, workdir, and write authorization. Record Git/test baseline, work one slice at a time, use real failing tests before behavior changes, implement minimum, rerun targeted and regression gates, preserve actual logs, avoid unrelated refactors, and commit only when authorized.

Prefer independent verification for consequential changes. Mutation or fault injection belongs in a worktree/copy, not the live tree.

## Phase 8 — Traceability and final gate

```markdown
| Context evidence | Decision/assumption | Requirement | Slice | Verification evidence | Status |
|---|---|---|---|---|---|
```

Final gate:

- context facts and inferences are distinct;
- meaningful alternatives were considered;
- recommendation survived challenge;
- ambiguity is resolved or visible;
- acceptance criteria are observable;
- non-goals are explicit;
- slices are vertical;
- no side effect exceeded authorization;
- every success claim has evidence.

## Handoff when pausing

Record active task, goal, inspected context, completed phases, current recommendation, decisions/assumptions, HITL/blockers, exact next phase and action, relevant paths, and verification status. The next agent should resume without reconstructing the session.
