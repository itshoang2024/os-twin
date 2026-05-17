#!/usr/bin/env bash
# Runtime entrypoint for Docker/Cloud Run.
#
# The image build runs .agents/install.sh with --no-start. This script starts
# the runtime services that must stay alive in the final container:
#   - opencode serve on OPENCODE_BASE_URL
#   - uvicorn dashboard.api:app on $PORT / $DASHBOARD_PORT
set -euo pipefail

APP_DIR="${OSTWIN_APP_DIR:-/app}"
INSTALL_DIR="${OSTWIN_HOME:-/root/.ostwin}"
VENV_DIR="${INSTALL_DIR}/.venv"
LOG_DIR="${INSTALL_DIR}/logs"
SERVER_DIR="${INSTALL_DIR}/opencode_server"

load_env_defaults() {
  local env_file="$1"
  [[ -f "$env_file" ]] || return 0

  local line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      ""|\#*) continue ;;
    esac
    if [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
      key="${line%%=*}"
      value="${line#*=}"
      if [[ -z "${!key+x}" ]]; then
        export "${key}=${value}"
      fi
    fi
  done < "$env_file"
}

parse_opencode_host_port() {
  local url="${OPENCODE_BASE_URL:-http://127.0.0.1:4096}"
  url="${url#http://}"
  url="${url#https://}"
  url="${url%%/*}"
  if [[ "$url" == *:* ]]; then
    OPENCODE_HOST="${url%%:*}"
    OPENCODE_PORT="${url##*:}"
  else
    OPENCODE_HOST="$url"
    OPENCODE_PORT="4096"
  fi
  OPENCODE_HEALTH_HOST="$OPENCODE_HOST"
  if [[ "$OPENCODE_HEALTH_HOST" == "0.0.0.0" ]]; then
    OPENCODE_HEALTH_HOST="127.0.0.1"
  fi
}

stop_children() {
  local status=$?
  trap - INT TERM EXIT
  [[ -n "${DASHBOARD_PID:-}" ]] && kill "$DASHBOARD_PID" 2>/dev/null || true
  [[ -n "${OPENCODE_PID:-}" ]] && kill "$OPENCODE_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  exit "$status"
}

cd "$APP_DIR"
mkdir -p "$LOG_DIR" "$SERVER_DIR"

export OSTWIN_HOME="$INSTALL_DIR"
export PATH="${VENV_DIR}/bin:${INSTALL_DIR}/.agents/bin:${PATH}"

load_env_defaults "$INSTALL_DIR/.env"
if [[ -f "$INSTALL_DIR/.env.sh" ]]; then
  # shellcheck source=/dev/null
  source "$INSTALL_DIR/.env.sh"
fi

export DASHBOARD_PORT="${PORT:-${DASHBOARD_PORT:-3366}}"
export OPENCODE_BASE_URL="${OPENCODE_BASE_URL:-http://127.0.0.1:4096}"
parse_opencode_host_port

if [[ "${OSTWIN_START_OPENCODE:-true}" == "true" ]]; then
  if ! command -v opencode >/dev/null 2>&1; then
    echo "[entrypoint] opencode CLI not found on PATH" >&2
    exit 1
  fi

  echo "[entrypoint] Generating OpenCode tools in ${SERVER_DIR}"
  "${VENV_DIR}/bin/python" -m dashboard.opencode_tools \
    --project-root "$SERVER_DIR" \
    --dashboard-port "$DASHBOARD_PORT"

  echo "[entrypoint] Starting opencode serve on ${OPENCODE_HOST}:${OPENCODE_PORT}"
  (
    cd "$SERVER_DIR"
    exec opencode serve --hostname "$OPENCODE_HOST" --port "$OPENCODE_PORT"
  ) > "$LOG_DIR/opencode-server.log" 2>&1 &
  OPENCODE_PID=$!
  echo "$OPENCODE_PID" > "$INSTALL_DIR/opencode.pid"

  auth_args=()
  if [[ -n "${OPENCODE_SERVER_PASSWORD:-}" ]]; then
    auth_args=(-u "${OPENCODE_SERVER_USERNAME:-opencode}:${OPENCODE_SERVER_PASSWORD}")
  fi

  for _i in $(seq 1 30); do
    if curl -sf "${auth_args[@]}" "http://${OPENCODE_HEALTH_HOST}:${OPENCODE_PORT}/global/health" >/dev/null 2>&1; then
      echo "[entrypoint] OpenCode healthy at http://${OPENCODE_HEALTH_HOST}:${OPENCODE_PORT}"
      break
    fi
    if ! kill -0 "$OPENCODE_PID" 2>/dev/null; then
      echo "[entrypoint] opencode serve exited during startup" >&2
      tail -n 80 "$LOG_DIR/opencode-server.log" >&2 || true
      exit 1
    fi
    if [[ "$_i" == "30" ]]; then
      echo "[entrypoint] OpenCode did not become healthy in 30s" >&2
      tail -n 80 "$LOG_DIR/opencode-server.log" >&2 || true
      exit 1
    fi
    sleep 1
  done
else
  echo "[entrypoint] OSTWIN_START_OPENCODE=false; skipping local OpenCode server"
fi

trap stop_children INT TERM EXIT

echo "[entrypoint] Starting dashboard on 0.0.0.0:${DASHBOARD_PORT}"
"${VENV_DIR}/bin/python" -m uvicorn dashboard.api:app \
  --host 0.0.0.0 \
  --port "$DASHBOARD_PORT" &
DASHBOARD_PID=$!

if [[ -n "${OPENCODE_PID:-}" ]]; then
  wait -n "$OPENCODE_PID" "$DASHBOARD_PID"
else
  wait "$DASHBOARD_PID"
fi
