# Vaultwarden operations: operator and agent handoff

Version **0.2.0**. A portable procedural package for CapRover **or** Coolify. No credential executor, shared broker or account migration is shipped. Approval/merge does not enable agent access or imply a live deployment.

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

- [Main skill](SKILL.md): safety gates and source of operational decisions.
- [Common implementation and CapRover](references/vaultwarden-implementation.md): full CapRover flow, CLI limits, effective policy and bounded recovery.
- [Coolify](references/coolify-deployment.md): native stack/control plane, encrypted-mount startup boundary, ingress/bootstrap and stateful acceptance.
- [Hermes integration](references/hermes-integration.md): capability discovery, private consumption, four-layer writer diagnosis, autofill, profile/session limits and future executor acceptance.
- [Environment checklist](templates/vaultwarden.env.example): non-secret non-runnable contract.
- [Coolify Compose candidate](templates/coolify.compose.yaml): explicit required variables, non-root single writer, no automatic enrollment and fail-closed mounted-storage marker.

## Verify the source package

From the repository root:

```sh
python3 tools/validate_skill.py skills/devops/vaultwarden-operations/SKILL.md
python3 tools/generate_catalog.py --check
python3 -B -m unittest discover -s skills/devops/vaultwarden-operations/tests -v
git diff --check
```

Verify every manifest hash and file inventory in addition to these gates. The tests are offline documentary/template regressions; they do not contact a vault, run an executor, prove storage encryption or validate a restore.

## Acceptance ledger

Use separate fixed outcomes:

- `source_contract_verified`: manifest, public neutrality, links, validators and contract tests.
- `configuration_verified`: image, storage, canonical URL, effective policy and secret delivery independently checked.
- `deployment_verified`: actual running resource, health and ingress/TLS verified.
- `human_client_acceptance_verified`: protected first owner, MFA, permissions/revocation, browser and native-client workflows confirmed.
- `backup_verified`: consistent encrypted off-host artifact/snapshot listed and fully checked.
- `restore_drill_verified`: isolated database, files and representative restored workflows verified.

Healthy HTTP or a green textual suite cannot stand in for human-client acceptance, persistence or recovery. Do not introduce real credentials while a required security/recovery gate is pending. Container or encrypted-volume separation is not protection against a malicious host administrator.
