#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# start-searxng.sh — Ensure the SearXNG metasearch container is running
#
# Uses docker-compose.searxng.yml from the source tree to create and start
# the container. Falls back to plain `docker run` if compose is unavailable.
#
# Provides: start_searxng
#
# Requires: lib.sh, globals: SOURCE_DIR, INSTALL_DIR
# ──────────────────────────────────────────────────────────────────────────────

# Guard against double-sourcing
[[ -n "${_START_SEARXNG_SH_LOADED:-}" ]] && return 0
_START_SEARXNG_SH_LOADED=1

SEARXNG_CONTAINER_NAME="ostwin-searxng"
SEARXNG_PORT="${SEARXNG_PORT:-8080}"

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

start_searxng() {
  # Skip if Docker CLI is not available
  if ! command -v docker &>/dev/null; then
    warn "Docker not found — skipping SearXNG (web research will be unavailable)"
    return 0
  fi

  # Ensure Docker daemon is running
  if ! _ensure_docker_running; then
    warn "Docker daemon not responding — skipping SearXNG"
    return 0
  fi

  # Check if container is already running
  local _state
  _state="$(docker inspect --format '{{.State.Status}}' "$SEARXNG_CONTAINER_NAME" 2>/dev/null || echo "missing")"

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

  # Container doesn't exist — create via docker compose
  local _compose_file="${SOURCE_DIR}/docker-compose.searxng.yml"

  if [[ -f "$_compose_file" ]] && docker compose version &>/dev/null 2>&1; then
    info "Creating SearXNG container via docker compose..."
    docker compose -f "$_compose_file" up -d >/dev/null 2>&1
  else
    # Fallback: plain docker run (mirrors docker-compose.searxng.yml)
    info "Creating SearXNG container (metasearch engine for web research)..."
    local _config_dir="${SOURCE_DIR}/searxng"
    if [[ ! -d "$_config_dir" ]]; then
      _config_dir="$INSTALL_DIR/searxng"
      mkdir -p "$_config_dir"
      if [[ ! -f "$_config_dir/settings.yml" ]]; then
        cat > "$_config_dir/settings.yml" <<'EOF'
use_default_settings: true
server:
  secret_key: "ostwin-dev-searxng-key"
  bind_address: "0.0.0.0"
  port: 8080
search:
  safe_search: 0
  autocomplete: ""
  default_lang: "en"
  formats:
    - html
    - json
EOF
      fi
    fi

    docker run -d \
      --name "$SEARXNG_CONTAINER_NAME" \
      --restart unless-stopped \
      -p "${SEARXNG_PORT}:8080" \
      -v "${_config_dir}:/etc/searxng:rw" \
      -e "SEARXNG_BASE_URL=http://localhost:${SEARXNG_PORT}/" \
      --cap-drop ALL \
      --cap-add CHOWN \
      --cap-add SETGID \
      --cap-add SETUID \
      searxng/searxng:latest >/dev/null 2>&1
  fi

  # Verify it started
  sleep 2
  if docker inspect --format '{{.State.Status}}' "$SEARXNG_CONTAINER_NAME" 2>/dev/null | grep -q running; then
    ok "SearXNG created and running on :$SEARXNG_PORT"
  else
    warn "SearXNG container created but may not be healthy — check 'docker logs $SEARXNG_CONTAINER_NAME'"
  fi
}
