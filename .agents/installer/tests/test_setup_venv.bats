#!/usr/bin/env bats
# Tests for setup-venv.sh

setup() {
  INSTALLER_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  source "$INSTALLER_DIR/lib.sh"
  source "$INSTALLER_DIR/versions.conf"
  source "$INSTALLER_DIR/check-deps.sh"
  source "$INSTALLER_DIR/setup-venv.sh"
}

@test "setup-venv.sh can be sourced without side effects" {
  [[ -n "$_SETUP_VENV_SH_LOADED" ]]
}

@test "setup_venv function is defined" {
  declare -f setup_venv > /dev/null
}

@test "setup_venv validates dashboard runtime imports" {
  declare -f _setup_venv_validate_runtime_deps > /dev/null
  declare -f _setup_venv_install_core_runtime_deps > /dev/null
  declare -f setup_venv | grep -q "_setup_venv_validate_runtime_deps"
}

@test "pip fallback supports dashboard pyproject.toml" {
  declare -f _setup_venv_pip_fallback > /dev/null
  declare -f _setup_venv_pip_fallback | grep -q "pyproject.toml"
}

@test "core MCP install stays on FastMCP-compatible SDK" {
  grep -Fq "mcp[cli]>=1.1.3,<2.0" "$INSTALLER_DIR/../mcp/requirements.txt"
  declare -f _setup_venv_install_core_runtime_deps | grep -Fq "mcp[cli]>=1.1.3,<2.0"
  ! declare -f _setup_venv_install_core_runtime_deps | grep -Fq -- "--prerelease=allow"
}
