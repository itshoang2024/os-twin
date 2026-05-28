#!/usr/bin/env bats
# Tests for versions.conf

setup() {
  INSTALLER_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  source "$INSTALLER_DIR/versions.conf"
}

@test "versions.conf can be sourced" {
  [[ -n "$_VERSIONS_CONF_LOADED" ]]
}

@test "MIN_PYTHON_VERSION is set" {
  [[ -n "$MIN_PYTHON_VERSION" ]]
}

@test "PYTHON_INSTALL_VERSION is set" {
  [[ -n "$PYTHON_INSTALL_VERSION" ]]
}

@test "MIN_PWSH_VERSION is set" {
  [[ -n "$MIN_PWSH_VERSION" ]]
}

@test "PWSH_INSTALL_VERSION is set" {
  [[ -n "$PWSH_INSTALL_VERSION" ]]
}

@test "NODE_VER is set and starts with v" {
  [[ -n "$NODE_VER" ]]
  [[ "$NODE_VER" == v* ]]
}

@test "AGENT_BROWSER_VERSION is set" {
  [[ -n "$AGENT_BROWSER_VERSION" ]]
}

@test "double-sourcing is safe" {
  source "$INSTALLER_DIR/versions.conf"
  source "$INSTALLER_DIR/versions.conf"
  [[ "$MIN_PYTHON_VERSION" == "3.10" ]]
}
