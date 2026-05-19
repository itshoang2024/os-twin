#!/usr/bin/env bash
# dashboard-daemon.sh — LaunchAgent wrapper for the Ostwin dashboard
#
# This script is called by launchd on macOS login.
# It sources .env for API keys, then starts the dashboard via dashboard.sh.
# KeepAlive=true in the plist means launchd will restart this if it exits.
set -euo pipefail

OSTWIN_HOME="${OSTWIN_HOME:-$HOME/.ostwin}"

# Source .env so the dashboard process inherits API keys and config
if [[ -f "$OSTWIN_HOME/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$OSTWIN_HOME/.env"
  set +a
fi

# Default port (can be overridden via .env)
DASHBOARD_PORT="${DASHBOARD_PORT:-3366}"

# Ensure log directory exists
mkdir -p "$OSTWIN_HOME/logs"

# Find the dashboard launcher
DASHBOARD_SCRIPT="$OSTWIN_HOME/.agents/dashboard.sh"
if [[ ! -f "$DASHBOARD_SCRIPT" ]]; then
  echo "[$(date +%H:%M:%S)] ERROR: dashboard.sh not found at $DASHBOARD_SCRIPT" >&2
  echo "[$(date +%H:%M:%S)] Re-run: ./install.sh --source-dir /path/to/agent-os" >&2
  exit 1
fi

echo "[$(date +%H:%M:%S)] Starting Ostwin dashboard (launchd) on :$DASHBOARD_PORT..."

# Start the dashboard — it handles its own PID file and health
exec bash "$DASHBOARD_SCRIPT" \
  --port "$DASHBOARD_PORT" \
  --project-dir "$OSTWIN_HOME" \
  --skip-build
