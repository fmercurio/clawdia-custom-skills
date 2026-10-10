# Private executor next slice: source-only preparation

**Status: proposed, not implemented.** This is a bounded implementation/review contract, not a new CLI or API, connector, runtime installer or permission to use a vault. The package remains a candidate; metadata-only preflight remains blocked. No enrollment, real grant, credential read or installation follows from this document; no runtime activation is authorized.

Read [the current synthetic core](private-consumer-core.md), [rollout](agent-access-rollout.md), [Hermes boundaries](hermes-integration.md) and [new-instance onboarding](new-instance-onboarding.md) first. Inspect the exact installed runtime and existing approved connector before deciding another adapter is needed. Source presence does not establish installation, session availability, authority or destination permission; unknown remains unknown. Discovery must not unlock/read a human vault or change another profile.

## 1. Current evidence versus missing runtime proof

The unchanged [core](../scripts/private_consumer_core.py) and [core tests](../tests/test_private_consumer_core.py) provide a useful private composition, not an OS isolation boundary:

- `Authority.claim()` provides exclusive nonce admission through the private ledger. This is replay protection for one grant, not cross-process admission for distinct grants using the same provider/account state.
- `Executor._busy` rejects a second call on that executor. Separate executors can overlap independent valid grants; injected providers can model separate private sessions while the parent remains locked. Production custody needs admission keyed to the actual shared provider/account resource, not merely a Python object or profile label.
- `Authority.validate()` rejects expiry/revocation again immediately before dispatch. Grant expiry is not cancellation: a synchronous provider acquisition can remain pending until it returns. Correct rejection after return does not prove a hard deadline during acquisition, network/DNS work or cleanup.
- Successful provider context exit and final `parent_locked() is True` gate the current fixed result. They are not native process qualification: the synthetic core does not launch, kill, wait or attest CLI descendants.
- HTTPS loopback tests exercise actual TLS and fixed readback, but not a production origin, egress policy, dedicated Bitwarden account, credential custody or recovery.

Bounded event-controlled thread probes can demonstrate the first three distinctions without a vault. Record only fixed outcomes/counters; release and join every owned thread in `finally`. Such probes characterize documented promotion blockers, not a new source regression, native descendant qualification or independent security approval. Keep exact-revision execution evidence outside public sources.

## 2. Interface choices and recommended boundary

1. **Model-facing field retrieval — reject.** A tool that returns an item/password/token and expects later redaction violates private consumption. Neither a narrow-looking selector nor final-answer masking repairs model-visible disclosure.
2. **Private worker facade — recommended next boundary.** A model-facing request refers only to a previously approved operation, never an arbitrary origin/command/item selector or grant/proof/key. An authenticated private host path resolves the fixed scope and composes the core, supervisor and consumer. Return only allowlisted bounded booleans/enums/fixed codes. The facade is a proposal, not a registered Hermes/MCP tool in this package.
3. **Long-lived shared broker — defer to separate architecture/review.** Broader decrypted visibility, shared caller custody and revocation increase the trust surface. Do not build or activate it as a fallback for failed worker isolation or enrollment.

Choose the private worker facade for the first implementation slice, with a synthetic provider only. Require private caller/issuer custody and a distinct OS identity for any later operational installation; same-OS-user profiles are not process-security isolation. Do not expose `Authority`, `Grant`, caller proof or provider construction as agent-controlled tool parameters.

## 3. Proposed bounded implementation slice

Implement the admission/supervision lifecycle against owned synthetic worker fixtures before adding any vault adapter. Preserve the current core gates and disabled preflight; any core/interface change needs its own exact-tree review and regression coverage. The initial slice has **no vault backend**, `bw` invocation, account enrollment, persistent key service, socket listener, MCP registration, installer, gateway restart, grants or real destination.

Required state ownership:

- Freeze scope/approved consumer in trusted private configuration; authenticate before provider status, unlock, lookup or external work. Unknown identity/scope/permission fails closed.
- Acquire cross-process admission for the shared provider resource, not just one executor. Prove exclusive ownership across distinct instances/processes; preserve the owner through startup, execution and cleanup. An atomic nonce marker cannot substitute for this lock.
- Start one fixed reviewed synthetic worker entry point with isolated private state and minimal allowlisted environment. No arbitrary shell, inherited session/password/proxies, borrowed human caches, tracing, core dumps or credential-bearing argv.
- Supervise a monotonic hard operation deadline and a separately bounded cleanup budget. Authorization expiry/revocation forbids later dispatch, but must not leave waiting/acquisition/cleanup indefinitely alive. Offloading a blocking call or canceling its awaiting coroutine does not terminate that native work.
- Terminate and wait **all descendants** on failure, timeout, cancellation and leader exit, including repeated cancellation during cleanup. Qualify the selected OS containment mechanism; a leader PID or process-group-only assertion is not a whole-descendant proof when a child can escape it. Do not silently substitute weaker containment when the qualified mechanism is absent.
- Keep admission owned until the worker boundary is actually empty and private state is discarded. Verify exact parent locked without inherited session material. Cleanup uncertainty quarantines the resource and blocks a successor; a returning coroutine or absent leader is insufficient.
- Promote success only after downstream readback, successful teardown, empty containment, discarded private state and final parent-lock verification. An uncertain external effect remains uncertain: no automatic retry or alternate provider. Reconciliation requires a separately approved exact-target path.

Linux cgroup v2 documents whole-tree termination through `cgroup.kill`; this is a candidate mechanism to investigate, not an implementation, deployment decision or local macOS qualification. Verify kernel/controller permissions and containment/escape behavior in the eventual separately authorized target. No privileged host lifecycle action is authorized by this source contract.

## 4. Acceptance matrix before operational promotion

Keep each criterion pending until the exact implementation tree and native execution supply evidence:

- **Admission:** distinct executors/processes, shared resource and different valid grants; canceled waiter cannot acquire an orphaned lock; canceled startup cannot overlap a successor; release cannot remove another owner's lease/lock.
- **Deadline:** blocked provider acquisition, stalled response, DNS/startup hang and stalled teardown are bounded by the selected worker supervisor. Test cold startup separately from in-flight timeout. Expired/revoked grants never dispatch after acquisition resumes.
- **Descendants:** leader exits first, child forks, attempted escape, repeated cancellation and cleanup interruption. Require actual PID/containment evidence, termination/wait and no later request. Missing native mechanisms are blocked, not silently skipped.
- **Private state:** unique owned non-symlink state with trusted ancestry, no copied human cache, no parent/consumer session inheritance and no durable unlock material. Test the real chosen transport/worker/error surfaces with explicitly synthetic canaries.
- **Results:** bounded allowlisted schema; no fields, raw item/status JSON, headers, response content, exception text, grants/proofs/keys or identity details in model-visible results. Teardown failure cannot emit verified success even when a parent probe says locked.
- **Identity and destination:** actual authenticated caller, private custody, exact approved account/item/collection/permission and canonical method/origin/resource/readback. Strings/profile names and synthetic visibility sets are not live evidence.
- **Restart and revocation:** fresh issuer/caller custody, durable replay rejection, no distributed-revocation claim from process-local state, and conservative handling of already-started external effects. No automatic replay after restart or uncertainty.
- **Governance:** independent security review of the final exact tree, source approval, named-host/profile installation approval, protected enrollment/MFA/recovery, scoped real grant and supervised pilot are separate gates. Source tests and CI cannot close them.

Documentation regression tests verify discoverability, public neutrality and these distinctions; they do not implement or qualify the proposed supervisor. Preserve the [source-only acceptance ledger](../README.md) and explicitly mark native, account, transport and live-pilot evidence pending.

## 5. Owner handoff and stop conditions

Source review, synthetic experiments, documentation/tests and draft publication can proceed without a new login or secret. Stop before choosing or mutating a runtime host/profile, connecting an unreviewed connector, enrolling an account, issuing real grants, deploying a listener/service or consuming a real field. Request only the missing non-secret decisions through the proper approval gate; enrollment/MFA stays in the protected interactive flow, never chat.

The later operator-local decision ledger must name the runtime/OS containment target, private caller/issuer custodian, dedicated least-visibility account, exact collection/item/field, one read-only HTTPS operation, recovery custodian and rollback. Do not infer these values from old session state, a loaded skill, a green check or approval to continue source work.

## Primary sources to re-check at implementation time

- [Hermes MCP integration and tool-result surface](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp).
- [Bitwarden Password Manager CLI: account state, session and sync contracts](https://bitwarden.com/help/cli/).
- [Linux cgroup v2: upstream lifecycle and whole-tree termination contract](https://github.com/torvalds/linux/blob/master/Documentation/admin-guide/cgroup-v2.rst).

These references inform the boundary; they do not attest the selected installed revision, host permissions, account state or operational readiness.
