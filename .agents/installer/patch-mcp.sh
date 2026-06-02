#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# patch-mcp.sh — MCP config patching, env injection, OpenCode merge
#
# Provides: patch_mcp_config
#
# Requires: lib.sh, globals: INSTALL_DIR, VENV_DIR
#           Python scripts in installer/scripts/
# ──────────────────────────────────────────────────────────────────────────────

# Guard against double-sourcing
[[ -n "${_PATCH_MCP_SH_LOADED:-}" ]] && return 0
_PATCH_MCP_SH_LOADED=1

# Installer scripts dir for Python helpers
_PATCH_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/scripts" 2>/dev/null && pwd || echo "")"

patch_mcp_config() {
  local mcp_config="$INSTALL_DIR/.agents/mcp/config.json"
  local env_file="$INSTALL_DIR/.env"

  # Safety net: if config.json wasn't seeded (e.g. both config.json and
  # mcp-config.json are gitignored and mcp-builtin.json fallback didn't
  # trigger), try to create it from the installed builtin template now.
  if [[ ! -f "$mcp_config" ]]; then
    local builtin="$INSTALL_DIR/.agents/mcp/mcp-builtin.json"
    if [[ -f "$builtin" ]]; then
      warn "mcp/config.json missing — creating from mcp-builtin.json"
      cp "$builtin" "$mcp_config"
    else
      warn "No MCP config found — opencode.json will have no MCP servers"
      return
    fi
  fi

  step "Patching MCP config..."

  # Detect OS for sed compatibility
  local sed_opts=()
  if [[ "$(uname -s)" == "Darwin" ]]; then
    sed_opts=("-i" "")
  else
    sed_opts=("-i")
  fi

  # 1. Ensure critical path env vars are set in .env
  # These are required for {env:AGENT_DIR} and {env:OSTWIN_PYTHON} resolution
  # Using 'export' so they're available to child processes (opencode, MCP servers)
  local venv_python="$VENV_DIR/bin/python"

  # Remove any existing entries (with or without export) and add fresh ones
  for key in AGENT_DIR OSTWIN_PYTHON PATH; do
    if [[ -f "$env_file" ]]; then
      # Remove lines starting with optional 'export ' followed by the key
      sed "${sed_opts[@]}" "/^export ${key}=/d" "$env_file"
      sed "${sed_opts[@]}" "/^${key}=/d" "$env_file"
    fi
  done

  # Construct PATH for MCP servers (npx, pwsh, ostwin bin, etc.)
  local mcp_path="$VENV_DIR/bin"
  # Add PowerShell if installed
  if command -v pwsh &>/dev/null; then
    local pwsh_dir
    pwsh_dir="$(dirname "$(command -v pwsh)")"
    mcp_path="$mcp_path:$pwsh_dir"
  fi
  # Add ostwin bin directories
  mcp_path="$mcp_path:$INSTALL_DIR/.agents/bin:$HOME/.local/bin:$HOME/.opencode/bin"
  # Add homebrew paths (macOS)
  if [[ -d "/opt/homebrew/bin" ]]; then
    mcp_path="$mcp_path:/opt/homebrew/bin:/opt/homebrew/sbin"
  fi
  if [[ -d "/usr/local/Homebrew/bin" ]]; then
    mcp_path="$mcp_path:/usr/local/Homebrew/bin"
  fi
  # Add standard system paths
  mcp_path="$mcp_path:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

  # Append the new entries
  {
    echo "export AGENT_DIR=$INSTALL_DIR"
    echo "export OSTWIN_PYTHON=$venv_python"
    echo "export PATH=$mcp_path"
  } >> "$env_file"

  # 2. Inject all .env variables into every MCP server's "environment" block
  if [[ -f "$env_file" ]]; then
    "$VENV_DIR/bin/python" "${_PATCH_SCRIPTS_DIR}/inject_env_to_mcp.py" \
      "$mcp_config" "$env_file"
  fi

  # 3. Normalize + validate + merge MCP servers into ~/.config/opencode/opencode.json
  local opencode_home="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
  mkdir -p "$opencode_home"
  OSTWIN_VENV_DIR="$VENV_DIR" OSTWIN_INSTALL_DIR="$INSTALL_DIR" \
    "$VENV_DIR/bin/python" "${_PATCH_SCRIPTS_DIR}/merge_mcp_to_opencode.py" \
    "$mcp_config" "$opencode_home/opencode.json" "$INSTALL_DIR/.agents/mcp"

  ok "MCP config synced"
}
