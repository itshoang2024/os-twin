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

@test "_create_env_sh_hook does not create Cloud SDK token refresh" {
  INSTALL_DIR="$BATS_TEST_TMPDIR/env-hook"
  mkdir -p "$INSTALL_DIR"

  run _create_env_sh_hook
  [ "$status" -eq 0 ]
  [ -f "$INSTALL_DIR/.env.sh" ]
  ! grep -q "VERTEX_API_KEY" "$INSTALL_DIR/.env.sh"
  ! grep -q "print-access-token" "$INSTALL_DIR/.env.sh"
}

@test "_create_env_sh_hook removes legacy Cloud SDK token refresh" {
  INSTALL_DIR="$BATS_TEST_TMPDIR/existing-hook"
  mkdir -p "$INSTALL_DIR"
  cat > "$INSTALL_DIR/.env.sh" <<'EOF'
# keep this line
# Refresh a Vertex AI access token from the active gcloud account.
if command -v gcloud >/dev/null 2>&1; then
  VERTEX_API_KEY="$(gcloud auth print-access-token 2>/dev/null || true)"
  export VERTEX_API_KEY
fi
export KEEP_ME=true
EOF

  run _create_env_sh_hook
  [ "$status" -eq 0 ]
  grep -q "KEEP_ME=true" "$INSTALL_DIR/.env.sh"
  ! grep -q "VERTEX_API_KEY" "$INSTALL_DIR/.env.sh"
  ! grep -q "print-access-token" "$INSTALL_DIR/.env.sh"
}

@test "_migrate_env_keys function is defined" {
  declare -f _migrate_env_keys > /dev/null
}
