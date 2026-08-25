# MCP service render templates (G5)

This package ships render-only templates for `launchd` (`launchagent`/`launchdaemon`) and `systemd` user units.

- Rendered output is **not** installed, enabled, started, or registered by this package.
- Deployment must be done by an explicit tenant-slice workflow with separate review approval.
- Rendering is render-only and is executed by `scripts/service_plan.py` with `--service` selectors; it does not install, enable, start, or register a service.
- Tenant approval must select service account and domain separately from this render operation (`--accept-owner`, `--accept-domain`).
- Per-tenant persistence requires a separate approved tenant-slice deployment.

## Placeholder vocabulary

Render these templates with explicit values for:

- `SERVICE_LABEL`: per-instance identity (service label)
- `INSTANCE_DIR`: absolute external instance directory
- `LAUNCHER_PATH`: absolute executable shell launcher path (normally the installed `run_mcp.sh`)
- `RUNTIME_PYTHON`: runtime Python executable
- `RUNTIME_ROOT`: runtime root directory for the launch context
- `CONFIG_PATH`: external instance config path
- `STDOUT_LOG_PATH`: stdout destination path
- `STDERR_LOG_PATH`: stderr destination path

Recommended synthetic render map:

```text
SERVICE_LABEL=second-brain-readonly
INSTANCE_DIR=/absolute/path/to/instance-dir
LAUNCHER_PATH=/absolute/path/to/launcher.sh
RUNTIME_PYTHON=/absolute/path/to/python
RUNTIME_ROOT=/absolute/path/to/runtime
CONFIG_PATH=/absolute/path/to/second-brain-kit/instances/second-brain-readonly/runtime-config.json
STDOUT_LOG_PATH=/absolute/path/to/second-brain-kit/instances/second-brain-readonly/logs/mcp-stdout.log
STDERR_LOG_PATH=/absolute/path/to/second-brain-kit/instances/second-brain-readonly/logs/mcp-stderr.log
```

Runtime launch contract:

- `launchd` and `launchdaemon` run `/bin/bash {LAUNCHER_PATH} --config {CONFIG_PATH}` via `ProgramArguments`.
- `systemd` runs `/bin/bash {LAUNCHER_PATH} --config {CONFIG_PATH}` via `ExecStart`.
- `launchdaemon` includes explicit `UserName` and `GroupName`.
- Both templates inject:
  - `SECOND_BRAIN_KIT_RUNTIME={RUNTIME_ROOT}`
  - `SECOND_BRAIN_KIT_PYTHON={RUNTIME_PYTHON}`
- No `--host` or `--port` arguments are injected; binding is controlled by the rendered config and tenant policy.
- `run_mcp.sh` is the v0.2 compatibility launcher: it accepts only an absolute tenant-owned runtime config and delegates to `run_mcp.py`. It does not install, activate, register, or authorize a service cutover.

## Operational posture

Both templates are intentionally explicit for HITL workflows:

- No `launchctl` bootstrap/load/kickstart lines are present in the file bodies.
- No `systemctl daemon-reload/enable/start` directives are present in the file bodies.
- launchd uses explicit `RunAtLoad=false` and `KeepAlive=false`.
- systemd keeps deterministic restart bounds (`Restart=on-failure`, `RestartSec=5`, `StartLimit*`) and does not request automatic activation by itself.
