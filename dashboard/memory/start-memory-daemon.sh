#!/bin/bash
# Start the memory MCP server as a persistent background daemon (SSE transport).
#
# Usage:
#   start-memory-daemon.sh [project-dir]         # auto-assigns port from project path
#   start-memory-daemon.sh [project-dir] --port PORT
#   start-memory-daemon.sh --stop [project-dir]  # stop daemon for a project
#   start-memory-daemon.sh --stop-all             # stop all memory daemons
#   start-memory-daemon.sh --status [project-dir] # check if running
#
# Each project gets a unique port derived from its path (range 6400-7399).
# PID files are stored per-project at <project-dir>/.memory/.daemon.pid

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${OSTWIN_PYTHON:-${HOME}/.ostwin/.venv/bin/python}"
PORT=""
PROJECT_DIR=""
ACTION="start"

# Portable symlink resolution: readlink -f works on Linux and recent macOS,
# but falls back to python on older macOS where -f is unsupported.
_realpath() {
  readlink -f "$1" 2>/dev/null || python3 -c "import os; print(os.path.realpath('$1'))"
}

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --stop) ACTION="stop"; shift ;;
    --stop-all) ACTION="stop-all"; shift ;;
    --status) ACTION="status"; shift ;;
    *) PROJECT_DIR="$1"; shift ;;
  esac
done

# Derive a deterministic port from project path (range 6400-7399)
_port_from_path() {
  local path="$1"
  local hash
  hash=$(echo -n "$path" | cksum | awk '{print $1}')
  local port=$(( 6400 + (hash % 1000) ))
  echo "$port"
  return 0
}

# Stop all daemons
if [[ "$ACTION" == "stop-all" ]]; then
  count=0
  for pid_file in $(find "${HOME}" -name ".daemon.pid" -path "*/.memory/*" 2>/dev/null); do
    pid=$(cat "$pid_file" 2>/dev/null)
    project=$(dirname "$(dirname "$pid_file")")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      # Verify PID belongs to mcp_server.py before killing
      pid_cmd=$(ps -p "$pid" -o args= 2>/dev/null || true)
      if echo "$pid_cmd" | grep -q "mcp_server.py"; then
        kill "$pid" 2>/dev/null
        echo "Stopped daemon for $project (PID $pid)"
        count=$((count + 1))
      else
        echo "Warning: PID $pid does not belong to mcp_server.py (cmd: $pid_cmd), skipping"
      fi
    fi
    rm -f "$pid_file"
  done
  [[ $count -eq 0 ]] && echo "No running daemons found"
  exit 0
fi

# Resolve project dir
if [[ -z "$PROJECT_DIR" ]]; then
  PROJECT_DIR="$(pwd)"
fi
PROJECT_DIR="$(cd "$PROJECT_DIR" 2>/dev/null && pwd || echo "$PROJECT_DIR")"

PERSIST_DIR="$(_realpath "$PROJECT_DIR/.memory")"
PID_FILE="$PERSIST_DIR/.daemon.pid"

# Auto-derive port if not specified
if [[ -z "$PORT" ]]; then
  # Check if a port file exists from a previous run
  if [[ -f "$PERSIST_DIR/.daemon.port" ]]; then
    PORT=$(cat "$PERSIST_DIR/.daemon.port")
  else
    PORT=$(_port_from_path "$PROJECT_DIR")
  fi
fi

# Status check
if [[ "$ACTION" == "status" ]]; then
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Running (PID $(cat "$PID_FILE"), port $PORT)"
    echo "  Project: $PROJECT_DIR"
    echo "  URL:     http://127.0.0.1:$PORT/sse"
  else
    echo "Not running for $PROJECT_DIR"
  fi
  exit 0
fi

# Stop daemon for this project
if [[ "$ACTION" == "stop" ]]; then
  if [[ -f "$PID_FILE" ]]; then
    pid=$(cat "$PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
      # Verify PID belongs to mcp_server.py before killing
      pid_cmd=$(ps -p "$pid" -o args= 2>/dev/null || true)
      if echo "$pid_cmd" | grep -q "mcp_server.py"; then
        kill "$pid" 2>/dev/null
        echo "Stopped memory daemon for $PROJECT_DIR (PID $pid)"
      else
        echo "Warning: PID $pid does not belong to mcp_server.py (cmd: $pid_cmd), skipping"
      fi
    else
      echo "Daemon not running (stale PID $pid)"
    fi
    rm -f "$PID_FILE"
  else
    echo "No daemon running for $PROJECT_DIR"
  fi
  exit 0
fi

# --- Start daemon ---

# Kill existing daemon for this project if running
if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE")"
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Stopping existing daemon (PID $OLD_PID)..."
    kill "$OLD_PID" 2>/dev/null
    sleep 1
  fi
  rm -f "$PID_FILE"
fi

# Check if port is already in use by another project
if command -v ss &>/dev/null && ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
  echo "Port $PORT in use. Trying next available..."
  for _i in $(seq 1 10); do
    PORT=$((PORT + 1))
    if ! ss -tlnp 2>/dev/null | grep -q ":${PORT} "; then
      break
    fi
  done
fi

mkdir -p "$PERSIST_DIR"

echo "Starting memory daemon..."
echo "  Project: $PROJECT_DIR"
echo "  Persist: $PERSIST_DIR"
echo "  Port:    $PORT"
echo "  URL:     http://127.0.0.1:$PORT/sse"

export MEMORY_PERSIST_DIR="$PERSIST_DIR"
export GOOGLE_API_KEY="${GOOGLE_API_KEY}"

nohup "$PYTHON" "$SCRIPT_DIR/mcp_server.py" --transport sse --port "$PORT" \
  > "$PERSIST_DIR/daemon.log" 2>&1 &

DAEMON_PID=$!
echo "$DAEMON_PID" > "$PID_FILE"
echo "$PORT" > "$PERSIST_DIR/.daemon.port"

# Update project MCP config to point to this daemon's port
PROJECT_MCP_CONFIG="$PROJECT_DIR/.agents/mcp/config.json"
if [[ -f "$PROJECT_MCP_CONFIG" ]]; then
  "$PYTHON" - "$PROJECT_MCP_CONFIG" "$PORT" <<'PYEOF'
import json, sys
config_path, port = sys.argv[1], sys.argv[2]
with open(config_path) as f:
    config = json.load(f)
config["mcpServers"]["memory"] = {
    "type": "sse",
    "url": f"http://127.0.0.1:{port}/sse"
}
with open(config_path, "w") as f:
    json.dump(config, f, indent=2)
    f.write("\n")
print(f"  Config: updated {config_path} → port {port}")
PYEOF
fi

# Wait and verify
sleep 1
if kill -0 "$DAEMON_PID" 2>/dev/null; then
  echo "  PID:     $DAEMON_PID"
  echo "  Log:     $PERSIST_DIR/daemon.log"
  echo ""
  echo "Memory daemon started."
  echo "  Stop:   $0 --stop $PROJECT_DIR"
  echo "  Status: $0 --status $PROJECT_DIR"
else
  echo "ERROR: Daemon failed to start. Check $PERSIST_DIR/daemon.log" >&2
  cat "$PERSIST_DIR/daemon.log" 2>/dev/null | tail -10
  rm -f "$PID_FILE" "$PERSIST_DIR/.daemon.port"
  exit 1
fi
