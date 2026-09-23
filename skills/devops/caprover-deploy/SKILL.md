---
name: caprover-deploy
description: "Use when planning or applying a CapRover deployment. Select one bounded method, preserve app state, and verify evidence; plan-only is the default."
version: 2.0.0
author: FMercurio Tech
license: MIT
metadata:
  hermes:
    tags: [caprover, deploy, docker, ci-cd, automation, playwright]
    related_skills: [caprover-operations]
---

# CapRover Deploy

## Overview

This version is intentionally narrower than 1.x. It validates the target, intent, source, selected method, and static local capability before credential access. Without `--apply`, it prints a plan and performs no browser launch, credential lookup, session read, login, API request, or deployment. A Playwright apply separately launches and prepares its local browser resources without navigation before credentials or controller mutations.

## When to Use

- Plan or explicitly apply a local artifact upload, remote Git configuration, or dashboard Force Build.
- Diagnose a saved CLI session with the companion `caprover-operations` probe first when session state is uncertain.
- Do not use this helper for server maintenance, backups, deletion, networking, HTTPS/WebSocket changes, or unapproved credential renewal.

## Supported operations

| Intent | Method | Result |
|---|---|---|
| `--tarball FILE` | CLI | Uploads the explicit local tarball |
| `--source-dir DIR --branch BRANCH` | CLI | Resolves the branch once, archives that immutable commit, and uploads it |
| `--repo URL --branch BRANCH --configure-only` | API | Configures remote Git and reports `configured_not_deployed` |
| `--repo URL --branch BRANCH` | Playwright | Preserving API config, then one authenticated Force Build |
| `--rebuild-only` | Playwright | One authenticated Force Build for an existing app |

`--method auto` selects one capable method before any write. It never changes method after a mutation is attempted. Explicit methods never fall back. A remote `--repo` is never interpreted as the current local skill checkout.

API tarball upload and API Git-build triggering are not implemented. HTTPS and WebSocket changes are also not implemented here; `--enable-https` and `--enable-websocket` fail with `capability_unavailable` before any write. Use a separately reviewed and authorized operations workflow for those settings.

## Safe plan and apply

All non-local examples use an exact target assertion. Replace placeholders with protected local paths; do not put tokens or passwords in arguments.

Before each action, verify that an explicit, current and sufficient authorization grant covers its exact scope. Reuse standing or session grants within their scope, and request a new decision when the scope is new, insufficient or ambiguous. Credential access does not authorize deployment, restart or deletion. Follow the companion operations skill's canonical [authorization gates](../caprover-operations/SKILL.md#authorization-gates); these sufficiency checks do not weaken `--apply`, `--allow-login`, `--allow-create`, exact-target, recovery, readback or reconciliation gates.

```bash
# Safe plan: validates intent and API capability without credentials or HTTP.
python3 scripts/caprover_deploy.py \
  --caprover-url https://captain.example.com \
  --expected-host captain.example.com \
  --app-name my-app \
  --repo https://github.com/org/repo \
  --branch main \
  --configure-only \
  --recovery-snapshot /secure/recovery/my-app-before-config.json
```

Saved-session CLI apply (preferred):

```bash
python3 scripts/caprover_deploy.py \
  --caprover-url https://captain.example.com \
  --expected-host captain.example.com \
  --app-name my-app \
  --tarball /work/releases/my-app.tar \
  --method cli --apply \
  --caprover-name production \
  --targets /secure/caprover-targets.json \
  --registry /secure/caprover-registry.json \
  --cli-root /trusted/caprover-2.4.4 \
  --node /trusted/node
```

Remote Git configuration requires `--recovery-snapshot` even in plan mode. The path must be absolute, new, have an existing parent, and be outside every Git tree. Apply creates it with mode `0600` before changing configuration and never prints its contents.

Add `--allow-create` only when creating a missing app is part of the approval. Creation occurs once and must pass an app-definition readback before configuration or deployment continues.

## Authentication

A complete saved session is selected by all five arguments: `--caprover-name`, `--targets`, `--registry`, `--cli-root`, and `--node`. The protected files must be owner-only regular files. Their target alias and registry machine must uniquely agree on the exact normalized origin, which must also match `--caprover-url`.

The selected token is loaded once, frozen in memory, and used for preflight and execution. The CLI receives only that selected session in a private ephemeral HOME/XDG store. Caller CapRover/proxy configuration is not inherited. Tokens and passwords are absent from CLI arguments and environment. An expired session stops nonzero; it never falls back to login.

Password authentication is separate and requires `--allow-login`. Before `get_password()` or `api.login()`, `CAPROVER_CREDENTIAL_ORIGIN` must exactly match the validated CapRover origin. Password lookup then uses `CAPROVER_PASSWORD`, an explicitly requested KeePass entry, or an interactive prompt. A valid saved CLI session never performs password lookup or login.

Git credentials are resolved only for `--repo` configuration. `github.com` may use `GITHUB_TOKEN` or `gh auth token`. Other hosts require `--expected-repo-host` and an exact host-specific binding in `CAPROVER_REPO_TOKEN_BINDINGS`; generic GitHub tokens are not used for custom hosts.

## Lifecycle and evidence

Apply follows this order:

```text
validate intent/source/method/capability
  → for Playwright apply, prepare local browser resources without navigation
  → authenticate one way
  → strict system/app preflight
  → optional approved create + readback
  → optional 0600 config recovery snapshot + preserving update/readback
  → capture build baseline immediately before the selected trigger
  → trigger once
  → poll against the baseline
  → verify changed generation/image evidence and optional exact replicas
```

CLI return zero, an asynchronous upload acknowledgment, or a clicked Force Build is not deployment verification. Guarded CLI upload succeeds only after the exact synchronous upload returns status `100` and the expected source is observed. Success is reported only as `deployment_evidence_verified`; it does not prove application or endpoint health. The reviewed webhook protocol cannot prove scheduling, so Playwright Force Build always reports an acknowledged-but-unconfirmed `reconcile_required` outcome after a possible click, even when the expected source is later observed. A timeout or failure after a possible write is never retried through another method.

## Request-boundary limits

Python API requests disable inherited proxies and reject every redirect while carrying CapRover credentials. Browser navigation separately permits only the configured origin.

CLI deployment uses a mandatory, hash-pinned `deployment_guard.cjs`. With the pinned CLI layout it permits only the two app inventory reads used by CLI 2.4.4, one multipart POST for the selected app, and bounded build-status reads for that same app. At the controller boundary, the guard validates the CLI's exact `?detached=1` request and removes that query parameter from the actual outgoing request so the reviewed server waits for `scheduleDeployNewVersion`; it never sends `detached=0`. The guard requires status `100` from that exact upload and validates credential headers, a private source snapshot/immutable commit, destination, method, path, response size, and redirects. Login, token renewal, proxies, alternate apps, and arbitrary API methods/paths are blocked.

The guard is a narrow request interlock, not a general Node sandbox. Support is limited to the pinned official CLI 2.4.4 layout. That layout was tested with Node 26.7.0; this is not a claim that every CLI command or every Node 26 release works.

See `references/api-v2-endpoints.md`, `references/playwright-deploy-pattern.md`, and `references/provenance.md`.

## Common Pitfalls

- A full update is not a partial patch. Preserve the current writable definition; never replace it with example defaults.
- Serialize app configuration changes. The API does not make the read/update/readback sequence atomic against concurrent writers.
- Do not infer health from a CLI zero exit, an accepted request, or an idle build. Require changed deployment evidence, then obtain application-specific health evidence separately.
- Never switch methods after a possible write. Reconcile the observed state before seeking approval for another attempt.

## Verification Checklist

- [ ] Intent, target, source, method and authentication grants are explicit, current, sufficient and within scope.
- [ ] Protected state remains outside Git and secrets are absent from arguments/output.
- [ ] Creation and configuration changes have their own readbacks.
- [ ] Build evidence is newer than the pre-trigger baseline and expected replicas are exact when checked.
- [ ] An inconclusive result exits nonzero; live health and runtime promotion are not inferred from fixtures.
