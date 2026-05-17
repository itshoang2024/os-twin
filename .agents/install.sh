#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Agent OS (Ostwin) — Cross-Platform Installer
#
# Installs all dependencies and the ostwin CLI on macOS and Linux.
#
# Usage:
#   ./install.sh               # Interactive mode — prompts before each step
#   ./install.sh --yes         # Non-interactive — auto-approve all installs
#   ./install.sh --dir /path   # Install to custom location (default: ~/.ostwin)
#   ./install.sh --channel        # Also install & start the channel connectors (Telegram + Discord + Slack)
#   ./install.sh --dashboard-only  # Install dashboard API + frontend only
#   ./install.sh --no-opencode-config  # Skip writing to ~/.config/opencode/opencode.json
#   ./install.sh --no-start       # Install only; do not start OpenCode/dashboard services
#   ./install.sh --help        # Show this help
#
# What gets installed:
#   - Python 3.10+       (via uv / brew / apt)
#   - PowerShell 7+      (via brew / Microsoft repos)
#   - uv                 (Python package/env manager)
#   - opencode            (Agent execution engine)
#   - Obscura            (built-in browser MCP runtime)
#   - Pester 5+          (PowerShell test framework)
#   - MCP dependencies   (fastapi, uvicorn, etc.)
#
# Supports: macOS (arm64/x86_64), Ubuntu/Debian, Fedora/RHEL/CentOS
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALLER_DIR="$SCRIPT_DIR/installer"
INSTALL_DIR="${HOME}/.ostwin"
# shellcheck disable=SC2034  # consumed by sourced modules
SOURCE_DIR="$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd || echo "")"
# shellcheck disable=SC2034
AUTO_YES=false; SKIP_OPTIONAL=false; DASHBOARD_ONLY=false
START_CHANNEL=false; DASHBOARD_PORT=3366; SKIP_OPENCODE_CONFIG=false; START_SERVICES=true
# shellcheck disable=SC2034
PYTHON_VERSION=""
# shellcheck disable=SC2034
PWSH_VERSION=""

# shellcheck disable=SC2034  # globals are consumed by sourced modules
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y)         AUTO_YES=true; shift ;;
    --dir)            INSTALL_DIR="$2"; shift 2 ;;
    --source-dir)     SOURCE_DIR="$2"; shift 2 ;;
    --port)           DASHBOARD_PORT="$2"; shift 2 ;;
    --skip-optional)  SKIP_OPTIONAL=true; shift ;;
    --dashboard-only) DASHBOARD_ONLY=true; AUTO_YES=true; shift ;;
    --channel)        START_CHANNEL=true; shift ;;
    --no-opencode-config) SKIP_OPENCODE_CONFIG=true; shift ;;
    --no-start|--skip-start) START_SERVICES=false; shift ;;
    --help|-h)        head -23 "$0" | tail -21; exit 0 ;;
    *)  echo "[ERROR] Unknown option: $1" >&2
        echo "Run './install.sh --help' for usage." >&2; exit 1 ;;
  esac
done
# shellcheck disable=SC2034
VENV_DIR="$INSTALL_DIR/.venv"

# Detect first-time install: venv doesn't exist yet
FIRST_INSTALL=false
if [[ ! -d "$VENV_DIR" ]]; then
  FIRST_INSTALL=true
fi

# ─── Source all modules ──────────────────────────────────────────────────────
for _mod in lib.sh versions.conf detect-os.sh check-deps.sh install-deps.sh \
            install-files.sh setup-venv.sh setup-env.sh setup-models.sh patch-mcp.sh \
            build-frontend.sh setup-path.sh setup-opencode.sh sync-agents.sh \
            start-opencode-server.sh start-dashboard.sh start-channels.sh verify.sh; do
  # shellcheck disable=SC1090
  source "$INSTALLER_DIR/$_mod"
done

# Ensure brew/local paths are available BEFORE any dependency checks
# This prevents "not in PATH" errors when tools are freshly installed
ensure_brew_paths

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "  ${BOLD}╔══════════════════════════════════════════════════╗${NC}"
echo -e "  ${BOLD}║     ${CYAN}Ostwin${NC}${BOLD} — Agent OS Installer                   ║${NC}"
echo -e "  ${BOLD}║     Multi-Agent War-Room Orchestrator            ║${NC}"
echo -e "  ${BOLD}╚══════════════════════════════════════════════════╝${NC}"
echo ""

header "1. Detecting platform"
detect_os
case "$OS" in
  macos) ok "macOS ($ARCH)" ;;
  linux) ok "Linux — $DISTRO ($ARCH) [pkg: $PKG_MGR]" ;;
  *)     fail "Unsupported OS: $(uname -s)"; exit 1 ;;
esac

# shellcheck disable=SC1091
source "$INSTALLER_DIR/_orchestrate-deps.sh"
echo ""

header "3. Building dashboard frontend (fe)"
build_frontend "dashboard/fe" "Dashboard FE" true

header "4. Installing Agent OS"
install_files
if [[ "$OS" == "..." ]]; then
  DAEMON_INSTALL="$INSTALL_DIR/.agents/daemons/macos-host/install.sh"
  # shellcheck disable=SC2015
  [[ -f "$DAEMON_INSTALL" ]] && {
    ask "Install macOS host daemon? (desktop automation)" && bash "$DAEMON_INSTALL" \
      || info "Skipped macOS daemon. Run manually later: bash $DAEMON_INSTALL"
  }
fi

header "5. Setting up Python environment"
setup_venv
header "5b. Setting up .env"
setup_env
header "5c. Initializing models catalog"
if $FIRST_INSTALL; then
  setup_models --force
else
  setup_models
fi
patch_mcp_config; sync_opencode_agents; compute_build_hash
header "5d. OpenCode agent permissions"
if $SKIP_OPENCODE_CONFIG; then
  info "Skipping OpenCode config (--no-opencode-config)"
else
  setup_opencode_permissions
fi

if $DASHBOARD_ONLY; then
  header "6. PowerShell modules (skipped — dashboard-only)"; info "Skipping in dashboard-only mode"
elif ! $SKIP_OPTIONAL && command -v pwsh &>/dev/null; then
  header "6. PowerShell modules"; install_pester
else
  header "6. PowerShell modules (skipped)"; info "PowerShell not available or --skip-optional set"
fi

if ! $DASHBOARD_ONLY; then
  header "7. Configuring PATH"; setup_path
else
  header "7. PATH (skipped — dashboard-only)"; info "Skipping PATH setup in dashboard-only mode"
  export PATH="$INSTALL_DIR/.agents/bin:$PATH"
fi

header "8. Verification"
verify_components
header "8a. Generating OpenCode tools"
generate_opencode_tools
section_9_start=$(get_now)
if $START_SERVICES; then
  header "9. Starting OpenCode server"
  start_opencode_server
  header "9a. Starting dashboard"
  start_dashboard; publish_skills
else
  header "9. Runtime services (skipped)"
  info "Skipping OpenCode/dashboard startup (--no-start). Start services from the runtime entrypoint."
fi
header "9c. Installing channel dependencies (Telegram + Discord + Slack)"
install_channels
ok_time "Section 9 complete" "$(print_duration "$section_9_start")"
# if $START_CHANNEL && [[ -n "${CHAN_DIR:-}" ]]; then
#   header "9d. Starting channel connectors"; start_channels
# fi
print_completion_banner
