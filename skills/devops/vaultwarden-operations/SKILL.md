---
name: vaultwarden-operations
description: "Use when deploying or operating Vaultwarden safely."
version: 0.1.0
status: approved
author: "Repository contributors + Hermes Agent"
license: MIT
metadata:
  hermes:
    tags: [vaultwarden, bitwarden, secrets, caprover, operations]
    related_skills: [caprover-operations, caprover-deploy]
---

# Vaultwarden Operations

Plan and review Vaultwarden operations through CapRover without turning an agent into a broad secret reader. This maintainer-approved skill is a procedural contract, not an executable credential integration or a tested credential wrapper. Approval of the skill does not authorize live deployment or secret access.

## When to Use

- Plan a single-tenant Vaultwarden deployment through CapRover.
- Review an explicitly authorized upgrade, health diagnosis, backup or isolated restore drill.
- Define bounded use of one credential for one named, authorized external operation.
- Do not use for unapproved retrieval, exports, inventory, arbitrary shell execution, account deletion or incident response.

## Prerequisites

- Owner authorization names the exact external target, technical purpose, allowed reads/writes, time window, confirmation and rollback scope in protected operator context, never in public artifacts.
- Maintainer approval is separately required before runtime installation, promotion, push or PR publication. The recorded approval covers this procedural skill only; additional installations and publications still need their own grant.
- Read [implementation](references/vaultwarden-implementation.md) completely, including the CapRover and CLI limitations. Review the companion CapRover sources at the selected revision; references to candidates do not approve their installation or use.
- Select the official `vaultwarden/server` image with a reviewed release and immutable digest. Check its configuration, database compatibility, migration and WebSocket behavior against official sources; do not resolve `latest` during deployment.
- Identify canonical public HTTPS origin, encrypted persistent storage, supported database, secret-store integration and recovery design before any write.
- Use [the environment template](templates/vaultwarden.env.example) only as a non-secret contract, never as a populated production file.

## Authorization and privacy boundaries

Every infrastructure, publication, DNS/domain, SMTP, database, backup, restore, upgrade, signup-policy, admin-token or user-account change needs explicit, specific owner authorization. An approved plan is not apply authorization. Possession of a credential does not authorize the external action it enables.

Never request or expose secret values in chat. Never include passwords, tokens, cookies, private keys, SMTP credentials, `ADMIN_TOKEN`, `BW_SESSION`, personal/customer data, real company names, private domains, internal addresses or host-local paths in repository content or reports. Examples use reserved domains and non-secret placeholders only. Do not copy an existing installation's configuration into this repository. Inspect protected live configuration inside a trusted boundary and return only allowlisted booleans/enums, not raw logs, app definitions, CLI status JSON or item JSON.

## Procedure

1. **Classify and gate.** Default to plan-only/read-only. Separate installation, configuration, secret access, external credential use, email tests, account actions and recovery into named grants. Stop when a grant or exact target is missing.
   - Completion: authorization covers the proposed effect, confirmation, verification and rollback; no credentials were read merely to plan.
2. **Preflight CapRover.** Confirm the exact controller origin/app binding, selected deployment method, official image digest, container HTTP port, persistent data mount, encryption evidence, single-replica placement and existing-state preservation. Treat ordinary CapRover environment values as inspectable configuration, not a secret manager.
   - Completion: a reviewed secret-injection method exists, or deployment is blocked; no app is created during preflight.
3. **Deploy only with an apply grant.** Follow the CapRover sequence in the reference. Keep `DOMAIN` equal to the canonical HTTPS origin, `SIGNUPS_ALLOWED=false`, an empty signup-domain allowlist and invitations off unless separately approved. Do not configure administration or SMTP by default. Do not enable public signup to bootstrap the first account.
   - Completion: one authorized deployment method was used; possible partial writes are reconciled before any retry, never via automatic fallback.
4. **Read back effective state.** Verify image, canonical domain match, certificate validation, proxy route, WebSocket behavior for the chosen release, persistent mount/database, encryption evidence, replica count, effective registration/invitation policy and absence/restriction of admin access. Environment key names alone do not prove effective values: persisted admin settings may override environment variables.
   - Completion: sanitized boolean/enum results match the approved design; account creation, email sending and persistence-write tests occur only if separately authorized.
5. **Use a credential only through the bounded contract below.** No operational wrapper is shipped here. If no independently reviewed implementation can enforce the boundary, stop rather than constructing an ad hoc secret-reading shell command.
   - Completion: exact-item and exact-target restrictions, child cleanup and parent lock verification all succeed without disclosing values.
6. **Back up and prove recovery.** With distinct approvals, make database-consistent encrypted backups including required file storage and configuration; perform an isolated restore drill. Keep recovery key access independent of the failed vault.
   - Completion: authorized test-account and file-integrity checks pass in isolation; a backup job alone is not recoverability.
7. **Upgrade or modify narrowly.** Approve the exact image/configuration delta and rollback method, capture protected recovery evidence, apply once, read back and verify service behavior. Database migrations can make image-only rollback unsafe.
   - Completion: health, state and policy match; unsupported rollback or missing restore evidence is reported, not assumed.

## Narrow Agent Secret-Access Contract

- Require a named technical purpose, exact external origin/resource/action, exact item selector and minimal field allowlist before any unlock or sync. Titles and identifiers stay in protected context, not output or process arguments.
- Keep the parent CLI locked with no `BW_SESSION`. A child process alone is not isolation: never share the parent's CLI application-data directory or unlock a broad personal vault.
- Use one authorized ephemeral worker boundary with a dedicated least-privilege account and private isolated CLI state. It may spawn only reviewed CLI commands and the fixed allowlisted external operation. No arbitrary shell text, environment inheritance, tracing, crash dumps or unbounded output.
- `bw sync` has no per-item filter. A "scoped sync" means one authorized sync within the dedicated account's server-side visibility, not selective sync of an item. If the account can access unrelated items, stop; do not claim command filtering restricts decryption authority.
- Prefer the exact item ID. An exact title is acceptable only if the reviewed resolver proves a unique exact match without broad enumeration, substring search or exposing candidates; otherwise require a protected exact ID and stop. No first-match fallback.
- Fetch only indispensable fields into worker memory and consume them inside that boundary. Prohibit `bw export`, `bw list items`, broad inventory, raw item JSON, clipboard access and secrets in CLI arguments. CLI field output must be captured privately, never relayed to tool stdout/stderr or chat.
- `BW_SESSION` exists only in the ephemeral worker's memory/environment and its allowlisted CLI descendants. Never persist it in any file, shell profile, env file, service unit, log, agent memory or chat. Do not pass it to the external consumer or parent.
- On success, failure, timeout or interruption, terminate/wait for all descendants, perform best-effort child lock, discard tokens and ephemeral state, then verify parent `bw status` is exactly `locked` with no session variable. Parse privately; never print the raw status payload. An unauthenticated, unlocked, unknown or unreachable parent is not a successful locked check.
- Report only bounded metadata, such as `item_found=true`, `required_field_present=true`, `operation_verified=true`, `vault_parent_locked=true`, and fixed failure codes. A lock check does not prove revocation of a leaked token or zeroization; suspected leakage requires a separate incident-response grant.

## Pitfalls

- A login page, health response, attached volume or passing static test proves neither recoverability nor encryption at rest.
- External SQL does not remove persistent attachment/Send/key-storage requirements for the selected release.
- CapRover-managed storage is not automatically encrypted. Its controller/Swarm administrators can inspect ordinary environment variables.
- An admin token is not a routine agent credential; configure it only if necessary and approved, in a reviewed secret store with network/proxy restrictions.
- Signup-domain allowlists and persisted admin overrides can defeat an apparent environment-only signup policy.
- Disabled signups do not themselves implement safe first-account onboarding; invitations and account creation are separate writes.
- The companion deployment helper does not implement HTTPS/WebSocket changes. Use an independently reviewed, authorized operation instead of inventing helper flags or silently editing generated proxy files.

## Verification

Run the repository validator, catalog generator/check, diff check and catalog integrity tests. Run the package's offline contract tests with `python3 -m unittest discover -s skills/devops/vaultwarden-operations/tests -v`. These tests exercise source invariants, not real credential handling or a deployment.

Before any operational use, verify independently:

- [ ] Exact scope, owner authorization and confirmation are recorded outside public artifacts.
- [ ] CapRover app/controller, image digest and secret-injection boundary are approved.
- [ ] TLS, domain match, effective configuration, encryption, data mounts and policy have sanitized readback.
- [ ] Credential use is isolated, exact-item, minimal-field and exact-target; all exit paths verify parent `locked`.
- [ ] A reviewed wrapper has synthetic timeout, failure, duplicate-title and output-leak tests before real credentials are used.
- [ ] Backup and isolated restore drill are separately authorized and documented; no recovery claim is based on backups alone.
- [ ] Governance status and approval/install records match explicit grants; no live infrastructure change was inferred from skill approval.
