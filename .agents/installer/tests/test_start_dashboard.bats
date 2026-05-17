#!/usr/bin/env bats
# Tests for start-dashboard.sh

setup() {
  INSTALLER_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  source "$INSTALLER_DIR/lib.sh"
  source "$INSTALLER_DIR/check-deps.sh"
  source "$INSTALLER_DIR/start-dashboard.sh"
}

@test "start-dashboard.sh can be sourced without side effects" {
  [[ -n "$_START_DASHBOARD_SH_LOADED" ]]
}

@test "start_dashboard function is defined" {
  declare -f start_dashboard > /dev/null
}

@test "publish_skills function is defined" {
  declare -f publish_skills > /dev/null
}

@test "_is_dashboard_process_for_port matches dashboard api.py even with truncated python comm" {
  ps() {
    case "$*" in
      "-p 123 -o comm=") echo "python3.12" ;;
      "-p 123 -o args=") echo "/Users/test/.ostwin/.venv/bin/python api.py --port 3366 --project-dir /Users/test/.ostwin" ;;
    esac
  }

  _is_dashboard_process_for_port 123 3366
  unset -f ps
}

@test "_is_dashboard_process_for_port rejects unrelated listeners" {
  ps() {
    case "$*" in
      "-p 123 -o comm=") echo "Browser Helper" ;;
      "-p 123 -o args=") echo "/Applications/Browser Helper --type=utility --port 3366" ;;
    esac
  }

  ! _is_dashboard_process_for_port 123 3366
  unset -f ps
}
