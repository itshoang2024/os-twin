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
