---
name: vaultwarden-operations
description: "Use when safely deploying or operating a Vaultwarden service."
version: 0.1.0
author: "Felippe M. + Hermes Agent"
license: MIT
metadata:
  hermes:
    tags: [vaultwarden, bitwarden, secrets, docker, operations]
    related_skills: [caprover-operations, caprover-deploy]
---

# Vaultwarden Operations

Operate a self-hosted Vaultwarden instance without turning the agent into a broad secret reader. This skill covers implementation, lifecycle, and bounded secret access; it does not authorize publication, administrator-token use, bulk vault extraction, or destructive account changes.

## When to Use

- Deploy or upgrade a single-tenant Vaultwarden service on a reviewed container platform.
- Establish safe agent access to one named credential for one approved technical operation.
- Diagnose Vaultwarden health, SMTP delivery, persistence, registrations, or backup readiness.
- Do not use for unapproved secret retrieval, vault exports, broad item enumeration, credential sharing, user deletion, or security incident response.

## Prerequisites

- Explicit owner authorization defining the target environment and whether this is plan-only, installation, upgrade, recovery, or a read-only diagnosis.
- A private DNS name, TLS termination, persistent storage, and a provider-supported backup target are identified before deployment.
- The official Vaultwarden image digest/version is selected and recorded outside of examples.
- All secrets are injected by the runtime secret store. Never commit `ADMIN_TOKEN`, SMTP passwords, database passwords, invitation tokens, API keys, session tokens, or recovery material.
- Review `references/vaultwarden-implementation.md` and use `templates/vaultwarden.env.example` only as a non-secret contract.

## Procedure

1. **Classify the request.** Record whether the task is plan-only, deploy, update, read-only health diagnosis, narrow credential use, backup, restore drill, or an account/security action. Treat every write as a separate authorization gate.
   - Completion: target, requested effect, operator authority, and rollback path are explicit.

2. **Preflight the platform.** Verify the exact hostname, TLS route, image provenance, volume/database persistence, outbound SMTP policy, registration policy, and backup destination. Do not create an application or resolve credentials during a plan-only request.
   - Completion: the design has a persistent data path, health endpoint, non-secret configuration contract, and a tested rollback approach.

3. **Deploy only after an installation gate.** Use the platform's reviewed deployment path. Set every security-sensitive field explicitly: public registration off unless expressly required, invitation policy, SMTP transport, domain URL, WebSocket support where applicable, logging scope, and persistent volume/database reference.
   - Completion: the platform readback matches the approved configuration and no secret appears in command arguments, logs, repository files, or reports.

4. **Verify service behavior without vault disclosure.** Check HTTPS, the login page, the health endpoint when exposed by the deployment design, SMTP test flow if authorized, and container/application logs with secret redaction. Confirm public registration is disabled when that was the approved policy.
   - Completion: availability, TLS, persistence attachment, and registration policy are observed from the live target.

5. **Use secrets through an ephemeral child process.** Keep the normal CLI locked. Unlock only a child process for one named item and one approved operation; scope lookup by exact title/identifier and fetch only required fields. Do not use `bw export`, `bw list items`, raw item JSON, shell arguments containing credentials, clipboard extraction, or transcript logging.
   - Completion: the approved operation finishes, its result is verified without echoing secret material, and the parent CLI is locked again.

6. **Back up and recover deliberately.** Back up the persistent database/volume and all required deployment configuration as separate protected artifacts. A successful backup job is not proof of recovery: run an isolated restore drill before declaring the recovery design valid.
   - Completion: restore drill evidence confirms the recovered instance can start and authenticate with the expected non-secret checks.

7. **Upgrade or change configuration safely.** Capture current configuration and backup evidence first, apply one reviewed change, read back the exact target, and rerun health checks. Do not combine a version upgrade with security-policy changes unless both were approved.
   - Completion: version/configuration, persistence, login, SMTP behavior (if in scope), and rollback posture are verified.

## Narrow Agent Secret-Access Contract

Use this contract whenever an agent needs a Vaultwarden credential:

- The owner authorizes a named technical purpose and exact external target; vault access is not deployment or production-change authorization.
- The agent selects a single item by exact expected title/identifier after a scoped sync, not by dumping or browsing the vault.
- `BW_SESSION` exists only in child-process memory. Do not persist it in shell profiles, environment files, service units, terminal history, or agent memory.
- Secrets never appear in prompts, stdout/stderr, screenshots, telemetry, repository artifacts, chat, or command-line arguments.
- Verify saved/updated credentials only by metadata or field presence, never by returning values.
- After the child exits, verify that a normal `bw status` is `locked` and that no session variable remains in the parent environment.

## Pitfalls

- A visible login page does not prove database persistence, SMTP, or backups work.
- An administrator token is an emergency management capability, not a normal automation credential. Keep it in the secret store and do not expose the admin panel publicly.
- Do not enable public registration to solve an invitation/onboarding issue without explicit approval.
- Do not use a Vaultwarden backup as a substitute for validating a restore. Encrypted or incomplete artifacts can be unusable in practice.
- Avoid long-lived unlocked CLI sessions and shared browser sessions; both expand the blast radius beyond the approved operation.
- Do not put a Vaultwarden server behind an unauthenticated debug endpoint or expose database/admin ports publicly.

## Verification Checklist

- [ ] Exact environment, purpose, write scope, owner authorization, and rollback scope are recorded.
- [ ] Image provenance/version and persistent storage/database are explicit.
- [ ] TLS, hostname, registration policy, SMTP configuration, and backups were read back from the target.
- [ ] No secret, tenant identity, internal host, session token, or local path was committed or reported.
- [ ] Secret access was limited to one approved item and operation; normal CLI state returned to `locked`.
- [ ] Restore drill evidence exists before recovery readiness is claimed.
