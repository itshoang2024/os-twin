#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# start-opencode-server.sh — Thin wrapper around dashboard.lib.opencode_service
#
# All start/stop/restart/status logic lives in
# ``dashboard/lib/opencode_service.py`` so the installer, the dashboard, and any
# auto-start daemon stay in lockstep.  This file just discovers a Python
# interpreter and shells out to that module.
#
# Provides: start_opencode_server
#
# Requires: lib.sh, globals: INSTALL_DIR
# ──────────────────────────────────────────────────────────────────────────────

[[ -n "${_START_OPENCODE_SERVER_SH_LOADED:-}" ]] && return 0
_START_OPENCODE_SERVER_SH_LOADED=1

# Locate the Python interpreter that has the dashboard package installed.
# Prints the path on stdout; returns 1 if no suitable interpreter is found.
_opencode_service_python() {
  if [[ -x "$INSTALL_DIR/.venv/bin/python" ]]; then
    echo "$INSTALL_DIR/.venv/bin/python"
    return 0
  fi
  if command -v python3 &>/dev/null; then
    command -v python3
    return 0
  fi
  return 1
}

# Invoke ``python -m dashboard.lib.opencode_service <subcommand>`` with the
# correct working directory and PYTHONPATH so the ``dashboard`` package is
# importable from the installed tree at $INSTALL_DIR.
_opencode_service_invoke() {
  local subcmd="$1"
  local py
  if ! py=$(_opencode_service_python); then
    warn "No Python interpreter found — cannot manage opencode-serve"
    return 1
  fi
  OSTWIN_HOME="$INSTALL_DIR" \
  PYTHONPATH="$INSTALL_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    "$py" -m dashboard.lib.opencode_service "$subcmd"
}

start_opencode_server() {
  if ! command -v opencode &>/dev/null; then
    warn "opencode CLI not on PATH — skipping server start"
    info "Re-run install.sh or install manually from https://opencode.ai"
    return
  fi

  # Start quietly on success; opencode_service logs are noisy during install and
  # are only useful when startup fails.
  if _opencode_service_invoke start >/dev/null 2>&1; then
    return 0
  else
    warn "OpenCode server did not start cleanly"
    info "Check logs: $INSTALL_DIR/logs/opencode-server.log"
    info "Inspect state: $INSTALL_DIR/.venv/bin/python -m dashboard.lib.opencode_service status"
    return 1
  fi
}
