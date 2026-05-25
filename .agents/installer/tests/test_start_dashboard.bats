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

@test "_dashboard_port_listeners queries only LISTEN sockets on the requested port" {
  lsof() {
    [[ "$*" == "-nP -tiTCP:3366 -sTCP:LISTEN" ]] && echo "123"
  }

  run _dashboard_port_listeners 3366

  [ "$status" -eq 0 ]
  [ "$output" = "123" ]
  unset -f lsof
}

@test "_kill_dashboard_port_listeners terminates every listener on the dashboard port" {
  export KILL_CALLS="$BATS_TEST_TMPDIR/kill-calls"
  mkdir -p "$BATS_TEST_TMPDIR/bin"
  cat > "$BATS_TEST_TMPDIR/bin/kill" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$KILL_CALLS"
exit 0
EOF
  chmod +x "$BATS_TEST_TMPDIR/bin/kill"
  PATH="$BATS_TEST_TMPDIR/bin:$PATH"

  local query_count_file="$BATS_TEST_TMPDIR/query-count"
  echo 0 > "$query_count_file"
  _dashboard_port_listeners() {
    local query_count
    query_count="$(cat "$query_count_file")"
    query_count=$((query_count + 1))
    echo "$query_count" > "$query_count_file"
    if [[ "$query_count" -eq 1 ]]; then
      printf '123\n456\n'
    fi
  }
  kill() {
    printf '%s\n' "$*" >> "$KILL_CALLS"
    return 1
  }

  _kill_dashboard_port_listeners 3366

  grep -Fq "123 456" "$KILL_CALLS"
  unset -f _dashboard_port_listeners
  unset -f kill
}

@test "_kill_dashboard_port_listeners fails when the port remains occupied" {
  sleep() { :; }
  _dashboard_port_listeners() {
    printf '123\n'
  }
  kill() {
    return 1
  }

  run _kill_dashboard_port_listeners 3366

  [ "$status" -eq 1 ]
  [[ "$output" == *"Port :3366 is still occupied"* ]]
  unset -f _dashboard_port_listeners
  unset -f kill
  unset -f sleep
}
