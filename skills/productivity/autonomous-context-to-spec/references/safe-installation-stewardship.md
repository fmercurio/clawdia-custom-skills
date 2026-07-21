# Safe installation stewardship

Use this reference when `execute` mode includes installing a package into an active agent/runtime, especially when the package has bootstrap, install, doctor, and uninstall lifecycle scripts.

## Decision ledger

Resolve and keep visible:

- durable absolute package-source path (not `/tmp` when uninstall/export still depend on source);
- explicit runtime home and target profile;
- new vs existing data/vault and absolute path;
- owner/tenant/scope metadata;
- privacy and restricted-content behavior;
- every optional outbound or operational capability (remote Git, remote embeddings, renderer, cron, delivery);
- overwrite policy and rollback path.

Ask one blocking decision at a time, with a recommended reversible default and reason. Do not ask what files or system state can answer.

## Dry-run dependency trap

Some installers require configuration created only by `bootstrap --apply`, so running `bootstrap` dry-run followed by `install` dry-run against a clean real target fails with “missing config.” Do not mutate the target merely to make the second dry-run work.

Instead:

1. Run bootstrap dry-run against the real target.
2. Create an isolated temporary runtime home and data/vault path.
3. Run bootstrap with `--apply` only inside that clean-room.
4. Run install dry-run against the clean-room.
5. Verify the real target remains untouched.
6. Show the clean-room operation list with paths clearly identified as representative; translate only the root prefix when summarizing expected target paths.

This preserves the no-side-effect gate while exercising the real configuration-dependent path.

## Apply sequencing

1. Capture baseline and conflicts.
2. Obtain an explicit apply gate that names all side effects, including system/user dependency installs.
3. Create the runtime profile explicitly when the user selected a named profile; installing files under a profile-shaped directory is not equivalent to creating a usable profile.
4. Apply bootstrap.
5. Apply confirmed config overrides that bootstrap defaults cannot express.
6. Apply the managed installer without force unless separately authorized.
7. Initialize local Git only if authorized; initialization does not authorize commit, remote configuration, or push.
8. Install optional dependencies separately so the core install can still be verified if an optional integration is blocked.
9. Run doctor/smoke, representative search/rebuild/health checks, and any allowed disposable probe.
10. Run or at least document uninstall dry-run and confirm the vault/data is preserved.

## Evidence and reporting

Distinguish four states precisely:

- **installed** — files were written;
- **configured** — confirmed options are reflected in config;
- **verified** — real checks passed;
- **optional capability pending** — core works but an integration is not yet proven.

Never label the whole setup complete when required doctor/smoke checks were not run. Report exact artifact, config, inventory, export, and rollback paths. Never restart a messaging gateway unless the user explicitly authorizes it.