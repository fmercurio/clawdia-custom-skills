# Vaultwarden operations: operator and agent handoff

Version **0.4.0**, review candidate extending the previously approved 0.2.0 contract. A portable operational package for CapRover **or** Coolify. Candidate infrastructure backup/recovery and metadata-only agent-access preflight helpers and a synthetic private-consumer core are shipped; no credential executor for real vaults, shared broker or account migration is shipped. Approval/merge does not enable agent access or imply a live deployment.

## Start with your agent

> Read this package's SKILL.md and linked references. First inspect the exact platform, current source/runtime state and independently authorized target without reading credential values. Maintain a protected decision ledger. Prepare a dry-run using synthetic inputs, then ask for the missing owner decisions before apply. Preserve existing services and keep human bootstrap, agent access, backup and restore authorizations separate. Never request secrets or recovery codes in chat; do not declare completion from static tests or a health page.

## Inspect → decisions → dry-run → apply

1. **Inspect:** verify package manifest, actual platform/version and current resources; distinguish public source, installed skill, session availability, grants and effective permissions.
2. **Decide with the owner:** exact server/project/environment/origin; reviewed image/digest; encrypted storage and host trust; independent key custodian/off-host destination; approved first-owner and SMTP/admin bootstrap; native-client/MFA acceptance and backup window. Missing choices stay pending, not inferred.
3. **Dry-run:** read the common contract and selected platform path; customize only an operator-local non-secret candidate and validate actual Compose/CapRover syntax. Keep public sources tenant-neutral.
4. **Apply:** only within exact-target grants, create/configure/start through the supported platform; read back each effect. Reconcile uncertain writes before retry. Do not install private connectors or broaden permissions as a fallback.
5. **Doctor and verification:** prove image/mount/effective policy, TLS, public admin denial, WebSockets and persistence. Perform protected owner/MFA/native-client checks, then consistent encrypted off-host backup and a real isolated restoration. Report partial states explicitly.
6. **Handoff:** record rollback, key custody, backup freshness and remaining human actions outside public artifacts. Recurring schedules and retention deletion are separate decisions.

## Choose the correct path

- [New-instance onboarding](references/new-instance-onboarding.md): dependency and source checks, five-layer availability ledger, explicit missing runtime/enrollment gates and CI disagreement handling; no automatic installation or access.
- [Main skill](SKILL.md): safety gates and source of operational decisions.
- [Common implementation and CapRover](references/vaultwarden-implementation.md): full CapRover flow, CLI limits, effective policy and bounded recovery.
- [Coolify](references/coolify-deployment.md): native stack/control plane, encrypted-mount startup boundary, ingress/bootstrap and stateful acceptance.
- [Hermes integration](references/hermes-integration.md): capability discovery, private consumption, four-layer writer diagnosis, autofill, profile/session limits and future executor acceptance.
- [Operational learnings](references/operational-learnings.md): generalized bootstrap, signup UI, exact-resource backup/restore and native-engine quota gates.
- [Agent-access rollout](references/agent-access-rollout.md): dedicated-account pilot, native-backend/source separation and remaining executor/enrollment gates.
- [Backup candidate](scripts/backup.py) and [example configuration](templates/backup-config.example.json): explicit private configuration; default check; mutation requires deliberate apply and separate review/authorization.
- [Private-consumer core](scripts/private_consumer_core.py) and [security-slice boundaries](references/private-consumer-core.md): synthetic signed-grant/private HTTPS execution only; no Bitwarden connector or runtime activation.
- [Next private-executor slice](references/private-executor-next-slice.md): proposed synthetic admission/supervision contract, interface choices and separate native/live acceptance gates; not a shipped adapter, CLI/API or activation.
- [Metadata-only preflight](scripts/agent_access_preflight.py) and [disabled policy example](templates/agent-access-policy.example.json): no login/unlock/sync/items/grants; always blocked for secret use.
- [Native signup stylesheet](templates/user.vaultwarden.scss.hbs) and [fresh-browser verifier](scripts/verify_signup_ui.py): visual screen closure only; isolated synthetic DOM or actual deployed signup/register/login verification, never a human browser profile.
- [Environment checklist](templates/vaultwarden.env.example): non-secret non-runnable contract.
- [Coolify Compose candidate](templates/coolify.compose.yaml): explicit required variables, non-root single writer, no automatic enrollment and fail-closed mounted-storage marker.

## Verify the source package

From the repository root, using Python 3.12 (including SQLite serialization support) and the pinned test dependencies:

```sh
python3 tools/validate_skill.py skills/devops/vaultwarden-operations/SKILL.md
python3 tools/generate_catalog.py --check
python3 -B -m unittest discover -s skills/devops/vaultwarden-operations/tests -v
git diff --check
```

Verify every manifest hash and file inventory in addition to these gates. The suite combines documentary/template regressions and isolated synthetic archive/SQLite/WAL/age/metadata-child tests. It exercises a synthetic provider and real loopback HTTPS consumer, but does not contact a real vault or run an operational vault credential executor, prove live storage encryption or validate a new real-controller restore. Install age and age-keygen to exercise both encryption subprocess tests rather than treating skips as proof.

## Acceptance ledger

Use separate fixed outcomes:

- `source_contract_verified`: manifest, public neutrality, links, validators and contract tests.
- `configuration_verified`: image, storage, canonical URL, effective policy and secret delivery independently checked.
- `deployment_verified`: actual running resource, health and ingress/TLS verified.
- `human_client_acceptance_verified`: protected first owner, MFA, permissions/revocation, browser and native-client workflows confirmed.
- `backup_verified`: consistent encrypted off-host artifact/snapshot listed and fully checked.
- `restore_drill_verified`: isolated database, files and representative restored workflows verified.

Healthy HTTP or a green textual suite cannot stand in for human-client acceptance, persistence or recovery. Do not introduce real credentials while a required security/recovery gate is pending. Container or encrypted-volume separation is not protection against a malicious host administrator.
