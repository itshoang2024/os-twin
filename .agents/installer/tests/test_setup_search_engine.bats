#!/usr/bin/env bats
# Tests for setup-search-engine.sh

setup() {
  INSTALLER_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  source "$INSTALLER_DIR/lib.sh"
  source "$INSTALLER_DIR/setup-search-engine.sh"
}

teardown() {
  if [[ -n "${TEST_INSTALL_DIR:-}" ]]; then
    rm -rf "$TEST_INSTALL_DIR"
  fi
}

@test "setup-search-engine.sh can be sourced without side effects" {
  [[ -n "$_SETUP_SEARCH_ENGINE_SH_LOADED" ]]
}

@test "setup_search_engine function is defined" {
  declare -f setup_search_engine > /dev/null
}

@test "setup_search_engine invokes installed search-engine manager" {
  TEST_INSTALL_DIR="$(mktemp -d)"
  mkdir -p "$TEST_INSTALL_DIR/.agents"
  cat > "$TEST_INSTALL_DIR/.agents/search-engine.sh" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$OSTWIN_HOME:$*" > "$OSTWIN_HOME/search-engine-invocation.txt"
EOF
  chmod +x "$TEST_INSTALL_DIR/.agents/search-engine.sh"

  INSTALL_DIR="$TEST_INSTALL_DIR"
  run setup_search_engine

  [ "$status" -eq 0 ]
  [ "$(cat "$TEST_INSTALL_DIR/search-engine-invocation.txt")" = "$TEST_INSTALL_DIR:install" ]
}
