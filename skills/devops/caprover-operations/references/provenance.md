# Provenance

- Candidate: `caprover-operations` 0.1.0.
- Author: ClawdIA contributors (original reauthoring).
- Created: 2026-09-15.
- License: MIT for the original code, documentation, tests, and templates in this directory.
- Purpose: clean-room, local-only reauthoring of a guarded CapRover operations workflow from an authorized specification and public official sources.

Official public sources consulted:

- [CapRover CLI commands](https://caprover.com/docs/cli-commands.html)
- [caprover/caprover-cli](https://github.com/caprover/caprover-cli/tree/418b8893fb2e49da02b9176cfd5e40b5edf76f64), immutable source revision reviewed alongside the official npm `caprover@2.4.4` built command/API/storage layout (Apache-2.0); reviewed package integrity `sha512-xBrjN3Ihv/0LDQ3eP59Ex1XhP96Z5h5BGL0693vwGB4BOcpXTszQRwkDM+/AmadBopaQNTWcjEBKMzsCLQuxlw==`. Runtime compatibility is pinned to the npm package layout hashes, not inferred from the source branch.
- [CapRover system router](https://github.com/caprover/caprover/blob/c0db36f334071599fd732e6f355e55444578b177/src/routes/user/system/SystemRouter.ts), for the `system/info` success fields.
- [CapRover full and partial update handlers](https://github.com/caprover/caprover/blob/c0db36f334071599fd732e6f355e55444578b177/src/handlers/users/apps/appdefinition/AppDefinitionHandler.ts) and [application schema](https://github.com/caprover/caprover/blob/c0db36f334071599fd732e6f355e55444578b177/src/models/AppDefinition.ts), reviewed at server v1.15.4. The companion uses a preservation-based full POST; it does not assume older servers support partial PATCH.

The upstream CLI is an external dependency and is not copied or vendored. Its license does not change this candidate's MIT license. No private skill, private source, credential store, live CapRover installation, or runtime deployment was used. Fixture evidence is synthetic loopback only; no production or staging validation is claimed.

Revalidate the transport guard, source-layout pins and response schemas when updating any upstream revision or Node runtime. Rejected adaptations include blanket Node-major failure claims, unguarded login renewal, implicit deployment fallback and full updates constructed from reset-prone defaults.
