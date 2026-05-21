#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# start-opencode-server.sh — Launch the OpenCode HTTP server
#
# The dashboard master agent (dashboard/master_agent.py) routes all LLM calls
# through this server via the opencode-ai Python SDK.  We start it from
# OSTWIN_PROJECT_DIR when one is configured, otherwise from the managed
# ~/.ostwin/opencode_server fallback.
#
# Provides: start_opencode_server
#
# Requires: lib.sh, globals: INSTALL_DIR, optional SOURCE_DIR / PROJECT_ROOT
# Env:      Loads ~/.ostwin/.env, ~/.ostwin/.env.sh, and project .env files
#           before spawning opencode serve. OPENCODE_BASE_URL defaults to
#           http://127.0.0.1:4096. OPENCODE_SERVER_PASSWORD is honored if set.
# ──────────────────────────────────────────────────────────────────────────────

[[ -n "${_START_OPENCODE_SERVER_SH_LOADED:-}" ]] && return 0
_START_OPENCODE_SERVER_SH_LOADED=1

_is_opencode_serve_process() {
  local pid="$1"
  local comm
  comm=$(ps -p "$pid" -o comm= 2>/dev/null || true)
  local args
  args=$(ps -p "$pid" -o args= 2>/dev/null || true)
  case "$comm $args" in
    *opencode*"serve"*) return 0 ;;
    *) return 1 ;;
  esac
}

# Parse host:port out of OPENCODE_BASE_URL; default 127.0.0.1:4096
_opencode_host_port() {
  local url="${OPENCODE_BASE_URL:-http://127.0.0.1:4096}"
  url="${url#http://}"; url="${url#https://}"
  url="${url%%/*}"
  if [[ "$url" == *:* ]]; then
    echo "${url%%:*} ${url##*:}"
  else
    echo "$url 4096"
  fi
}

_source_opencode_env_file() {
  local env_file="$1"
  [[ -f "$env_file" ]] || return 0
  set -a
  # shellcheck source=/dev/null
  source "$env_file" || true
  set +a
}

_load_opencode_global_env() {
  _source_opencode_env_file "$INSTALL_DIR/.env"
  _source_opencode_env_file "$INSTALL_DIR/.env.sh"
}

_load_opencode_project_env() {
  local project_dir="$1"

  if [[ -n "$project_dir" ]]; then
    _source_opencode_env_file "$project_dir/.env"
    _source_opencode_env_file "$project_dir/.env.sh"
    _source_opencode_env_file "$project_dir/.agents/.env"
    _source_opencode_env_file "$project_dir/.agents/.env.sh"
  fi
}

_load_opencode_service_env() {
  local project_dir="$1"
  _load_opencode_global_env
  _load_opencode_project_env "$project_dir"
}

start_opencode_server() {
  if ! command -v opencode &>/dev/null; then
    warn "opencode CLI not on PATH — skipping server start"
    info "Re-run install.sh or install manually from https://opencode.ai"
    return
  fi

  local server_dir="$INSTALL_DIR/opencode_server"
  mkdir -p "$server_dir"

  _load_opencode_global_env
  local project_dir="${OSTWIN_PROJECT_DIR:-${PROJECT_ROOT:-${SOURCE_DIR:-$server_dir}}}"
  _load_opencode_project_env "$project_dir"

  project_dir="${OSTWIN_PROJECT_DIR:-${PROJECT_ROOT:-$project_dir}}"
  export OSTWIN_PROJECT_DIR="$project_dir"
  mkdir -p "$project_dir"

  local host port
  read -r host port < <(_opencode_host_port)

  mkdir -p "$INSTALL_DIR/logs"

  # Stop any existing opencode serve on the port.  Only kill opencode
  # processes — don't touch other listeners (SSH tunnels, etc.).
  local existing
  existing=$(lsof -ti:"$port" 2>/dev/null || true)
  if [[ -n "$existing" ]]; then
    local oc_pids=""
    for p in $existing; do
      _is_opencode_serve_process "$p" && oc_pids="$oc_pids $p"
    done
    if [[ -n "$oc_pids" ]]; then
      step "Stopping existing opencode server on :$port..."
      echo "$oc_pids" | xargs kill 2>/dev/null || true
      sleep 1
      for p in $oc_pids; do
        kill -0 "$p" 2>/dev/null && kill -9 "$p" 2>/dev/null || true
      done
    fi
  fi

  step "Generating OpenCode tools in ${project_dir}..."
  if [[ -x "$INSTALL_DIR/.venv/bin/python" ]]; then
    "$INSTALL_DIR/.venv/bin/python" -m dashboard.opencode_tools \
      --project-root "$project_dir" \
      --dashboard-port "${DASHBOARD_PORT:-3366}" \
      2>/dev/null || true
  elif command -v python3 &>/dev/null; then
    python3 -m dashboard.opencode_tools \
      --project-root "$project_dir" \
      --dashboard-port "${DASHBOARD_PORT:-3366}" \
      2>/dev/null || true
  fi
  step "Starting opencode server (workdir: $project_dir, listen: $host:$port)..."
  (
    cd "$project_dir"
    nohup opencode serve --hostname "$host" --port "$port" \
      > "$INSTALL_DIR/logs/opencode-server.log" 2>&1 &
    echo $! > "$INSTALL_DIR/opencode.pid"
  )
  local pid
  pid=$(cat "$INSTALL_DIR/opencode.pid" 2>/dev/null || echo "")
  [[ -n "$pid" ]] && echo "[$(date +%H:%M:%S)] VERBAL: opencode serve launched (PID: $pid)"

  # Health-check /global/health up to 30s.
  # NOTE: macOS ships bash 3.2; expanding "${arr[@]}" on an empty array under
  # `set -u` triggers "unbound variable", so use the ${arr[@]+...} guard.
  local auth_args=()
  if [[ -n "${OPENCODE_SERVER_PASSWORD:-}" ]]; then
    auth_args=(-u "${OPENCODE_SERVER_USERNAME:-opencode}:${OPENCODE_SERVER_PASSWORD}")
  fi
  local ok=false
  for _i in $(seq 1 30); do
    if curl -sf ${auth_args[@]+"${auth_args[@]}"} "http://${host}:${port}/global/health" >/dev/null 2>&1; then
      ok=true; break
    fi
    sleep 1
  done

  if $ok; then
    ok "OpenCode server healthy at http://${host}:${port} (PID ${pid:-?})"
  else
    warn "OpenCode server did not respond on http://${host}:${port} in 30s"
    info "Check logs: $INSTALL_DIR/logs/opencode-server.log"
    info "Start manually: cd $project_dir && opencode serve --hostname $host --port $port"
  fi
}
