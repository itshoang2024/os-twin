#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Agent OS (Ostwin) Bootstrap Installer
#
# This is the public curl entrypoint:
#   curl -fsSL https://raw.githubusercontent.com/igot-ai/os-twin/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/igot-ai/os-twin/main/install.sh | bash -s -- --yes
#
# Downloads the source archive and runs the native Bash installer directly.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info() { echo -e "  ${BLUE}info${NC}  $1"; }
ok()   { echo -e "  ${GREEN}ok${NC}    $1"; }
warn() { echo -e "  ${YELLOW}warn${NC}  $1"; }
fail() { echo -e "  ${RED}fail${NC}  $1"; exit 1; }

REPO="${OSTWIN_INSTALLER_REPO:-igot-ai/os-twin}"
SOURCE_REF="${OSTWIN_SOURCE_REF:-main}"
if [[ -z "${OSTWIN_SOURCE_REF+x}" && -n "${OSTWIN_INSTALLER_VERSION:-}" && "${OSTWIN_INSTALLER_VERSION}" != "latest" ]]; then
  SOURCE_REF="$OSTWIN_INSTALLER_VERSION"
fi

cleanup_dir() {
  local dir="$1"
  [[ -n "$dir" && -d "$dir" ]] && rm -rf "$dir"
}

source_archive_url() {
  local ref="$1"
  if [[ "$ref" == refs/* ]]; then
    printf 'https://github.com/%s/archive/%s.tar.gz' "$REPO" "$ref"
  elif [[ "$ref" == v* ]]; then
    printf 'https://github.com/%s/archive/refs/tags/%s.tar.gz' "$REPO" "$ref"
  else
    printf 'https://github.com/%s/archive/refs/heads/%s.tar.gz' "$REPO" "$ref"
  fi
}

download_to() {
  local url="$1"
  local dest="$2"
  if command -v curl &>/dev/null; then
    curl -fsSL "$url" -o "$dest"
  elif command -v wget &>/dev/null; then
    wget -q "$url" -O "$dest"
  else
    return 1
  fi
}

run_source_fallback() {
  local tmp_dir
  local archive_url
  local extracted_dir=""

  info "Checking bootstrap dependencies..."
  if ! command -v curl &>/dev/null && ! command -v wget &>/dev/null; then
    fail "Either 'curl' or 'wget' is required to download the installer."
  fi
  if ! command -v tar &>/dev/null; then
    fail "'tar' is required to extract the installer."
  fi
  ok "Bootstrap dependencies checked."

  info "Downloading Agent OS source archive..."
  tmp_dir=$(mktemp -d -t ostwin-source-XXXXXX)
  archive_url=$(source_archive_url "$SOURCE_REF")

  if ! download_to "$archive_url" "$tmp_dir/source.tar.gz"; then
    cleanup_dir "$tmp_dir"
    fail "Failed to download source archive from $archive_url."
  fi
  if ! tar -xzf "$tmp_dir/source.tar.gz" -C "$tmp_dir"; then
    cleanup_dir "$tmp_dir"
    fail "Failed to extract source archive."
  fi

  for candidate in "$tmp_dir"/os-twin-*; do
    if [[ -d "$candidate" ]]; then
      extracted_dir="$candidate"
      break
    fi
  done

  if [[ -z "$extracted_dir" ]]; then
    cleanup_dir "$tmp_dir"
    fail "Failed to find extracted source directory in $tmp_dir."
  fi

  ok "Source code downloaded and extracted."
  info "Launching native Bash installer..."
  bash "$extracted_dir/.agents/install.sh" "$@"
}

echo -e "\n  ${BOLD}╔══════════════════════════════════════════════════╗${NC}"
echo -e "  ${BOLD}║     ${BLUE}Ostwin${NC}${BOLD} — Agent OS Bootstrapper                ║${NC}"
echo -e "  ${BOLD}╚══════════════════════════════════════════════════╝${NC}\n"

if [[ "${OSTWIN_BOOTSTRAP_SOURCE_ONLY:-0}" == "1" ]]; then
  run_source_fallback "$@"
  exit $?
fi

run_source_fallback "$@"
