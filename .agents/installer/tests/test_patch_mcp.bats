#!/usr/bin/env bats
# Tests for patch-mcp.sh

setup() {
  INSTALLER_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  source "$INSTALLER_DIR/lib.sh"
  source "$INSTALLER_DIR/patch-mcp.sh"
}

@test "patch-mcp.sh can be sourced without side effects" {
  [[ -n "$_PATCH_MCP_SH_LOADED" ]]
}

@test "patch_mcp_config function is defined" {
  declare -f patch_mcp_config > /dev/null
}

@test "patch_mcp_config adds AGENT_DIR, OSTWIN_PYTHON, and PATH to .env" {
  # Create temp test directory
  TEST_DIR=$(mktemp -d)
  INSTALL_DIR="$TEST_DIR"
  VENV_DIR="$TEST_DIR/.venv"
  MCP_DIR="$TEST_DIR/.agents/mcp"
  
  mkdir -p "$MCP_DIR"
  mkdir -p "$VENV_DIR/bin"
  
  # Create minimal mcp config
  echo '{"mcp":{}}' > "$MCP_DIR/config.json"
  
  # Create scripts dir
  SCRIPTS_DIR="$INSTALLER_DIR/scripts"
  
  # Run patch_mcp_config (suppress output)
  run patch_mcp_config
  
  # Check .env was created with exports
  [[ -f "$TEST_DIR/.env" ]]
  grep -q "export AGENT_DIR=" "$TEST_DIR/.env"
  grep -q "export OSTWIN_PYTHON=" "$TEST_DIR/.env"
  grep -q "export PATH=" "$TEST_DIR/.env"
  
  # Cleanup
  rm -rf "$TEST_DIR"
}

@test "patch_mcp_config writes opencode config under install dir" {
  TEST_DIR=$(mktemp -d)
  INSTALL_DIR="$TEST_DIR"
  VENV_DIR="$TEST_DIR/.venv"
  MCP_DIR="$TEST_DIR/.agents/mcp"

  mkdir -p "$MCP_DIR" "$VENV_DIR/bin"
  echo '{"mcp":{}}' > "$MCP_DIR/config.json"

  cat > "$VENV_DIR/bin/python" <<EOF
#!/usr/bin/env bash
echo "\$*" >> "$TEST_DIR/python-args.txt"
if [[ "\$1" == *merge_mcp_to_opencode.py ]]; then
  mkdir -p "\$(dirname "\$3")"
  printf '{}\n' > "\$3"
fi
exit 0
EOF
  chmod +x "$VENV_DIR/bin/python"

  run patch_mcp_config

  [[ -f "$TEST_DIR/.opencode/opencode.json" ]]
  grep -Fq "$TEST_DIR/.opencode/opencode.json" "$TEST_DIR/python-args.txt"
  ! grep -Fq "$HOME/.config/opencode/opencode.json" "$TEST_DIR/python-args.txt"

  rm -rf "$TEST_DIR"
}

@test "patch_mcp_config respects SKIP_OPENCODE_CONFIG" {
  TEST_DIR=$(mktemp -d)
  INSTALL_DIR="$TEST_DIR"
  VENV_DIR="$TEST_DIR/.venv"
  MCP_DIR="$TEST_DIR/.agents/mcp"
  SKIP_OPENCODE_CONFIG=true

  mkdir -p "$MCP_DIR" "$VENV_DIR/bin"
  echo '{"mcp":{}}' > "$MCP_DIR/config.json"

  cat > "$VENV_DIR/bin/python" <<EOF
#!/usr/bin/env bash
echo "\$*" >> "$TEST_DIR/python-args.txt"
exit 0
EOF
  chmod +x "$VENV_DIR/bin/python"

  run patch_mcp_config

  [[ ! -f "$TEST_DIR/.opencode/opencode.json" ]]
  ! grep -Fq "merge_mcp_to_opencode.py" "$TEST_DIR/python-args.txt"

  unset SKIP_OPENCODE_CONFIG
  rm -rf "$TEST_DIR"
}

@test "patch_mcp_config replaces existing AGENT_DIR and PATH in .env" {
  TEST_DIR=$(mktemp -d)
  INSTALL_DIR="$TEST_DIR"
  VENV_DIR="$TEST_DIR/.venv"
  MCP_DIR="$TEST_DIR/.agents/mcp"
  
  mkdir -p "$MCP_DIR"
  mkdir -p "$VENV_DIR/bin"
  
  echo '{"mcp":{}}' > "$MCP_DIR/config.json"
  
  # Create .env with old AGENT_DIR
  echo "AGENT_DIR=/old/path" > "$TEST_DIR/.env"
  echo "export AGENT_DIR=/old/path" >> "$TEST_DIR/.env"
  echo "PATH=/old/path" >> "$TEST_DIR/.env"
  echo "export PATH=/old/path" >> "$TEST_DIR/.env"
  
  run patch_mcp_config
  
  # Should have only one AGENT_DIR line
  AGENT_COUNT=$(grep -c "AGENT_DIR=" "$TEST_DIR/.env" || echo 0)
  [[ "$AGENT_COUNT" -eq 1 ]]
  PATH_COUNT=$(grep -c "^export PATH=" "$TEST_DIR/.env" || echo 0)
  [[ "$PATH_COUNT" -eq 1 ]]
  
  # Should be the new value
  grep -q "export AGENT_DIR=$TEST_DIR" "$TEST_DIR/.env"
  
  rm -rf "$TEST_DIR"
}
