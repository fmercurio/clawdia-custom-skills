# Private consumer core: source-only security slice

This is an executable **synthetic-core candidate**, not an operational Vaultwarden connector. [The core](../scripts/private_consumer_core.py) has no CLI, daemon, MCP registration, account enrollment, `bw` command, master-password source or runtime installer. Construction is private trusted-host code, not an agent-visible input surface. Access remains disabled by default; the existing metadata-only preflight still always blocks real secret use.

## Implemented and exercised

- A trusted operator issuer signs an exact caller/profile/item/collection/operation/destination-digest scope using HMAC-SHA-256. The destination digest binds GET, canonical host/port/path and expected readback to the grant; a mismatched consumer is rejected before acquiring the field. Independent per-caller keys authenticate the proof bound to that grant. A profile string alone authenticates nothing. Key issuance and custody are not supplied by this package.
- Grants last at most 60 seconds, reject future/expired timestamps and revoked callers, and are checked again after provider acquisition immediately before consumer dispatch.
- Protected directory-FD custody and exclusive, fsynced nonce markers provide fail-closed single use across authorities sharing the ledger. Markers contain no raw grant, token, identity or item payload; ambiguous filesystem failure burns/rejects authorization rather than retrying it.
- One executor serializes its own provider lifecycle. It rejects unknown permissions and visible-item/collection sets other than the exact approved pair. A synthetic provider verifies this interface in tests; these assertions are not real account visibility evidence.
- The fixed consumer performs one GET to a trusted configured HTTPS host/port/path, with verified certificate/hostname, no proxy-environment use, redirect following, retry, arbitrary command or returned response content. It accepts one restricted bearer field privately and compares a bounded response with a trusted synthetic SHA-256 expectation. No server content, token, raw exception, grant or key enters its fixed result.
- Provider teardown and an exact parent-lock boolean are required after acquisition. Consumer success inside a context manager is **not** acceptance until its exit succeeds. A teardown exception blocks even if the provider says it is locked.

The tests use generated synthetic signing keys, one explicitly fake bearer token, a synthetic provider and a real loopback TLS server. Whole-core tests exercise signed grant → caller proof → atomic claim → private provider → HTTPS Authorization header → body readback → teardown → fixed result. They also test replay after authority reconstruction, two-authority nonce races, incorrect scope/proof/signature, expiry/revocation during acquisition, unknown permissions, excess visibility, busy admission, interruptions, cleanup faults, TLS rejection, redirects, response canaries and body limits.

## Explicit non-goals and promotion blockers

1. **Real service account:** enrollment, master password, MFA/recovery, native-client acceptance and org/collection grants remain operator-controlled and separately authorized. No real vault is contacted by this module or these tests.
2. **Private transport and caller custody:** there is no authenticated Unix-socket/MCP adapter or issuer tool. Never send a grant/proof/caller key to a model-visible tool, chat or command-line argument. Per-caller keys must not be shared between identities. Private custody and a distinct OS identity must be reviewed before installation; same-OS-user profiles are not a process-security boundary.
3. **Vault provider:** `open_exact()` is an injected *trusted* interface, not a security sandbox. No production implementation ships. A real adapter must verify actual dedicated account/server identity, visibility, field permissions and locked parent state, without borrowing human caches or exposing unlock/session material. Provider code can observe a token, so it belongs inside the private boundary.
4. **Descendants and hard deadlines:** the synthetic core does not launch CLI children. It does not implement all-descendant cleanup, process-level cancellation, repeated-interruption supervision, DNS hard deadlines or zeroization of immutable Python strings. Socket timeouts and synchronous context cleanup are not substitutes. These are required in the worker/transport slice before a real CLI adapter can be approved.
5. **Revocation and restart:** caller revocation is process-local. Restart the authority with fresh issuer/caller keys; this library is not a distributed revocation or persistent-key service. The durable ledger proves replay rejection, not distributed permission revocation. Revocation after the final pre-dispatch check cannot undo an already-started request; external ambiguity is reported and never auto-retried.
6. **Destination approval:** the constructor's host/port/path/readback are trusted private configuration, never request parameters. A real destination/resource/action must be explicitly chosen and approved. Production DNS/egress policy and certificate trust need independent verification. The loopback test destination is not a production grant.
7. **Cross-instance concurrency:** atomic nonce claims prevent one grant being reused; they do not serialize unrelated grants across separate executors or shared providers. Production custody must have its own cross-process admission lock.
8. **No production readiness:** source tests, publication, review or merge do not grant enrollment, installation, runtime activation or real credential access. Backup/MFA/recovery gates still apply.

## Verification

Use a real owned scratch directory on local runs (not a symlinked system temporary directory). Tests select explicit `VW_TEST_SCRATCH` first and otherwise the isolated fixture HOME, never the checkout or ambient `TMPDIR`. Preserve the selected path literally: an unsafe explicit scratch is rejected without fallback or symlink normalization. CI validates a private namespace outside checkout ancestry before preparing isolated fixtures; directory ancestry restrictions are never relaxed. Follow [new-instance onboarding](new-instance-onboarding.md) for the exact source gate and dependencies.

The next worker/admission boundary is [source-only preparation, not an operational implementation](private-executor-next-slice.md).

```sh
VW_TEST_SCRATCH=/approved/private/scratch python3 -B -m unittest discover \
  -s skills/devops/vaultwarden-operations/tests -p test_private_consumer_core.py -v
```

`openssl` must be available for the real synthetic TLS fixture. Failure to generate it is a test failure, not a skipped TLS proof. The certificate key is deliberately synthetic and removed with the fixture; no real credential manager or browser profile is touched.

Primary documentation used for integration boundaries:
- Hermes authoritative documentation: https://hermes-agent.nousresearch.com/docs/
- Bitwarden password-manager CLI: https://bitwarden.com/help/cli/
