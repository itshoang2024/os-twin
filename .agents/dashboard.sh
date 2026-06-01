#!/usr/bin/env bash
# Ostwin — Web Dashboard Launcher
#
# Starts the FastAPI web dashboard for monitoring war-rooms.
#
# Usage: dashboard.sh [--port PORT] [--project-dir PATH] [--background]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "[$(date +%H:%M:%S)] VERBAL: dashboard.sh script started in $SCRIPT_DIR"
AGENTS_DIR="$SCRIPT_DIR"
# Resolve Python: local .venv → ~/.ostwin/.venv (install dir) → system python3
PYTHON="${AGENTS_DIR}/.venv/bin/python"
echo "[$(date +%H:%M:%S)] VERBAL: Using Python: $PYTHON"
[[ -x "$PYTHON" ]] || PYTHON="$HOME/.ostwin/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="python3"

# Resolve dashboard directory:
#   1. Inside .agents/dashboard/ (installed via ostwin init)
#   2. Sibling to .agents/ (source repo layout)
if [[ -d "$AGENTS_DIR/dashboard" ]]; then
  DASHBOARD_DIR="$AGENTS_DIR/dashboard"
elif [[ -d "$AGENTS_DIR/../dashboard" ]]; then
  DASHBOARD_DIR="$AGENTS_DIR/../dashboard"
else
  DASHBOARD_DIR=""
fi
PORT=3366
PROJECT_DIR="$(pwd)"
BACKGROUND=false

SKIP_BUILD=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)        PORT="$2"; shift 2 ;;
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    --background)  BACKGROUND=true; shift ;;
    --skip-build)  SKIP_BUILD=true; shift ;;
    -h|--help)
      echo "Usage: dashboard.sh [--port PORT] [--project-dir PATH] [--background] [--skip-build]"
      echo "  --port PORT         Server port (default: 3366)"
      echo "  --project-dir PATH  Project to monitor (default: current directory)"
      echo "  --background        Run in background"
      echo "  --skip-build        Skip Next.js frontend rebuild"
      exit 0
      ;;
    *) shift ;;
  esac
done

if [[ -z "$DASHBOARD_DIR" ]] || [[ ! -f "$DASHBOARD_DIR/api.py" ]]; then
  echo "[ERROR] Web dashboard not found." >&2
  echo "  Looked in:" >&2
  echo "    $AGENTS_DIR/dashboard/api.py" >&2
  echo "    $AGENTS_DIR/../dashboard/api.py" >&2
  echo "" >&2
  echo "  If installed via 'ostwin init', re-run init to copy the dashboard." >&2
  echo "  If running from source, ensure dashboard/api.py exists alongside .agents/." >&2
  exit 1
fi

# Check Python dependencies
"$PYTHON" -c "import fastapi, uvicorn" 2>/dev/null || {
  echo "[ERROR] Missing Python dependencies." >&2
  echo "  Install with: pip install fastapi uvicorn" >&2
  exit 1
}

# Resolve project dir to absolute path
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"

select_dashboard_pm() {
  local fe_dir="$1"
  if [[ ( -f "$fe_dir/bun.lockb" || -f "$fe_dir/bun.lock" ) ]] && command -v bun >/dev/null 2>&1; then
    printf '%s\n' "bun"
    return 0
  fi
  if [[ ( -f "$fe_dir/package-lock.json" || -f "$fe_dir/npm-shrinkwrap.json" ) ]] && command -v npm >/dev/null 2>&1; then
    printf '%s\n' "npm"
    return 0
  fi
  if command -v npm >/dev/null 2>&1; then
    printf '%s\n' "npm"
    return 0
  fi
  if command -v bun >/dev/null 2>&1; then
    printf '%s\n' "bun"
    return 0
  fi
  return 1
}

install_dashboard_deps() {
  local pm="$1"
  case "$pm" in
    bun)
      if [[ -f bun.lockb || -f bun.lock ]]; then
        bun install --frozen-lockfile 2>/dev/null || bun install
      else
        bun install
      fi
      ;;
    npm)
      if [[ -f package-lock.json || -f npm-shrinkwrap.json ]]; then
        npm ci 2>/dev/null || npm install
      else
        npm install
      fi
      ;;
    *)
      return 1
      ;;
  esac
}

# Build frontend if source is newer than output (unless skipped)
FE_DIR="$DASHBOARD_DIR/fe"
FE_OUT="$FE_DIR/out"
if [[ "$SKIP_BUILD" == "false" && -d "$FE_DIR" && -f "$FE_DIR/package.json" ]]; then
  if [[ ! -d "$FE_OUT" ]] || [[ -n "$(find "$FE_DIR/src" -newer "$FE_OUT" -print -quit 2>/dev/null)" ]]; then
    DASHBOARD_PM="$(select_dashboard_pm "$FE_DIR" || true)"
    if [[ -z "$DASHBOARD_PM" ]]; then
      echo "[WARN] No JavaScript package manager found (expected bun or npm) — serving with stale assets" >&2
    else
      echo "[DASHBOARD] Building frontend with $DASHBOARD_PM..."
      (cd "$FE_DIR" && install_dashboard_deps "$DASHBOARD_PM" && "$DASHBOARD_PM" run build 2>&1) || {
        echo "[WARN] Frontend build failed — serving with stale assets" >&2
      }
    fi
  fi
fi

PID_FILE="$AGENTS_DIR/dashboard.pid"

# Log verbosity for the dashboard's file log (~/.ostwin/dashboard/debug.log).
# Defaults to DEBUG; override by exporting OSTWIN_LOG_LEVEL (e.g. in .env).
export OSTWIN_LOG_LEVEL="${OSTWIN_LOG_LEVEL:-DEBUG}"

# Raise open-file limit — the polling loop + background zvec sync can easily
# exhaust macOS's default 256-fd limit, causing "Too many open files" errors.
ulimit -n 4096 2>/dev/null || ulimit -n 2048 2>/dev/null || true

if $BACKGROUND; then
  DASHBOARD_LOG_DIR="$HOME/.ostwin/dashboard"
  mkdir -p "$DASHBOARD_LOG_DIR"
  echo "[DASHBOARD] Starting in background on http://localhost:${PORT}"
  echo "  Project: $PROJECT_DIR"
  cd "$DASHBOARD_DIR"
  echo "[$(date +%H:%M:%S)] VERBAL: Starting python api.py with nohup..."
  nohup "$PYTHON" api.py --port "$PORT" --project-dir "$PROJECT_DIR" > "$DASHBOARD_LOG_DIR/stdout.log" 2>&1 &
  DASH_PID=$!
  echo "$DASH_PID" > "$PID_FILE"
  echo "  PID: $DASH_PID"
  echo "  Logs: $DASHBOARD_LOG_DIR/debug.log (debug) | stdout.log (raw)"
  # Check for ngrok tunnel after dashboard starts
  sleep 3
  TUNNEL_URL=$(curl -sf "http://localhost:${PORT}/api/tunnel/status" 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('url',''))" 2>/dev/null || true)
  if [[ -n "$TUNNEL_URL" ]]; then
    echo "  Tunnel: $TUNNEL_URL"
  fi
else
  echo "[DASHBOARD] Starting web dashboard on http://localhost:${PORT}"
  echo "  Project: $PROJECT_DIR"
  echo "  War-rooms: $PROJECT_DIR/.war-rooms"
  echo "  Press Ctrl+C to stop."
  echo ""
  echo "$$" > "$PID_FILE"
  cd "$DASHBOARD_DIR"
  exec "$PYTHON" api.py --port "$PORT" --project-dir "$PROJECT_DIR"
fi

