# Operational implementation and acceptance boundaries

This is a tenant-neutral record of mechanisms exercised during an authorized pilot, generalized into reusable source. It is not a live receipt, an account export or permission to operate another deployment. Private origins, recipients, service identifiers, paths, credentials and artifacts are intentionally absent.

## Package and implementation layers

- The earlier procedural contract remains the origin of the deployment/integration rules. This revision adds candidate executable operational helpers, a native stylesheet and metadata-only access preflight. All new helpers need review and exact-target authorization before installation/use; source publication is not runtime promotion.
- [Backup candidate](../scripts/backup.py) derives from the pilot's operator-local implementation. Generalization removes tenant-specific custody-vault names, domains, labels, paths and configuration. The command now requires an explicit private configuration and defaults to `check`; backup/restore also require `--apply`. That flag records deliberate invocation, not an authenticated grant or proof of permissions.
- [Backup configuration](../templates/backup-config.example.json) is an incomplete non-secret example, never the pilot's configuration. Review the exact provider wrapper and field selectors privately. The helper is an infrastructure operator, **not** an agent credential resolver, item reader or caller-authentication service.
- [Agent-access preflight](../scripts/agent_access_preflight.py) validates an exact disabled policy and optionally checks only CLI status in a protected dedicated app-data directory. It cannot create accounts/grants, unlock/sync or consume credentials. It always exits blocked for secret use.
- [Signup stylesheet](../templates/user.vaultwarden.scss.hbs) uses the application's native template mechanism, not a patched JavaScript bundle. It is only presentation; server registration policy remains the security boundary.

## Temporary administration and first-owner bootstrap

A closed deployment needs a separately authorized single-owner invitation bootstrap. Keep public signup/domain allowlist/ordinary invitations closed throughout. Generate temporary administration material in the protected process; do not preserve its value or verifier in notes, examples, scripts, logs or chat.

For the reviewed Coolify path, inline Argon2 dollar characters can be misinterpreted by Compose/environment parsing. Use a named variable reference and the controller's protected environment interface with literal handling (`is_literal=true`) when independently approved. This does not make the controller/host administrator unable to inspect that verifier. If policy forbids even controller-managed materialization of the verifier, stop and design another delivery path; never call it secret-free.

A controller HTTP 500 can leave partial state. Read back the exact resource and reconcile both Compose and environment state before another mutation. After the single invitation, return Compose to baseline, remove the temporary variable and persisted override, read back managed/runtime state, and prove administration is closed. An absent admin token can leave a disabled-banner page at `/admin`; require the disabled banner and denied administrative subroutes, not a guessed root status code.

An invitation is a pending placeholder, not a usable account, master-password definition, MFA, email delivery or authenticated client. SMTP disabled means no invitation email was sent. Direct web access may go to login; use the installed frontend's actual signup route for the invited account without opening public signup. Human password/MFA/recovery stays on the protected human interface. Account initialization and invitation consumption can be checked with boolean-only metadata; do not retrieve password hashes or vault items to prove these states.

## Close the screen as well as the API

`settings.disableUserRegistration` in the public API configuration is nested under `settings`. Do not query only a top-level property. Effective environment and persisted overrides must also be checked. Disabling Bitwarden Secrets Manager configuration says nothing about the password-manager CLI/native autofill backend.

A frontend may hide the signup link while its direct signup/register route still renders a form. When the owner requires screen closure, inspect the current DOM and existing customizations first. Under a specifically authorized write, add/merge the native user stylesheet at `/data/templates/scss/user.vaultwarden.scss.hbs`, preserving unrelated styles. Template loading may require a recreation of the owned Vaultwarden workload through its controller; do not restart shared ingress or the Hermes gateway.

The supplied selectors were exercised against web-vault 2026.7.0: registration-start/finish forms are hidden, a Portuguese closure notice appears, the existing login link remains and login inputs are unaffected. Revalidate selectors at every frontend upgrade. They are not a route redirect, an API restriction or a guarantee that all future registration components match.

Use the [fresh-browser verifier](../scripts/verify_signup_ui.py) with a separately installed pinned Playwright/browser. It accepts bounded non-secret configuration on stdin (server origin and optional browser executable), never credentials or browser-profile paths. `--synthetic` uses explicitly synthetic DOM plus the stylesheet, while `--live` checks the real server without injecting replacement CSS; the outputs distinguish them. Use a fresh unauthenticated headless browser, not a locked human profile or unrelated CDP lease. Verify the actual deployed stylesheet, zero visible forms/inputs on signup and its register alias, closure notice, functioning login link, and unchanged visible login form. Source-string/CSS parse checks alone do not prove UI behavior. If no browser is available, preserve a UI-validation gate rather than reporting completion.

## Consistent encrypted recovery candidate

The candidate coordinates exactly one managed workload through supported controller stop/start operations, using non-mutating lifecycle method checks before applying. Treat failed Docker inventory as unknown, not an absent/stopped writer. Verify encrypted mount identity separately from a marker or a different filesystem device; the marker/dev check in this helper is secondary and cannot by itself prove LUKS/key custody.

After quiescence, the snapshot uses SQLite Online Backup API and collects required files with an exact image/member/size/checksum manifest. It excludes only declared ephemeral state, rejects symlinks/hardlinks and source changes, streams directly to `age`, and resumes the exact workload in a failure path before publishing. Signing state, attachments, Sends, configuration and native user styles belong to the recovery unit. A consistent database alone is not a full backup.

Publication uses immutable ciphertext, then full remote byte readback and checksum comparison. A filename/listing or provider checksum alone is insufficient. No prune/retention deletion is enabled. Local reports containing deployment paths/destinations remain protected; only fixed summaries go to the caller.

Restoration downloads ciphertext again, authenticates decryption using independent custody, validates the full gzip stream/CRC and TAR/PAX structure under bounds, and checks exact manifest members and hashes before extraction. Reject traversal, duplicate members, implicit-parent collisions, links/devices, malformed sizes/trailers, concatenated gzip and malicious/invalid SQLite schemas. Validate WAL-format serialized databases using a copy with rollback-mode header bytes; never modify the bytes preserved in the archive or restored snapshot.

Restore only into fresh owned encrypted storage. Read back non-root/read-only root/no-capability/no-host-port/`network=none` fixture isolation, health, database integrity and representative synthetic file integrity. Cleanup checks exact fixture ownership and readback of absence. A healthy restored zero-user snapshot proves infrastructure recovery, not recovery of a human account/MFA/client or production data. Representative authorized account/client recovery remains its own acceptance gate.

### Review limits of the generalized candidate

The synthetic suite exercises archive rejection, actual SQLite/WAL validation, real age encryption, bounded owned-child reads and exact-workload recovery branches with explicitly injected controller fixtures. It is not a new live Coolify/SSH/Drive restore, a reapproval of the credential wrapper or an adversarial whole-process-tree safety proof. Some operator commands still capture output in trusted process memory; no arbitrary untrusted command execution is authorized. A stronger supervisor, protected configuration/credential-provider review and representative recovery evidence are required before deploying this portable helper elsewhere. The existing operational deployment is not automatically replaced by this source.

## Native scheduler and quota failure

A direct successful backup is not acceptance of the native scheduler. Test the actual engine with no model inference, private local delivery and explicit executable/configuration paths after installation approval. Check the engine exit code **and** artifact publication/readback, healthy source recovery and failure reporting. A read-only preflight only proves prerequisites, not the scheduled operation.

The pilot's direct encrypted backup and isolated restore were verified. A subsequent native-engine canary generated new ciphertext and restored source health but failed remote upload with Drive HTTP 403 `RATE_LIMIT_EXCEEDED` (queries/requests per minute). A bounded rate-limited re-upload of the existing ciphertext also failed. The new ciphertext has no verified remote readback; it is not interchangeable with the earlier verified snapshot. The daily job remains paused. Do not change OAuth, rotate accounts, switch remote, repeatedly quiesce the source or enable the schedule to mask this gate.

Before enabling recurring operation, resolve the actual quota/provider boundary, test the real engine once under authorization, verify the exact newly published ciphertext in full, and read back the exact schedule state. Alert destination/contents and retention actions are separately authorized. The recovery key must not depend on the failed vault/host.

## Acceptance recorded separately

Keep private evidence for source checks, effective hardening/encryption, deployment/ingress, initialized owner, consumed invitation, signup UI closure, human MFA/recovery, authenticated human/native clients, direct backup, full remote check, isolated representative restore, native engine, schedule, and per-agent authorization. Do not collapse them into a single production-ready flag.

The pilot completed deployment and owner initialization/UI closure. MFA/recovery/native-client acceptance, recurring recovery and agent credential execution remain pending. No agent enrollment or shared secret distribution is inferred from any of the completed infrastructure/source steps.

## Primary references

- Vaultwarden native styles and template reload: https://github.com/dani-garcia/vaultwarden/blob/1.37.4/src/api/web.rs
- Vaultwarden account/invitation flow: https://github.com/dani-garcia/vaultwarden/blob/1.37.4/src/api/core/accounts.rs
- Vaultwarden configuration: https://github.com/dani-garcia/vaultwarden/blob/1.37.4/src/config.rs
- Bitwarden CLI status and app-data scope: https://bitwarden.com/help/cli/
- SQLite WAL/deserialize boundary: https://www.sqlite.org/c3ref/deserialize.html

Exact versions above document the exercised contracts, not a recommendation to deploy an old release without a fresh upstream/security review.
