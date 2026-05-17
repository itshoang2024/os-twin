#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# start-dashboard.sh — Dashboard launch, health check, tunnel detection
#
# Provides: start_dashboard, publish_skills
#
# Requires: lib.sh, check-deps.sh, globals: INSTALL_DIR, VENV_DIR,
#           DASHBOARD_PORT, OSTWIN_API_KEY
# ──────────────────────────────────────────────────────────────────────────────

# Guard against double-sourcing
[[ -n "${_START_DASHBOARD_SH_LOADED:-}" ]] && return 0
_START_DASHBOARD_SH_LOADED=1

_is_dashboard_process_for_port() {
  local pid="$1"
  local port="$2"
  local comm
  comm=$(ps -p "$pid" -o comm= 2>/dev/null || true)
  local args
  args=$(ps -p "$pid" -o args= 2>/dev/null || true)
  case "$comm $args" in
    *uvicorn*|*api.py*"--port $port"*) return 0 ;;
    *) return 1 ;;
  esac
}

start_dashboard() {
  local dashboard_script="$INSTALL_DIR/.agents/dashboard.sh"
  if [[ ! -f "$dashboard_script" ]] || [[ ! -f "$INSTALL_DIR/dashboard/api.py" ]]; then
    warn "Dashboard not found — skipping auto-start"
    info "Re-run: ./install.sh --source-dir /path/to/agent-os"
    return
  fi

  # ╔══════════════════════════════════════════════════════════════════╗
  # ║  DO NOT simplify this to "lsof | xargs kill" !                 ║
  # ║                                                                ║
  # ║  lsof returns ALL processes on the port — including SSH        ║
  # ║  tunnels and VS Code port forwards (ESTABLISHED connections).  ║
  # ║  Killing those drops the developer's SSH session.              ║
  # ║                                                                ║
  # ║  We MUST filter by process name (python/uvicorn) to only       ║
  # ║  kill the old dashboard, not the developer's IDE connection.   ║
  # ╚══════════════════════════════════════════════════════════════════╝
  local local_pids
  local_pids=$(lsof -ti:"$DASHBOARD_PORT" 2>/dev/null || true)
  if [[ -n "$local_pids" ]]; then
    local py_pids=""
    for p in $local_pids; do
      _is_dashboard_process_for_port "$p" "$DASHBOARD_PORT" && py_pids="$py_pids $p"
    done
    if [[ -n "$py_pids" ]]; then
      step "Stopping existing dashboard on :$DASHBOARD_PORT..."
      echo "$py_pids" | xargs kill 2>/dev/null || true
      sleep 2
      for p in $py_pids; do
        kill -0 "$p" 2>/dev/null && kill -9 "$p" 2>/dev/null || true
      done
    fi
  fi

  # Source .env so the dashboard process inherits API keys
  local env_file="$INSTALL_DIR/.env"
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$env_file"
    set +a
  fi

  mkdir -p "$INSTALL_DIR/logs"
  step "Starting dashboard on http://localhost:${DASHBOARD_PORT}..."
  echo "[$(date +%H:%M:%S)] VERBAL: Launching dashboard.sh with --skip-build..."
  # Pin --project-dir to $INSTALL_DIR
  nohup bash "$dashboard_script" \
    --background --port "$DASHBOARD_PORT" \
    --project-dir "$INSTALL_DIR" \
    --skip-build \
    > "$INSTALL_DIR/logs/dashboard.log" 2>&1 &
  DASHBOARD_PID=$!
  echo "[$(date +%H:%M:%S)] VERBAL: dashboard.sh launched (PID: $DASHBOARD_PID)"
  echo "$DASHBOARD_PID" > "$INSTALL_DIR/dashboard.pid"

  # Read OSTWIN_API_KEY for auth headers
  OSTWIN_API_KEY="${OSTWIN_API_KEY:-}"

  # Health-check: poll /api/status up to 60s
  step "Waiting for dashboard to be healthy (up to 60s)..."
  local start_time
  start_time=$(get_now)
  DASH_OK=false
  for _i in $(seq 1 60); do
    if [[ -n "$OSTWIN_API_KEY" ]]; then
      curl -v -sf "http://127.0.0.1:${DASHBOARD_PORT}/api/status" >/tmp/ostwin_curl.log 2>&1 && DASH_OK=true
    else
      curl -v -sf "http://127.0.0.1:${DASHBOARD_PORT}/api/status" >/tmp/ostwin_curl.log 2>&1 && DASH_OK=true
    fi
    if $DASH_OK; then break; fi
    echo "  [$(date +%H:%M:%S)] Health check failed (attempt $_i/60). Details: $(tail -n 1 /tmp/ostwin_curl.log)"
    sleep 1
  done

  if $DASH_OK; then
    ok_time "Dashboard healthy at http://localhost:${DASHBOARD_PORT} (PID $DASHBOARD_PID)" "$(print_duration "$start_time")"
    _check_tunnel
  else
    warn "Dashboard did not respond in 60s — check $INSTALL_DIR/logs/dashboard.log"
    info "Start manually: bash $dashboard_script"
  fi
}

publish_skills() {
  header "9b. Publishing skills to backend"
  local start_time
  start_time=$(get_now)
  local sync_script="$INSTALL_DIR/.agents/sync-skills.sh"
  if [[ -x "$sync_script" ]]; then
    OSTWIN_HOME="$INSTALL_DIR" DASHBOARD_PORT="$DASHBOARD_PORT" \
      bash "$sync_script" --install-from "$INSTALL_DIR/.agents" \
      && ok_time "Skills published" "$(print_duration "$start_time")"
  else
    warn "sync-skills.sh not found — skipping skill sync"
    info "Expected at $sync_script"
  fi
}

# ─── Internal helpers ────────────────────────────────────────────────────────

_check_tunnel() {
  # Check for ngrok tunnel URL
  local tunnel_url=""
  local tunnel_error=""
  local python_for_tunnel="$VENV_DIR/bin/python"
  [[ -x "$python_for_tunnel" ]] || python_for_tunnel="python3"
  local tunnel_json=""
  if [[ -n "${OSTWIN_API_KEY:-}" ]]; then
    tunnel_json=$(curl -sf -H "X-API-Key: $OSTWIN_API_KEY" \
      "http://localhost:${DASHBOARD_PORT}/api/tunnel/status" 2>/dev/null || true)
  else
    tunnel_json=$(curl -sf \
      "http://localhost:${DASHBOARD_PORT}/api/tunnel/status" 2>/dev/null || true)
  fi
  if [[ -n "$tunnel_json" ]]; then
    tunnel_url=$("$python_for_tunnel" -c "import sys,json; print(json.load(sys.stdin).get('url') or '')" <<< "$tunnel_json" 2>/dev/null || true)
    tunnel_error=$("$python_for_tunnel" -c "import sys,json; print(json.load(sys.stdin).get('error') or '')" <<< "$tunnel_json" 2>/dev/null || true)
  fi
  if [[ -n "$tunnel_url" ]]; then
    ok "Tunnel active: $tunnel_url"
    # shellcheck disable=SC2034  # consumed by verify.sh banner
    TUNNEL_URL="$tunnel_url"
  elif [[ -n "$tunnel_error" ]]; then
    warn "Tunnel failed: $tunnel_error"
  elif [[ -z "${NGROK_AUTHTOKEN:-}" ]]; then
    info "Tunnel not configured — set NGROK_AUTHTOKEN in ~/.ostwin/.env to enable port forwarding"
  else
    warn "Tunnel not active — check dashboard logs at $INSTALL_DIR/logs/dashboard.log"
  fi
}
