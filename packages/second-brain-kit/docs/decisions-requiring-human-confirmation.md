# Decisions requiring human confirmation

- Owner, optional organization, vault path, profile, scope, and sensitivity defaults.
- Whether an existing vault may be changed after read-only audit.
- Any physical migration, canonical promotion, or restricted-content write.
- Overwriting a conflicting installed skill.
- Initializing Git, configuring a remote, committing, or pushing.
- Sending text to a remote embeddings provider.
- Including restricted notes in search or static publication.
- Creating a Hermes cron job and selecting its delivery target.
- Enabling OKF static render and choosing title, layout, link, and output.
- Removing modified runtime artifacts during uninstall.

No confirmation is needed for read-only audit, dry-run, local FTS5 rebuild over authorized non-restricted notes, or silent health checks.
