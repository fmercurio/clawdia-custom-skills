# Architecture

## Boundaries

1. **Package source:** governed files in this repository.
2. **Hermes runtime:** installed profile skills, config, wrappers, and deterministic scripts under `HERMES_HOME`.
3. **Vault:** Markdown knowledge plus rebuildable `.brain-index`; no runtime configuration or credentials.
4. **Backups/exports:** external to runtime and vault.

## Selection

- New vault: create minimum folders/root contracts idempotently.
- Existing vault: audit read-only first; produce an adaptation plan; migrate only with a separate approval.
- PARA mode: folder and frontmatter contracts.
- Hybrid mode: intent/type retrieval with PARA fallback.
- OKF mode: optional detection and validation; never a minimum dependency.

The OKF adapter requires the configured CLI version, validates the bundle before render, and refuses restricted notes and Markdown symlinks before invoking the renderer.

## Iterative refinement

Bootstrap → install → doctor → deterministic correction → health check → search rebuild → representative query. Every phase has an explicit exit criterion and can be repeated safely.

## Runtime placement

Named profiles install under `${HERMES_HOME}/profiles/${PROFILE}/skills/note-taking`. The default profile installs under `${HERMES_HOME}/skills/note-taking`. Config is stored as deterministic JSON, which is valid YAML, at `${HERMES_HOME}/second-brain-kit/profiles/${PROFILE}/config.yaml`. Runtime-safe operational helpers are copied to `${HERMES_HOME}/second-brain-kit/bin`; source-dependent install and export lifecycle scripts remain in the package source.
