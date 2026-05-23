#!/usr/bin/env bats
# Tests for setup-env.sh

setup() {
  INSTALLER_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  source "$INSTALLER_DIR/lib.sh"
  source "$INSTALLER_DIR/detect-os.sh"
  source "$INSTALLER_DIR/setup-env.sh"
}

@test "setup-env.sh can be sourced without side effects" {
  [[ -n "$_SETUP_ENV_SH_LOADED" ]]
}

@test "setup_env function is defined" {
  declare -f setup_env > /dev/null
}

@test "_create_env_sh_hook function is defined" {
  declare -f _create_env_sh_hook > /dev/null
}

@test "_migrate_env_keys function is defined" {
  declare -f _migrate_env_keys > /dev/null
}
