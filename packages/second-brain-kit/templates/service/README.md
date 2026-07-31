# MCP service render templates (G5)

This package ships render-only templates for `launchd` and `systemd` user units.

- Rendered output is **not** installed, enabled, started, or registered by this package.
- Deployment must be done by an explicit tenant-slice workflow with separate review approval.
- Per-tenant persistence requires a separate approved tenant-slice deployment.

## Placeholder vocabulary

Render these templates with explicit values for:

- `SERVICE_LABEL`: per-instance identity (service label)
- `INSTANCE_DIR`: absolute external instance directory
- `RUNTIME_PYTHON`: runtime Python executable
- `SERVER_ENTRYPOINT`: server module/script entrypoint path
- `CONFIG_PATH`: external instance config path
- `SERVICE_PORT`: loopback bind port
- `STDOUT_LOG_PATH`: stdout destination path
- `STDERR_LOG_PATH`: stderr destination path

Recommended synthetic render map:

```text
SERVICE_LABEL=second-brain-readonly
INSTANCE_DIR=/absolute/path/to/instance-dir
RUNTIME_PYTHON=/absolute/path/to/python
SERVER_ENTRYPOINT=/absolute/path/to/server-entrypoint.py
CONFIG_PATH=/absolute/path/to/second-brain-kit/instances/second-brain-readonly/runtime-config.json
SERVICE_PORT=6282
# Host is deliberately fixed by both templates: 127.0.0.1
STDOUT_LOG_PATH=/absolute/path/to/second-brain-kit/instances/second-brain-readonly/logs/mcp-stdout.log
STDERR_LOG_PATH=/absolute/path/to/second-brain-kit/instances/second-brain-readonly/logs/mcp-stderr.log
```

## Operational posture

Both templates are intentionally explicit for HITL workflows:

- No `launchctl` bootstrap/load/kickstart lines are present in the file bodies.
- No `systemctl daemon-reload/enable/start` directives are present in the file bodies.
- launchd uses explicit `RunAtLoad=false` and `KeepAlive=false`.
- systemd keeps deterministic restart bounds (`Restart=on-failure`, `RestartSec=5`, `StartLimit*`) and does not request automatic activation by itself.
