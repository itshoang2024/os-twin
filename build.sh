#!/usr/bin/env bash
# Backward-compatible local source installer wrapper. Prefer install.sh for
# public/curl installs; use build.sh from a checkout to exercise this tree.
# Native local source installer wrapper. Optional features are opt-in here:
#   ./build.sh --search-engine   # install/start SearXNG
#   ./build.sh --daemon          # install dashboard/host daemon autostart
#   ./build.sh --ngrok           # allow ngrok auto-start when token is set
#   ./build.sh --no-channel      # skip bot/channel connector startup
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

has_source_dir=false
wants_search_engine=false
sets_daemon=false
sets_ngrok=false
sets_channel=false
for arg in "$@"; do
  case "$arg" in
    --source-dir)
      has_source_dir=true
      ;;
    --search-engine|--with-search-engine)
      wants_search_engine=true
      ;;
    --daemon|--with-daemon|--no-daemon|--without-daemon|--deamon|--with-deamon|--no-deamon|--without-deamon)
      sets_daemon=true
      ;;
    --ngrok|--with-ngrok|--no-ngrok|--without-ngrok)
      sets_ngrok=true
      ;;
    --channel|--with-channel|--no-channel|--without-channel)
      sets_channel=true
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

native_defaults=(--native)
if ! $sets_daemon; then
  native_defaults+=(--no-daemon)
fi
if ! $sets_ngrok; then
  native_defaults+=(--no-ngrok)
fi
if ! $sets_channel; then
  native_defaults+=(--channel)
fi

exec bash "$SCRIPT_DIR/.agents/install.sh" "${source_args[@]}" "${native_defaults[@]}" "$@"
