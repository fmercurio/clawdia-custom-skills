# Provenance and Upstream Revalidation

This document records the external ideas and internal skills that shaped `explain-code-change`. It exists so future maintainers can revisit upstream sources without losing attribution, importing code blindly, or repeating the original evaluation.

## Canonical implementation

- Runtime skill: `~/.hermes/skills/software-development/explain-code-change/`
- Governed source: `fmercurio/clawdia-custom-skills`, path `skills/software-development/explain-code-change/`
- Initial PR: <https://github.com/fmercurio/clawdia-custom-skills/pull/15>
- Skills Lab catalog ID: `geoffreylitt-explain-diff`

## External sources and influences

| Role | Source | Author | Revision reviewed | License observed | Relationship to this skill |
|---|---|---|---|---|---|
| Primary conceptual source | [explain-diff gist](https://gist.github.com/geoffreylitt/a29df1b5f9865506e8952488eac3d524), file `explain-diff-html.md` | Geoffrey Litt | Gist `126e7fe9eecaafadfe1ac8bb183d135812b608f2`; HTML raw revision `e4982a26bc8975dd45eeb96ad8c68f2f25fc42c7`; reviewed 2026-07-17 | No explicit license found | Inspired the Background → Intuition → Code → Quiz teaching structure and the self-contained HTML format. No prose or code was copied verbatim. |
| Upstream sibling considered | Same gist, file `explain-diff-notion.md` | Geoffrey Litt | Gist revision above; raw revision `a10eb18f5b03aa35cbcd5f9d977bb5edb2f237ad` | No explicit license found | Evaluated and intentionally excluded because Felippe confirmed that this environment does not use Notion. |
| Community quality feedback | [Comments on the primary gist](https://gist.github.com/geoffreylitt/a29df1b5f9865506e8952488eac3d524) | Butanium, fm1randa, yudhiesh-oc and others | Reviewed 2026-07-17 | Comment authors retain their own rights | Informed answer-position balancing, comparable option lengths, plausible distractors, and browser validation. Used as design feedback, not copied implementation. |
| Renderer separation idea | [ankitg12 fork](https://gist.github.com/ankitg12/8e808d387799de4e9839bc393f8e6405), referenced from a source comment | ankitg12 | Link reviewed 2026-07-17; fork code was not executed or imported | Not established during initial review | Reinforced the architectural decision to separate a structured content spec from deterministic rendering. The local renderer was written clean-room with Python stdlib. |

## Internal skills composed

These are dependencies or operating patterns, not upstream ownership claims:

- `software-development-workflows` — inspect the real change, tests, contracts, and surrounding code.
- `github-operations` — obtain and verify PR/base/commit state.
- `claude-design` — produce and visually verify a standalone HTML artifact.
- `skills-discovery` — compare capabilities, avoid duplicate imports, and revalidate external sources safely.

## What was adopted, changed, and rejected

### Adopted conceptually

- Beginner-to-expert background followed by change-specific context.
- A concise intuition section before implementation details.
- Code walkthrough grouped by behavior rather than arbitrary file order.
- Five interactive questions for reinforcement.
- A single responsive HTML artifact outside the code repository.

### Strengthened locally

- Mandatory inspection of diff, base, callers, tests, configuration, and documentation.
- Explicit fact-versus-interpretation discipline.
- JSON content contract plus a deterministic stdlib renderer.
- Balanced answer positions and quiz-leakage heuristics.
- HTML/JavaScript escaping, offline assets, atomic write, and mode `0600`.
- Automated tests, checksum manifest, strict mode, and browser interaction checks.

### Rejected or deferred

- Notion publishing: rejected by explicit product decision.
- External installers or third-party scripts: not needed and never executed.
- Automatic upstream synchronization: rejected; every delta requires review.

## Revalidation policy

Do not run a blind scheduled import. Revalidate read-only when either condition is true:

1. this skill is being materially changed and the last review is more than 90 days old; or
2. the upstream gist revision differs from the revision recorded above.

Recommended read-only check:

```bash
curl -fsSL \
  https://api.github.com/gists/a29df1b5f9865506e8952488eac3d524 \
  -o /tmp/explain-diff-upstream.json
python3 - <<'PY'
import json
p = "/tmp/explain-diff-upstream.json"
d = json.load(open(p, encoding="utf-8"))
print("updated_at:", d["updated_at"])
print("gist_version:", d["history"][0]["version"])
for name, item in d["files"].items():
    print(name, item["raw_url"])
PY
```

Then:

1. inspect changed prose and comments without executing anything;
2. compare mechanisms, not filenames;
3. classify each delta as already covered, useful improvement, incompatible scope, or reject;
4. record the decision in this file and in Skills Lab catalog entry `geoffreylitt-explain-diff`;
5. update the skill only through its governed repository, tests, manifest, and PR review;
6. update `Revision reviewed` only after the comparison is complete.

## Revalidation log

| Date | Upstream gist version | Result |
|---|---|---|
| 2026-07-17 | `126e7fe9eecaafadfe1ac8bb183d135812b608f2` | Initial clean-room adaptation. HTML teaching structure adopted; quiz feedback incorporated; Notion excluded; deterministic local renderer implemented. |
