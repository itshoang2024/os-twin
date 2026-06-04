#!/bin/bash
# migrate-memory.sh — Move per-project .memory/ dirs to centralized store
#
# For each project with a real .memory/ directory (not a symlink):
# 1. Look up the plan_id from the plan registry
# 2. Move contents to ~/.ostwin/memory/<plan_id>/
# 3. Replace .memory/ with a symlink
#
# Usage:
#   bash scripts/migrate-memory.sh                     # migrate all
#   bash scripts/migrate-memory.sh --dry-run            # preview only
#   bash scripts/migrate-memory.sh /path/to/project     # migrate one

set -euo pipefail

MEMORY_BASE="${HOME}/.ostwin/memory"
PLANS_DIR="${HOME}/os-twin/.agents/plans"
DRY_RUN=false
TARGET=""

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        *) TARGET="$arg" ;;
    esac
done

mkdir -p "$MEMORY_BASE"

migrate_one() {
    local project_memory="$1"
    local project_dir
    project_dir=$(dirname "$project_memory")
    local project_name
    project_name=$(basename "$project_dir")

    # Skip symlinks
    if [ -L "$project_memory" ]; then
        echo "  SKIP (already symlink): $project_memory → $(readlink "$project_memory")"
        return
    fi

    # Skip empty .memory dirs
    if [ -z "$(ls -A "$project_memory" 2>/dev/null)" ]; then
        echo "  SKIP (empty): $project_memory"
        return
    fi

    # Try to find plan_id from plan registry
    local plan_id=""
    if [ -d "$PLANS_DIR" ]; then
        for meta in "$PLANS_DIR"/*.meta.json; do
            [ -f "$meta" ] || continue
            local working_dir
            working_dir=$(python3 -c "import json; print(json.load(open('$meta')).get('working_dir',''))" 2>/dev/null || true)
            if [ "$working_dir" = "$project_dir" ]; then
                plan_id=$(basename "$meta" .meta.json)
                break
            fi
        done
    fi

    # Fallback: use project directory name
    if [ -z "$plan_id" ]; then
        plan_id="$project_name"
        echo "  WARN: No plan registry entry for $project_dir, using name '$plan_id'"
    fi

    local central_dir="$MEMORY_BASE/memory-$plan_id"

    if $DRY_RUN; then
        echo "  DRY-RUN: $project_memory → $central_dir"
        return
    fi

    echo "  MIGRATE: $project_memory → $central_dir"
    mkdir -p "$central_dir"
    rsync -a "$project_memory/" "$central_dir/" 2>/dev/null || cp -a "$project_memory"/* "$central_dir/" 2>/dev/null
    rm -rf "$project_memory"
    ln -sfn "$central_dir" "$project_memory"
    echo "  OK: symlink created"
}

if [ -n "$TARGET" ]; then
    # Migrate single project
    if [ -d "$TARGET/.memory" ]; then
        migrate_one "$TARGET/.memory"
    else
        echo "ERROR: $TARGET/.memory does not exist"
        exit 1
    fi
else
    # Migrate all projects under ~/ostwin-workingdir
    echo "Scanning ~/ostwin-workingdir for .memory directories..."
    found=0
    for project_memory in ~/ostwin-workingdir/*/.memory; do
        [ -d "$project_memory" ] || continue
        found=$((found + 1))
        migrate_one "$project_memory"
    done
    echo ""
    echo "Done. Processed $found directories."
    echo "Centralized store: $MEMORY_BASE"
    ls -la "$MEMORY_BASE" 2>/dev/null
fi
