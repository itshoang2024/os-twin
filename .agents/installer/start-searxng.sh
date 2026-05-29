#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# start-searxng.sh — Ensure the SearXNG metasearch engine is running
#
# Uses docker-compose.searxng.yml from the source tree when Docker Compose is
# available. Falls back to the local source/venv install managed by
# .agents/search-engine.sh when Docker Compose is unavailable.
#
# Provides: start_searxng
#
# Requires: lib.sh, globals: SOURCE_DIR, INSTALL_DIR
# ──────────────────────────────────────────────────────────────────────────────

# Guard against double-sourcing
[[ -n "${_START_SEARXNG_SH_LOADED:-}" ]] && return 0
_START_SEARXNG_SH_LOADED=1

SEARXNG_CONTAINER_NAME="ostwin-searxng"
SEARXNG_PORT="${SEARXNG_PORT:-${OSTWIN_SEARCH_PORT:-6633}}"
SEARCH_ENGINE_MODE="${SEARCH_ENGINE_MODE:-${OSTWIN_SEARCH_ENGINE_MODE:-}}"
export SEARXNG_PORT

_ensure_docker_running() {
  if ! docker info &>/dev/null 2>&1; then
    if [[ "${OS:-}" == "macos" ]]; then
      info "Starting Docker Desktop..."
      open -a Docker 2>/dev/null || true
      local _wait=0
      while ! docker info &>/dev/null 2>&1 && (( _wait < 30 )); do
        sleep 2
        (( _wait += 2 ))
      done
    fi
    if ! docker info &>/dev/null 2>&1; then
      return 1
    fi
  fi
  return 0
}

_searxng_container_uses_port() {
  local _ports
  _ports="$(docker port "$SEARXNG_CONTAINER_NAME" 8080/tcp 2>/dev/null || true)"
  [[ -n "$_ports" ]] && printf '%s\n' "$_ports" | grep -Eq ":${SEARXNG_PORT}$"
}

_searxng_manager_script() {
  local _candidate
  for _candidate in \
    "${INSTALL_DIR:-}/.agents/search-engine.sh" \
    "${SOURCE_DIR:-}/.agents/search-engine.sh"; do
    if [[ -f "$_candidate" ]]; then
      printf '%s\n' "$_candidate"
      return 0
    fi
  done
  return 1
}

_searxng_manual_installed() {
  [[ -x "${INSTALL_DIR:-}/search-engine/searx-pyenv/bin/python" ]] \
    && [[ -d "${INSTALL_DIR:-}/search-engine/searxng-src" ]]
}

_remove_searxng_container_before_manual_start() {
  if command -v docker &>/dev/null \
    && docker info &>/dev/null 2>&1 \
    && docker inspect "$SEARXNG_CONTAINER_NAME" &>/dev/null 2>&1; then
    info "Removing existing SearXNG Docker container before local source start"
    docker rm -f "$SEARXNG_CONTAINER_NAME" >/dev/null 2>&1 || true
  fi
}

_start_searxng_manual() {
  local _reason="${1:-Docker Compose unavailable}"
  local _script
  if ! _script="$(_searxng_manager_script)"; then
    warn "$_reason; search-engine.sh not found, skipping SearXNG"
    return 1
  fi

  info "$_reason; using local SearXNG source install"
  _remove_searxng_container_before_manual_start
  if _searxng_manual_installed; then
    OSTWIN_HOME="$INSTALL_DIR" OSTWIN_SEARCH_PORT="$SEARXNG_PORT" \
      bash "$_script" start --port "$SEARXNG_PORT" --bind 127.0.0.1
  else
    OSTWIN_HOME="$INSTALL_DIR" OSTWIN_SEARCH_PORT="$SEARXNG_PORT" \
      bash "$_script" install --port "$SEARXNG_PORT" --bind 127.0.0.1 --start
  fi
}

start_searxng() {
  local _compose_file="${SOURCE_DIR}/docker-compose.searxng.yml"
  local _mode
  _mode="$(printf '%s' "${SEARCH_ENGINE_MODE:-${OSTWIN_SEARCH_ENGINE_MODE:-docker}}" | tr '[:upper:]' '[:lower:]')"

  case "$_mode" in
    local)
      _start_searxng_manual "Local SearXNG selected"
      return $?
      ;;
    docker)
      ;;
    *)
      warn "Unknown SearXNG install method: $_mode; using docker"
      ;;
  esac

  if ! command -v docker &>/dev/null; then
    _start_searxng_manual "Docker not found"
    return $?
  fi

  if ! docker compose version &>/dev/null 2>&1; then
    _start_searxng_manual "Docker Compose not found"
    return $?
  fi

  if [[ ! -f "$_compose_file" ]]; then
    _start_searxng_manual "SearXNG compose file not found"
    return $?
  fi

  # Ensure Docker daemon is running
  if ! _ensure_docker_running; then
    _start_searxng_manual "Docker daemon not responding"
    return $?
  fi

  # Check if container is already running
  local _state
  _state="$(docker inspect --format '{{.State.Status}}' "$SEARXNG_CONTAINER_NAME" 2>/dev/null || echo "missing")"

  if [[ "$_state" != "missing" ]] && ! _searxng_container_uses_port; then
    warn "Existing SearXNG container is not published on :$SEARXNG_PORT; recreating it"
    docker rm -f "$SEARXNG_CONTAINER_NAME" >/dev/null 2>&1 || true
    _state="missing"
  fi

  if [[ "$_state" == "running" ]]; then
    ok "SearXNG already running on :$SEARXNG_PORT"
    return 0
  fi

  # Container exists but is stopped — start it
  if [[ "$_state" != "missing" ]]; then
    info "Starting existing SearXNG container..."
    docker start "$SEARXNG_CONTAINER_NAME" >/dev/null 2>&1
    ok "SearXNG started on :$SEARXNG_PORT"
    return 0
  fi

  info "Creating SearXNG container via docker compose..."
  docker compose -f "$_compose_file" up -d >/dev/null 2>&1

  # Verify it started
  sleep 2
  if docker inspect --format '{{.State.Status}}' "$SEARXNG_CONTAINER_NAME" 2>/dev/null | grep -q running; then
    ok "SearXNG created and running on :$SEARXNG_PORT"
  else
    warn "SearXNG container created but may not be healthy — check 'docker logs $SEARXNG_CONTAINER_NAME'"
  fi
}
