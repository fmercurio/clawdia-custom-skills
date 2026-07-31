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

Cron health scheduling is explicitly separate from installation:

- `install.py --enable-cron` materializes `${HERMES_HOME}/scripts/second-brain-health-${PROFILE}.py`.
- `activate_cron.py --apply --hermes-cli ...` is the only command that invokes `hermes cron create` and records `{cron_registered, cron_job_id}` back into install inventory atomically.

## Optional MCP read-only bridge

`install.py --enable-mcp` adds explicit optional artifacts without running services or clients:

- `${HERMES_HOME}/second-brain-kit/instances/<instance>/runtime-config.json`
- `${HERMES_HOME}/second-brain-kit/instances/<instance>/policy.json`
- `${HERMES_HOME}/second-brain-kit/instances/<instance>/projection-manifest.json` (artifact path contract; manifest is supplied by the tenant runtime pipeline)
- helper scripts in `${HERMES_HOME}/second-brain-kit/bin` (`brain_policy_check.py`, `mcp_smoke.py`, `run_mcp.py`, `service_plan.py`)
- runtime modules needed for local validation and explicit Streamable HTTP serving

`runtime-config.json` includes:
- `runtime_schema_version` (`v0.2`)
- `mode` (`readonly`)
- `transport` (`http`)
- `listener` contract with loopback host/port/path constraints
- `policy_path` and `projection_manifest_path` as instance-relative artifact names

Artifacts are owner-only (`0o600`) and deterministic.
`doctor.py --check-optional` validates artifact presence and local policy/manifest contract shape without endpoint traffic.

`service_plan.py` renders launchd LaunchAgent, launchd LaunchDaemon, or systemd-user deployment units from instance config and an explicit output directory. LaunchDaemon plans additionally require explicit user and group values; all rendered output remains HITL and separate from service-manager activation.
It never calls `launchctl` or `systemctl`, and it never starts services.

The bridge remains inert until explicitly enabled and invoked.
