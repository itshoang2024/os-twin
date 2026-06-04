#!/bin/bash
# Switch memory MCP transport between stdio and sse for a project.
#
# Usage:
#   switch-memory-transport.sh stdio [project-dir]   # switch to stdio (stateless per-call)
#   switch-memory-transport.sh sse [project-dir]      # switch to sse (persistent daemon)
#   switch-memory-transport.sh status [project-dir]   # show current transport

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${OSTWIN_PYTHON:-${HOME}/.ostwin/.venv/bin/python}"
TRANSPORT="${1:-status}"
shift 2>/dev/null || true
PROJECT_DIR="${1:-$(pwd)}"
PROJECT_DIR="$(cd "$PROJECT_DIR" 2>/dev/null && pwd || echo "$PROJECT_DIR")"

# Portable symlink resolution: readlink -f works on Linux and recent macOS,
# but falls back to python on older macOS where -f is unsupported.
_realpath() {
  readlink -f "$1" 2>/dev/null || python3 -c "import os; print(os.path.realpath('$1'))"
}

MCP_CONFIG="$PROJECT_DIR/.agents/mcp/config.json"

if [[ ! -f "$MCP_CONFIG" ]]; then
  echo "No MCP config at $MCP_CONFIG"
  echo "Run 'ostwin init' first."
  exit 1
fi

case "$TRANSPORT" in
  status)
    "$PYTHON" - "$MCP_CONFIG" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    c = json.load(f)
mem = c.get("mcpServers", {}).get("memory", {})
if "type" in mem and mem["type"] == "sse":
    print(f"Transport: sse")
    print(f"URL:       {mem.get('url', 'N/A')}")
    # Check if daemon is running
    import subprocess
    port = mem.get("url", "").split(":")[-1].split("/")[0]
    if port:
        r = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True)
        if f":{port} " in r.stdout:
            print(f"Daemon:    running (port {port})")
        else:
            print(f"Daemon:    NOT running (port {port})")
elif "command" in mem:
    print(f"Transport: stdio")
    print(f"Command:   {mem.get('command', 'N/A')}")
    print(f"Args:      {mem.get('args', [])}")
else:
    print("Transport: unknown")
    print(json.dumps(mem, indent=2))
PYEOF
    ;;

  stdio)
    "$PYTHON" - "$MCP_CONFIG" "$PROJECT_DIR" <<'PYEOF'
import json, sys, os
config_path, project_dir = sys.argv[1], sys.argv[2]
with open(config_path) as f:
    config = json.load(f)

home = os.path.expanduser("~")
# Resolve .memory symlink to the centralized ~/.ostwin/memory directory
persist_dir = os.path.realpath(os.path.join(project_dir, ".memory"))
config["mcpServers"]["memory"] = {
    "command": os.path.join(home, ".ostwin", ".venv", "bin", "python"),
    "args": [os.path.join(home, ".ostwin", "dashboard", "memory", "mcp_server.py")],
    "env": {
        "AGENT_OS_ROOT": project_dir,
        "MEMORY_PERSIST_DIR": persist_dir,
        "GOOGLE_API_KEY": os.environ.get("GOOGLE_API_KEY", "${GOOGLE_API_KEY}")
    }
}

with open(config_path, "w") as f:
    json.dump(config, f, indent=2)
    f.write("\n")
print(f"Switched to stdio")
print(f"  Config: {config_path}")
print(f"  Persist: {persist_dir}")
print(f"  Note: each tool call spawns a new server process (stateless)")
PYEOF
    ;;

  sse)
    # Resolve .memory symlink to centralized directory for port/pid files
    MEMORY_DIR="$(_realpath "$PROJECT_DIR/.memory")"
    PORT_FILE="$MEMORY_DIR/.daemon.port"
    if [[ -f "$PORT_FILE" ]]; then
      PORT=$(cat "$PORT_FILE")
    else
      echo "No SSE daemon running for $PROJECT_DIR"
      echo "Start one with: $SCRIPT_DIR/start-memory-daemon.sh $PROJECT_DIR"
      exit 1
    fi

    # Verify daemon is actually running
    PID_FILE="$MEMORY_DIR/.daemon.pid"
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      "$PYTHON" - "$MCP_CONFIG" "$PORT" <<'PYEOF'
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
print(f"Switched to sse (port {port})")
print(f"  Config: {config_path}")
print(f"  Note: persistent daemon, 60s auto-sync")
PYEOF
    else
      echo "SSE daemon not running for $PROJECT_DIR"
      echo "Start one with: $SCRIPT_DIR/start-memory-daemon.sh $PROJECT_DIR"
      exit 1
    fi
    ;;

  *)
    echo "Usage: $0 {stdio|sse|status} [project-dir]"
    exit 1
    ;;
esac
