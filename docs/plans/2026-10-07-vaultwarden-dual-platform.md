# Vaultwarden Dual-Platform Implementation Plan

> **For Hermes:** Use native tools or a bounded `delegate_task` worker for code-changing implementation. The parent independently verifies the diff and tests; do not invoke Codex CLI automatically.

**Goal:** Deliver a portable CapRover/Coolify operations contract, incorporate the seven integration improvements, and enable an explicitly authorized human-only deployment with verifiable recovery.

**Architecture:** Keep the package procedural, tenant-neutral and separate from private execution state. Preserve the dedicated CLI-worker boundary; do not introduce a credential broker, grants, account migration or automatic agent access. Deploy only through the selected platform's supported control plane; encryption, protected bootstrap, native-client compatibility and recovery are independent acceptance gates.

**Tech Stack:** Vaultwarden official immutable image, SQLite, supported CapRover or Coolify resource flow, upstream HTTPS/WebSocket contract, unittest documentary regressions and repository catalog gates.

---

## Task 1: Freeze source and authorization boundaries — AFK/HITL

- Inspect live base/head, PR state, repository instructions and approval/check requirements.
- Preserve the reviewed foundation PR; use an isolated durable worktree for its follow-up.
- Record operational target/recipient/storage decisions only in protected operator context, never this public plan.
- HITL: live filesystem encryption, independent key custody, off-host destination and first-owner/SMTP choices must be decided before first start or enrollment. No answer is not consent to a weaker design.

## Task 2: Add documentary regressions — AFK

- Create `skills/devops/vaultwarden-operations/tests/test_integration_contract.py`.
- Exercise the seven issue topics, both platform paths, fail-closed Compose defaults, local links, public neutrality and manifest coverage.
- Run `python3 -B -m unittest discover -s skills/devops/vaultwarden-operations/tests -v` before adding missing documents; retain the expected red result.
- Update existing contract expectations only where the approved version/file inventory changes, preserving the original security assertions.

## Task 3: Implement both deployment paths and integration contract — AFK

- Modify `skills/devops/vaultwarden-operations/SKILL.md`, `references/vaultwarden-implementation.md` and `templates/vaultwarden.env.example`.
- Create `references/hermes-integration.md`, `references/coolify-deployment.md`, `templates/coolify.compose.yaml` and `README.md` inside that package.
- Preserve the full CapRover procedure. Add supported Coolify create/configure/start/readback, image/mount gates and a non-secret fail-closed template.
- Separate discovery, model-visible results, writer authorization, autofill, session availability, untrusted-backup validation and future executor acceptance. No executor ships with these documents.

## Task 4: Regenerate and review governed metadata — AFK

- Generate `skills/devops/vaultwarden-operations/MANIFEST.sha256` after cache hygiene.
- Update only the Vaultwarden entry of `registry/skills-registry.yaml`: version, findings, inventory byte sizes and changelog; runtime installation fields stay null.
- Run `python3 tools/generate_catalog.py`, `python3 tools/generate_catalog.py --check`, `python3 tools/validate_skill.py skills/devops/vaultwarden-operations/SKILL.md`, package tests, repository tool suites and staged diff checks.
- Render the template through the target's actual `docker compose config --quiet` with synthetic variables. This proves configuration syntax only, not encryption, startup or recovery.
- Re-read base/head after tests; independently review the final immutable tree and all public surfaces.

## Task 5: Publish and merge sequentially — HITL/AFK

- With explicit maintainer authorization, preserve the contributor foundation PR. If `maintainer_can_modify` is verified, append the reviewed follow-up to that same head branch with no force push; do not forge authorship or create a redundant PR merely to increase the queue.
- Read back the exact remote head and require actual PR-triggered CI, not a forged status or a green local command.
- Review/approve the contributor PR only from an eligible identity and exact validated head, then merge and verify its merge commit. Re-read protection rather than assuming administrative authority removes the review gate.
- If a separate follow-up PR is necessary, refresh it against newly merged main and revalidate. Do not bypass required review or change protection merely because its author cannot self-approve.
- Verify final remote main and package integrity from a clean isolated worktree. Merge does not install the skill or enable secret access.

## Task 6: Private deployment and recovery — HITL/AFK

- Resolve current upstream release/security notes and pin the official image by version plus digest.
- Preserve incumbent services; no shared proxy restart, host-port publication, unrelated volumes or Docker socket.
- Establish approved encrypted storage and independent recovery custody before creating the resource. Prevent empty-directory fallback when encrypted storage is sealed.
- Create/configure/start via the selected supported platform; reconcile uncertain writes before retrying.
- Verify effective policy, mount/image identity, TLS, admin denial and WebSockets. Complete protected first-owner/MFA and native-client checks separately.
- Prove persistence with a resource-scoped restart and synthetic test state. Make a consistent encrypted off-host backup; list/read back the exact artifact and restore to an isolated destination.
- Validate bounded structure, database integrity and representative restored file/client behavior. Enable a daily job only under a specific schedule grant; no automatic retention deletion.

## Completion and rollback

- Report `source_contract_verified`, `configuration_verified`, `deployment_verified`, `human_client_acceptance_verified`, `backup_verified` and `restore_drill_verified` independently.
- A blocked onboarding/native-client/encryption/recovery gate means not production-ready, even with healthy HTTP.
- Rollback affects only the new owned resource and explicit DNS record. Preserve volumes, encrypted artifacts and prior immutable image metadata; database migration can require data restoration rather than image-only rollback.
