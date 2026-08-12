# Attribution and licensing notice

This package contains an adaptation of **llm-wiki** by Charles Luxinger:

- Source: https://github.com/CharlesLuxinger/llm-wiki-skill
- Reviewed revision: `016a81078df121f377627ed314e3807e620e3d92`
- Upstream license declaration: `CC-BY-4.0` in the reviewed `SKILL.md`
- License terms: https://creativecommons.org/licenses/by/4.0/

The reviewed upstream tree did not contain a repository-level `LICENSE` file. This
package therefore preserves the upstream declaration explicitly rather than
inferring one from GitHub metadata.

## Changes made

The material was selectively adapted rather than installed verbatim. Changes
include:

- preserving standalone wiki behavior from the existing Hermes runtime skill;
- adding a role boundary `researcher -> llm-wiki staging ->
  second-brain governance -> push-brain promotion`;
- defining isolated staging, provenance, sensitivity, tenant, approval, and
  no-canonical-write contracts;
- adding a deterministic read-only staging validator and adversarial tests;
- documenting promotion evidence, rollback, and operational gates.

Charles Luxinger and the upstream project do not endorse this adaptation.

The adapted skill documentation is distributed under **CC-BY-4.0**. Original
validator code and tests authored for this repository are covered by the
repository's MIT license. See `references/provenance.md` for the complete source
record and byte-level review information.
