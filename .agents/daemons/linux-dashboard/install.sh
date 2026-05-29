#!/usr/bin/env bash
# install.sh — Install the Ostwin dashboard systemd user service (Linux auto-start)
#
# What it does:
#   1. Substitutes home dir in the service unit
#   2. Copies to ~/.config/systemd/user/
#   3. Enables and starts the service
#
# Usage: bash .agents/daemons/linux-dashboard/install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OSTWIN_HOME="${OSTWIN_HOME:-$HOME/.ostwin}"
SERVICE_NAME="ostwin-dashboard.service"
SERVICE_SRC="$SCRIPT_DIR/$SERVICE_NAME"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
SERVICE_DEST="$SYSTEMD_USER_DIR/$SERVICE_NAME"

info()  { echo "[ostwin-dashboard] $*"; }
error() { echo "[ostwin-dashboard] ERROR: $*" >&2; exit 1; }

# ── Preflight checks ─────────────────────────────────────────────────────────

[[ "$(uname -s)" == "Linux" ]] || error "This installer is Linux-only."
[[ -f "$SERVICE_SRC" ]] || error "Service unit not found: $SERVICE_SRC"

# Check if systemd user session is available
if ! systemctl --user status &>/dev/null; then
  error "systemd user session not available. Enable lingering: loginctl enable-linger $USER"
fi

# ── 1. Create directories ────────────────────────────────────────────────────

mkdir -p "$SYSTEMD_USER_DIR"
mkdir -p "$OSTWIN_HOME/logs"

# ── 2. Make daemon script executable ─────────────────────────────────────────

chmod +x "$SCRIPT_DIR/dashboard-daemon.sh"

# ── 3. Install service unit ──────────────────────────────────────────────────

# systemd supports %h for $HOME natively, so the service file uses %h.
# Copy directly — no substitution needed since %h is a systemd specifier.
cp "$SERVICE_SRC" "$SERVICE_DEST"
info "Installed service unit: $SERVICE_DEST"

# ── 4. Reload and enable ─────────────────────────────────────────────────────

systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME"
info "Service enabled: $SERVICE_NAME"

# ── 5. Start the service ─────────────────────────────────────────────────────

systemctl --user start "$SERVICE_NAME" 2>/dev/null || true
sleep 2

if systemctl --user is-active --quiet "$SERVICE_NAME"; then
  info "Dashboard service is running."
else
  info "Warning: dashboard service may not have started yet. Check:"
  info "  systemctl --user status ostwin-dashboard"
  info "  journalctl --user -u ostwin-dashboard -f"
fi

info ""
info "The dashboard will now auto-start on every login."
info "To stop temporarily:   systemctl --user stop ostwin-dashboard"
info "To remove auto-start:  bash $SCRIPT_DIR/uninstall.sh"
