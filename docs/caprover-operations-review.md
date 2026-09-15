# CapRover operations candidate — review contract

## Scope and authorization

This branch reauthors a generic `caprover-operations` skill and hardens its existing
`caprover-deploy` companion. Both remain **candidate**. The deliverable is governed
source for human evaluation, not an installed capability.

Authorized here: source edits, disposable local fixtures with synthetic tokens,
local validation, and a local review branch. Not authorized here: push/PR/merge,
runtime installation, credential-manager access, reading real CLI sessions,
CapRover server access, or production/staging mutations.

No private skill/source package is copied. Official upstream projects are used as
API/CLI references; dependencies are not vendored. See each skill's provenance.

## Independent implementation slices

1. Read-only CLI session probe: protected target binding, isolated selected-session
   snapshot, mandatory request-time guard, bounded noninteractive execution,
   neutral diagnostics, and real CLI against local HTTP fixtures.
2. App-definition/build safety: preserve a current definition through an explicit
   writable-field allowlist, distinguish missing app from failed inventory, validate
   server response schemas, read back writes, and reject ambiguous build evidence.
3. Deployment control flow: select the requested method before credential access,
   separate authentication approval from deploy approval, avoid blind fallback after
   possible writes, and propagate verification failures as nonzero exits.
4. Candidate governance: accurate references, manifests, file inventory, catalog
   regeneration, and a reproducible local review.

## Acceptance checklist

- [x] Protected alias-to-origin binding is checked before any credential is sent.
- [x] The probe's mandatory guard prevents login, writes, forbidden endpoints and redirects.
- [x] Real CLI fixture tests exercise success, rejected session, malformed schema,
      transport failure, timeout, mutation races and secret-canary containment.
- [x] Generic CLI warnings, EOF, interruption and timeout do not imply logout.
- [x] Current app state is preserved; `redirectDomain` is a string when present.
- [x] App creation is an explicit path, not inferred from an unavailable inventory.
- [x] Idle/missing build fields, unchanged deployment or missing image cannot pass.
- [x] Method-specific failure and verification failure have nonzero process status.
- [x] Ambiguous completion stops for reconciliation; no automatic repeat mutation.
- [x] Runtime/installation/approval fields remain null for both candidates.
- [x] Manifests, registry inventory, generated catalog and relevant suites pass.

## Reproducible validation

Use a disposable Python environment and a separately installed, trusted official
`caprover@2.4.4` dependency. Do not point test variables at a real CLI registry.

```sh
python -m pip install -r requirements-dev.txt pytest
npm install --prefix "$CLI_FIXTURE_DIR" --ignore-scripts --no-audit --no-fund caprover@2.4.4
CAPROVER_TEST_CLI_ROOT="$CLI_FIXTURE_DIR/node_modules/caprover" \
  python -m pytest skills/devops/caprover-operations/tests skills/devops/caprover-deploy/tests -q -o addopts=''
python -m unittest discover -s tools/tests -p 'test_*.py'
python -m unittest discover -s tools/skill_deploy/tests -p 'test_*.py'
python tools/validate_skill.py skills/devops/caprover-operations/SKILL.md
python tools/validate_skill.py skills/devops/caprover-deploy/SKILL.md
python tools/generate_catalog.py --check
```

Record exact versions, completed test counts and skips in the final review result.
A skipped CLI fixture suite is **not** a validated probe.

## Verified local result — 2026-09-15

- `caprover-operations` 0.1.0: **67 tests passed**.
- `caprover-deploy` 2.0.0: **140 tests passed**, including four actual
  CLI/controller loopback integration cases (tarball, local branch, stale version,
  and redirect rejection).
- Combined candidate suite: **207 passed, zero skipped**.
- Repository tooling: **97 passed**; installation-planner suite: **31 passed**.
- Total across those non-overlapping suites: **335 passed**.
- Skill frontmatter, Python/Node syntax, manifests and complete byte inventories,
  public-marker scan, relative documentation links, and generated catalog passed.
- Registry comparison preserves all unrelated entries and the capability catalog;
  both skills remain candidates with null approval/runtime/installation fields.

Tested toolchain: Python 3.12.13, pytest 9.1.1, Node 26.7.0, official CapRover CLI
2.4.4. These are local results; the checked-in CI workflow has not run remotely.
The Playwright safety tests use fake browser boundaries, not a live dashboard.

### Review the intentional compatibility changes

Version 2 defaults to plan-only; mutations require `--apply`. Login and app
creation have separate grants. API mode is configuration-only, while local
artifact upload uses the pinned CLI and remote Git builds use the explicitly
selected dashboard path. HTTPS/WebSocket changes are rejected as outside scope.
No failure silently chooses another method or repeats an uncertain mutation.

## Evidence boundaries

Local unit/fixture verification does not prove a live CapRover session, an actual
application deployment, dashboard compatibility, application health, backup
restorability or production readiness. Even a successful build/version readback is
not an application-specific health check. Any representative live validation,
credential access, login renewal, configure/deploy/start, migration or deletion
requires its own explicit scope and authorization.

The supported full app-definition update is not a server-side atomic
compare-and-swap. Preserving a freshly read configuration and verifying readback
does not prevent a concurrent writer between those requests. Future operators
must serialize configuration changes and reconcile any drift; the recovery
snapshot is evidence for review, not permission for an automatic rollback.

The Node request guard is a narrow interlock for a trusted pinned CLI installation,
not an operating-system sandbox for hostile code. Revalidate after dependency,
CLI layout, Node support or server schema changes. Never relax the guard to make a
failed fixture pass.
