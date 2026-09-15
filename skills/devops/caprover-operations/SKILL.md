---
name: caprover-operations
description: "Use when diagnosing a saved CapRover CLI session or planning authorized application configuration, rollback, recovery, scaling, or retirement operations with explicit safety gates. Do not use it as deployment authorization or as a credential-discovery mechanism."
version: 0.1.0
author: ClawdIA contributors
license: MIT
metadata:
  hermes:
    tags: [caprover, operations, diagnostics, rollback, safety]
    related_skills: [caprover-deploy]
---

# CapRover Operations

## Overview

Treat an operation, a deployment, credential access, and authorization as separate facts. This candidate provides a guarded, read-only saved-session probe and procedures for reviewing later operations. It grants no production access. The companion `caprover-deploy` has its own explicit execution gates and support limits; a valid session is not permission to deploy.

## When to use

Use for diagnosing a preselected saved session, reviewing an application change, or planning recovery, rollback, scaling and retirement. Do not use to discover credentials, renew authentication, silently switch deployment methods, or authorize a production mutation.

## Route the task

- For saved-session diagnosis, read [references/cli-session-and-auth.md](references/cli-session-and-auth.md) and use `scripts/probe.py`. Never infer authentication from `caprover list`.
- Before changing an app definition, read [references/safe-app-definition-updates.md](references/safe-app-definition-updates.md).
- For provenance, rollout verification, or rollback, read [references/deployment-provenance-and-rollback.md](references/deployment-provenance-and-rollback.md).
- For scaling, recovery, or retirement, read [references/app-lifecycle-and-retirement.md](references/app-lifecycle-and-retirement.md).
- For authorship, licenses, versions, and source limits, read [references/provenance.md](references/provenance.md).

## Authorization gates

Verify that explicit, current, and sufficient authorization exists for each action. Reuse standing or session grants within their scope. Request a new decision when the scope is new, insufficient, or ambiguous. Authorization to access credentials does not authorize deployment, restart, or deletion. Apply this policy to credential access, configuration writes, deployment/build, start or scale-up, data migration, and deletion; distinct scopes do not require repeated confirmation when a current grant already covers the exact action. Authentication renewal is a separate operation and is never performed by the probe. A timeout on a mutation may mean it applied: reconcile by reading current state before considering a retry.

Use [templates/operation-report.md](templates/operation-report.md) for a sanitized record. Do not put credentials, raw API responses, private snapshots, or private infrastructure identifiers in reports.

## Safety boundaries

- Default to reads. A successful API acceptance is not proof that an operation completed.
- Bind a saved CLI alias to an exact expected origin in an owner-only targets file outside source control.
- The accepted targets and registry bytes remain the private request snapshot through the probe's end-of-query source recheck. Concurrent source change makes the result inconclusive; the probe neither locks nor rewrites operator files.
- Do not accept a target-host override, relax TLS, follow redirects, use proxies, or reuse an ambient CapRover environment.
- The Node preload is a narrow interlock for the pinned CLI layout, not a universal sandbox. Missing or incompatible guard, CLI, schema, or evidence is inconclusive and fails closed.
- Never blindly retry a timed-out write or delete. Verify readback and app-specific health first.

## Common pitfalls

- Local CLI inventory is not an authentication check, and a generic token warning is not evidence that the operator logged out.
- The fully specified official CLI probe makes three GETs: app inventory, captain information, then the requested system information. Pin the actual sequence rather than assuming one request.
- A subprocess exit, API acceptance, build completion, deployed image and application health are different evidence levels. Never collapse them into a single success claim.
- CapRover full POST updates default omitted fields. Preserve the current supported writable state, validate the intended diff and read it back.
- Node compatibility is established by the pinned version and real fixture execution, not by a blanket claim that an entire major version is broken.

## Verification checklist

- [ ] Approved alias and exact origin come from protected files outside Git.
- [ ] A conclusive result covers source stability only from the accepted reads through the end-of-query recheck, not changes after the response.
- [ ] The CLI version, runtime version and mandatory guard match the pinned contract.
- [ ] Diagnosis used no login, token renewal, redirect or write endpoint.
- [ ] Reports contain only fixed neutral metadata, not server payloads or credentials.
- [ ] Full real-CLI fixtures ran; skips or sandbox restrictions are reported explicitly.
- [ ] Any later mutation has explicit, current and sufficient authorization for its exact scope, plus a private recovery snapshot and readback.
- [ ] Application-specific health and representative live validation remain separate gates.
