# second-brain-kit 0.1.0-rc1

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

## Existing vault

Omit `--apply` and pass `--existing` for the mandatory read-only first audit. The audit does not move or rewrite notes.

## Optional OKF 1.6 render

When `okf` is detected and OKF is enabled in config:

```bash
python3 scripts/okf_render.py --hermes-home "$HERMES_HOME" --profile second-brain --title "Knowledge Graph" --layout force --link "https://example.invalid/repository" --apply
```

The adapter uses `okf render DIR -o FILE` and supports title, layout, and repository link. It refuses bundles containing restricted notes by default. Output is a frozen snapshot; rerun after changes. Large bundles create large self-contained HTML files.

## Lifecycle

- `bootstrap.py`: new/existing selection and idempotent config/vault creation.
- `install.py`: profile-aware managed installation; cron requires explicit flags.
- `doctor.py`: config, FTS5, vault, skills, and optional capability report.
- `brain_ops.py`: deterministic pull/push smoke harness.
- `uninstall.py`: hash-aware managed removal; vault preserved.
- `export.py`: deterministic checksums and reproducible ZIP.

If a cron was registered, remove it with `hermes cron list` / `hermes cron remove JOB_ID` before uninstalling, then pass `--cron-removed`. The RC refuses to orphan a scheduler job silently.

See `docs/architecture.md`, `docs/decisions-requiring-human-confirmation.md`, and `docs/provenance.md`.
