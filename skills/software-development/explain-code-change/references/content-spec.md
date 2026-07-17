# explain-code-change Content Spec

Use this schema to build JSON consumed by `scripts/render_explanation.py`.

## JSON root

```json
{
  "metadata": { ... },
  "sections": [ ... ]
}
```

## Metadata

Required fields:

- `title`: Human title shown on artifact.
- `artifact_slug`: Short slug for default filename.
- `change_id`: Stable change identifier.
- `base_ref`: Source/base reference (branch, tag, or commit).
- `target_ref`: Target/reference being explained.

Optional:

- `seed`: Quiz shuffle seed override (int).
- `generated_at`: Informational timestamp.

## Sections

Exactly four sections in strict order:

1. `background`
2. `intuition`
3. `code`
4. `quiz`

Each section is validated with required keys; order mismatch fails fast.

## Non-quiz blocks

Supported `type` values:

- `paragraph` — `{ "text": "..." }`
- `heading` — `{ "level": 2..4, "text": "..." }`
- `callout` — `{ "tone": "note|tip|warning|critical|info", "text": "..." }`
- `code` — `{ "language": "python|bash|...", "label": "optional", "code": "..." }`
- `list` — `{ "ordered": true|false, "items": ["..."] }`
- `table` — `{ "header": ["..."], "rows": [["...", ...], ...] }`
- `flow` — `{ "steps": ["...", ...] }`
- `before_after` — `{ "title": "...", "before": [blocks], "after": [blocks] }`

`blocks` may use any of the above and are individually escaped by the renderer.

## Fact vs interpretation labeling

The script accepts additional labels for authoring discipline but does not require them in runtime validation:

- `provenance: fact` for evidence-backed text.
- `provenance: interpretation` for analysis and recommendation.

When ambiguous, include `interpretation` explicitly.

## Quiz schema

`quiz` section requires:

- exactly five `questions`.
- each question with:
  - `prompt` (or legacy `question`)
  - `options` (3–5 entries)
  - `correct_index` (integer within range)
  - optional `explanation`
  - optional `id`

The renderer shuffles options per run deterministically from metadata/app CLI seed and balances answer positions.

## Quiz quality checks

- duplicate options are flagged.
- correct option length should not be an outlier versus distractors.
- in `--strict` mode, quality warnings fail rendering.

## Asset/interaction contract

- one local HTML output file
- no remote assets
- no inline JS event handlers
- semantic structure (sections, TOC, forms-like quiz interactions)
- visible focus states, reduced-motion support
- `<pre><code>` for code blocks
- mode `0600` file permissions
