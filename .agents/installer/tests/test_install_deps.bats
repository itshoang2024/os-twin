#!/usr/bin/env bats
# Tests for install-deps.sh — verifies functions are defined (does NOT actually install)

setup() {
  INSTALLER_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  source "$INSTALLER_DIR/lib.sh"
  source "$INSTALLER_DIR/versions.conf"
  source "$INSTALLER_DIR/detect-os.sh"
  source "$INSTALLER_DIR/check-deps.sh"
  source "$INSTALLER_DIR/install-deps.sh"
}

@test "install-deps.sh can be sourced without side effects" {
  [[ -n "$_INSTALL_DEPS_SH_LOADED" ]]
}

@test "install_brew function is defined" {
  declare -f install_brew > /dev/null
}

@test "install_uv function is defined" {
  declare -f install_uv > /dev/null
}

@test "install_python function is defined" {
  declare -f install_python > /dev/null
}

@test "install_pwsh function is defined" {
  declare -f install_pwsh > /dev/null
}

@test "install_node function is defined" {
  declare -f install_node > /dev/null
}

@test "install_opencode function is defined" {
  declare -f install_opencode > /dev/null
}

@test "install_chrome_devtools function is defined" {
  declare -f install_chrome_devtools > /dev/null
}

@test "install_agent_browser function is defined" {
  declare -f install_agent_browser > /dev/null
}

@test "install_agent_browser installs CLI and runs post-install setup" {
  local body
  body=$(declare -f install_agent_browser)
  [[ "$body" == *'pnpm add -g "agent-browser@$AGENT_BROWSER_VERSION"'* ]]
  [[ "$body" == *"agent-browser install"* ]]
}

@test "install_agent_browser uses pinned version from versions.conf" {
  local body
  body=$(declare -f install_agent_browser)
  [[ -n "$AGENT_BROWSER_VERSION" ]]
  [[ "$body" == *"AGENT_BROWSER_VERSION"* ]]
}

@test "install_agent_browser uses pnpm instead of npm" {
  local body
  body=$(declare -f install_agent_browser)
  [[ "$body" == *"command -v pnpm"* ]]
  [[ "$body" != *"npm install -g"* ]]
  [[ "$body" != *"npm prefix"* ]]
}

@test "install_chrome_devtools does not enable stealth by default" {
  local body
  body=$(declare -f install_chrome_devtools)
  [[ "$body" != *"OBSCURA_ARGS"* ]]
  [[ "$body" != *"--stealth"* ]]
}

@test "install_chrome_devtools preserves companion binary" {
  local body
  body=$(declare -f install_chrome_devtools)
  [[ "$body" == *"obscura-worker"* ]]
}

@test "install_pester function is defined" {
  declare -f install_pester > /dev/null
}

@test "install_node uses version from versions.conf" {
  # Verify the function body references NODE_VER
  local body
  body=$(declare -f install_node)
  [[ "$body" == *"NODE_VER"* ]]
}
