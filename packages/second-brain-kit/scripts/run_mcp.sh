#!/usr/bin/env bash
# Compatibility launcher for a tenant-owned, read-only v0.2 MCP instance.
# It deliberately accepts no listener overrides; run_mcp.py validates the config.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  run_mcp.sh --help
  run_mcp.sh --check --config <ABSOLUTE_RUNTIME_CONFIG_JSON>
  run_mcp.sh --config <ABSOLUTE_RUNTIME_CONFIG_JSON>

This launcher only delegates to the validated v0.2 runtime. It does not install,
activate, register, or authorize an MCP service.
EOF
}

fail() {
  printf 'run_mcp.sh: %s\n' "$1" >&2
  exit 2
}

if [[ $# -eq 1 && "$1" == "--help" ]]; then
  usage
  exit 0
fi

MODE=""
CONFIG_PATH=""
if [[ $# -eq 3 && "$1" == "--check" && "$2" == "--config" ]]; then
  MODE="check"
  CONFIG_PATH="$3"
elif [[ $# -eq 2 && "$1" == "--config" ]]; then
  MODE="serve"
  CONFIG_PATH="$2"
else
  fail "unsupported arguments"
fi

[[ "$CONFIG_PATH" == /* ]] || fail "config must be an absolute path"
[[ -f "$CONFIG_PATH" && ! -L "$CONFIG_PATH" ]] || fail "config must be an existing regular non-symlink file"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
RUNTIME_ROOT="${SECOND_BRAIN_KIT_RUNTIME:-$SCRIPT_DIR}"
[[ "$RUNTIME_ROOT" == /* ]] || fail "SECOND_BRAIN_KIT_RUNTIME must be an absolute path"
[[ -d "$RUNTIME_ROOT" && ! -L "$RUNTIME_ROOT" ]] || fail "runtime root must be an existing non-symlink directory"
RUNTIME_ROOT="$(cd "$RUNTIME_ROOT" && pwd -P)"
RUNNER="$RUNTIME_ROOT/run_mcp.py"
[[ -f "$RUNNER" && ! -L "$RUNNER" ]] || fail "runtime root must contain a regular run_mcp.py"

if [[ -n "${SECOND_BRAIN_KIT_PYTHON:-}" ]]; then
  PYTHON_EXE="$SECOND_BRAIN_KIT_PYTHON"
  [[ "$PYTHON_EXE" == /* ]] || fail "SECOND_BRAIN_KIT_PYTHON must be an absolute path"
else
  PYTHON_EXE="$(command -v python3 || true)"
  [[ -n "$PYTHON_EXE" && "$PYTHON_EXE" == /* ]] || fail "python3 must resolve to an absolute executable path"
fi

[[ -f "$PYTHON_EXE" && -x "$PYTHON_EXE" ]] || fail "configured Python must be an executable regular file"
PYTHON_REALPATH="$(realpath "$PYTHON_EXE" 2>/dev/null || true)"
[[ -n "$PYTHON_REALPATH" && -f "$PYTHON_REALPATH" && -x "$PYTHON_REALPATH" ]] || fail "configured Python must resolve to an executable file"

# Invoke the configured venv path, not its resolved target: resolving it can discard
# the virtualenv site-packages required by the MCP SDK.
if [[ "$MODE" == "check" ]]; then
  exec "$PYTHON_EXE" "$RUNNER" --config "$CONFIG_PATH" --check
fi
exec "$PYTHON_EXE" "$RUNNER" --config "$CONFIG_PATH" --serve
