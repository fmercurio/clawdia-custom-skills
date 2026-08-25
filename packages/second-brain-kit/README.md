# second-brain-kit 0.2.0-rc1

Hermes-native candidate package for creating a new Second Brain or connecting an existing Markdown vault without hardcoded identities, paths, optional services, or credentials.

## Minimum requirements

- Python 3.11+
- SQLite with FTS5
- A writable explicit `HERMES_HOME` and vault path

All package lifecycle entry points verify this minimum before operating. State-changing commands therefore refuse unsupported interpreters before they create, modify, remove, export, register, render, plan, or serve anything.

OKF, embeddings, Obsidian, Git remote, cron, and read-only MCP are optional.

## Quick clean-room flow

```bash
export HERMES_HOME="$(mktemp -d)"
VAULT="$(mktemp -d)/brain"
python3 scripts/bootstrap.py --hermes-home "$HERMES_HOME" --profile second-brain --vault "$VAULT" --owner "Example Owner" --apply --json
python3 scripts/install.py --hermes-home "$HERMES_HOME" --profile second-brain --apply --json
python3 scripts/doctor.py --hermes-home "$HERMES_HOME" --profile second-brain --smoke --json
```

No gateway restart is performed or required by these scripts.

## Optional read-only MCP artifacts

Enable read-only MCP wiring with an explicit opt-in flag only:

```bash
python3 scripts/install.py --hermes-home "$HERMES_HOME" --profile second-brain --enable-mcp --apply --json
```

This creates deterministic, owner-only artifact files outside the vault at:
- `second-brain-kit/instances/<instance>/runtime-config.json`
- `second-brain-kit/instances/<instance>/policy.json`
- `second-brain-kit/instances/<instance>/projection-manifest.json` (expected by policy; external manifest path is not created automatically)

It also installs helper scripts under `second-brain-kit/bin`:
- `brain_policy_check.py`
- `mcp_smoke.py`

No server is launched, no listener is registered, and no network call is made during installation.

The generated MCP configuration now contains a runtime contract for local validation and serving:
- `runtime_schema_version` (currently `v0.2`)
- `mode` (`readonly`)
- `transport` (`http`)
- `listener` with explicit `host`, `port`, and `path` contract
- `policy_path` and `projection_manifest_path` as instance-relative artifact names
- optional policy-owned `max_record_age_days`; when set, a record needs a valid, non-future RFC3339 UTC `freshness.updated_at` timestamp within that age window before it can be materialized

Use the runner with trusted local files:

```bash
python3 scripts/run_mcp.py --config second-brain-kit/instances/<instance>/runtime-config.json --check --json
python3 scripts/run_mcp.py --config second-brain-kit/instances/<instance>/runtime-config.json --serve
```

`--check` validates local policy and projection manifest and never contacts network services.
`--serve` starts the official MCP SDK's Streamable HTTP transport only at the configured loopback host/path; it blocks for the server lifetime and requires a separately prepared runtime with `mcp>=2,<3`. Starting it remains explicit HITL work.

### Optional staging-only Brain Delta proposals

The default v0.2 server exposes only four read-only retrieval tools. An operator may opt into the additional `propose_brain_delta` capability by adding an instance-relative `proposal_staging_path` to `runtime-config.json`, pointing to a **pre-existing, owner-only** directory below that instance root. The runtime never creates this directory during `--check` or startup.

The tool accepts only bounded semantic fields (`title`, `summary`, typed `proposed_changes`, and `provenance`), performs DLP validation, generates its own opaque proposal ID, and writes one private JSON artifact in that staging directory. It cannot select a filename or write destination. Clean proposals return a citable `proposal:<id>` reference; secret-shaped or review/PII-shaped values are rejected without an artifact or payload echo.

This is not canonical vault writing: it never modifies Markdown, Git, the remote, policy, manifest, service manager, listener or runtime configuration. A proposal remains subject to validation, human review and `push-brain` before any promotion.

Render a deterministic LaunchAgent service plan without installing or starting anything. When the config is in the managed instance layout, the planner derives the sibling `second-brain-kit/bin` runtime and captures the absolute Python interpreter used to run the planner (including a prepared venv):

```bash
uv run --offline --project runtime python scripts/service_plan.py \
  --config "$HERMES_HOME/second-brain-kit/instances/<instance>/runtime-config.json" \
  --output-dir /tmp/second-brain-mcp-service --service launchagent --json
```

To render for a separately prepared runtime, pass **absolute** paths explicitly with `--runtime-root /absolute/path/to/second-brain-kit/bin` and `--runtime-python /absolute/path/to/venv/bin/python`. Do not use `/usr/bin/env python3`: a service template needs one concrete executable path.

Run the production smoke check against an endpoint:

```bash
uv run --offline --project runtime python scripts/mcp_smoke.py --url https://example.invalid/mcp
```

The helper uses the official MCP Python SDK transport; it does not handcraft protocol HTTP requests.

Validate the copied policy file locally without network traffic:

```bash
python3 scripts/brain_policy_check.py second-brain-kit/instances/<instance>/policy.json
```

## Portable install from an exported ZIP

Build the deterministic artifact on the source machine, copy it to the target environment, then run the explicit-home flow from the extracted directory:

```bash
python3 scripts/export.py --output /tmp/second-brain-kit.zip
unzip second-brain-kit.zip
cd second-brain-kit
export HERMES_HOME="/absolute/path/to/hermes-home"
python3 scripts/bootstrap.py --hermes-home "$HERMES_HOME" --profile second-brain --vault "/absolute/path/to/vault" --owner "Owner" --apply --json
python3 scripts/install.py --hermes-home "$HERMES_HOME" --profile second-brain --apply --json
python3 scripts/doctor.py --hermes-home "$HERMES_HOME" --profile second-brain --smoke --json
```

For OKF rendering, install the pinned optional dependency with `gem install okf -v 1.6.0`.
Cron enablement is split from installation:

```bash
python3 scripts/install.py --hermes-home "$HERMES_HOME" --profile second-brain --enable-cron --apply --json
python3 scripts/activate_cron.py --hermes-home "$HERMES_HOME" --profile second-brain --apply --hermes-cli <hermes path or hermes> --json
```

## Agent-guided setup handoff

For another Hermes-capable agent, give the package path and instruct it to follow the handoff flow in [docs/agent-guided-setup.md](docs/agent-guided-setup.md).

Copy/paste starter:

```text
Use the second-brain-kit at <ABSOLUTE_PACKAGE_PATH> and follow docs/agent-guided-setup.md. Inspect the package and target environment first, then conduct the setup interview in my language, one blocking question at a time, with a recommended default and reason. After the decision ledger is complete, run dry-runs, request the documented apply gate, deploy, run doctor/smoke checks, and report rollback details.
```

For a tenant-local read-only integration and local-only validation, follow [tenant-projection-pilot-handoff.md](docs/tenant-projection-pilot-handoff.md).

## Existing vault

Omit `--apply` and pass `--existing` for the mandatory read-only first audit. The audit does not move or rewrite notes.

## Optional OKF 1.6 render

When `okf` is detected and OKF is enabled in config:

```bash
python3 scripts/okf_render.py --hermes-home "$HERMES_HOME" --profile second-brain --title "Knowledge Graph" --layout force --link "https://example.invalid/repository" --apply
```

The adapter requires the configured OKF version, validates the bundle before rendering, and supports title, layout, and repository link. It refuses bundles containing restricted notes or Markdown symlinks. Output is a frozen snapshot; rerun after changes. Large bundles create large self-contained HTML files.

## Lifecycle

- `bootstrap.py`: new/existing selection and idempotent config/vault creation.
- `install.py`: profile-aware managed installation; cron and MCP require explicit flags.
- `doctor.py`: config, FTS5, vault, skills, optional capability report.
- `brain_ops.py`: deterministic pull/push smoke harness.
- `uninstall.py`: hash-aware removal of managed files and optional MCP instance artifacts, vault preserved.
- `export.py`: deterministic checksums and reproducible ZIP.

If a cron was registered, remove it with `hermes cron list` / `hermes cron remove JOB_ID` before uninstalling, then pass `--cron-removed`. The RC refuses to orphan a scheduler job silently.

See `docs/architecture.md`, `docs/decisions-requiring-human-confirmation.md`, and `docs/provenance.md`.
