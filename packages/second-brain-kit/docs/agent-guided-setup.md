# Agent-guided setup handoff for `second-brain-kit`

This document is designed for another Hermes-capable agent that receives only the package path and must complete a safe setup end-to-end.

## Scope and constants

- Ask for decisions only when not discoverable from package files/system state.
- Ask **exactly one blocking question at a time**.
- Provide a **recommended default** and one-sentence reason with every question.
- Keep a concise setup decision ledger and keep it visible.
- Stop asking once required decisions are finalized.
- Never restart the Hermes gateway.
- Never enable Git, cron, remote embeddings, or OKF render without explicit authorization.
- Never use `--force` without explicit user authorization.

## Phases

### 1) Inspect

1. Read package materials first:
   - `README.md`
   - `manifest.yaml`
   - `docs/trigger-tests.md`
   - `docs/decisions-requiring-human-confirmation.md`
   - `skills/*/SKILL.md`
2. Inspect target environment:
   - current process-level `HERMES_HOME` (if any)
   - existing config at `${HERMES_HOME}/second-brain-kit/profiles/<profile>/config.yaml`
   - existing vault path if provided
3. Record all discovered facts in the ledger as “Pre-filled.”

### 2) Interview

Ask one question, wait, then update the ledger.

- **Question format**
  - **Question:** `<clear question>`
  - **Recommended:** `<default>` (`why this default is safe`)
- Do not ask questions whose answers can be read from files or system state.
- Stop when all required decisions are decided.

### Required decision sequence

1. **Absolute package path**
   - Default: the inspected package path you were provided.
   - Reason: keeps commands deterministic and avoids accidental cross-package drift.
2. **Explicit `HERMES_HOME` (absolute)**
   - Default: the inspected absolute `$HERMES_HOME` only when it is the intended target; otherwise propose `$HOME/.hermes` and require confirmation before treating it as the zero-state environment.
   - Reason: using an explicit confirmed home prevents accidental installation into an active Hermes runtime.
3. **New vs existing vault**
   - Default: infer `existing` when the path already contains Markdown or vault markers; infer `new` only when the target is absent or empty.
   - Reason: filesystem evidence is safer than assuming a new vault and protects existing knowledge.
4. **Absolute vault path**
   - Default: `${HERMES_HOME}/vaults/second-brain`.
   - Reason: keeps vault and runtime isolated and discoverable.
5. **Owner**
   - Default: the owner label discoverable from authorized environment/context; if none is available, explicitly ask and do not write a placeholder owner.
   - Reason: owner is required metadata, but inventing identity would contaminate the generated vault.
6. **Optional organization**
   - Default: empty.
   - Reason: organization is optional and omitting it avoids accidental tenant leakage.
7. **Target profile**
   - Default: `second-brain`.
   - Reason: existing scripts and skills assume this canonical profile unless requested otherwise.
8. **Mode (`para`, `hybrid`, `okf`)**
   - Default: `hybrid`.
   - Reason: enables PARA structure now while preserving optional renderer path availability.
9. **Sensitivity defaults + restricted handling**
   - Default: sensitivity default `internal`; `restricted_search: false`.
   - Reason: safe-by-default posture keeps restricted notes out of normal index/render flows.
10. **Git / remote / push policy**
   - Default: `enabled=false`, `remote=null`, `push_policy=confirm`.
   - Reason: remote write paths introduce mutable side effects and must be explicit.
11. **Embeddings and remote-data consent**
   - Default: `embeddings.enabled=auto`, `allow_remote=false`, `endpoint=null`.
   - Reason: remote calls can leak vault content and must require explicit authorization.
12. **Obsidian integration**
   - Default: `obsidian.enabled=false`.
   - Reason: optional integrations are opt-in to keep setup minimal.
13. **OKF render**
   - Default: `okf.render.enabled=false`.
   - Reason: static rendering is snapshot-oriented and must be an explicit decision.
14. **Cron and delivery**
   - Default: `cron.enabled=false`, `deliver=unset`.
   - Reason: scheduled execution changes operational behavior and should remain opt-in.
15. **Overwrite conflicts**
   - Default: fail preflight on conflicts (`--force` not set).
   - Reason: prevents unreviewed overwrite of managed runtime files.
16. **Rollback policy**
   - Default: keep install inventory and perform uninstall dry-run before any irreversible action.
   - Reason: preserves traceability and supports recovery without vault mutation.

## Setup decision ledger (template)

- `package_path`: unset
- `HERMES_HOME`: unset
- `vault_mode`: unset (`new`/`existing`)
- `vault_path`: unset
- `owner`: unset
- `organization`: unset (optional)
- `profile`: unset
- `mode`: unset
- `sensitivity_default`: unset
- `restricted_search`: unset
- `git_enabled`: unset
- `git_remote`: unset
- `git_push_policy`: unset
- `embeddings_enabled`: unset
- `embeddings_allow_remote`: unset
- `obsidian_enabled`: unset
- `okf_enabled`: unset
- `cron_enabled`: unset
- `cron_deliver`: unset
- `overwrite_policy`: unset
- `rollback_plan`: unset

## Execution flow

1. **Summarize plan**
   - Show the resolved command sequence, key paths, and inferred risks.
2. **Dry-run without `--apply`**
   - Show:
     - `bootstrap.py` output (no `--apply`)
     - `install.py` output (no `--apply`)
   - Do not change data during this phase.
3. **Show dry-run result**
   - Share operation list, created paths, and detected conflicts exactly as JSON output.
4. **Explicit apply gate**
   - Require explicit authorization before any `--apply`.
5. **`bootstrap.py --apply`**
   - New vaults: create structure and config; existing vaults: read-only-first audit.
6. **`install.py --apply`**
   - Install runtime and skills with managed-file tracking.
7. **`doctor.py --smoke --check-optional`**
   - Verify core checks, search rebuild, and optional capability states.
8. **Representative FTS/search/health validation**
   - Always run read-only/rebuildable checks: `brain_search.py --rebuild`, a representative query, `brain_ops.py pull`, and `brain_health_check.py`.
   - For a **new empty vault**, a disposable `brain_ops.py push` probe is allowed only after the apply gate; remove the probe after verifying pull/search.
   - For an **existing vault**, do not run a push probe without a separate explicit write authorization. Search and health validation are sufficient for onboarding.
9. **Final report**
   - Include ledger, dry-run diff summary, final health status, and rollback path.

## Required command templates

- Inspect-only dry-runs:
  - `python3 scripts/bootstrap.py --hermes-home "$HERMES_HOME" --profile "$PROFILE" --vault "$VAULT_PATH" --owner "$OWNER" ${ORGANIZATION:+--organization "$ORGANIZATION"} --mode "$MODE" [--existing] --json`
  - `python3 scripts/install.py --hermes-home "$HERMES_HOME" --profile "$PROFILE" --json`
- Safe apply phase:
  - `python3 scripts/bootstrap.py ... --apply --json`
  - `python3 scripts/install.py ... --apply --json`
  - `python3 scripts/doctor.py --hermes-home "$HERMES_HOME" --profile "$PROFILE" --smoke --check-optional --json`
- Representative checks after apply:
  - `python3 "$HERMES_HOME/second-brain-kit/bin/brain_ops.py" --hermes-home "$HERMES_HOME" --profile "$PROFILE" pull --query "agent-guided setup probe"`
  - `python3 "$HERMES_HOME/second-brain-kit/bin/brain_search.py" --vault "$VAULT_PATH" --rebuild --json`
  - `python3 "$HERMES_HOME/second-brain-kit/bin/brain_search.py" --vault "$VAULT_PATH" --query "agent-guided setup probe" --json`
  - `python3 "$HERMES_HOME/second-brain-kit/bin/brain_health_check.py" --vault "$VAULT_PATH" --json`
  - New empty vault only, after apply authorization: `python3 "$HERMES_HOME/second-brain-kit/bin/brain_ops.py" --hermes-home "$HERMES_HOME" --profile "$PROFILE" push --title "Setup smoke" --body "agent-guided setup probe" --layer resource`; verify it, then remove the disposable probe.

## Compact copy-paste handoff prompt

```text
You are now the second-brain-kit setup steward for this user.
Conduct the interview in the user's language.
Use only information discoverable from files and environment for defaults; never assume unknown details.
Ask one blocking question at a time, and for each, include:
- Recommended default
- one-sentence reason

Package path is:
${PACKAGE_PATH}

Follow this exact flow:
inspect -> interview -> summarize plan -> bootstrap dry-run -> install dry-run -> show dry-run -> explicit apply gate -> bootstrap --apply -> install --apply -> doctor --smoke --check-optional -> representative FTS/search/health checks -> final report.

Do not restart the Hermes gateway at any point.
Do not enable Git, cron, remote embeddings, or OKF rendering without explicit authorization.
Do not use --force without explicit authorization.
No physical migration for existing vaults during onboarding; perform read-only audit first.
```
