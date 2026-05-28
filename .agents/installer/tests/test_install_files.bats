#!/usr/bin/env bats
# Tests for install-files.sh

setup() {
  INSTALLER_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  source "$INSTALLER_DIR/lib.sh"
  source "$INSTALLER_DIR/versions.conf"
  source "$INSTALLER_DIR/detect-os.sh"
  source "$INSTALLER_DIR/check-deps.sh"
  source "$INSTALLER_DIR/install-files.sh"
}

@test "install-files.sh can be sourced without side effects" {
  [[ -n "$_INSTALL_FILES_SH_LOADED" ]]
}

@test "install_files function is defined" {
  declare -f install_files > /dev/null
}

@test "compute_build_hash function is defined" {
  declare -f compute_build_hash > /dev/null
}

@test "internal helpers are defined" {
  declare -f _seed_mcp_config > /dev/null
  declare -f _setup_mcp_symlink > /dev/null
  declare -f _migrate_mcp_config > /dev/null
  declare -f _sync_dashboard > /dev/null
  declare -f _load_contributed_roles > /dev/null
}

# ─── _seed_mcp_config tests ─────────────────────────────────────────────────────

@test "_seed_mcp_config: seeds config.json from mcp-builtin.json on fresh install" {
  local tmp_install="$(mktemp -d)"
  local tmp_script="$(mktemp -d)"
  
  # Create mcp-builtin.json as source
  mkdir -p "$tmp_script/mcp"
  cat > "$tmp_script/mcp/mcp-builtin.json" <<'EOF'
{
  "mcp": {
    "memory": {
      "type": "local",
      "command": ["python", "server.py"]
    }
  }
}
EOF

  # Override globals for test
  SCRIPT_DIR="$tmp_script"
  INSTALL_DIR="$tmp_install"
  
  # Run _seed_mcp_config (fresh install - no config.json exists)
  run _seed_mcp_config
  [ "$status" -eq 0 ]
  
  # Verify config.json was created from mcp-builtin.json
  [ -f "$tmp_install/.agents/mcp/config.json" ]
  
  # Verify content matches mcp-builtin.json
  local cfg_content="$(cat "$tmp_install/.agents/mcp/config.json")"
  [[ "$cfg_content" == *"memory"* ]]
  [[ "$cfg_content" == *"local"* ]]
  
  rm -rf "$tmp_install" "$tmp_script"
}

@test "_seed_mcp_config: prefers mcp-builtin.json over ignored config.json" {
  local tmp_install="$(mktemp -d)"
  local tmp_script="$(mktemp -d)"

  mkdir -p "$tmp_script/mcp"
  cat > "$tmp_script/mcp/config.json" <<'EOF'
{
  "mcp": {
    "stale": { "type": "local", "command": ["python", "stale.py"] }
  }
}
EOF
  cat > "$tmp_script/mcp/mcp-builtin.json" <<'EOF'
{
  "mcp": {
    "chrome-devtools": { "type": "local", "command": ["obscura", "mcp"] }
  }
}
EOF

  SCRIPT_DIR="$tmp_script"
  INSTALL_DIR="$tmp_install"

  run _seed_mcp_config
  [ "$status" -eq 0 ]

  local cfg_content="$(cat "$tmp_install/.agents/mcp/config.json")"
  [[ "$cfg_content" == *"chrome-devtools"* ]]
  [[ "$cfg_content" != *"stale"* ]]

  rm -rf "$tmp_install" "$tmp_script"
}

@test "_seed_mcp_config: preserves existing config.json on re-install" {
  local tmp_install="$(mktemp -d)"
  local tmp_script="$(mktemp -d)"
  
  # Create mcp-builtin.json as source
  mkdir -p "$tmp_script/mcp"
  cat > "$tmp_script/mcp/mcp-builtin.json" <<'EOF'
{
  "mcp": {
    "memory": { "type": "local", "command": ["python", "server.py"] },
    "channel": { "type": "local", "command": ["python", "channel.py"] }
  }
}
EOF

  # Create existing config.json with custom server
  mkdir -p "$tmp_install/.agents/mcp"
  cat > "$tmp_install/.agents/mcp/config.json" <<'EOF'
{
  "mcp": {
    "memory": { "type": "local", "command": ["python", "server.py"] },
    "custom-server": { "type": "remote", "url": "http://localhost:8080" }
  }
}
EOF
  touch "$tmp_install/.agents/mcp/obscura-browser-server.py"
  touch "$tmp_install/.agents/mcp/test_obscura_browser.py"

  # Override globals for test
  SCRIPT_DIR="$tmp_script"
  INSTALL_DIR="$tmp_install"
  VENV_DIR="/tmp/fake-venv"
  PYTHON_CMD="python3"
  
  # Run _seed_mcp_config (re-install - config.json exists)
  run _seed_mcp_config
  [ "$status" -eq 0 ]
  
  # Verify custom server is preserved
  local cfg_content="$(cat "$tmp_install/.agents/mcp/config.json")"
  [[ "$cfg_content" == *"custom-server"* ]]
  [[ "$cfg_content" == *"localhost:8080"* ]]
  [ ! -f "$tmp_install/.agents/mcp/obscura-browser-server.py" ]
  [ ! -f "$tmp_install/.agents/mcp/test_obscura_browser.py" ]
  
  rm -rf "$tmp_install" "$tmp_script"
}

@test "_seed_mcp_config: handles missing mcp-builtin.json gracefully" {
  local tmp_install="$(mktemp -d)"
  local tmp_script="$(mktemp -d)"
  
  # No mcp-builtin.json in source
  mkdir -p "$tmp_script/mcp"
  
  # Override globals for test
  SCRIPT_DIR="$tmp_script"
  INSTALL_DIR="$tmp_install"
  
  # Run _seed_mcp_config (should warn but not fail)
  run _seed_mcp_config
  [ "$status" -eq 0 ]
  
  # Verify config.json was NOT created
  [ ! -f "$tmp_install/.agents/mcp/config.json" ]
  
  rm -rf "$tmp_install" "$tmp_script"
}
