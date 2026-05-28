#!/usr/bin/env bash
# Backward-compatible local source installer wrapper. Prefer install.sh for
# public/curl installs; use build.sh from a checkout to exercise this tree.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

has_source_dir=false
for arg in "$@"; do
  if [[ "$arg" == "--source-dir" ]]; then
    has_source_dir=true
    break
  fi
done

source_args=()
if ! $has_source_dir; then
  source_args=(--source-dir "$SCRIPT_DIR")
fi

exec bash "$SCRIPT_DIR/.agents/install.sh" "${source_args[@]}" "$@"
