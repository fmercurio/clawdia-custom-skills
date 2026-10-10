# Dedicated-agent access: staged implementation, not global sharing

This roadmap is the next implementation slice. The shipped [preflight](../scripts/agent_access_preflight.py) is executable metadata validation, **not a secret executor**. It always reports blocked even if policy shape and CLI status match. No daemon, MCP secret reader, autofill grant, account enrollment or runtime distribution is implemented by publishing this package.

## Do not conflate the access paths

1. **Infrastructure operator:** controller/SSH/recovery custody can administer the service or back up encrypted payloads. It does not authenticate to or decrypt the user's password-manager vault. Privileged host administrators remain a separate trust concern.
2. **Secrets Manager source:** `secrets.bitwarden` belongs to Bitwarden Secrets Manager (`bws`), not the password-manager CLI (`bw`). Its disabled setting neither proves `bw` is disabled nor configures Vaultwarden as a Secrets Manager endpoint.
3. **Native browser password-manager backend:** the installed Hermes backend can autodetect an installed `bw` CLI unless explicitly opted out. Installation/autodetection, status, per-session unlock, origin-bound handles and an authenticated target login are different states. Do not assume that setting a Secrets Manager flag controls autofill. A broad human account unlocked for this backend does not satisfy the dedicated narrow worker contract.
4. **Dedicated exact-item worker:** requires separate account visibility, isolated state, genuine caller authentication, a valid per-operation grant, a fixed private consumer and verified cleanup. It must not return passwords/tokens into model-visible tools.
5. **Shared broker:** a different architecture with decrypted shared visibility and caller authentication/revocation requirements. It is not an automatic workaround for the worker gates.

Audit the exact installed runtime and approved connector before building another. Use current official Hermes docs and the selected runtime source. A newly spawned interpreter cannot establish another process's in-memory unlock state. A default-scope `bw status` cannot prove every profile/session is unauthenticated. Profiles running under the same OS user do not provide a process-security boundary; a profile string is not authenticated identity.

## Pilot before widening

Start with one separately enrolled dedicated service account, one profile/caller, one collection exposing only the exact pilot item and one fixed read-only HTTPS API operation. The human owner creates/approves the organization/collection membership and account credentials through a secure interactive path; no master password, MFA or recovery code belongs in chat. Confirm the proposed dedicated identity with the owner before issuing an invitation. Do not reuse the human owner's unlocked session or presume a new account/grant already exists.

Record in protected operator context:

- service-account identity and exact canonical vault origin;
- account and collection visibility/permission evidence (no broad human/shared vault exposure);
- exact literal item ID, minimal field, fixed target/resource/action and private consumer;
- caller authentication method, expiry, issuance/revocation custody and operation authorization;
- independent recovery/enrollment flow and each required runtime installation/lifecycle approval.

Only after pilot acceptance can additional profiles be considered through separate scopes and revocation tests. There is no wildcard/all-profiles default and no automatic availability in old sessions. Installing source or a tool is not granting it authority.

## Executable preflight

The [example policy](../templates/agent-access-policy.example.json) uses an explicitly synthetic item ID, a reserved origin, disabled access and expired authorization. Never populate or commit it with live deployment/account/item/profile details. Store the actual policy privately and make a protected dedicated CLI app-data directory before an approved status probe; do not copy an existing human cache.

```sh
# Offline schema/expiry check; expected exit 2 and blocked outcome.
python3 -B skills/devops/vaultwarden-operations/scripts/agent_access_preflight.py \
  --policy skills/devops/vaultwarden-operations/templates/agent-access-policy.example.json
```

For separately approved metadata discovery, pass only the protected policy file with `--probe-cli`. The program requires private file/directory ownership and permissions, rejects symlink state ancestry/default human directories, discards inherited session/password/proxy environment, and invokes only `bw status --nointeraction` in the configured dedicated state. Status can create provider bookkeeping/cache files within that private CLI directory; this is not a vault/account/secret mutation. Do not point the probe at an existing human session. A missing state/unauthenticated account is an enrollment gate, not permission to log in automatically.

The bounded process reader accounts for stdout **and** stderr before JSON parsing, kills/waits the owned metadata child on error/timeout and never replays raw status/identity or errors. These tests cover that child, not every possible adversarial descendant or credential-bearing executor. Report only shape/expiry/status/identity-match/parent-lock booleans and fixed blocking codes. Caller authentication, destination permissions and private executor remain pending; neither configured profile names nor CLI `locked` prove them.

## Synthetic private-consumer security core

A [source-only core](private-consumer-core.md) now exercises signed caller proof, expiring exact-scope grants, atomic single-use admission and private fixed HTTPS consumption against a synthetic provider. It has no CLI/vault adapter, secure enrollment, private transport or installed runtime. Do not enable the existing preflight based on these tests. Actual Bitwarden identity/visibility, caller-key custody, worker isolation/all-descendant cleanup, cross-process provider locks and production destination approval remain blockers.

## Runtime executor still required

Implement and independently review the worker/private consumer as a separate security slice, preserving the matrix in [Hermes integration](hermes-integration.md). Start with the [proposed source-only admission/supervision slice](private-executor-next-slice.md), not a real vault adapter; its contract and documentary regressions do not implement or qualify native cleanup:

- bind a real authenticated caller and non-forgeable, operation-specific expiring grant; authenticate before any unlock or external action;
- enroll a least-visibility service identity, isolate CLI app-data/cache and verify exact parent `locked` without inherited session; `unauthenticated` is not parent-lock acceptance;
- `bw sync` is account-scoped, not per-item. Reject unrelated visible items/collections instead of claiming selective decryption;
- unlock/resolve the literal item and consume indispensable fields privately through one fixed HTTPS target/action; no arbitrary shell, export, list, raw JSON, clipboard or password-returning MCP;
- bind destination permission/origin and validate downstream readback without exposing content/credentials;
- supervise all descendants and cleanup under failure, timeout, repeated cancellation and leader exit; keep session material away from the consumer/parent;
- audit/revoke grants, test wrong caller/profile/item/origin/expiry, preserve `unknown` permissions and reconcile uncertain external effects;
- prove canary non-disclosure through real executor/transport/error paths and final parent-lock/cleanup before any real credential use.

Never promote the metadata-only preflight into an operational broker by changing its blocked exit to success. MFA/recovery/client acceptance and the recurring offsite-recovery gate still apply before real credential migration. Using only synthetic pilot items is not evidence of production readiness.

## Decision gate for the owner

Before enrollment/apply, obtain the dedicated service-account email and the first authorized profile/collection/item/operation, plus secure enrollment and runtime-installation approval. If missing, complete source/code/test publication but leave account/grants/runtime blocked. Do not infer these choices from approval to document implementations or to move the access project forward.

## Primary sources

- Hermes authoritative docs: https://hermes-agent.nousresearch.com/docs/
- Bitwarden CLI status, session, app-data isolation and sync: https://bitwarden.com/help/cli/
- Vaultwarden service documentation and limitations: https://github.com/dani-garcia/vaultwarden/wiki

Native browser-backend behavior must also be checked in the exact installed revision. Upstream documentation describing a capability is not evidence that a specific local session/account has it enabled.
