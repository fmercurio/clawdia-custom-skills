# `second-brain-kit` 0.1.0-rc2 deployment notes

Use this reference only when installing or reviewing the `second-brain-kit` package. Revalidate against the current package version before applying these details.

## Package boundaries

- Source lifecycle scripts remain source-dependent; keep a durable checkout outside `HERMES_HOME` runtime and outside the vault.
- Named-profile skills install under `${HERMES_HOME}/profiles/<profile>/skills/note-taking`.
- Package config lives under `${HERMES_HOME}/second-brain-kit/profiles/<profile>/config.yaml`.
- Runtime helpers live under `${HERMES_HOME}/second-brain-kit/bin`.
- Managed hashes live in `install-inventory.json`; uninstall is hash-aware and preserves the vault.

## Zero-state dry-run dependency

`install.py` requires the package config created by `bootstrap.py --apply`. On a genuinely new target, bootstrap dry-run therefore cannot be followed directly by install dry-run.

Safe workaround:

1. run bootstrap dry-run against the real target;
2. create a temporary home/vault;
3. apply bootstrap only in that temporary sandbox;
4. run install dry-run in the sandbox;
5. verify real target paths remain absent.

## OKF mode corrections to check

In rc2, `bootstrap.py --mode okf` creates PARA-oriented root Markdown but may not create an OKF-conformant bundle by itself.

Before render:

- add `type`, `title`, `description`, and `sensitivity` to each Markdown concept;
- ensure the canonical note template carries the same required concept fields;
- create the `okf.yml` or `okf.yaml` marker expected by `brain_health_check.py`;
- run `okf validate <vault> --json` independently of package health.

Example marker used successfully:

```yaml
schema_version: "0.1"
name: organization-second-brain
title: Organization Knowledge Graph
owner: Organization
mode: okf
```

Treat marker fields as package-health metadata unless current OKF documentation defines a stricter schema.

## Layout vocabulary

The package examples may describe a force layout, while OKF 1.6 CLI accepts:

- `cose`
- `concentric`
- `breadthfirst`
- `circle`
- `grid`

For force-directed intent, use `cose`. Always verify with `okf render --help` for the installed version.

## Push compatibility warning

The rc2 `brain_ops.py push` writes PARA/search frontmatter (`para`, `status`, `sensitivity`, owner/dates) but omits OKF concept fields such as `type`, `title`, and `description`.

Consequences:

- FTS rebuild, search, and pull can pass;
- `okf validate` can still fail after the push.

For smoke tests, remove the disposable probe and rerun FTS rebuild, health, and OKF validation. For durable notes in OKF mode, create from the canonical OKF-compatible template or update the helper in a reviewed package revision.

## OKF 1.6 without system Ruby

A working user-local combination was:

- platform-matched prebuilt Ruby 3.3.x;
- gem installed with `ruby path/to/gem`, bypassing fixed archive shebangs;
- `GEM_HOME` under `~/.local/share/gems/ruby/3.3.0`;
- a wrapper under `~/.local/bin/okf` that scopes `LD_LIBRARY_PATH`, `RUBYLIB`, `GEM_HOME`, and `GEM_PATH` to OKF only.

Verify:

```bash
okf --version        # must exactly match configured 1.6.0
okf --help
okf validate "$VAULT" --json
```

Do not export relocation variables globally.

## Profile readiness

A newly created Hermes profile can have skills but no explicit inference provider. Validate all three independently:

```bash
hermes -p second-brain skills list
hermes -p second-brain config set model.default <model>
hermes -p second-brain config set model.provider <provider>
hermes -p second-brain chat -q 'Reply exactly: READY' --quiet
```

Credential listing alone is not proof that model/provider selection is configured.

## Inventory refresh and rollback

If package config changes after the first installation, uninstall dry-run may report the config as modified. When runtime artifacts still match source, rerun the normal installer with `--apply` and without `--force` to refresh managed hashes, then rerun uninstall without `--apply`.

Expected final rollback properties:

- `ok: true` and `dry_run: true`;
- no skipped modified/unsafe files;
- explicit managed-file removal plan;
- explicit `vault_preserved` path.
