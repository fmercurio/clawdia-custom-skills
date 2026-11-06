# Provenance

- Package: `archiver-contextual-recall`
- Version: `1.3.0` source candidate
- Repository URL: `https://github.com/fmercurio/clawdia-custom-skills`
- Source baseline SHA: `7fe64290863e0793bb9c89ba95489208283b17a0`
- Package maintainer: `Skills Lab`
- License: MIT
- Public-only adaptation: all deployment-specific IDs, branch assumptions, private DB recovery notes, and routing state were excluded from this package.

## Source baseline and adaptation notes

- The adapted implementation is derived from validated runtime scripts with hardening updates for:
  - path escape detection,
  - schemeless URL redaction,
  - fail-closed index loading,
  - 0600 atomic artifact writes,
  - cron wrapper timeout behavior.

- Reconciliation and backfill helpers were kept with:
  - configurable paths through `ARCHIVER_HOME`, `ARCHIVER_VAULT`, `ARCHIVER_DB`,
  - no hardcoded private tenant/topic values,
  - synthetic tests for regression coverage.

## Capture and recall foundation

The additive source candidate separates local annotations from automatic source
prefixes, records capture quality/coverage and parser observations, and uses
relevance-ranked lexical/FTS5 recall without schema writes on queries. Existing
network, redirect, filesystem and PDF-worker controls are retained. Tests cover
legacy schema compatibility, honest unknown states, same-source evidence binding,
read-only permissions, and committed-WAL backups. These source checks do not
authorize runtime installation, archive migration, bulk refresh or public release.
