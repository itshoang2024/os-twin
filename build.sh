#!/usr/bin/env bash
# Backward-compatible local source installer wrapper. Prefer install.sh for
# public/curl installs; use build.sh from a checkout to exercise this tree.
# Pass --search-engine to install .agents/search-engine.sh through the native
# installer hook.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

has_source_dir=false
wants_search_engine=false
for arg in "$@"; do
  case "$arg" in
    --source-dir)
      has_source_dir=true
      ;;
    --search-engine|--with-search-engine)
      wants_search_engine=true
      ;;
  esac
done

if $wants_search_engine && [[ ! -f "$SCRIPT_DIR/.agents/search-engine.sh" ]]; then
  echo "[ERROR] Missing search engine manager: $SCRIPT_DIR/.agents/search-engine.sh" >&2
  exit 1
fi

source_args=()
if ! $has_source_dir; then
  source_args=(--source-dir "$SCRIPT_DIR")
fi

exec bash "$SCRIPT_DIR/.agents/install.sh" "${source_args[@]}" "$@"
