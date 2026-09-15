# CapRover candidates — corrected review contract

## Scope and custody

This branch reauthors the generic `caprover-operations` skill and hardens its
`caprover-deploy` companion. Both remain **candidate**, without approval or runtime
installation. The deliverable is governed source for human evaluation, not an
installed or production-validated capability.

Authorized here: source edits, disposable local fixtures with synthetic tokens,
local verification, and a local review branch. Not authorized here: push/PR/merge,
runtime installation, credential-manager access, reading real CLI sessions,
CapRover server access, production/staging mutations, or real SSH/Docker actions.
The operational host CLI was not replaced. Test dependencies are isolated.

Complete-patch baseline: `81d88608c29dffae4efc02f0cf737237557d5f28`.
Correction input: `17d7dee8f4b1f06ecbe54fdf1d505e1785ab097e`.
The final export records the exact candidate commit/tree and patch checksum; a
review of an earlier slice is not approval of a later tree.

No private skill/source package is copied. Official upstream projects are API/CLI
references, not vendored dependencies. See the packages' provenance documents.
The unreleased candidate versions remain operations **0.1.0** and deploy **2.0.0**;
the exported commit/tree distinguishes this correction revision.

## F1–F6 correction map

### F1 — causal deployment evidence

The controller binds the expected source before the trigger. For CLI uploads,
the guarded wire path requests synchronous completion and confirmation requires
its exact awaited Captain `status: 100` response together with matching expected
source evidence. A detached `101`, an idle builder, a zero CLI exit, or an
unrelated later version/image cannot substitute for that causal acknowledgement.
An already-building baseline is rejected before triggering.

A source digest supplied by this client is a fingerprint, not an independent
server attestation. The reviewed Force Build webhook cannot attribute scheduling:
even an acknowledged click followed by the expected source remains nonzero
`reconcile_required`. The controller does not retry or switch methods after an
ambiguous possible write. Application health remains independent.

### F2 — await browser request, response and body

The browser observes the exact trigger request, matching HTTP response and complete
body under a bounded deadline before releasing its resources. Delayed response,
rejection, timeout, and body stalls are covered. An acknowledgement does not become
proof that this invocation scheduled the build. No larger fixed sleep substitutes
for response observation, and no failure schedules a second trigger.

### F3 — local browser availability before writes

An applicable apply path prepares Chromium before credential access or controller
writes, without navigating during local preparation. The same browser, context
and page are reused. Startup failure blocks early; cleanup owns only those local
resources. Plan-only remains static and does not launch a browser.

### F4 — exact remote replica observation

SSH receives one shell-quoted remote command. A synthetic local shell verifies that
the Go-template's literal TAB survives parsing; no real SSH or Docker is used in
that test. The reviewed server's boolean `isLegacyAppName` selects either
`srv-captain--<app>` or `<app>`; absent or malformed flags are inconclusive before
SSH.

The parser requires exactly one **exact-name matching row**, with running and
desired counts equal to the validated positive `instanceCount`. Docker name filters
can also return prefix siblings; they are not extra matching target rows. Modern
and legacy characterization cases cover healthy target plus sibling, sibling-only,
duplicate target, and unhealthy target plus healthy sibling. Zero, partial or
excess replicas do not pass. This is not application-health validation.

### F5 — unexpected exceptions at the public probe boundary

Unexpected ordinary exceptions become fixed JSON `inconclusive` /
`internal_error` results with nonzero exit and no raw exception text. Existing
`ProbeError` handling, normal parser/help behavior, `KeyboardInterrupt`,
`SystemExit`, and other `BaseException` semantics remain distinct. Regressions
exercise recursion overflow, symlink cycles and synthetic exception markers through
actual public subprocess entrypoints.

### F6 — concurrent source changes

The accepted targets/registry bytes and their private witnesses come from the same
protected descriptor reads. After query and temporary-state cleanup, bounded
read-only rechecks compare both sources' identity, protected metadata and content.
Detected changes, replacement, deletion or inability to establish unchanged state
produce nonzero `inconclusive` / `source_changed`, before valid/invalid authentication
classification. The in-flight query retains only its original private snapshot:
it neither redirects credentials to a later target nor restores over operator edits.

This is a bounded temporal observation, not continuous monitoring, an atomic
transaction across both files, or protection from hostile same-UID code. Changes
after the final observation remain outside that evidence window.

## Authorization and integration consolidation

For each action, verify an explicit, current and sufficient authorization grant.
Reuse standing/session grants only within scope. Request a new decision for new,
insufficient or ambiguous scope. Credential access does not authorize deployment,
restart or deletion. This does not weaken apply/login/create flags, exact targets,
recovery snapshots, readbacks, data-loss boundaries or post-timeout reconciliation.
App deletion and volume/data deletion remain distinct scopes.

The candidate CI pins Playwright, provisions Chromium with its OS dependencies,
shares a runner-temp browser directory, and sets mandatory `CI=1`. Both complete
CapRover fixture suites remain required; missing CLI/browser prerequisites cannot
silently count as successful validation. The workflow contract has local tests;
no remote GitHub Actions execution is claimed.

## Reproducible local verification

Use Python 3.12 and Node 26.7.0. Select fresh, disposable `PYTHON_FIXTURE_DIR`,
`CLI_FIXTURE_DIR` and `BROWSER_FIXTURE_DIR`; do not reuse a personal browser profile
or supply any real saved-session registry. From the repository root:

```sh
python3.12 -m venv "$PYTHON_FIXTURE_DIR"
"$PYTHON_FIXTURE_DIR/bin/python" -m pip install --disable-pip-version-check \
  -r requirements-dev.txt pytest==9.1.1 playwright==1.58.0
npm install --prefix "$CLI_FIXTURE_DIR" --ignore-scripts --no-audit --no-fund caprover@2.4.4
PLAYWRIGHT_BROWSERS_PATH="$BROWSER_FIXTURE_DIR" \
  "$PYTHON_FIXTURE_DIR/bin/python" -m playwright install --with-deps chromium

CI=1 PYTHONDONTWRITEBYTECODE=1 \
PLAYWRIGHT_BROWSERS_PATH="$BROWSER_FIXTURE_DIR" \
CAPROVER_TEST_CLI_ROOT="$CLI_FIXTURE_DIR/node_modules/caprover" \
  "$PYTHON_FIXTURE_DIR/bin/python" -m pytest \
  skills/devops/caprover-operations/tests skills/devops/caprover-deploy/tests \
  -q -o addopts=''

PYTHONDONTWRITEBYTECODE=1 "$PYTHON_FIXTURE_DIR/bin/python" \
  -m unittest discover -s tools/tests -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 "$PYTHON_FIXTURE_DIR/bin/python" \
  -m unittest discover -s tools/skill_deploy/tests -p 'test_*.py'
"$PYTHON_FIXTURE_DIR/bin/python" tools/validate_skill.py skills/devops/caprover-operations/SKILL.md
"$PYTHON_FIXTURE_DIR/bin/python" tools/validate_skill.py skills/devops/caprover-deploy/SKILL.md
node --check skills/devops/caprover-operations/scripts/readonly_guard.cjs
node --check skills/devops/caprover-deploy/scripts/deployment_guard.cjs
PYTHONDONTWRITEBYTECODE=1 "$PYTHON_FIXTURE_DIR/bin/python" tools/generate_catalog.py --check
```

Record exit codes, completed counts and skips; a skipped required fixture is not
validation. Run repository suites in a disposable source copy, and verify source
integrity afterward. Package checks additionally recompute all manifest hashes,
complete registry byte inventories (including each manifest), internal guard pins,
relative documentation links, public-marker scans and the exact staged diff.

## Recorded local results — 2026-09-15

The orchestrator independently executed the complete, non-overlapping suites after
consolidation, using disposable official CLI and browser dependencies:

- `caprover-operations`: **83 passed**.
- `caprover-deploy`: **191 passed**.
- Combined CapRover suites: **274 passed**, zero failures/errors/skips.
- Repository tooling: **100 tests, OK**.
- Installation-planner tooling: **31 tests, OK**.
- Total across these non-overlapping suites: **405 passed**, zero skipped.

Toolchain: Python **3.12.13**, pytest **9.1.1**, Node **26.7.0**, official CapRover
CLI **2.4.4**, Playwright **1.58.0**, Chromium **145.0.7632.6**.

This includes actual official CLI requests and actual Chromium against synthetic
loopback fixtures, plus mocked boundaries and a synthetic shell. It is not a real
CapRover dashboard/server test. Earlier totals and overlapping reviewer selections
are not added to this total. Causal RED logs, final exact-tree reruns and metadata
checks are retained in the local review export rather than published as raw logs.

Slice-specific specification/quality reviews do not approve the whole revision.
The final source-review verdict must identify the complete candidate tree and its
patch hash. Maintainer evaluation, any publication, promotion and live validation
remain separate decisions.

## Intentional compatibility changes and limitations

Version 2 defaults to plan-only; mutations require `--apply`. Login and app creation
have distinct scopes. API mode is configuration-only. Local artifact upload uses
the pinned CLI; remote Git builds use the explicitly selected dashboard path, whose
current acknowledgement remains `reconcile_required`. HTTPS/WebSocket changes are
rejected as unsupported. No failure silently selects another method or repeats an
uncertain mutation.

The full app-definition update is not a server-side atomic compare-and-swap.
Preservation and readback do not prevent a writer between requests: serialize
configuration changes and reconcile drift. A recovery snapshot is not permission
for automatic rollback.

The Node guards are narrow interlocks for trusted pinned CLI code, not operating-
system sandboxes. Revalidate after CLI/dependency layout, Node, browser or server
schema changes. Never relax a guard to make a fixture pass. Local results do not
prove a live session, deployed application, dashboard compatibility, backup
restorability, application health or production readiness.
