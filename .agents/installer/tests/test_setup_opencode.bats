#!/usr/bin/env bats
# Tests for setup-opencode.sh

INSTALLER_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
SCRIPTS_DIR="$INSTALLER_DIR/scripts"

setup() {
  export PYTHON="${PYTHON:-python3}"
  source "$INSTALLER_DIR/lib.sh"
  source "$INSTALLER_DIR/setup-opencode.sh"
}

@test "setup-opencode.sh can be sourced without side effects" {
  [[ -n "$_SETUP_OPENCODE_SH_LOADED" ]]
}

@test "setup_opencode_permissions function is defined" {
  declare -f setup_opencode_permissions > /dev/null
}

@test "patch_opencode_permissions.py adds file-read permissions" {
  TEST_DIR="$(mktemp -d)"

  cat > "$TEST_DIR/opencode.json" <<'JSONEOF'
{
  "$schema": "https://opencode.ai/config.json"
}
JSONEOF

  run "$PYTHON" "$SCRIPTS_DIR/patch_opencode_permissions.py" "$TEST_DIR/opencode.json"

  [ "$status" -eq 0 ]
  grep -q '"read"' "$TEST_DIR/opencode.json"
  grep -Fq '"*.env.example": "allow"' "$TEST_DIR/opencode.json"
  grep -q '"external_directory"' "$TEST_DIR/opencode.json"

  rm -rf "$TEST_DIR"
}

@test "patch_opencode_permissions.py does not rewrite unchanged config" {
  TEST_DIR="$(mktemp -d)"

  cat > "$TEST_DIR/opencode.json" <<'JSONEOF'
{
  "$schema": "https://opencode.ai/config.json",
  "permission": {
    "read": {
      "*": "allow",
      "*.env": "allow",
      "*.env.*": "allow",
      "*.env.example": "allow"
    },
    "external_directory": {
      "*": "allow"
    }
  }
}
JSONEOF

  touch -t 200001010000 "$TEST_DIR/opencode.json"
  before_mtime="$("$PYTHON" -c 'import os,sys; print(os.stat(sys.argv[1]).st_mtime_ns)' "$TEST_DIR/opencode.json")"

  run "$PYTHON" "$SCRIPTS_DIR/patch_opencode_permissions.py" "$TEST_DIR/opencode.json"

  [ "$status" -eq 0 ]
  [[ "$output" == *"already up to date"* ]]

  after_mtime="$("$PYTHON" -c 'import os,sys; print(os.stat(sys.argv[1]).st_mtime_ns)' "$TEST_DIR/opencode.json")"
  [ "$before_mtime" = "$after_mtime" ]

  rm -rf "$TEST_DIR"
}
