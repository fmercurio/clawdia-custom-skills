# Provenance — LLM Wiki Second Brain Staging Adaptation

## Primary external source

- Repository: https://github.com/CharlesLuxinger/llm-wiki-skill
- Author: Charles Luxinger
- Reviewed revision: `016a81078df121f377627ed314e3807e620e3d92`
- Commit date observed: `2026-08-10T11:30:57-03:00`
- Review date: `2026-08-10`
- License observed in external `SKILL.md`: `CC-BY-4.0`
- Repository-level `LICENSE` file observed in reviewed tree: **no**
- Review method: temporary shallow clone, five Markdown files read, no external code executed, no installer run, no package imported.

## Other primary influence

- Andrej Karpathy's LLM Wiki pattern: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- Existing Hermes runtime skill baseline: `${HERMES_HOME}/skills/research/llm-wiki/SKILL.md`, version `2.1.0`, SHA-256 `a37ae04745b04b8e9bbd8de37cdcbc2b2187ccafb68418e436a46ebb1e491ee5` at proposal baseline.

## Internal composing skills and contracts

- `second-brain-knowledge-architecture`
- `second-brain-operations`
- `pull-brain`
- `push-brain`
- `brain-search`
- `grounded-citations`
- Hybrid OKF/PARA source-integrity and evidence-gate references

## Mechanisms adopted from the external source

- explicit `discover → approve → ingest → compile → query → promote → lint` lifecycle;
- human-approved source checklist before curated ingest;
- separation between query output and canonical promotion;
- sources treated as hostile data rather than instructions;
- read-only lint default and patch-preview gate;
- source summaries, contradiction tracking, and failure continuation.

## Mechanisms strengthened or changed

- External `promote` becomes `propose Brain Delta → push-brain`; `llm-wiki` never writes canonical Second Brain state.
- Staging and canonical roots must be resolved, distinct, and compared before/after.
- Destructive sanitization is replaced by inert capture, preserved provenance, quarantine/rejection, and explicit data boundaries.
- Private/local source ingestion is off by default and requires sensitivity/DLP/secret gates.
- Discovery count is a hard budget, not the external `2N` expansion.
- Canonical target paths are not trusted from staging; only semantic/search hints cross the boundary.
- Source versions carry real hashes and supersession rather than silent replacement.
- Deterministic checks own structure, hashes, links, secret patterns, and no-write verification.
- The pre-existing standalone Obsidian-headless example is hardened by removing password-as-CLI guidance; staging explicitly disables sync/watchers as indirect writers.

## Mechanisms rejected or deferred

- Obsidian as a mandatory runtime dependency;
- current working directory as implicit vault selection;
- direct copying of private files into `raw/private/`;
- deleting source text solely because it contains prompt-injection phrases;
- permanent blocklist entries with no review/supersession policy;
- compile-time canonical edits without an explicit promotion gate;
- broad YouTube/X/GitHub/PDF support without tool, auth, cost, and failure contracts;
- bulk import, enterprise cutover, daemon automation, and direct MCP writes in this proposal.

## Governed package paths and status

- Runtime baseline at implementation start: `${HERMES_HOME}/skills/research/llm-wiki/`, version `2.1.0`
- Governed repository path: `skills/research/llm-wiki/` in this repository
- Package status: **candidate implementation; runtime promotion remains evidence-gated**
- Canonical Second Brain status: **not modified by package implementation or validator tests**

## Attribution and licensing note

The upstream `SKILL.md` declares `CC-BY-4.0`; the reviewed upstream tree contains no repository-level `LICENSE`. This adapted skill documentation is therefore distributed under `CC-BY-4.0`, with the source, revision, attribution, change summary, and license URL preserved in `NOTICE.md` and this file. Original deterministic validator code and tests authored for this repository remain covered by its MIT license.

The package is a selective Hermes-native adaptation, not a verbatim installation. It preserves standalone behavior while adding an isolated Second Brain staging contract, deterministic validation, tenant/sensitivity controls, and a `push-brain`-only promotion boundary. Charles Luxinger and the upstream project do not endorse this adaptation.

## Revalidation log

| Date | External revision | Result |
|---|---|---|
| 2026-08-10 | `016a81078df121f377627ed314e3807e620e3d92` | Initial read-only review; selective Second Brain staging adaptation proposed. |

Revalidate read-only when the upstream revision changes or before materially editing the derived contract after approximately 90 days. Never auto-import upstream changes.
