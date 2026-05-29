#!/usr/bin/env bash
# Ostwin local search engine manager.
#
# Installs and runs SearXNG from a user-owned tree under ~/.ostwin.

set -euo pipefail

OSTWIN_HOME="${OSTWIN_HOME:-$HOME/.ostwin}"
SEARCH_HOME="${OSTWIN_SEARCH_HOME:-$OSTWIN_HOME/search-engine}"
SRC_DIR="$SEARCH_HOME/searxng-src"
VENV_DIR="$SEARCH_HOME/searx-pyenv"
CONFIG_DIR="$SEARCH_HOME/etc"
SETTINGS_PATH="${SEARXNG_SETTINGS_PATH:-$CONFIG_DIR/settings.yml}"
PID_FILE="$SEARCH_HOME/searxng.pid"
LOG_DIR="$OSTWIN_HOME/logs"
DEFAULT_PORT="${OSTWIN_SEARCH_PORT:-6633}"
DEFAULT_BIND="${OSTWIN_SEARCH_BIND:-127.0.0.1}"
REPO_URL="${OSTWIN_SEARCH_REPO:-https://github.com/searxng/searxng}"

usage() {
  cat <<'EOF'
ostwin search-engine -- manage the local SearXNG search engine

Usage:
  ostwin search-engine install [--port PORT] [--bind HOST] [--start]
  ostwin search-engine configure [--port PORT] [--bind HOST]
  ostwin search-engine start [--port PORT] [--bind HOST]
  ostwin search-engine stop
  ostwin search-engine status
  ostwin search-engine settings

Files:
  source:   ~/.ostwin/search-engine/searxng-src
  venv:     ~/.ostwin/search-engine/searx-pyenv
  config:   ~/.ostwin/search-engine/etc/settings.yml
  logs:     ~/.ostwin/logs/searxng.log
EOF
}

info() { printf '  %s\n' "$*"; }
ok() { printf '  [OK] %s\n' "$*"; }
fail() { printf '  [ERROR] %s\n' "$*" >&2; }

parse_port_bind() {
  PORT="$DEFAULT_PORT"
  BIND="$DEFAULT_BIND"
  START_AFTER_INSTALL=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --port)
        if [[ $# -lt 2 ]]; then
          fail "--port requires a value"
          exit 1
        fi
        PORT="${2:-}"
        shift 2
        ;;
      --bind|--host)
        if [[ $# -lt 2 ]]; then
          fail "$1 requires a value"
          exit 1
        fi
        BIND="${2:-}"
        shift 2
        ;;
      --start)
        START_AFTER_INSTALL=true
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fail "Unknown option: $1"
        usage
        exit 1
        ;;
    esac
  done

  if [[ ! "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then
    fail "Invalid port: $PORT"
    exit 1
  fi
  if [[ -z "$BIND" ]]; then
    fail "Bind host cannot be empty"
    exit 1
  fi
}

ensure_prereqs() {
  command -v git >/dev/null 2>&1 || { fail "git is required"; exit 1; }
  command -v python3 >/dev/null 2>&1 || { fail "python3 is required"; exit 1; }
}

ensure_dirs() {
  mkdir -p "$SEARCH_HOME" "$CONFIG_DIR" "$LOG_DIR"
}

secret_key() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
}

write_minimal_settings() {
  ensure_dirs
  local secret
  secret="$(secret_key)"
  cat > "$SETTINGS_PATH" <<EOF
# Managed by Ostwin. Edit with: ostwin search-engine configure
use_default_settings: true

general:
  debug: false
  instance_name: "Ostwin Search"

search:
  safe_search: 0
  autocomplete: "google"
  formats:
    - html
    - json

server:
  port: $PORT
  bind_address: "$BIND"
  secret_key: "$secret"
  limiter: false
  image_proxy: true
  method: "GET"

ui:
  query_in_title: false

engines:
  - name: bing
    disabled: false
  - name: google
    disabled: false
EOF
  ok "Wrote SearXNG settings: $SETTINGS_PATH"
}

settings_python() {
  if [[ -x "$VENV_DIR/bin/python" ]]; then
    printf '%s\n' "$VENV_DIR/bin/python"
  else
    printf '%s\n' "python3"
  fi
}

patch_settings_yaml() {
  local py="$1"
  local secret="$2"
  "$py" - "$SETTINGS_PATH" "$PORT" "$BIND" "$secret" <<'PY'
import sys
from pathlib import Path

import yaml

settings_path = Path(sys.argv[1])
port = int(sys.argv[2])
bind = sys.argv[3]
secret = sys.argv[4]

with settings_path.open("r", encoding="utf-8") as f:
    data = yaml.safe_load(f) or {}

data["use_default_settings"] = True

general = data.setdefault("general", {})
general["debug"] = False
general["instance_name"] = "Ostwin Search"

search = data.setdefault("search", {})
search["safe_search"] = 0
search["autocomplete"] = "google"
formats = search.get("formats") or []
if not isinstance(formats, list):
    formats = [formats]
for fmt in ("html", "json"):
    if fmt not in formats:
        formats.append(fmt)
search["formats"] = formats

server = data.setdefault("server", {})
server["port"] = port
server["bind_address"] = bind
server["secret_key"] = secret
server["limiter"] = False
server["image_proxy"] = True
server["method"] = "GET"

ui = data.setdefault("ui", {})
ui["query_in_title"] = False

engines = data.setdefault("engines", [])
if not isinstance(engines, list):
    engines = []
    data["engines"] = engines

by_name = {
    engine.get("name"): engine
    for engine in engines
    if isinstance(engine, dict)
}
for name in ("bing", "google"):
    engine = by_name.get(name)
    if engine is None:
        engine = {"name": name}
        engines.append(engine)
    engine["disabled"] = False

with settings_path.open("w", encoding="utf-8") as f:
    yaml.safe_dump(data, f, sort_keys=False, allow_unicode=False)
PY
}

write_settings() {
  ensure_dirs
  local template="$SRC_DIR/utils/templates/etc/searxng/settings.yml"
  local secret
  secret="$(secret_key)"

  if [[ -f "$template" ]]; then
    cp "$template" "$SETTINGS_PATH"
    local py
    py="$(settings_python)"
    if "$py" -c "import yaml" >/dev/null 2>&1; then
      patch_settings_yaml "$py" "$secret"
      ok "Copied SearXNG template and wrote settings: $SETTINGS_PATH"
    else
      info "PyYAML unavailable in $py; writing minimal settings instead"
      write_minimal_settings
    fi
  else
    info "SearXNG settings template not found; writing minimal settings"
    write_minimal_settings
  fi
}

install_source() {
  ensure_prereqs
  ensure_dirs

  if [[ -d "$SRC_DIR/.git" ]]; then
    info "Updating SearXNG source in $SRC_DIR"
    git -C "$SRC_DIR" fetch --depth 1 origin
    local default_branch
    default_branch="$(git -C "$SRC_DIR" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##' || true)"
    if [[ -z "$default_branch" ]]; then
      default_branch="$(git -C "$SRC_DIR" branch --show-current 2>/dev/null || true)"
    fi
    default_branch="${default_branch:-master}"
    git -C "$SRC_DIR" reset --hard "origin/$default_branch"
  else
    rm -rf "$SRC_DIR"
    info "Cloning SearXNG into $SRC_DIR"
    git clone --depth 1 "$REPO_URL" "$SRC_DIR"
  fi
}

install_venv() {
  ensure_prereqs
  if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtualenv: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi

  local pip="$VENV_DIR/bin/pip"
  info "Installing SearXNG build requirements"
  "$pip" install -U pip
  "$pip" install -U setuptools
  "$pip" install -U wheel
  "$pip" install -U pyyaml
  "$pip" install -U msgspec
  "$pip" install -U typing-extensions
  "$pip" install -U pybind11

  info "Installing SearXNG editable package"
  (cd "$SRC_DIR" && "$pip" install --use-pep517 --no-build-isolation -e .)
}

is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(tr -d '[:space:]' < "$PID_FILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

pid_value() {
  tr -d '[:space:]' < "$PID_FILE" 2>/dev/null || true
}

server_url() {
  printf 'http://%s:%s' "$BIND" "$PORT"
}

is_serving() {
  command -v curl >/dev/null 2>&1 || return 1
  curl -fsS \
    -H "X-Forwarded-For: 127.0.0.1" \
    -H "X-Real-IP: 127.0.0.1" \
    --max-time 3 "$(server_url)/" >/dev/null 2>&1
}

start_server() {
  parse_port_bind "$@"
  if [[ ! -x "$VENV_DIR/bin/python" || ! -d "$SRC_DIR" ]]; then
    fail "SearXNG is not installed. Run: ostwin search-engine install"
    exit 1
  fi
  if [[ ! -f "$SETTINGS_PATH" ]]; then
    write_settings
  fi
  if is_running; then
    if is_serving; then
      ok "SearXNG already running (PID $(pid_value))"
      info "URL: $(server_url)"
      return
    fi
    info "SearXNG PID $(pid_value) is not serving on $(server_url); restarting"
    stop_server
  fi

  ensure_dirs
  info "Starting SearXNG on $(server_url)"
  (
    cd "$SRC_DIR"
    export SEARXNG_SETTINGS_PATH="$SETTINGS_PATH"
    export SEARXNG_PORT="$PORT"
    export SEARXNG_BIND_ADDRESS="$BIND"
    nohup "$VENV_DIR/bin/python" -m searx.webapp > "$LOG_DIR/searxng.log" 2>&1 &
    echo $! > "$PID_FILE"
  )

  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if ! is_running; then
      break
    fi
    if is_serving; then
      ok "SearXNG started (PID $(pid_value))"
      info "URL: $(server_url)"
      info "Log: $LOG_DIR/searxng.log"
      return
    fi
    sleep 1
  done

  if is_running; then
    fail "SearXNG started but is not responding on $(server_url). Check $LOG_DIR/searxng.log"
    info "Log: $LOG_DIR/searxng.log"
  else
    fail "SearXNG failed to start. Check $LOG_DIR/searxng.log"
  fi
  exit 1
}

stop_server() {
  if ! is_running; then
    info "SearXNG is not running"
    rm -f "$PID_FILE"
    return
  fi

  local pid
  pid="$(tr -d '[:space:]' < "$PID_FILE")"
  info "Stopping SearXNG (PID $pid)"
  kill "$pid" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  ok "SearXNG stopped"
}

status_server() {
  PORT="$DEFAULT_PORT"
  BIND="$DEFAULT_BIND"
  if is_running; then
    if is_serving; then
      ok "SearXNG running (PID $(pid_value))"
    else
      info "SearXNG process exists (PID $(pid_value)) but is not responding on $(server_url)"
    fi
  else
    info "SearXNG is not running"
  fi
  info "Home: $SEARCH_HOME"
  info "Settings: $SETTINGS_PATH"
  info "URL: $(server_url)"
}

cmd="${1:-help}"
shift || true

case "$cmd" in
  install)
    parse_port_bind "$@"
    install_source
    install_venv
    write_settings
    ok "Search engine installed under $SEARCH_HOME"
    info "Start it with: ostwin search-engine start"
    if [[ "$START_AFTER_INSTALL" == true ]]; then
      start_server --port "$PORT" --bind "$BIND"
    fi
    ;;
  configure)
    parse_port_bind "$@"
    write_settings
    ;;
  start)
    start_server "$@"
    ;;
  stop)
    stop_server
    ;;
  status)
    status_server
    ;;
  settings)
    if [[ -f "$SETTINGS_PATH" ]]; then
      printf '%s\n' "$SETTINGS_PATH"
    else
      fail "Settings file does not exist yet: $SETTINGS_PATH"
      exit 1
    fi
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    fail "Unknown subcommand: $cmd"
    usage
    exit 1
    ;;
esac
