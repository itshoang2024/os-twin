#!/usr/bin/env bats
# Tests for start-opencode-server.sh

setup() {
  INSTALLER_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  source "$INSTALLER_DIR/lib.sh"
  source "$INSTALLER_DIR/start-opencode-server.sh"
}

@test "start-opencode-server.sh can be sourced without side effects" {
  [[ -n "$_START_OPENCODE_SERVER_SH_LOADED" ]]
}

@test "start_opencode_server function is defined" {
  declare -f start_opencode_server > /dev/null
}

@test "_is_opencode_serve_process matches serve process even with truncated comm" {
  ps() {
    case "$*" in
      "-p 123 -o comm=") echo "opencode" ;;
      "-p 123 -o args=") echo "opencode serve --hostname 127.0.0.1 --port 4096" ;;
    esac
  }

  _is_opencode_serve_process 123
  unset -f ps
}

@test "_is_opencode_serve_process rejects non-server opencode commands" {
  ps() {
    case "$*" in
      "-p 123 -o comm=") echo "opencode" ;;
      "-p 123 -o args=") echo "opencode auth login" ;;
    esac
  }

  ! _is_opencode_serve_process 123
  unset -f ps
}
