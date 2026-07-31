# Architecture

## Boundaries

1. **Package source:** governed files in this repository.
2. **Hermes runtime:** installed profile skills, config, wrappers, and deterministic scripts under `HERMES_HOME`.
3. **Vault:** Markdown knowledge plus rebuildable `.brain-index`; no runtime configuration or credentials.
4. **Backups/exports:** external to runtime and vault.
5. **Optional MCP artifacts:** read-only instances in `${HERMES_HOME}/second-brain-kit/instances/<instance>` outside the vault.

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

Named profiles install under `${HERMES_HOME}/profiles/${PROFILE}/skills/note-taking`. The default profile installs under `${HERMES_HOME}/skills/note-taking`. Config is stored as deterministic JSON, which is valid YAML, at `${HERMES_HOME}/second-brain-kit/profiles/${PROFILE}/config.yaml`.

Runtime helper scripts are copied to `${HERMES_HOME}/second-brain-kit/bin`.

## Optional MCP read-only bridge

`install.py --enable-mcp` adds explicit optional artifacts without running services or clients:

- `${HERMES_HOME}/second-brain-kit/instances/<instance>/runtime-config.json`
- `${HERMES_HOME}/second-brain-kit/instances/<instance>/policy.json`
- helper scripts in `${HERMES_HOME}/second-brain-kit/bin` (`brain_policy_check.py`, `mcp_smoke.py`)
- runtime modules needed only for local validation

Artifacts are owner-only (`0o600`) and deterministic. `doctor.py --check-optional` validates artifact presence and local policy shape without endpoint traffic.

The bridge remains inert until explicitly enabled and invoked.
