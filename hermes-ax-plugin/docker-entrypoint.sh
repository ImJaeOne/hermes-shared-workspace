#!/usr/bin/env bash
set -euo pipefail

export HERMES_HOME="${HERMES_HOME:-/data/.hermes}"
export PORT="${PORT:-9119}"
export RUN_MODE="${RUN_MODE:-both}"
export HERMES_ACCEPT_HOOKS="${HERMES_ACCEPT_HOOKS:-1}"

HERMES_BIN="/opt/hermes-agent/venv/bin/hermes"
HERMES_PYTHON="/opt/hermes-agent/venv/bin/python3"
PLUGIN_SRC="/opt/hermes-ax-plugin"
PLUGIN_DIR="${HERMES_HOME}/plugins/hermes-ax-plugin"
CONFIG_PATH="${HERMES_HOME}/config.yaml"

mkdir -p "${HERMES_HOME}" "${HERMES_HOME}/plugins" "${HERMES_HOME}/logs" "${HERMES_HOME}/skills"
mkdir -p "${PLUGIN_DIR}"

# Copy the baked plugin into the persistent Hermes volume without deleting
# runtime state such as ax.db, artifacts, uploads, or user-created files.
cp -a "${PLUGIN_SRC}/." "${PLUGIN_DIR}/"

# Ensure Hermes can import the plugin MCP server and the dashboard plugin.
"${HERMES_PYTHON}" - <<'PY'
from pathlib import Path
import os
import yaml

home = Path(os.environ["HERMES_HOME"])
config_path = home / "config.yaml"
plugin_dir = home / "plugins" / "hermes-ax-plugin"
python_path = Path("/opt/hermes-agent/venv/bin/python3")

if config_path.exists():
    data = yaml.safe_load(config_path.read_text()) or {}
else:
    data = {}

plugins = data.setdefault("plugins", {})
enabled = plugins.setdefault("enabled", [])
if "hermes-ax-plugin" not in enabled:
    enabled.append("hermes-ax-plugin")

mcp_servers = data.setdefault("mcp_servers", {})
mcp_servers["hermes-ax"] = {
    "command": str(python_path),
    "args": [str(plugin_dir / "mcp_server.py")],
    "timeout": 30,
}

model = data.setdefault("model", {})
if os.getenv("OPENROUTER_API_KEY"):
    model.setdefault("provider", os.getenv("HERMES_PROVIDER", "openrouter"))
    model.setdefault("default", os.getenv("HERMES_MODEL", "openai/gpt-4.1-mini"))

# Dashboard must bind externally in containers. --insecure is also passed at runtime.
dashboard = data.setdefault("dashboard", {})
dashboard.setdefault("host", "0.0.0.0")
dashboard.setdefault("port", int(os.getenv("PORT", "9119")))

config_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
print(f"Configured Hermes at {config_path}")
print(f"Installed AX plugin at {plugin_dir}")
PY

case "${RUN_MODE}" in
  dashboard)
    exec "${HERMES_BIN}" dashboard --host 0.0.0.0 --port "${PORT}" --no-open --insecure --skip-build
    ;;
  gateway)
    exec "${HERMES_BIN}" gateway run --replace --accept-hooks
    ;;
  both)
    "${HERMES_BIN}" dashboard --host 0.0.0.0 --port "${PORT}" --no-open --insecure --skip-build >"${HERMES_HOME}/logs/dashboard.log" 2>&1 &
    dashboard_pid=$!
    echo "Started Hermes dashboard on 0.0.0.0:${PORT} pid=${dashboard_pid}"
    exec "${HERMES_BIN}" gateway run --replace --accept-hooks
    ;;
  *)
    echo "Unknown RUN_MODE='${RUN_MODE}'. Use dashboard, gateway, or both." >&2
    exit 2
    ;;
esac
