#!/usr/bin/env bash
# install.sh — Install the Ostwin dashboard LaunchAgent (macOS auto-start)
#
# What it does:
#   1. Creates log directory
#   2. Substitutes OSTWIN_HOME in the plist and copies to ~/Library/LaunchAgents/
#   3. Loads the LaunchAgent via launchctl (starts on login)
#
# Usage: bash .agents/daemons/macos-dashboard/install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OSTWIN_HOME="${OSTWIN_HOME:-$HOME/.ostwin}"
PLIST_NAME="com.ostwin.dashboard.plist"
PLIST_SRC="$SCRIPT_DIR/$PLIST_NAME"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_DEST="$LAUNCH_AGENTS_DIR/$PLIST_NAME"
LOGS_DIR="$OSTWIN_HOME/logs"

info()  { echo "[ostwin-dashboard] $*"; }
error() { echo "[ostwin-dashboard] ERROR: $*" >&2; exit 1; }

# ── Preflight checks ─────────────────────────────────────────────────────────

[[ "$(uname -s)" == "Darwin" ]] || error "This installer is macOS-only."
[[ -f "$PLIST_SRC" ]] || error "Plist not found: $PLIST_SRC"

# ── 1. Create directories ────────────────────────────────────────────────────

mkdir -p "$LOGS_DIR"
mkdir -p "$LAUNCH_AGENTS_DIR"
info "Log directory: $LOGS_DIR"

# ── 2. Substitute OSTWIN_HOME placeholder and install plist ──────────────────

# macOS sed requires empty string after -i for in-place without backup
sed "s|OSTWIN_HOME|${OSTWIN_HOME}|g" "$PLIST_SRC" > "$PLIST_DEST"
chmod 644 "$PLIST_DEST"
info "Installed plist: $PLIST_DEST"

# Make daemon script executable
chmod +x "$SCRIPT_DIR/dashboard-daemon.sh"

# ── 3. Load (or reload) the LaunchAgent ──────────────────────────────────────

# Unload first in case it was already loaded (ignore error if not loaded)
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load -w "$PLIST_DEST"
info "LaunchAgent loaded: com.ostwin.dashboard"

# ── 4. Verify it started ────────────────────────────────────────────────────

sleep 2
if launchctl list | grep -q "com.ostwin.dashboard"; then
  info "Dashboard LaunchAgent is running."
else
  info "Warning: dashboard LaunchAgent may not have started yet. Check logs:"
  info "  tail -f $LOGS_DIR/dashboard-autostart-err.log"
fi

info ""
info "The dashboard will now auto-start on every login."
info "To stop temporarily:  launchctl unload $PLIST_DEST"
info "To remove auto-start: bash $SCRIPT_DIR/uninstall.sh"
