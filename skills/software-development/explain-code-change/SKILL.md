---
name: explain-code-change
description: "Use when a diff, branch, commit, or PR needs a secure, source-grounded teaching artifact with deterministic quiz reinforcement and offline self-contained HTML output."
version: 0.1.1
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags:
      - explainability
      - code-review
      - quiz
      - hermes
      - software-development
    related_skills:
      - software-development-workflows
      - github-operations
      - claude-design
---

# Explain Code Change

This skill implements an **Explain Change** mode for code-review workflows. It is a clean-room Hermes-native adaptation inspired by the external outline at `https://gist.github.com/geoffreylitt/a29df1b5f9865506e8952488eac3d524`. No prose from that source was copied verbatim; only high-level structure was reused as a conceptual reference.

Use this skill when the request is to summarize a code diff and teach what changed, why it changed, and how to reason about it safely.

## Provenance and Upstream Maintenance

The complete source ledger, adopted/rejected decisions, reviewed revisions, license observations, and revalidation procedure live in `references/provenance.md`.

Use that reference when:

- changing this skill materially;
- checking whether the original sources evolved;
- deciding whether an upstream improvement should be incorporated;
- answering who influenced a specific mechanism.

Do not auto-import upstream changes. Revalidate read-only, compare capability deltas, and incorporate only reviewed improvements through the governed repo, tests, manifest, and PR workflow.

## Triggers

- User asks for a code-review explanation artifact for a diff, patch, merge request, or change bundle.
- User asks for a teaching output that includes a small quiz.
- User explicitly requests a local artifact path and a deterministic render for reproducibility.
- User asks for an “Explain Change” mode tied to `software-development-workflows`, `github-operations`, or `claude-design` workflows.

## Counter-Triggers

- Do not use for general chat or creative writing.
- Do not use for PR approvals, approvals text, or legal sign-off.
- Do not use for secrets extraction, credential sharing, or dumping raw private artifacts.
- Do not use for external publishing or sending artifacts outside the approved runtime scope.
- Do not use as a substitute for direct code execution or policy validation.

## Source-of-Truth Investigation Workflow (Mandatory)

Before drafting explanations, the agent must inspect and cite only verified sources:

1. **Primary diff**
   - Inspect the actual change diff/patch and confirm every factual statement against it.
2. **Baseline and target state**
   - Inspect the base reference (`main`, previous tag, previous commit) and the target change.
3. **Callers and integration points**
   - Inspect caller paths (importers, routers, entry points, and CLI entrypoints) to ground behavioral impact.
4. **Tests and config**
   - Inspect affected tests, CI gates, and runtime config that gate behavior.
5. **Documentation and issues**
   - Inspect in-repo docs, comments, and prior context to identify intended behavior and constraints.

The artifact must distinguish:

- **Fact**: directly evidenced by the inspected diff/base/callers/tests/config/docs.
- **Interpretation**: reasoned synthesis, risk framing, and educational guesswork.

Do not invent behavior not visible in source. If evidence is missing, mark it as “interpretation” and keep wording explicit about uncertainty.

## Security and Privacy Rules

- Never embed secrets, tokens, private keys, or raw credentials.
- Do not include large proprietary code blocks that are not necessary for explanation.
- Redact or summarize private values instead of reproducing them.
- Keep artifact path constrained to the requested local artifact directory.
- Never send artifacts, rendered HTML, or intermediate data outside scope.
- Do not include external network calls or remote asset URLs in the artifact.

Return the exact artifact path produced by the renderer.

## Content Spec and Render Workflow

1. Collect evidence and draft a JSON content spec that conforms to `references/content-spec.md`.
2. Validate locally by running:

```bash
SKILL_DIR="${HERMES_HOME:-$HOME/.hermes}/skills/software-development/explain-code-change"
python3 "$SKILL_DIR/scripts/render_explanation.py" \
  "$SKILL_DIR/templates/content-spec.example.json" \
  --output /tmp/explain-code-change.html
```

3. The renderer requires:

- `metadata` with required fields.
- Exactly four sections in order:
  - `background`
  - `intuition`
  - `code`
  - `quiz`
- Quiz block with exactly five questions.
- Each question with 3 to 5 options and one valid correct index.

4. Default artifact behavior:

- If `--output` is not provided, output path must be
  `~/.hermes/artifacts/explain-code-change/<YYYY-MM-DD>-<slug>.html`.
- The renderer must write a single local, self-contained, offline HTML file.
- If `--strict` is passed, all quiz-quality warnings must fail the run.

## Quiz Quality Rules

- Exactly **five** questions.
- Each question has exactly 3 to 5 options.
- One and only one valid correct index.
- Options should not duplicate each other (case-insensitive normalized form).
- Correct option length should not be a conspicuous outlier compared to distractors.
- Shuffle options deterministically from seed and balance correct-answer positions across questions.
- Feedback must be textual ("Correct"/"Incorrect") and cannot rely on color alone.

## Output Contract

- Output is a single standalone `.html` file.
- No external JS/CSS/asset dependencies.
- No inline JS event handlers.
- Include TOC, semantic sections, accessible focus states, responsive layout, and reduced-motion support.
- Preserve source-derived text with escaping to prevent injection.

## Pitfalls

- Confusing interpretation as fact.
- Forgetting to validate exactly five quiz questions.
- Exposing correct answer metadata in DOM attributes or accessibility labels before interaction.
- Allowing duplicate distractors to make quiz quality degenerate.
- Running a renderer with defaults that writes outside approved artifact scope.
- Ignoring caller-level impact while only reading file-local diff.

## Verification Checklist

- [ ] Metadata validated and required fields present.
- [ ] Sections are exactly `background`, `intuition`, `code`, `quiz` in that order.
- [ ] Quiz has exactly five questions.
- [ ] Each quiz question has 3-5 options and one valid correct index.
- [ ] Leakage warnings are reviewed and either fixed or justified.
- [ ] No secrets or private identifiers in rendered artifact.
- [ ] Output file is a single local artifact with mode `0600`.
- [ ] Returned path is the exact artifact path used.
