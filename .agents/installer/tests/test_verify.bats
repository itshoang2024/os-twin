#!/usr/bin/env bats
# Tests for verify.sh

setup() {
  INSTALLER_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  source "$INSTALLER_DIR/lib.sh"
  source "$INSTALLER_DIR/check-deps.sh"
  source "$INSTALLER_DIR/verify.sh"
}

@test "verify.sh can be sourced without side effects" {
  [[ -n "$_VERIFY_SH_LOADED" ]]
}

@test "verify_components function is defined" {
  declare -f verify_components > /dev/null
}

@test "print_completion_banner function is defined" {
  declare -f print_completion_banner > /dev/null
}

@test "verify_components reports agent-browser status" {
  local body
  body=$(declare -f verify_components)
  [[ "$body" == *"agent-browser"* ]]
}
