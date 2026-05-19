#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# setup-autostart.sh — OS-level auto-start registration for the Ostwin dashboard
#
# Provides: setup_autostart
#
# Registers the dashboard to start automatically at login on:
#   - macOS:  LaunchAgent (~/Library/LaunchAgents/com.ostwin.dashboard.plist)
#   - Linux:  systemd user service (ostwin-dashboard.service)
#
# The registration is independent of whether the dashboard starts immediately.
# This means --no-start skips immediate launch but still registers auto-start
# so the dashboard will start on the next login.
#
# Requires: lib.sh, detect-os.sh (OS), globals: INSTALL_DIR, DASHBOARD_PORT
# ──────────────────────────────────────────────────────────────────────────────

# Guard against double-sourcing
[[ -n "${_SETUP_AUTOSTART_SH_LOADED:-}" ]] && return 0
_SETUP_AUTOSTART_SH_LOADED=1

setup_autostart() {
  local daemon_install_script=""

  case "$OS" in
    macos)
      daemon_install_script="$INSTALL_DIR/.agents/daemons/macos-dashboard/install.sh"
      ;;
    linux)
      daemon_install_script="$INSTALL_DIR/.agents/daemons/linux-dashboard/install.sh"
      ;;
    *)
      # Unsupported OS (e.g., Windows uses PowerShell module)
      info "Auto-start registration not available for OS: $OS"
      return
      ;;
  esac

  if [[ ! -f "$daemon_install_script" ]]; then
    warn "Auto-start installer not found: $daemon_install_script"
    info "Dashboard will not auto-start on login. Start manually: ostwin dashboard start"
    return
  fi

  # Ensure the daemon scripts are executable
  local daemon_dir
  daemon_dir="$(dirname "$daemon_install_script")"
  find "$daemon_dir" -name "*.sh" -exec chmod +f {} \; 2>/dev/null || true

  step "Registering dashboard auto-start for $OS..."

  # Run the platform-specific installer
  # These scripts handle their own idempotency (unload before load, etc.)
  if bash "$daemon_install_script"; then
    ok "Dashboard auto-start registered (will start on login)"
  else
    warn "Auto-start registration failed for $OS"
    info "You can register manually: bash $daemon_install_script"
    info "Or start the dashboard manually: ostwin dashboard start"
  fi
}
