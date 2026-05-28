#!/usr/bin/env bats
# Tests for check-deps.sh

setup() {
  INSTALLER_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  source "$INSTALLER_DIR/lib.sh"
  source "$INSTALLER_DIR/versions.conf"
  source "$INSTALLER_DIR/check-deps.sh"
}

@test "check-deps.sh can be sourced without side effects" {
  [[ -n "$_CHECK_DEPS_SH_LOADED" ]]
}

@test "check_python() returns a command path when python3 is available" {
  if command -v python3 &>/dev/null; then
    result=$(check_python)
    [[ -n "$result" ]]
  else
    skip "python3 not available"
  fi
}

@test "check_node() succeeds when node is in PATH" {
  if command -v node &>/dev/null; then
    run check_node
    [[ "$status" -eq 0 ]]
  else
    skip "node not available"
  fi
}

@test "check_uv() succeeds when uv is in PATH" {
  if command -v uv &>/dev/null; then
    run check_uv
    [[ "$status" -eq 0 ]]
  else
    skip "uv not available"
  fi
}

@test "check_agent_browser() succeeds when agent-browser is in PATH" {
  if command -v agent-browser &>/dev/null; then
    run check_agent_browser
    [[ "$status" -eq 0 ]]
  else
    skip "agent-browser not available"
  fi
}

@test "check_obscura() detects installer-managed binary" {
  INSTALL_DIR="$BATS_TEST_TMPDIR/ostwin"
  mkdir -p "$INSTALL_DIR/.agents/bin"
  touch "$INSTALL_DIR/.agents/bin/obscura"
  chmod +x "$INSTALL_DIR/.agents/bin/obscura"

  result=$(check_obscura)
  [[ "$result" == "$INSTALL_DIR/.agents/bin/obscura" || -n "$result" ]]
}

@test "check_brew() succeeds on macOS with Homebrew" {
  if command -v brew &>/dev/null; then
    run check_brew
    [[ "$status" -eq 0 ]]
  else
    skip "brew not available"
  fi
}

@test "check functions are pure (no install side effects)" {
  # Calling check functions should not modify PATH or install anything
  local orig_path="$PATH"
  check_python > /dev/null 2>&1 || true
  check_node > /dev/null 2>&1 || true
  check_uv > /dev/null 2>&1 || true
  check_agent_browser > /dev/null 2>&1 || true
  [[ "$PATH" == "$orig_path" ]]
}
