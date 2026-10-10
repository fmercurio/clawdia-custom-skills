---
name: vaultwarden-operations
description: "Use when deploying or operating Vaultwarden safely."
version: 0.4.0
status: candidate
author: "Repository contributors + Hermes Agent"
license: MIT
metadata:
  hermes:
    tags: [vaultwarden, bitwarden, secrets, caprover, coolify, operations]
    related_skills: [caprover-operations, caprover-deploy]
---

# Vaultwarden Operations

Plan and review Vaultwarden operations through **CapRover or Coolify** without turning an agent into a broad secret reader. The prior 0.2.0 procedural revision was maintainer-approved; this 0.4.0 source revision is a review candidate. It adds candidate backup/recovery helpers, metadata-only preflight and a [synthetic private-consumer core](references/private-consumer-core.md), not an executable vault credential integration or a tested Bitwarden credential wrapper. Approval of the skill does not authorize live deployment, installation, enrollment or secret access.

## When to Use

- Plan a single-tenant human Vaultwarden deployment through the owner's selected CapRover or Coolify platform.
- Review an explicitly authorized upgrade, health diagnosis, backup or isolated restore drill.
- Discover existing approved integration capabilities and define bounded use of one credential for one named authorized operation.
- Do not use for unapproved retrieval, exports, inventory, arbitrary shell execution, account deletion or incident response.

## Prerequisites

- For a new host/profile, start with [new-instance onboarding](references/new-instance-onboarding.md): verify source/install/session/authority/destination independently, reproduce the isolated source gates and preserve missing executor/enrollment/runtime blockers. Repository presence or a loaded skill is not working credential access.
- Owner authorization names the exact target, technical purpose, allowed effects, time window, confirmation and rollback in protected operator context, never public artifacts.
- Maintainer approval for installation/promotion/publication and owner approval for live operations remain separate. Approval of source does not create a runtime grant.
- Read [common implementation and CapRover](references/vaultwarden-implementation.md), including CLI limitations. For a Coolify target, also read [Coolify deployment](references/coolify-deployment.md); choose one platform path rather than combining controllers. Review companion capabilities at their exact selected revision; existence does not approve installation/use.
- Read [Hermes integration boundaries](references/hermes-integration.md) before capability discovery, autofill or any proposed agent use. Discover existing reviewed connector/private consumer before inventing a wrapper; no secret reads merely to discover tooling. For source development, use the [proposed next-slice contract](references/private-executor-next-slice.md); it does not implement a vault adapter, private transport or runtime supervisor.
- Select the official `vaultwarden/server` image with a reviewed stable release and immutable digest; verify image/configuration/database/migration/notification contracts. Do not resolve `latest` during deployment.
- Identify canonical HTTPS origin, encrypted persistent storage, host trust, supported database, protected delivery and independent recovery before first start.
- Use [the environment checklist](templates/vaultwarden.env.example) and [Coolify candidate](templates/coolify.compose.yaml) only as non-secret contracts. Never populate a public file with live secrets/configuration. The [operator handoff](README.md) guides inspect → decisions → dry-run → apply.

## Authorization and privacy boundaries

Every infrastructure, publication, DNS/domain, SMTP, database, backup, restore, upgrade, signup-policy, admin-token or user-account change needs explicit, specific owner authorization. An approved plan is not apply authorization. Possession of a credential does not authorize its external effect.

Never request or expose secrets in chat, model-visible MCP/tool results, logs or history. Never put passwords, tokens, cookies, private keys, SMTP credentials, `ADMIN_TOKEN`, `BW_SESSION`, personal/customer data, real company names, private origins/addresses or host-local paths in repository examples/reports. Use reserved domains and non-secret placeholders. Do not copy an installation's configuration into this package. Inspect protected live configuration inside a trusted private boundary and return only allowlisted booleans/enums, never raw logs, definitions, CLI status or item JSON.

## Procedure

1. **Classify and gate.** Default plan-only/read-only. Separate source installation/publication, platform apply, secret use, email/account actions, backup and restoration into exact named scopes.
   - Completion: owner authorization covers the proposed effect, confirmation, verification and rollback; missing choices remain pending.
2. **Preflight the selected platform.** Confirm exact controller/server/project/environment/app identity, supported method, immutable image, internal port, encrypted persistent mount, one SQLite writer, existing state and independent recovery custody. Privileged platform/host operators can inspect runtime state; a container is not their trust boundary.
   - Completion: reviewed storage/secret-delivery and recovery exist, or first start is blocked; no resource is created merely to inspect capabilities.
3. **Deploy only with an apply grant.** Follow the selected platform reference through its native supported control plane. Keep `DOMAIN` canonical, `SIGNUPS_ALLOWED=false`, signup-domain whitelist empty and invitations off unless separately approved. Administration and SMTP are not enabled by default; never use public signup as bootstrap.
   - Completion: one authorized method applied; potentially partial writes reconciled through exact-target readback before retry/fallback.
4. **Read back effective state.** Verify actual image/digest, canonical domain, TLS, proxy/notification behavior, encrypted mounted recovery unit/database, one writer, registration/invitations and absent/private administration. Persisted admin `config.json` may override env; key names alone prove nothing.
   - Completion: fixed sanitized outcomes match the approved design; enrollment, SMTP/send, native-client and persistence-write tests remain separately scoped.
5. **Evaluate integration separately.** Distinguish package presence, independently reviewed installation, session availability, active grants and effective destination permission. Read-only MCP or a generic denial cannot prove absence of a writer; unknown remains unknown. No agent secret-consumption wrapper ships here. Candidate infrastructure helpers are documented separately in [operational learnings](references/operational-learnings.md); review [agent-access rollout](references/agent-access-rollout.md) before proposing enrollment.
   - Completion: private resolution/consumption, exact item/target and all worker cleanup/parent-lock gates independently tested before any real credential use. No broker or autofill fallback expands authority.
6. **Back up and prove recovery.** Under specific approvals, make database-consistent encrypted off-host backups including required files/configuration; boundedly verify untrusted archives, then perform an isolated restore with no production outbound effects. Recovery key access must not depend on the failed vault/host.
   - Completion: remote artifact/snapshot full check, database integrity and authorized representative restored data/files/workflows verified; a running job is not recovery evidence.
7. **Complete human acceptance or modify narrowly.** Verify first-owner/MFA, org/collection permissions/revocation and native clients before real credentials. For changes/upgrades, approve exact delta and rollback, capture recovery first, apply once and verify. Migrations may make image-only rollback unsafe.
   - Completion: report configuration, deployment, human workflow, persistence, backup and restore separately; no production-ready claim while a required gate is pending.

## Narrow Agent Secret-Access Contract

- Require purpose, exact external origin/resource/action, exact item selector, minimal fields and valid grant before unlock/sync. Selectors/identities remain in protected context, not output/argv.
- Keep the parent CLI locked with no `BW_SESSION`. A process child using the same CLI data/cache is not isolation; never unlock a broad human vault.
- Use one ephemeral reviewed worker, dedicated least-privilege account, private isolated state and fixed allowlisted consumer. No arbitrary shell, inherited environment/proxies, tracing/core dumps or unbounded output.
- `bw sync` has no per-item filter. Account-scoped sync is not selective item decryption; unrelated visible items block this path. A shared broker is a different architecture requiring independent review, not a substitute for worker restrictions.
- Prefer exact item ID. Exact title requires a reviewed unique exact-match resolver without enumeration/substring/first-match fallback; otherwise stop for a protected ID.
- Resolve and consume indispensable fields **inside the private boundary**. Prohibit `bw export`, `bw list items`, broad inventory, raw item JSON, clipboard and credential-bearing argv. Do not return secret fields via MCP/tool output for later consumption; final-answer redaction does not undo exposure.
- `BW_SESSION` exists only in ephemeral worker memory/environment and allowlisted CLI descendants. Never persist it in files, profiles, units, logs, agent memory/history or chat; never pass it to the external consumer or parent.
- On success, error, timeout or interruption, supervise termination/wait of **all descendants**, best-effort child lock, state/token discard and exact parent `locked` verification without a session variable. An exited leader is not cleanup proof; unknown/unreachable/unlocked/unauthenticated parent is failure.
- Report only bounded booleans/enums/fixed codes. Cleanup uncertainty blocks further work. Parent lock is not token revocation or zeroization; suspected exposure requires a separate incident-response grant.

## Pitfalls

- HTTP health, a UI resource, an attached volume or passing text test proves neither encryption, native-client compatibility nor recovery.
- Both platform administrators can inspect runtime environment. A named volume, E2EE payload or encrypted mounted filesystem is not host-admin isolation or whole-recovery-unit encryption evidence.
- External SQL still requires persistent attachments/Sends/keys/configuration.
- Signup-domain allowlists and persisted admin settings can defeat env-only policy. Disabled signups are not first-owner enrollment; private bootstrap, invite/account and MFA are separate scopes.
- An admin token is not an agent credential. Enable only when necessary/approved, hashed and privately restricted; inspect persisted overrides when disabling.
- The CapRover helper does not implement HTTPS/WebSocket changes. Coolify generated labels/database are not editing shortcuts; use supported managed controls and never restart shared ingress automatically.
- Item discovery is not autofill, authentication, a writer grant or effective permission. Profile selectors do not authenticate privileged callers; stale sessions do not authorize restarts.
- Backup verification alone does not authorize extraction/restoration/cleanup. Structural integrity is not provenance or usable recovery.

## Verification

Run repository validator, catalog generation/check, manifest/file-inventory/neutrality checks, staged diff check and package tests:

```sh
python3 -B -m unittest discover -s skills/devops/vaultwarden-operations/tests -v
```

Documentary checks and owned synthetic archive/SQLite/age/metadata-child tests are **not agent executor, live encryption or deployment safety proof**. Validate the selected template with actual platform tooling and synthetic inputs; runtime gates require their own evidence.

- [ ] Exact owner scope and rollback recorded outside public artifacts; no authority inferred from merge/installation.
- [ ] Selected platform/controller/resource, immutable image, encrypted mount/ownership and protected delivery approved.
- [ ] TLS/canonical origin, effective policy, admin denial and no secret-bearing logs verified.
- [ ] Human owner/MFA/org permissions/revocation, native-client sync and notifications verified before real data.
- [ ] Any agent path separately reviewed with private results, actual identity/grant/permissions, isolated dedicated account and all cleanup/parent-lock paths.
- [ ] Backup full remote check and isolated representative restoration specifically authorized/verified; no false green from running jobs.
- [ ] Source registry/manifest/approval and installed runtime states distinguished; other profiles and existing credential managers untouched.
