# Hermes integration: discovery, custody and authority

This is a neutral procedural contract, not a credential executor, a broker implementation or a runtime approval. Preserve every worker gate in [implementation](vaultwarden-implementation.md). Installing or merging this package does not create grants, authenticate a profile, enroll agents or share a human vault.

## 1. Capability discovery

Perform narrowly authorized metadata-only discovery before concluding that a connector is absent. Record these states separately, with evidence or `unknown`:

1. **Package:** not shipped by the package, or present in its verified manifest.
2. **Environment:** installed and independently reviewed at a known revision. Code presence alone proves neither review nor readiness.
3. **Session:** loaded in this session and available to the actual caller; a declared configuration is not a loaded tool.
4. **Authority:** active operation-specific grant with exact scope, expiry and required owner confirmation.
5. **Destination:** effective destination permissions, if an authorized read can actually establish them.

Look for an existing approved connector **and its private consumer** before requesting another bootstrap or inventing a wrapper. Discovery does not activate grants, unlock/sync the vault, fetch secret fields, enumerate unrelated items or issue an external operation. Return minimal metadata; an entire tool/configuration inventory is not implied by discovery permission.

An account-scoped CLI worker and a shared broker are not interchangeable. A broker is a different trust boundary: shared decrypted visibility, server credentials, caller authentication and revocation require their own review. Neither command filtering nor item selection makes broad account decryption item-scoped. Do not relax the dedicated-account, isolated-state, parent-lock or descendant-cleanup gates to accommodate a broker.

Acceptance: each layer is independently `verified`, `absent`, `denied`, `pending` or `unknown`; no missing layer is silently filled by another profile, a new grant or an ad hoc consumer.

## 2. Model-visible results

The exposure prohibition explicitly covers MCP and other model-visible tool results, in addition to stdout, stderr, chat, logs, tracing, exceptions and persisted history.

A metadata search or field-presence check is not permission to fetch a password, token, OTP or secret note into a tool response and pass it to another command. Later redacting the final answer does not undo disclosure already delivered to the model. Do not use raw item JSON or note text as a generic field fallback.

The reviewed private adapter must resolve and consume indispensable fields within the authorized boundary, for the fixed external operation, and return only bounded sanitized outcomes. Unlock/session material stays separate from the consumer. Exact IDs, titles, account/server details and unnecessary metadata remain in protected operational context, not diagnostic output.

Acceptance: synthetic canaries placed in fields, error messages, downstream output and cancellation paths never reach model-facing results; the fixed schema contains only allowed booleans/enums/codes. These are executor tests, not assertions this document can prove.

## 3. Four-layer writer diagnosis

Diagnose write capability in four distinct layers:

- **Owner:** owner authorization covers this precise write and destination, not merely reading a secret.
- **Implementation:** a reviewed installed writer exists at the required revision and is available through the approved private path.
- **Grant:** a valid active grant covers this operation, caller, target and expiry without borrowing another identity.
- **Destination:** effective collection permissions actually permit the requested mutation.

A read-only MCP does not prove there is no approved private writer. A generic sanitized denial does not prove missing editor access. Metadata lacking access flags means unknown is not denied. Preserve uncertainty; do not request global administrator access or broaden sharing to compensate for an unproven diagnosis.

Reuse an existing authorization only if still valid and within its original scope. Verify the private persistence path and exact destination **before issuing an external credential**. In a two-system operation, define persistence, external issuance and failure reconciliation before either write. If a response is uncertain, reconcile the exact targets via authorized reads before another mutation; do not repeat issuance, rotation or deletion automatically. A successful write call is not persisted-state evidence.

Acceptance: failures identify the unverified layer without guessing permissions; ambiguous outcomes preserve ownership and reconcile once through exact-target readback rather than producing duplicate credentials or widened grants.

## 4. Browser autofill

Distinguish **item found**, **origin-bound handle available** and **confirmed login**. A vault item identifier is not a browser handle. A missing handle does not establish that the item is absent.

Autofill requires the exact origin, actual browser backend, correct handle and approved browser identity/session. Use the protected autofill operation; do not ferry a password via MCP to text input, JavaScript or screen control. Do not duplicate a credential into another vault silently. MFA and reCAPTCHA use the appropriate protected prompt or human device flow; never request a code in chat.

A browser integration failure does not block an independent CLI/API operation if its own reviewed adapter and valid grant are available. It also does not authorize a browser/profile switch or credential migration.

Acceptance: wrong origin/backend/handle fails before any fill; login is verified from the destination after filling. Merely locating the item or clicking a button is not a successful login.

## 5. Profiles and sessions

Confirm real caller identity, the actual selected profile, narrowly relevant managed configuration and tools loaded into the running session without printing whole environments/configuration files.

A profile selector is policy context, not caller authentication and not privileged-process isolation. Do not declare a different profile to use another profile's grant. MCP discovery proves neither authentication to a vault nor visibility of an item, autofill or writer authority.

An old session may not expose newly installed tooling. Mark availability pending; do not reset conversations, enable prohibited tools, copy credentials, reuse another identity or restart services automatically as a consequence of discovery. A separate runtime-change grant is necessary for configuration or lifecycle changes.

Acceptance: identity and grant checks bind the actual caller/session; stale availability is reported independently from auth/permissions and does not trigger unapproved recovery actions.

## 6. Executor acceptance matrix

The integration-contract tests are **offline/documentary, not runtime safety proof**. Candidate infrastructure/preflight tests also exercise isolated synthetic SQLite/age/metadata children, not an agent credential executor. See [operational learnings](operational-learnings.md) and [agent-access rollout](agent-access-rollout.md). Before any future executor is approved, its owning component must independently exercise the implementation and preserve failed evidence:

| Case | Required observable result |
|---|---|
| duplicate JSON keys; invalid policy types | Reject the policy before a grant or side effect; no first/last-key ambiguity or type coercion. |
| Cancellation before and after spawn | No late dispatch/grant; supervisor owns and waits for every already-created descendant. |
| Worker leader has exited while a descendant holds a secret | Cleanup still finds/terminates/waits for the descendant; leader exit alone cannot mark cleanup successful. |
| Oversized stdout/stderr | Bound capture before field selection; do not parse/select after unbounded allocation. |
| wrong autofill backend/origin/handle | Reject before fill; never transfer secret text or switch browser identity. |
| unknown grant or permission | Preserve unknown and refuse the write without requesting broader access. |
| uncertain write response | Reconcile exact persisted state before retry; no duplicate issuance/rotation/deletion. |
| Slow CLI cold start and transport timeout | Deterministic fixtures separate startup budget from transport timeout; require the real request and owned child before asserting transport cancellation. |
| Cleanup or final parent-lock failure | No success, no further operation until reviewed; all descendants and final parent state verified. |

Retain the initial failure and causal fixture observations; do not rerun until green, remove assertions, increase production deadlines or present source-string tests as execution proof. Test fixture servers must release bounded waits and join all owned handlers during teardown.

## Public source boundary

Keep actual origins, profile grants, item/collection IDs, host paths, recipients, account identities and private configuration out of this package. Execution records stay in protected operator context. Verify the exact selected Bitwarden CLI, browser backend and platform versions against official documentation before operational use.
