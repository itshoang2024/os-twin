#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Agent OS (Ostwin) Bootstrap Installer
#
# This is the public curl entrypoint:
#   curl -fsSL https://raw.githubusercontent.com/igot-ai/os-twin/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/igot-ai/os-twin/main/install.sh | bash -s -- --yes
#
# Preferred path:
#   1. Download the packaged Go installer from GitHub Releases.
#   2. Let that binary provide the interactive terminal UX.
#   3. The binary downloads source and delegates to .agents/install.sh.
#
# Fallback path:
#   If no release binary exists yet, download the source archive and run the
#   existing Bash installer directly.
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
VERSION="${OSTWIN_INSTALLER_VERSION:-latest}"
SOURCE_REF="${OSTWIN_SOURCE_REF:-main}"
if [[ -z "${OSTWIN_SOURCE_REF+x}" && "$VERSION" != "latest" ]]; then
  SOURCE_REF="$VERSION"
fi
BINARY_NAME="ostwin-installer"
RELEASE_UNAVAILABLE=100
INTEGRITY_FAILURE=101

cleanup_dir() {
  local dir="$1"
  [[ -n "$dir" && -d "$dir" ]] && rm -rf "$dir"
}

detect_os() {
  case "$(uname -s)" in
    Darwin) printf 'darwin' ;;
    Linux)  printf 'linux' ;;
    *)      return 1 ;;
  esac
}

detect_arch() {
  case "$(uname -m)" in
    x86_64|amd64) printf 'amd64' ;;
    arm64|aarch64) printf 'arm64' ;;
    *) return 1 ;;
  esac
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

sha256_file() {
  local file="$1"
  if command -v shasum &>/dev/null; then
    shasum -a 256 "$file" | cut -d ' ' -f 1
  elif command -v sha256sum &>/dev/null; then
    sha256sum "$file" | cut -d ' ' -f 1
  else
    return 1
  fi
}

verify_release_checksum() {
  local archive="$1"
  local asset="$2"
  local base_url="$3"
  local tmp_dir="$4"
  local checksums="$tmp_dir/checksums.txt"
  local expected
  local actual

  if ! download_to "$base_url/checksums.txt" "$checksums"; then
    warn "Checksum file unavailable; continuing without checksum verification."
    return 0
  fi

  expected=$(awk -v asset="$asset" '$2 == asset {print $1; exit}' "$checksums")
  if [[ -z "$expected" ]]; then
    warn "Checksum entry for $asset not found; continuing without checksum verification."
    return 0
  fi

  if ! actual=$(sha256_file "$archive"); then
    warn "No SHA256 tool found; continuing without checksum verification."
    return 0
  fi

  if [[ "$actual" != "$expected" ]]; then
    warn "Checksum mismatch for $asset."
    return "$INTEGRITY_FAILURE"
  fi

  ok "Release checksum verified."
}

run_release_installer() {
  local os
  local arch
  local asset
  local base_url
  local tmp_dir
  local archive
  local installer
  local status

  os=$(detect_os) || return "$RELEASE_UNAVAILABLE"
  arch=$(detect_arch) || return "$RELEASE_UNAVAILABLE"
  asset="ostwin-installer_${os}_${arch}.tar.gz"

  if [[ "$VERSION" == "latest" ]]; then
    base_url="https://github.com/${REPO}/releases/latest/download"
  else
    base_url="https://github.com/${REPO}/releases/download/${VERSION}"
  fi

  tmp_dir=$(mktemp -d -t ostwin-bootstrap-XXXXXX)
  archive="$tmp_dir/$asset"

  info "Downloading packaged installer: $asset"
  if ! download_to "$base_url/$asset" "$archive"; then
    cleanup_dir "$tmp_dir"
    return "$RELEASE_UNAVAILABLE"
  fi

  if ! verify_release_checksum "$archive" "$asset" "$base_url" "$tmp_dir"; then
    cleanup_dir "$tmp_dir"
    return "$INTEGRITY_FAILURE"
  fi

  if ! tar -xzf "$archive" -C "$tmp_dir"; then
    cleanup_dir "$tmp_dir"
    return "$INTEGRITY_FAILURE"
  fi

  installer="$tmp_dir/$BINARY_NAME"
  if [[ ! -f "$installer" ]]; then
    for candidate in "$tmp_dir"/*/"$BINARY_NAME"; do
      if [[ -f "$candidate" ]]; then
        installer="$candidate"
        break
      fi
    done
  fi

  if [[ ! -f "$installer" ]]; then
    cleanup_dir "$tmp_dir"
    return "$INTEGRITY_FAILURE"
  fi

  chmod +x "$installer"
  ok "Launching interactive Go installer."
  "$installer" "$@"
  status=$?
  cleanup_dir "$tmp_dir"
  return "$status"
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

status=0
run_release_installer "$@" || status=$?
if [[ "$status" -eq 0 ]]; then
  exit 0
fi
if [[ "$status" -eq "$INTEGRITY_FAILURE" ]]; then
  fail "Packaged installer integrity check failed; refusing source fallback."
fi
if [[ "$status" -ne "$RELEASE_UNAVAILABLE" ]]; then
  exit "$status"
fi

warn "Packaged installer unavailable; falling back to source installer."
run_source_fallback "$@"
