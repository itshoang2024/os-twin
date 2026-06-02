#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# setup-opencode.sh — OpenCode permissions patching + custom tool generation
#
# Provides: setup_opencode_permissions, generate_opencode_tools
#
# Requires: lib.sh, globals: VENV_DIR, INSTALL_DIR
#           Python script: installer/scripts/patch_opencode_permissions.py
#           Python module: dashboard.opencode_tools
# ──────────────────────────────────────────────────────────────────────────────

# Guard against double-sourcing
[[ -n "${_SETUP_OPENCODE_SH_LOADED:-}" ]] && return 0
_SETUP_OPENCODE_SH_LOADED=1

_OPENCODE_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/scripts" 2>/dev/null && pwd || echo "")"

setup_opencode_permissions() {
  local oc_dir="$HOME/.config/opencode"
  local oc_config="$oc_dir/opencode.json"

  if ! command -v python3 &>/dev/null && ! [[ -x "$VENV_DIR/bin/python" ]]; then
    warn "Python not available — skipping OpenCode permission patch"
    return
  fi

  local py_cmd="python3"
  [[ -x "$VENV_DIR/bin/python" ]] && py_cmd="$VENV_DIR/bin/python"

  step "Patching OpenCode permissions (allow file reads + external directories)..."
  mkdir -p "$oc_dir"

  if "$py_cmd" "${_OPENCODE_SCRIPTS_DIR}/patch_opencode_permissions.py" "$oc_config"; then
    ok "OpenCode permissions ensured at $oc_config"
  else
    warn "Failed to patch OpenCode permissions — headless agents may wait on file-read prompts"
    info "Manually add to $oc_config:"
    info '  "permission": { "read": { "*": "allow" }, "external_directory": { "*": "allow" } }'
  fi
}

generate_opencode_tools() {
  local project_root="$INSTALL_DIR/opencode_server"
  local dashboard_port="${DASHBOARD_PORT:-3366}"

  if ! command -v python3 &>/dev/null && ! [[ -x "$VENV_DIR/bin/python" ]]; then
    warn "Python not available — skipping OpenCode tool generation"
    return
  fi

  local py_cmd="python3"
  [[ -x "$VENV_DIR/bin/python" ]] && py_cmd="$VENV_DIR/bin/python"

  mkdir -p "$project_root" "$INSTALL_DIR/logs"
  local log_file="$INSTALL_DIR/logs/opencode-tools.log"

  # Tool generation is expected on every install; keep stdout/stderr out of the
  # installer transcript unless something fails. The detailed generator output is
  # still available for debugging in $log_file.
  if "$py_cmd" -m dashboard.opencode_tools \
      --project-root "$project_root" \
      --dashboard-port "$dashboard_port" \
      >"$log_file" 2>&1; then
    return 0
  else
    warn "Failed to generate OpenCode tools"
    info "Details: $log_file"
    info "Run manually: python -m dashboard.opencode_tools --project-root $project_root"
  fi
}
