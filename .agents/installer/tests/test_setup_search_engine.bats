#!/usr/bin/env bats
# Tests for setup-search-engine.sh

setup() {
  INSTALLER_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  source "$INSTALLER_DIR/lib.sh"
  source "$INSTALLER_DIR/setup-search-engine.sh"
}

@test "setup-search-engine.sh can be sourced without side effects" {
  [[ -n "$_SETUP_SEARCH_ENGINE_SH_LOADED" ]]
}

@test "setup_search_engine function is defined" {
  declare -f setup_search_engine > /dev/null
}
