# Coolify deployment and recovery path

Choose this path when the owner selected Coolify, not CapRover. This document and [Compose template](../templates/coolify.compose.yaml) are portable contracts, not a live stack definition or execution authorization. Read the common [implementation](vaultwarden-implementation.md) and [integration boundaries](hermes-integration.md) first.

## 1. Design and private decision ledger

Record exact server/project/environment/resource, approved HTTPS origin, image version/digest, storage, recovery custodians, recipients and allowed mutations only in protected operator context. Missing decisions remain blocked, not implicitly defaulted.

- Use one native Service Stack with a dedicated network and `/data` recovery unit, one SQLite writer, no public host ports, no Docker socket, no privileged mode and no unrelated mounts/networks.
- Select the latest reviewed stable upstream security release at execution time, then pin its approved version **and immutable digest**. Do not deploy a moving `latest` or unattended updater. Verify architecture, entrypoint, current notification listener and migration compatibility from that selected image.
- Budget free disk, actual available memory, image extraction and incumbent-service headroom from live measurements. A disk-cleanup result is not a RAM gate.
- Audit host/Coolify/Docker administrators explicitly. Containers, projects, accounts and an encrypted mounted filesystem do not isolate data from a privileged host administrator.
- Require proven encrypted persistent storage before real data. Application E2EE protects vault item payloads, not all metadata, logs, configuration or signing state. A named Docker volume does not prove filesystem encryption.

### Encrypted-storage startup boundary

A dedicated LUKS volume is an optional reviewed implementation of the filesystem gate, not something this package provisions automatically. Keep its unlock/recovery material outside both the vault and source host. Approve size, persistence, operator, reboot/unseal method and recovery separately; never store an unlock key in source, argv, logs or an ad hoc plaintext env file.

Prove the mountpoint is actually backed by the expected encrypted filesystem, has the required ownership and has sufficient space. For the provided non-root template, prepare the mounted data root for UID/GID 1000 under an explicit ownership grant. Create the non-secret `.vaultwarden-volume-ready` marker **only inside the verified mounted filesystem**, never in the underlying directory. The template refuses first start if that marker is absent; `create_host_path: false` refuses directory auto-creation. The marker is a secondary fail-closed restart guard, not encryption evidence or authentication.

On reboot, a sealed/missing mount must block startup rather than initialize a fresh empty vault. Verify this behavior in an isolated fixture before production. Do not imply unattended unseal if independent protected key delivery has not been approved.

## 2. Read-only preflight

1. Verify target identity, OS/architecture, Docker/Compose version, capacity, private operator route, current ports, routed CIDRs and workload inventory. Preserve incumbent services and use strict host-key checking.
2. Inspect a healthy native stack on the same server/destination for working directory, mount/network ownership, managed labels, internal HTTP port and proxy attachment. Return only allowlisted metadata, never a full secret-bearing inspect/configuration.
3. Query the exact DNS hostname, unwanted AAAA and wildcard before any creation; do not revive an old wildcard or assume a synthesized answer belongs to this deployment.
4. Prove the reviewed control-plane API token works via a private authorized endpoint. Cloudflare Access interception of a public management API is not token failure; do not weaken the Access policy or broaden scopes.
5. Verify an independent backup destination and restore design before accepting stateful readiness. Local file existence or an unused storage credential is not backup evidence.

## 3. Offline candidate validation

Customize only an operator-local non-secret candidate. The template requires explicit `VAULTWARDEN_IMAGE`, `VAULTWARDEN_DOMAIN` and `VAULTWARDEN_DATA_PATH`; unresolved variables fail rather than select a default image or volume. The mount path itself is private deployment metadata, not a public example to copy from a real host.

The template preserves the selected official image's entrypoint/healthcheck contract, drops capabilities, uses non-root UID/GID, a read-only root filesystem and a bounded `/tmp` tmpfs. Verify these assumptions from the pinned image and prove writable `/data`; do not silently fall back to root if ownership fails. A Dockerfile inspection and successful Compose renderer are not runtime proof.

Run the target's actual `docker compose --file <candidate> config --quiet` with synthetic variables, not production secret values. Resolve the template variables through supported protected Environment/configuration facilities, not a populated `.env` artifact. No credentials, SMTP, admin token or agent session are present in the base template.

Review any supplemental SMTP/admin/backup configuration independently. Literal secret-store references and arbitrary `_FILE` names do not automatically resolve. Coolify privileged operators can inspect runtime environment; protected Environment delivery does not make the host a trust boundary. Block a delivery mechanism that would expose values in source, tool results, arguments, logs or prohibited plaintext files.

## 4. Supported native creation/configuration/start

Use Coolify's documented **Docker Compose Empty / Service Stack** UI or supported public API. Do not insert database records, invoke private framework models, create a managed workdir manually or deploy around Coolify with standalone Compose.

For installed versions exposing `POST /api/v1/services`, the request contract accepts a base64-encoded `docker_compose_raw`, explicit project/environment/server/destination selectors, a resource name and **instant_deploy: false**. Verify the selected version's supported schema and URLs shape from official documentation/source first. Keep the compose body free of secret values; protected env writes are separate. Never double-encode a payload or retry an ambiguous create without exact-resource readback.

1. Create once, before DNS or exposure, and read back its exact resource identity and project/environment.
2. Persist required non-secret settings through the supported resource API/UI. Secrets, if independently approved, use the protected Environment/Secrets or reviewed external secret-store path and are verified privately by equality/presence, never echoed.
3. Bind the FQDN only to the intended Vaultwarden subservice. A value such as `https://vault.example.com:8080` identifies the **container target port**; public clients still use HTTPS/443. Never publish 8080 on the host.
4. Before a lifecycle mutation, issue the exact non-mutating GET preflight for the documented action route. A method guard proves the route exists; exact 404 means unavailable, not a reason to send speculative POSTs or increase token permissions. When unavailable, use an explicitly authorized visible managed dashboard action, not a private endpoint.
5. Start through the supported platform action only after storage, key custody and configuration gates pass. Read back materialized workdir, actual container/image digest, app health, mount ownership, proxy/app network membership, effective policy and no unexpected host ports.

A UI resource or accepted queue action is not a deployment. Reconcile a potentially successful write before any retry or method change.

## 5. Ingress, policy and protected bootstrap

- After container/network materialization passes, create only the approved explicit DNS-only record with short TTL. Verify authoritative DNS, public resolvers and operator resolution, including absence of unintended AAAA.
- Let Coolify own its generated ingress labels and TLS lifecycle. Verify HTTP-to-HTTPS redirect, chain/SAN, intended login and `/alive`. Do not restart the shared proxy to solve a new resource's problem; preserve all incumbent routes. Shared proxy changes require their own approval and rollback.
- Keep `DOMAIN` equal to the canonical HTTPS origin. The default template has signups off, an empty signup-domain whitelist, invitations off and admin absent. Verify effective values, including persisted `config.json`, not environment names alone.
- There is no automatic enrollment in this closed initial state. Approve a private admin/invitation bootstrap, exact owner email and SMTP/send scope separately. Never briefly enable public signup merely to create the first account. If admin is enabled, use upstream Argon2id hashing and origin-side private restriction; edge-only Access is not an origin boundary. Remove the temporary admin capability after bootstrap when that was the approved plan, accounting for persisted overrides and existing sessions.
- Do not put interactive Cloudflare Access in front of the complete native-client API path without actual client compatibility evidence. DNS-only public HTTPS is distinct from private administration. If proxying is approved later, prove origin identity first and use Full (strict); no global zone downgrade or unrelated policy edits.
- Revalidate IP-header semantics against the pinned release. For the rightmost-untrusted X-Forwarded-For behavior, set `IP_HEADER_TRUSTED_PROXIES` to the verified chain, never trust arbitrary client-supplied addresses or a guessed whole network. An intermediate CDN changes this chain.
- Review proxy/application request logging: notification URLs can contain `access_token`; disable or redact query-bearing request logs before any authenticated client connects. No raw token-bearing diagnostic traces.
- Complete an individual human owner, company organization, least-privilege collections, MFA and independent recovery custody through protected channels. Do not migrate another credential manager or grant agents access as part of enrollment.

## 6. Acceptance, backup and restore

Separate these observations; do not replace them with HTTP 200:

- **Container/configuration:** immutable image, writable encrypted mount, one writer, health, effective closed registration and public admin denial.
- **Persistence:** resource-scoped restart with approved synthetic state; compare both database state and representative file integrity. No volume deletion or service-wide restart of unrelated workloads.
- **Human workflow:** invitation/delivery and acceptance when in scope; login/MFA, organization/collection permissions, revocation and native-client extension/desktop/mobile sync. An authenticated browser does not prove native-client compatibility. Verify notification WebSockets through the actual ingress path.
- **Backup:** a consistent SQLite Online Backup API or built-in `/vaultwarden backup` snapshot plus matching attachments/Sends/configuration/signing state. Coordinate filesystem writers through an approved consistency window; do not claim an online arbitrary volume copy is coherent. External SQL requires its own consistent dump.
- **Off-host custody:** an independent encryption key and private off-host destination with least-privilege access. Existing storage credentials do not authorize reuse of an unrelated application's backup repository. List/read back the exact uploaded artifact or snapshot and perform full data verification.
- **Isolated restore:** restore only to fresh separately approved storage, no production SMTP/webhooks/domain/live database. Apply the bounded untrusted-file verifier contract from the common reference, then database integrity and representative restored synthetic data/file/client tests. Never extract over live state or infer restore authority from verification permission.
- **Schedule/monitoring:** daily encrypted backups, bounded freshness checks and failure reporting require explicit schedule/destination authorization. Do not enable automatic deletion/pruning just because the first restore passed.

When native-client, MFA, encrypted storage or restore gates are still pending, report the deployment as a constrained pilot/not production-ready. A backup sidecar that is running proves none of the backup/restore observations.

## 7. Rollback and public evidence

Rollback only the newly owned resource and exact DNS record after identity/readback comparison. Preserve volumes, encrypted backups, recovery custody and immutable image/configuration inventory. Never use `down -v`, bulk cleanup or image-only downgrade after a potentially incompatible database migration.

Public reports use fixed booleans/statuses. Actual destinations, recipients, grants, service IDs, host paths and recovery artifacts stay in protected operator context. Merging this package does not authorize installing it, launching agents or operating any specific coffer.

## Primary sources and version revalidation

- Coolify Vaultwarden service: https://coolify.io/docs/services/vaultwarden
- Coolify public API reference: https://coolify.io/docs/api-reference/api/operations/create-service
- Coolify supported service-controller schema: https://github.com/coollabsio/coolify/blob/v4.3.23/app/Http/Controllers/Api/ServicesController.php
- Vaultwarden release/security guidance: https://github.com/dani-garcia/vaultwarden/releases
- Vaultwarden configuration: https://github.com/dani-garcia/vaultwarden/blob/main/.env.template
- Vaultwarden image entrypoint/build: https://github.com/dani-garcia/vaultwarden/blob/main/docker/Dockerfile.j2
- Vaultwarden consistent backups: https://github.com/dani-garcia/vaultwarden/wiki/Backing-up-your-vault
- Vaultwarden registration/admin: https://github.com/dani-garcia/vaultwarden/wiki/Enabling-admin-page
- Docker Compose interpolation and bind semantics: https://docs.docker.com/reference/compose-file/services/

Moving sources are references, not approval of a current runtime version. Validate exact installed/pinned contracts again at execution time.
