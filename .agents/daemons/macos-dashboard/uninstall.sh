#!/usr/bin/env bash
# uninstall.sh — Remove the Ostwin dashboard LaunchAgent (macOS auto-start)
#
# Usage: bash .agents/daemons/macos-dashboard/uninstall.sh
set -euo pipefail

OSTWIN_HOME="${OSTWIN_HOME:-$HOME/.ostwin}"
PLIST_NAME="com.ostwin.dashboard.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME"

info()  { echo "[ostwin-dashboard] $*"; }

# ── Unload the LaunchAgent ───────────────────────────────────────────────────

if [[ -f "$PLIST_DEST" ]]; then
  launchctl unload "$PLIST_DEST" 2>/dev/null && \
    info "LaunchAgent unloaded." || \
    info "LaunchAgent was not loaded."
  rm -f "$PLIST_DEST"
  info "Removed plist: $PLIST_DEST"
else
  info "Plist not found — already uninstalled."
fi

info "Dashboard auto-start removed. Start manually with: ostwin dashboard start"
