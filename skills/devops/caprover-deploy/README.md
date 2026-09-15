# CapRover deploy candidate

A bounded, plan-first helper. This directory is governed source, **not an approved
runtime installation**. Start with [SKILL.md](SKILL.md) and the
[provenance](references/provenance.md).

## Ask an agent to use it safely

> Read this directory's SKILL.md and references. Inspect the requested target,
> source, method, and the companion caprover-operations probe contract. Produce
> only a plan first. Do not discover or renew credentials, create an app, change
> configuration, upload, click Force Build, or install anything until the specific
> action is authorized. Treat inconclusive evidence as a blocker, not permission
> to change methods or repeat a mutation.

## Requirements and inputs

- Python 3.12 (tested), with the standard library for the controller.
- For CLI upload: an explicitly located, trusted official `caprover@2.4.4`
  installation and Node `26.7.0`; layout and guard hashes are enforced.
- For local branch upload: an explicitly selected checkout/branch and system Git
  at `/usr/bin/git` or `/bin/git`, with root-owned, non-writable executable and
  containing directory. An arbitrary ambient `PATH` is not inherited.
- For dashboard Force Build: Playwright and its browser must already be available.
  Installing them and authorizing login are separate decisions.
- Protected target bindings and a saved-session registry use the same format as
  the companion [operations examples](../caprover-operations/templates/targets.example.json).
  Copy/configure examples **outside Git**, use owner-only regular files, and never
  put a real token in a tracked example, command argument, or review message.
- Remote Git configuration needs a new absolute recovery-snapshot path with an
  existing private parent outside Git. Snapshot content can contain secrets.

Run `python3 scripts/caprover_deploy.py --help` for the exact argument contract.
The main skill has complete plan/apply examples. Omit `--apply` for a no-network,
no-credential plan; a plan is not evidence that a later deployment will work.

## Deliberate restrictions

- CLI handles an explicit tarball or local checkout/branch, not a remote `--repo`.
- API handles Git configuration only, returning `configured_not_deployed`.
- Remote Git deployment and rebuild use one explicitly selected dashboard trigger.
- HTTPS/WebSocket changes, backups, migrations and retirement are outside this
  helper. Unsupported requests fail before writes.
- `--allow-login` and `--allow-create` are independent of `--apply`.
- An accepted upload, idle build, or zero CLI exit is insufficient. The controller
  requires newer generation/image evidence; application health is a separate test.
- A possible-write failure ends with `reconcile_required`, not another method.

## Local verification, not live validation

From the repository root, with the official dependency installed in a disposable
location:

```sh
CAPROVER_TEST_CLI_ROOT="$CLI_FIXTURE_DIR/node_modules/caprover" \
  python -m pytest skills/devops/caprover-deploy/tests -q -o addopts=''
```

The suite uses synthetic credentials, local fixtures, and mocked boundaries.
It does not authorize or prove a real CapRover deployment, live dashboard
compatibility, SSH/container health, or production readiness. See the repository's
[review contract](../../../docs/caprover-operations-review.md) for the full gate.
