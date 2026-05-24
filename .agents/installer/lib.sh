#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# lib.sh — Shared utility functions for the Ostwin installer
#
# Provides: colors, formatting helpers (header, ok, warn, fail, info, step),
#           interactive prompt (ask), and semantic version comparison (version_gte).
#
# Usage:  source "$(dirname "$0")/installer/lib.sh"
#
# This module has NO side effects when sourced — it only defines functions
# and color variables.
# ──────────────────────────────────────────────────────────────────────────────

# Guard against double-sourcing
[[ -n "${_LIB_SH_LOADED:-}" ]] && return 0
_LIB_SH_LOADED=1

# ─── Colors & formatting ─────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m' # No Color

# ─── Output helpers ──────────────────────────────────────────────────────────

header()  { echo -e "\n${BLUE}${BOLD}  $1${NC}"; }
ok()      { echo -e "    ${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "    ${YELLOW}[WARN]${NC} $1"; }
fail()    { echo -e "    ${RED}[FAIL]${NC} $1"; }
info()    { echo -e "    ${DIM}$1${NC}"; }
step()    { echo -e "  ${CYAN}→${NC} $1"; }
ok_time() { echo -e "    ${GREEN}[OK]${NC} $1 ${DIM}($2)${NC}"; }

# ─── Timing helpers ──────────────────────────────────────────────────────────

get_now() {
  date +%s
}

print_duration() {
  local start=$1
  local end
  end=$(get_now)
  echo "$((end - start))s"
}

# ─── Interactive prompt ──────────────────────────────────────────────────────
# Returns 0 (yes) if AUTO_YES is true or user answers Y/y.

ask() {
  local prompt="$1"
  if ${AUTO_YES:-false}; then
    return 0
  fi
  echo -en "    ${YELLOW}?${NC} $prompt ${DIM}[Y/n]${NC} "
  read -r answer
  case "${answer:-y}" in
    [Yy]*) return 0 ;;
    *)     return 1 ;;
  esac
}

# ─── Version comparison ─────────────────────────────────────────────────────
# Returns 0 if $1 >= $2 (semantic version comparison).

version_gte() {
  # Returns 0 if $1 >= $2
  printf '%s\n%s' "$2" "$1" | sort -V | head -n1 | grep -qF "$2"
}

# ─── PATH helpers ────────────────────────────────────────────────────────────

# Ensure brew paths are in current session PATH (call before any brew installs)
ensure_brew_paths() {
  if command -v brew &>/dev/null; then
    local brew_prefix
    brew_prefix=$(brew --prefix 2>/dev/null || echo "/opt/homebrew")
    # Add to PATH if not already present
    if [[ ":$PATH:" != *":${brew_prefix}/bin:"* ]]; then
      export PATH="${brew_prefix}/bin:${brew_prefix}/sbin:$PATH"
    fi
  fi
  # Also ensure user-local binary paths are in PATH.
  # The opencode official installer currently installs to ~/.opencode/bin.
  if [[ ":$PATH:" != *":$HOME/.opencode/bin:"* ]]; then
    export PATH="$HOME/.opencode/bin:$PATH"
  fi
  if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    export PATH="$HOME/.local/bin:$PATH"
  fi
  # Refresh command hash
  hash -r 2>/dev/null || rehash 2>/dev/null || true
}
