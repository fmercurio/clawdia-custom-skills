# second-brain-kit 0.1.0-rc2

Hermes-native candidate package for creating a new Second Brain or connecting an existing Markdown vault without hardcoded identities, paths, optional services, or credentials.

## Minimum requirements

- Python 3.11+
- SQLite with FTS5
- A writable explicit `HERMES_HOME` and vault path

OKF, embeddings, Obsidian, Git remote, and cron are optional.

## Quick clean-room flow

```bash
export HERMES_HOME="$(mktemp -d)"
VAULT="$(mktemp -d)/brain"
python3 scripts/bootstrap.py --hermes-home "$HERMES_HOME" --profile second-brain --vault "$VAULT" --owner "Example Owner" --apply --json
python3 scripts/install.py --hermes-home "$HERMES_HOME" --profile second-brain --apply --json
python3 scripts/doctor.py --hermes-home "$HERMES_HOME" --profile second-brain --smoke --json
```

No gateway restart is performed or required by these scripts.

## Portable install from an exported ZIP

Build the deterministic artifact on the source machine, copy it to the target environment, then run the same explicit-home flow from the extracted directory:

```bash
python3 scripts/export.py --output /tmp/second-brain-kit.zip
unzip second-brain-kit.zip
cd second-brain-kit
export HERMES_HOME="/absolute/path/to/hermes-home"
python3 scripts/bootstrap.py --hermes-home "$HERMES_HOME" --profile second-brain --vault "/absolute/path/to/vault" --owner "Owner" --apply --json
python3 scripts/install.py --hermes-home "$HERMES_HOME" --profile second-brain --apply --json
python3 scripts/doctor.py --hermes-home "$HERMES_HOME" --profile second-brain --smoke --json
```

For OKF rendering, install the pinned optional dependency with `gem install okf -v 1.6.0`. Cron registration requires a compatible `hermes` CLI and is always explicit.

## Agent-guided setup handoff

For another Hermes-capable agent, give the package path and instruct it to follow the handoff flow in [docs/agent-guided-setup.md](docs/agent-guided-setup.md).

Copy/paste starter:

```text
Use the second-brain-kit at <ABSOLUTE_PACKAGE_PATH> and follow docs/agent-guided-setup.md. Inspect the package and target environment first, then conduct the setup interview in my language, one blocking question at a time, with a recommended default and reason. After the decision ledger is complete, run dry-runs, request the documented apply gate, deploy, run doctor/smoke checks, and report rollback details.
```

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
- `install.py`: profile-aware managed installation; cron requires explicit flags.
- `doctor.py`: config, FTS5, vault, skills, and optional capability report.
- `brain_ops.py`: deterministic pull/push smoke harness.
- `uninstall.py`: hash-aware managed removal; vault preserved.
- `export.py`: deterministic checksums and reproducible ZIP.

If a cron was registered, remove it with `hermes cron list` / `hermes cron remove JOB_ID` before uninstalling, then pass `--cron-removed`. The RC refuses to orphan a scheduler job silently.

See `docs/architecture.md`, `docs/decisions-requiring-human-confirmation.md`, and `docs/provenance.md`.
