#!/usr/bin/env bats
# Tests for start-searxng.sh

setup() {
  INSTALLER_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  unset SEARXNG_PORT
  unset SEARCH_ENGINE_MODE
  unset OSTWIN_SEARCH_ENGINE_MODE
  source "$INSTALLER_DIR/lib.sh"
  source "$INSTALLER_DIR/start-searxng.sh"
}

@test "start-searxng.sh can be sourced without side effects" {
  [[ -n "$_START_SEARXNG_SH_LOADED" ]]
}

@test "start_searxng function is defined" {
  declare -f start_searxng > /dev/null
}

@test "SearXNG docker helper defaults to host port 6633" {
  [ "$SEARXNG_PORT" = "6633" ]
}

@test "start-searxng.sh does not choose install method while sourced" {
  [ "${SEARCH_ENGINE_MODE:-}" = "" ]
}

@test "start_searxng recreates container published on stale port" {
  INSTALL_DIR="$BATS_TEST_TMPDIR/install"
  SOURCE_DIR="$BATS_TEST_TMPDIR/source"
  export DOCKER_CALLS="$BATS_TEST_TMPDIR/docker-calls"
  mkdir -p "$INSTALL_DIR" "$SOURCE_DIR"
  touch "$SOURCE_DIR/docker-compose.searxng.yml"

  docker() {
    printf '%s\n' "$*" >> "$DOCKER_CALLS"
    case "$1" in
      info)
        return 0
        ;;
      compose)
        return 0
        ;;
      inspect)
        printf 'running\n'
        ;;
      port)
        printf '0.0.0.0:8080\n'
        ;;
      rm)
        return 0
        ;;
    esac
  }
  sleep() { :; }

  run start_searxng

  [ "$status" -eq 0 ]
  grep -Fq "rm -f ostwin-searxng" "$DOCKER_CALLS"
  grep -Fq "compose -f $SOURCE_DIR/docker-compose.searxng.yml up -d" "$DOCKER_CALLS"
  [[ "$output" == *"not published on :6633"* ]]
  [[ "$output" == *"SearXNG created and running on :6633"* ]]

  unset -f docker
  unset -f sleep
}

@test "start_searxng falls back to local source install when Docker Compose is missing" {
  INSTALL_DIR="$BATS_TEST_TMPDIR/install-manual"
  SOURCE_DIR="$BATS_TEST_TMPDIR/source-manual"
  export DOCKER_CALLS="$BATS_TEST_TMPDIR/docker-compose-missing-calls"
  mkdir -p "$INSTALL_DIR/.agents" "$SOURCE_DIR"
  cat > "$INSTALL_DIR/.agents/search-engine.sh" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$OSTWIN_HOME:$OSTWIN_SEARCH_PORT:$*" > "$OSTWIN_HOME/manual-invocation.txt"
EOF
  chmod +x "$INSTALL_DIR/.agents/search-engine.sh"

  docker() {
    printf '%s\n' "$*" >> "$DOCKER_CALLS"
    case "$1" in
      info)
        return 0
        ;;
      inspect)
        return 0
        ;;
      rm)
        return 0
        ;;
      compose)
        return 1
        ;;
    esac
  }

  run start_searxng

  [ "$status" -eq 0 ]
  grep -Fq "rm -f ostwin-searxng" "$DOCKER_CALLS"
  [ "$(cat "$INSTALL_DIR/manual-invocation.txt")" = "$INSTALL_DIR:6633:install --port 6633 --bind 127.0.0.1 --start" ]
  [[ "$output" == *"Docker Compose not found; using local SearXNG source install"* ]]

  unset -f docker
}

@test "local mode uses source install when Docker is unavailable" {
  INSTALL_DIR="$BATS_TEST_TMPDIR/install-local-mode"
  SOURCE_DIR="$BATS_TEST_TMPDIR/source-local-mode"
  SEARCH_ENGINE_MODE="local"
  export DOCKER_CALLS="$BATS_TEST_TMPDIR/local-mode-docker-calls"
  mkdir -p "$INSTALL_DIR/.agents" "$SOURCE_DIR"
  cat > "$INSTALL_DIR/.agents/search-engine.sh" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$OSTWIN_HOME:$OSTWIN_SEARCH_PORT:$*" > "$OSTWIN_HOME/manual-invocation.txt"
EOF
  chmod +x "$INSTALL_DIR/.agents/search-engine.sh"

  docker() {
    printf '%s\n' "$*" >> "$DOCKER_CALLS"
    return 1
  }

  run start_searxng

  [ "$status" -eq 0 ]
  [ "$(cat "$INSTALL_DIR/manual-invocation.txt")" = "$INSTALL_DIR:6633:install --port 6633 --bind 127.0.0.1 --start" ]
  ! grep -Fq "compose" "$DOCKER_CALLS"
  [[ "$output" == *"Local SearXNG selected; using local SearXNG source install"* ]]

  unset -f docker
}

@test "manual fallback starts existing local source install" {
  INSTALL_DIR="$BATS_TEST_TMPDIR/install-existing-manual"
  SOURCE_DIR="$BATS_TEST_TMPDIR/source-existing-manual"
  mkdir -p \
    "$INSTALL_DIR/.agents" \
    "$INSTALL_DIR/search-engine/searx-pyenv/bin" \
    "$INSTALL_DIR/search-engine/searxng-src" \
    "$SOURCE_DIR"
  touch "$INSTALL_DIR/search-engine/searx-pyenv/bin/python"
  chmod +x "$INSTALL_DIR/search-engine/searx-pyenv/bin/python"
  cat > "$INSTALL_DIR/.agents/search-engine.sh" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$OSTWIN_HOME:$OSTWIN_SEARCH_PORT:$*" > "$OSTWIN_HOME/manual-invocation.txt"
EOF
  chmod +x "$INSTALL_DIR/.agents/search-engine.sh"
  docker() { return 1; }

  run _start_searxng_manual "test fallback"

  [ "$status" -eq 0 ]
  [ "$(cat "$INSTALL_DIR/manual-invocation.txt")" = "$INSTALL_DIR:6633:start --port 6633 --bind 127.0.0.1" ]
  [[ "$output" == *"test fallback; using local SearXNG source install"* ]]

  unset -f docker
}
