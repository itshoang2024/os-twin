#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# check-deps.sh — Dependency presence checks (pure — no installs)
#
# Provides: check_python, check_pwsh, check_node, check_uv, check_opencode,
#           check_agent_browser, check_chrome_devtools, check_brew
#
# Requires: lib.sh (version_gte), versions.conf (MIN_PYTHON_VERSION, MIN_PWSH_VERSION)
#
# Side effects: sets PYTHON_VERSION and PWSH_VERSION globals on success.
# ──────────────────────────────────────────────────────────────────────────────

# Guard against double-sourcing
[[ -n "${_CHECK_DEPS_SH_LOADED:-}" ]] && return 0
_CHECK_DEPS_SH_LOADED=1

# ─── Python ──────────────────────────────────────────────────────────────────
# Prints the path of a suitable python command, or empty string.
# Sets PYTHON_VERSION as a side effect.

check_python() {
  local py_cmd=""
  for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
      local ver
      ver=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
      if version_gte "$ver" "${MIN_PYTHON_VERSION:-3.10}"; then
        py_cmd="$cmd"
        PYTHON_VERSION="$ver"
        break
      fi
    fi
  done
  # Fallback: check uv-managed Python
  if [[ -z "$py_cmd" ]] && check_uv; then
    local uv_py
    uv_py=$(uv python find 2>/dev/null || true)
    if [[ -n "$uv_py" && -x "$uv_py" ]]; then
      # shellcheck disable=SC2034  # consumed by caller
      PYTHON_VERSION=$("$uv_py" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
      py_cmd="$uv_py"
    fi
  fi
  echo "$py_cmd"
}

# ─── PowerShell ──────────────────────────────────────────────────────────────

check_pwsh() {
  if command -v pwsh &>/dev/null; then
    PWSH_VERSION=$(pwsh --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
    if version_gte "$PWSH_VERSION" "${MIN_PWSH_VERSION:-7}"; then
      return 0
    fi
  fi
  return 1
}

# ─── Node.js ─────────────────────────────────────────────────────────────────

check_node() {
  command -v node &>/dev/null
}

# ─── uv (Python package manager) ────────────────────────────────────────────

check_uv() {
  command -v uv &>/dev/null
}

# ─── opencode (Agent execution engine) ──────────────────────────────────────

check_opencode() {
  command -v opencode &>/dev/null
}

# ─── agent-browser (Browser automation CLI) ─────────────────────────────────

check_agent_browser() {
  command -v agent-browser &>/dev/null
}

# ─── Chrome DevTools browser runtime ────────────────────────────────────────

check_chrome_devtools() {
  if command -v obscura &>/dev/null; then
    command -v obscura
    return 0
  fi
  if [[ -n "${INSTALL_DIR:-}" && -x "$INSTALL_DIR/.agents/bin/obscura" ]]; then
    echo "$INSTALL_DIR/.agents/bin/obscura"
    return 0
  fi
  return 1
}

# ─── Homebrew ────────────────────────────────────────────────────────────────

check_brew() {
  command -v brew &>/dev/null
}

# ─── Ollama (local LLM host) ────────────────────────────────────────────────

check_ollama() {
  command -v ollama &>/dev/null
}
