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

_dashboard_port_listeners() {
  local port="$1"
  lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
}

# Detect an OS-level supervisor (LaunchAgent / systemd user unit) that
# would auto-respawn the dashboard. When one is active, we MUST restart via
# the supervisor — otherwise launchd/systemd races our manual start, both
# fight for the port, and the loser's exit leaves a stale PID file.
_dashboard_supervisor() {
  case "${OS:-}" in
    macos)
      if launchctl list 2>/dev/null | awk '{print $3}' | grep -qx "com.ostwin.dashboard"; then
        echo "launchd"
        return 0
      fi
      ;;
    linux)
      if command -v systemctl >/dev/null 2>&1 \
         && systemctl --user is-enabled ostwin-dashboard.service >/dev/null 2>&1; then
        echo "systemd"
        return 0
      fi
      ;;
  esac
  echo ""
  return 1
}

_restart_dashboard_via_supervisor() {
  local supervisor="$1"
  local port="$2"
  case "$supervisor" in
    launchd)
      local uid
      uid="$(id -u)"
      step "Restarting dashboard via launchctl (com.ostwin.dashboard)..."
      # kickstart -k stops and restarts the job atomically; launchd remains
      # the sole owner of the process, so there is no race for the port.
      if launchctl kickstart -k "gui/${uid}/com.ostwin.dashboard" 2>/dev/null; then
        return 0
      fi
      # Older launchctl (pre-10.10) doesn't know kickstart. Fall back to
      # unload + load using the installed plist.
      local plist="$HOME/Library/LaunchAgents/com.ostwin.dashboard.plist"
      if [[ -f "$plist" ]]; then
        launchctl unload "$plist" 2>/dev/null || true
        launchctl load -w "$plist" 2>/dev/null && return 0
      fi
      return 1
      ;;
    systemd)
      step "Restarting dashboard via systemctl (ostwin-dashboard)..."
      systemctl --user restart ostwin-dashboard.service && return 0
      return 1
      ;;
  esac
  return 1
}

# Kill every local process listening on $port so a fresh install can replace
# the dashboard cleanly. Restrict to LISTEN sockets to avoid touching clients.
_kill_dashboard_port_listeners() {
  local port="$1"
  local listener_pids
  listener_pids="$(_dashboard_port_listeners "$port")"
  [[ -n "$listener_pids" ]] || return 0

  step "Stopping processes listening on :$port..."
  echo "$listener_pids" | xargs kill 2>/dev/null || true
  # Wait up to 10s for graceful shutdown before SIGKILL.
  for _i in $(seq 1 10); do
    local still_alive=""
    for p in $listener_pids; do
      kill -0 "$p" 2>/dev/null && still_alive="$still_alive $p"
    done
    [[ -z "$still_alive" ]] && break
    sleep 1
  done
  for p in $listener_pids; do
    kill -0 "$p" 2>/dev/null && kill -9 "$p" 2>/dev/null || true
  done
  # Confirm the port is actually free before returning.
  for _i in $(seq 1 5); do
    [[ -z "$(_dashboard_port_listeners "$port")" ]] && return 0
    sleep 1
  done
  warn "Port :$port is still occupied after stop attempts"
  return 1
}

start_dashboard() {
  local dashboard_script="$INSTALL_DIR/.agents/dashboard.sh"
  if [[ ! -f "$dashboard_script" ]] || [[ ! -f "$INSTALL_DIR/dashboard/api.py" ]]; then
    warn "Dashboard not found — skipping auto-start"
    info "Re-run: ./install.sh --source-dir /path/to/agent-os"
    return
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
  local runtime_pid_file="$INSTALL_DIR/.agents/dashboard.pid"

  local supervisor
  supervisor="$(_dashboard_supervisor || true)"

  if [[ -n "$supervisor" ]]; then
    # Supervisor remains responsible for the managed dashboard lifecycle, but
    # first clear any stray/manual listener that the supervisor would not stop.
    # This avoids a restart racing an unmanaged debug process for the port.
    _kill_dashboard_port_listeners "$DASHBOARD_PORT" || true
    _restart_dashboard_via_supervisor "$supervisor" "$DASHBOARD_PORT" \
      || {
        warn "Supervisor restart failed; new dashboard may not load"
        return 1
      }
  else
    if ! _kill_dashboard_port_listeners "$DASHBOARD_PORT"; then
      warn "Dashboard port :$DASHBOARD_PORT is still occupied; refusing to start over an unknown listener"
      return 1
    fi

    rm -f "$runtime_pid_file"
    step "Starting dashboard on http://localhost:${DASHBOARD_PORT}..."
    echo "[$(date +%H:%M:%S)] VERBAL: Launching dashboard.sh with --skip-build..."
    nohup bash "$dashboard_script" \
      --background --port "$DASHBOARD_PORT" \
      --project-dir "$INSTALL_DIR" \
      --skip-build \
      > "$INSTALL_DIR/logs/dashboard.log" 2>&1 &
    DASHBOARD_WRAPPER_PID=$!
    echo "[$(date +%H:%M:%S)] VERBAL: dashboard.sh launched (PID: $DASHBOARD_WRAPPER_PID)"
    echo "$DASHBOARD_WRAPPER_PID" > "$INSTALL_DIR/dashboard.pid"
  fi

  OSTWIN_API_KEY="${OSTWIN_API_KEY:-}"
  local curl_log="$INSTALL_DIR/logs/dashboard-health-curl.log"
  if ! : > "$curl_log" 2>/dev/null; then
    curl_log=$(mktemp "${TMPDIR:-/tmp}/ostwin-curl-${UID:-$(id -u)}.XXXXXX")
  fi

  # Health check: the only reliable signal is "something is listening on the
  # port AND /api/status responds". Under a supervisor we don't own the PID
  # file, so checking it is unsafe — go straight to the socket.
  step "Waiting for dashboard to be healthy (up to 60s)..."
  local start_time
  start_time=$(get_now)
  DASH_OK=false
  DASHBOARD_PID=""
  for _i in $(seq 1 60); do
    if [[ -f "$runtime_pid_file" ]]; then
      DASHBOARD_PID="$(cat "$runtime_pid_file" 2>/dev/null || true)"
    fi
    local listener
    listener="$(_dashboard_port_listeners "$DASHBOARD_PORT" | head -n1 || true)"
    if [[ -n "$listener" ]]; then
      if curl -sf "http://127.0.0.1:${DASHBOARD_PORT}/api/status" >"$curl_log" 2>&1; then
        DASH_OK=true
        [[ -z "$DASHBOARD_PID" ]] && DASHBOARD_PID="$listener"
        break
      fi
    else
      printf 'Nothing listening on port %s yet\n' "$DASHBOARD_PORT" > "$curl_log"
    fi
    echo "  [$(date +%H:%M:%S)] Health check failed (attempt $_i/60). Details: $(tail -n 1 "$curl_log" 2>/dev/null || true)"
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
  elif [[ "${OSTWIN_NGROK_ENABLED:-true}" =~ ^(0|false|no|off)$ ]]; then
    info "Tunnel disabled — run build/install with --ngrok to enable port forwarding"
  elif [[ -z "${NGROK_AUTHTOKEN:-}" ]]; then
    info "Tunnel not configured — set NGROK_AUTHTOKEN in ~/.ostwin/.env to enable port forwarding"
  else
    warn "Tunnel not active — check dashboard logs at $INSTALL_DIR/logs/dashboard.log"
  fi
}
