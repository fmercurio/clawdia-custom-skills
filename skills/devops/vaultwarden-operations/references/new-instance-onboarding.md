# New-instance onboarding: availability is not authority

This guide is the handoff for a new host or Hermes profile evaluating this **0.4.0 candidate**. It is source-only: no automatic enrollment, runtime installation, daemon/MCP registration, grant issuance or credential access is included. A copied repository, a merged PR and a loaded skill do not make the missing vault executor available.

Use the [operator handoff](../README.md), [integration boundaries](hermes-integration.md), [dedicated-access rollout](agent-access-rollout.md) and [core boundaries](private-consumer-core.md) together. Do not weaken the always-blocked preflight to make onboarding appear complete.

## 1. Establish five independent layers

Record a bounded private ledger for the exact host/profile/caller and operation:

- **Source:** exact checkout path and immutable commit, skill version/status, manifest and file inventory. Compare the selected remote ref and local HEAD; do not assume another clone was updated. Candidate code may be validated in isolation, but is not approved for operational installation.
- **Installation:** independently reviewed artifact actually installed in the approved target, with provenance and matching hashes. Existing approved procedural revisions do not approve these new helpers. A global skill and a deliberate profile overlay are different installations; do not replicate global skills or overwrite an overlay automatically.
- **Session:** the selected profile and actual running session expose the intended skill/tool/private adapter. Files, configuration and CLI discovery do not establish a live tool schema or a connected provider.
- **Authority:** genuine caller authentication plus an active, expiring, exact-operation owner grant. A profile name is policy context, not authenticated identity.
- **Destination:** account/item/collection visibility and effective permission for the fixed external origin/resource/action are independently established through the approved private path. Missing permission metadata stays `unknown`, not allowed or denied.

Use `verified`, `absent`, `denied`, `pending` or `unknown` per layer. Report `runtime_not_provisioned` when a required reviewed adapter/supervisor is missing. These are operator ledger labels, **not a new CLI or API** and not evidence that a provider was exercised.

Before any target action, the owner must confirm the actual target home/profile and scope. Metadata discovery may inspect the selected implementation/version/help and relevant artifact hashes; it must not unlock, sync, enumerate items or read credential fields. For an already authorized metadata inspection, verify commands against the installed CLI before using them:

```sh
hermes --version
hermes skills list --help
hermes tools list --help
hermes -p "$TARGET_PROFILE" skills list --enabled-only
hermes -p "$TARGET_PROFILE" tools list --platform "$TARGET_PLATFORM"
```

Keep unrelated inventory out of reports. These commands do not install or enable anything. Current upstream skill discovery can notify an open conversation on its next message; older builds may differ. Verify availability in the intended session instead of assuming a reset is always required. Tool configuration/lifecycle changes remain separately authorized: **no gateway restart**, reset, profile switch or tool enablement merely to satisfy discovery.

## 2. What this source actually supplies

- **CapRover/Coolify deployment:** reviewed procedural contracts and non-secret templates, not a provisioned service. Choose one supported platform path; require exact-target approval, immutable image, encrypted mounted storage, effective policy, TLS and independent recovery before apply.
- **Backup/recovery:** [scripts/backup.py](../scripts/backup.py) is candidate code with a default check and explicit mutation gates. Its synthetic archive/SQLite/WAL/encryption tests do not establish a real off-host backup, restore drill or recurring scheduler.
- **Signup UI:** [scripts/verify_signup_ui.py](../scripts/verify_signup_ui.py) and the native stylesheet address visible screen closure. A live browser check requires its separately installed Playwright/browser dependencies and approved exact origin; use an isolated browser, not a human profile. Service health or data normalization is not UI acceptance.
- **Dedicated-account discovery:** [scripts/agent_access_preflight.py](../scripts/agent_access_preflight.py) validates policy metadata and, only with an approved `--probe-cli`, a protected dedicated CLI status. It is **always blocked** for secret use, including when metadata matches. It performs no enrollment, login, unlock, sync, field read or grant issuance.
- **Private-consumer core:** [scripts/private_consumer_core.py](../scripts/private_consumer_core.py) is an importable synthetic security library, not a command-line broker. Signed proofs, expiry, exact destination binding, replay protection and cleanup are exercised against a synthetic provider and real loopback TLS. There is no production Bitwarden adapter, private transport, key custodian, all-descendant supervisor or runtime installer.
- **Real agent access:** not supplied. Browser autofill, password-manager `bw`, Secrets Manager `bws` and a dedicated private executor are separate paths. Do not configure `secrets.bitwarden`, unlock a human backend or borrow another profile's grant to compensate for missing runtime.

## 3. Reproduce the source gate before proposing installation

Prerequisites belong to an **isolated validation environment**, not an automatic production bootstrap:

- Python 3.12 with SQLite `Connection.serialize` support; do not use an incompatible system interpreter just because it is on PATH.
- An external-to-checkout validation venv with the dependencies in the repository's `requirements-dev.txt`. Its pinned direct dependencies do not pin every transitive dependency.
- A verified `actionlint` **1.7.12** binary for the validation host, selected explicitly through `ACTIONLINT_BIN` or on PATH. Follow the pinned/checksummed workflow-validator instructions in the repository's `CONTRIBUTING.md`; do not use a different version or silently download a fallback. Repository tooling tests require this dependency, not only the final workflow lint.
- `openssl` for the real synthetic TLS fixture; `age` and `age-keygen` for both encryption subprocess tests. Missing required dependencies are blockers, not successful skips.
- An owned `0700`, non-symlink scratch directory and an **isolated HOME**, with fixture TMPDIR as a sibling outside that HOME and outside the repository. Every actual ancestor must be root/operator-owned and must not be writable by group/others. A `0700` leaf below a public or sticky temporary ancestor such as `/tmp` is still rejected. Set `VW_TEST_SCRATCH` explicitly for local runs. Do not use an operational Hermes home or human CLI state as a fixture.
- Fresh source manifest/file inventory and generated catalog. Hash verification is integrity evidence, not a digital signature or permission to install.

The private-core tests use explicit `VW_TEST_SCRATCH` first and otherwise the isolated fixture `HOME`, never the checkout or ambient `TMPDIR`. The selected path is preserved literally; a symlink is not normalized into an acceptable target. Neither the name `HOME` nor a private leaf proves trusted ancestry: the unchanged core checks the real directory-FD chain. An unsafe explicit scratch is rejected, not replaced by a convenient fallback. Do not chmod shared runner, checkout or system-temp ancestors to make a test pass; select an already trusted, operator-owned validation namespace or stop at the fixture prerequisite.

The catalog CI harness creates a fresh `0700` namespace beneath the disposable CI runner's `HOME`, validates its ancestry with the unchanged core before preparing isolated sibling HOME/TMPDIR fixtures, explicitly passes `VW_TEST_SCRATCH`, and removes only that owned namespace on exit. Controlled permissive-ancestor regressions remain fenced inside an outer `0700` fixture and exercise the actual core/test bytes. These are synthetic filesystem/TLS checks, not vault access or an operational enrollment path.

From the repository root, with the validation interpreter and already-approved fixture paths set:

```sh
set -eu
: "${VALIDATION_PYTHON:?select the external Python 3.12 venv}"
: "${FIXTURE_HOME:?select the owned isolated fixture HOME}"
: "${FIXTURE_TMPDIR:?select owned scratch outside fixture HOME and checkout}"
: "${ACTIONLINT_BIN:?select the verified actionlint 1.7.12 binary}"

run_source_check() {
  env -u PYTHONPATH -u PYTHONHOME -u BW_SESSION \
    HOME="$FIXTURE_HOME" HERMES_HOME="$FIXTURE_HOME/.hermes" \
    TMPDIR="$FIXTURE_TMPDIR" VW_TEST_SCRATCH="$FIXTURE_TMPDIR" \
    ACTIONLINT_BIN="$ACTIONLINT_BIN" PYTHONDONTWRITEBYTECODE=1 \
    "$VALIDATION_PYTHON" -B "$@"
}

run_source_check -c 'import sys, sqlite3; assert sys.version_info[:2] == (3, 12); assert hasattr(sqlite3.Connection, "serialize")'
command -v openssl
command -v age
command -v age-keygen
"$ACTIONLINT_BIN" -version
"$ACTIONLINT_BIN" -oneline -shellcheck= -pyflakes=
(cd skills/devops/vaultwarden-operations && shasum -a 256 -c MANIFEST.sha256)
run_source_check -m unittest discover -s skills/devops/vaultwarden-operations/tests -p 'test_*.py' -v
run_source_check -m unittest discover -s tools/tests -p 'test_*.py' -v
run_source_check -m unittest skills/research/llm-wiki/tests/test_validate_staging.py -v
run_source_check -m unittest discover -s tools/skill_deploy/tests -p 'test_*.py' -v
run_source_check tools/generate_catalog.py --check
run_source_check tools/validate_skill.py skills/devops/vaultwarden-operations/SKILL.md
git diff --check
```

Require **no skips**, successful suite summaries, complete manifest/file-inventory checks and no failed intermediate command. Review the final tracked diff, including staged/new files: plain `git diff --check` alone does not check untracked additions. Run the pinned workflow semantic checker locally; after draft publication triggers CI, require the complete repository CI gates for that exact head before review/promotion acceptance. Publication alone is not acceptance. These source gates are **not live Vaultwarden E2E** and authorize **no credential access**.

The disabled [example policy](../templates/agent-access-policy.example.json) can also be exercised offline without a CLI probe:

```sh
# Expected exit 2; inspect the fixed JSON report, not merely the exit code.
"$VALIDATION_PYTHON" -B skills/devops/vaultwarden-operations/scripts/agent_access_preflight.py \
  --policy skills/devops/vaultwarden-operations/templates/agent-access-policy.example.json
```

Expected outcome: `status` is `blocked`, `agent_access_enabled` and `secret_executor_implemented` are false, and `private_executor_pending` remains a blocking code. The policy is disabled and expired by design. Do not edit it into an enabled/live public policy, add `--probe-cli` as an automatic retry or turn exit 2 into success.

## 4. Promotion and operational gates

1. **Source review:** independent security/governance review and maintainer approval of the exact revision. Keep candidate and pending security status until approved; earlier procedural approval cannot substitute. Review source publication/merge independently from target installation.
2. **Named target installation:** owner approval of the specific host, home and profile, reviewed artifacts, dependencies, configuration, overlay intent, rollback and runtime lifecycle. Use an independently reviewed installer; this package ships none. The repository deployment planner is read-only and its apply helpers are sandbox-only, not a real-runtime installer. Do not edit their safety checks or declare the candidate approved to force an installation.
3. **Infrastructure/human acceptance:** independently approve and verify platform configuration/deployment, first-owner bootstrap, MFA/native clients, collection permission/revocation, encrypted off-host recovery and a representative isolated restore drill before real data. A green health endpoint is not acceptance.
4. **Secure enrollment:** the owner chooses the dedicated account, collection, exact pilot item, minimal field, first caller/profile and fixed read-only HTTPS operation. Enroll through a protected interactive flow with independent MFA/recovery custody. No master password, OTP, recovery code, private ID or deployment details in public source/chat. There is no automatic enrollment and no reuse of a human CLI cache.
5. **Missing security implementation:** implement/review real provider identity and exact visibility, a distinct OS identity and private caller/key/transport custody, cross-process admission, hard deadlines and cancellation cleanup of **all descendants**. Profiles under the same OS user are not process isolation. Verify exact **parent locked** state without inherited session material; unauthenticated is not locked acceptance. Destination configuration is trusted private configuration, not agent request input.
6. **Supervised pilot acceptance:** synthetic negative-path/canary tests first, then a separately approved real exact-item/private-consumer pilot. Prove expiry/replay/wrong-caller/wrong-destination/unknown-permission rejection, revocation, bounded output, teardown on failure/timeout/repeated cancellation, exact parent lock and destination readback. No success before cleanup; do not return credentials into tool/model output. Preserve ambiguous external effects and do not retry automatically.
7. **Persistence/widening:** daemon/MCP registration, persistent services, gateway lifecycle, schedules, new profiles/collections/items and cleanup/deletion each require separate scope and readback. One pilot does not grant all profiles access. A manual smoke does not prove restart/reboot readiness.

The current source stops before gates 4–7 can be accepted as an implemented real agent path. Missing implementation is an engineering blocker, not a reason to ask for the owner's password or to relax the metadata preflight.

## 5. CI disagreement and handoff

For each check, record provider, exact head, check/job identity, completion status and its actual suite output separately. A green GitHub Actions job does not cancel a failed mirrored check, and source tests on one host do not diagnose another runner.

Obtain the **read-only build log** for the exact failed job and compare checkout revision, failed command/assertion, Python/SQLite support, TLS/encryption dependencies, fixture path ancestry and cleanup evidence. Those are comparison questions, not inferred causes. An HTTP access failure establishes only an observer/authentication block. Do not close a user's browser, change CI/permissions, rerun repeatedly or remove assertions to obtain a green result without approval.

If the log remains inaccessible, preserve that diagnosis blocker in the PR/acceptance ledger. A head with a failed check is not fully green; a later all-green head updates current CI status but does not explain or erase an earlier failure. Request a protected log export or an authorized read-only session, never a password/token in chat. Hand off verified source state, installed/session state or `unknown`, separate approvals, rollback and remaining blockers. Do not mark runtime or credential access complete.

## Primary references

- [Hermes skills discovery](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/)
- [Hermes tools and toolsets](https://hermes-agent.nousresearch.com/docs/user-guide/features/tools)
- [Bitwarden password-manager CLI](https://bitwarden.com/help/cli/)

Check the exact installed runtime/source and CLI help as well as current documentation. Upstream support is not proof that a particular target profile/session has that capability.
