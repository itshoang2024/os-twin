#!/usr/bin/env bash
# setup-search-engine.sh -- optional local SearXNG installer hook.
#
# Provides: setup_search_engine

[[ -n "${_SETUP_SEARCH_ENGINE_SH_LOADED:-}" ]] && return 0
_SETUP_SEARCH_ENGINE_SH_LOADED=1

setup_search_engine() {
  local search_script="$INSTALL_DIR/.agents/search-engine.sh"
  if [[ ! -f "$search_script" ]]; then
    warn "Search engine manager not found: $search_script"
    return 1
  fi

  OSTWIN_HOME="$INSTALL_DIR" bash "$search_script" install
}
