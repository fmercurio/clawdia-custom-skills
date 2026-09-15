# Provenance

- This repository and the `caprover-deploy` skill are distributed under the repository's MIT license.
- Server API contracts were checked against official CapRover v1.15.4 commit `c0db36f334071599fd732e6f355e55444578b177`.
- CLI behavior and the pinned layout were checked against official `caprover-cli` 2.4.4 commit `418b8893fb2e49da02b9176cfd5e40b5edf76f64`.
- The official CLI is external Apache-2.0 software. It is not vendored by this skill.
- Protected registries, target bindings, credentials, recovery snapshots, and other private files are not part of the skill or provenance material.

The commit identifiers above are immutable review references. Runtime capability checks additionally require package version 2.4.4 and exact hashes for the CLI files used by deployment.

## Official source anchors

- [Server source at the reviewed revision](https://github.com/caprover/caprover/tree/c0db36f334071599fd732e6f355e55444578b177), including `src/handlers/users/apps/appdefinition/AppDefinitionHandler.ts`, `src/routes/user/apps/appdata/AppDataRouter.ts`, and `src/api/ApiStatusCodes.ts`.
- [Official CLI at the reviewed revision](https://github.com/caprover/caprover-cli/tree/418b8893fb2e49da02b9176cfd5e40b5edf76f64), including the built deployment, validation, API and HTTP client behavior in the published npm package.
- [Official CLI command documentation](https://caprover.com/docs/cli-commands.html).

## Adopted and rejected behavior

Adopted: explicit local-artifact versus remote-Git intent, saved-session reuse,
full-update preservation/readback, detached-upload acknowledgment, strict build
fields and post-trigger generation evidence. The Python controller and request
interlock are original implementations, not imported private skill packages.

Rejected: incomplete default-filled update examples, empty-Git-hash build claims,
implicit creation, automatic method cascades after possible writes, password
arguments, blanket Node-version failure claims, and treating a successful request
as application health. Unsupported server schemas fail closed rather than being
silently normalized.

Review date: 2026-09-15. Validation is local-only; the review contract distinguishes
unit/CLI fixtures from unperformed live dashboard, server, SSH and health checks.
Any CLI layout/dependency, Node support, API field, or dashboard-selector change
requires revalidation and review before changing pins or promoting this candidate.
