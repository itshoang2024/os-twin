#!/usr/bin/env bash
# uninstall.sh — Remove the Ostwin dashboard systemd user service (Linux auto-start)
#
# Usage: bash .agents/daemons/linux-dashboard/uninstall.sh
set -euo pipefail

SERVICE_NAME="ostwin-dashboard.service"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
SERVICE_DEST="$SYSTEMD_USER_DIR/$SERVICE_NAME"

info()  { echo "[ostwin-dashboard] $*"; }

# ── Stop and disable ─────────────────────────────────────────────────────────

if [[ -f "$SERVICE_DEST" ]]; then
  systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
  systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
  rm -f "$SERVICE_DEST"
  systemctl --user daemon-reload
  info "Service stopped, disabled, and unit file removed."
else
  info "Service unit not found — already uninstalled."
fi

info "Dashboard auto-start removed. Start manually with: ostwin dashboard start"
