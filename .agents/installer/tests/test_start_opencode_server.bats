#!/usr/bin/env bats
# Tests for start-opencode-server.sh
#
# The script is now a thin wrapper that delegates all lifecycle work to
# ``dashboard.lib.opencode_service``.  These tests verify the delegation
# contract (how the Python module is invoked) rather than reimplementing
# the supervisor logic in bash.

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

@test "start_opencode_server delegates to dashboard.lib.opencode_service" {
  grep -Fq 'dashboard.lib.opencode_service' "$INSTALLER_DIR/start-opencode-server.sh"
}

@test "wrapper no longer reimplements env loading in bash" {
  ! grep -Fq '_load_opencode_service_env' "$INSTALLER_DIR/start-opencode-server.sh"
  ! grep -Fq '_normalize_vertex_env_aliases' "$INSTALLER_DIR/start-opencode-server.sh"
  ! grep -Fq '_isolate_external_google_adc_fallback' "$INSTALLER_DIR/start-opencode-server.sh"
}

@test "wrapper no longer spawns opencode serve directly" {
  ! grep -E 'opencode serve --hostname' "$INSTALLER_DIR/start-opencode-server.sh"
}

@test "_opencode_service_python prefers the install venv interpreter" {
  INSTALL_DIR="$BATS_TEST_TMPDIR/install"
  mkdir -p "$INSTALL_DIR/.venv/bin"
  printf '#!/usr/bin/env bash\n' > "$INSTALL_DIR/.venv/bin/python"
  chmod +x "$INSTALL_DIR/.venv/bin/python"

  run _opencode_service_python
  [[ "$status" -eq 0 ]]
  [[ "$output" == "$INSTALL_DIR/.venv/bin/python" ]]
}

@test "_opencode_service_python falls back to python3 when venv is absent" {
  INSTALL_DIR="$BATS_TEST_TMPDIR/install"
  mkdir -p "$INSTALL_DIR"

  if ! command -v python3 &>/dev/null; then
    skip "python3 not available on this system"
  fi

  run _opencode_service_python
  [[ "$status" -eq 0 ]]
  [[ "$output" == "$(command -v python3)" ]]
}

@test "_opencode_service_invoke passes OSTWIN_HOME and PYTHONPATH to python" {
  INSTALL_DIR="$BATS_TEST_TMPDIR/install"
  mkdir -p "$INSTALL_DIR/.venv/bin"

  # Stub the interpreter — echo the env values we care about so the test
  # can assert on them, then exit successfully.
  cat > "$INSTALL_DIR/.venv/bin/python" <<'EOF'
#!/usr/bin/env bash
echo "argv=$*"
echo "OSTWIN_HOME=$OSTWIN_HOME"
echo "PYTHONPATH=$PYTHONPATH"
EOF
  chmod +x "$INSTALL_DIR/.venv/bin/python"

  run _opencode_service_invoke start
  [[ "$status" -eq 0 ]]
  [[ "$output" == *"argv=-m dashboard.lib.opencode_service start"* ]]
  [[ "$output" == *"OSTWIN_HOME=$INSTALL_DIR"* ]]
  [[ "$output" == *"PYTHONPATH=$INSTALL_DIR"* ]]
}
