#!/usr/bin/env bash
# Agent OS — Framework Sync
#
# Re-syncs framework files from the os-twin source to an already-initialized
# target project, preserving project-specific data (plans, .env, config).
#
# Usage: sync.sh [target-directory]
#
# If no directory is specified, syncs to the current directory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_AGENTS="$SCRIPT_DIR"

TARGET_DIR="${1:-.}"
TARGET_AGENTS="$TARGET_DIR/.agents"

if [[ ! -d "$TARGET_AGENTS" ]]; then
  echo "[ERROR] .agents/ not found in $TARGET_DIR"
  echo "  Run 'ostwin init $TARGET_DIR' first to initialize."
  exit 1
fi

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║        Ostwin — Framework Sync        ║"
echo "  ╚══════════════════════════════════════╝"
echo ""
echo "  Source: $SOURCE_AGENTS"
echo "  Target: $TARGET_AGENTS"
echo ""

# Sync entire .agents content, excluding project-specific files
rsync -a \
  --exclude='plans/' \
  --exclude='.env' \
  --exclude='config.json' \
  --exclude='dashboard/' \
  "$SOURCE_AGENTS/" "$TARGET_AGENTS/"

echo "  [synced] core framework files"

# Sync channel tools (bash + PowerShell)
for script in read.sh wait-for.sh Read-Messages.ps1 Wait-ForMessage.ps1; do
  [[ -f "$SOURCE_AGENTS/channel/$script" ]] && cp "$SOURCE_AGENTS/channel/$script" "$TARGET_AGENTS/channel/$script"
done
echo "  [synced] channel tools"

# Sync plan tools (bash + PowerShell)
mkdir -p "$TARGET_AGENTS/plan"
for script in New-Plan.ps1 Start-Plan.ps1 New-Plan.Tests.ps1 Start-Plan.Tests.ps1; do
  [[ -f "$SOURCE_AGENTS/plan/$script" ]] && cp "$SOURCE_AGENTS/plan/$script" "$TARGET_AGENTS/plan/$script"
done
echo "  [synced] plan tools"

# Sync role definitions and runners (bash + PowerShell)
mkdir -p "$TARGET_AGENTS/roles/_base"
for role in manager engineer qa architect; do
  mkdir -p "$TARGET_AGENTS/roles/$role"
  for file in ROLE.md run.sh loop.sh deepagents-cli.md role.json Start-*.ps1; do
    for src in "$SOURCE_AGENTS/roles/$role/"$file; do
      [[ -f "$src" ]] && cp "$src" "$TARGET_AGENTS/roles/$role/$(basename "$src")"
    done
  done
done
# Sync _base role engine
for file in "$SOURCE_AGENTS/roles/_base/"*.ps1; do
  [[ -f "$file" ]] && cp "$file" "$TARGET_AGENTS/roles/_base/$(basename "$file")"
done
# Sync role registry
[[ -f "$SOURCE_AGENTS/roles/registry.json" ]] && cp "$SOURCE_AGENTS/roles/registry.json" "$TARGET_AGENTS/roles/registry.json"
echo "  [synced] roles"

# Sync release tools
for script in draft.sh signoff.sh; do
  [[ -f "$SOURCE_AGENTS/release/$script" ]] && cp "$SOURCE_AGENTS/release/$script" "$TARGET_AGENTS/release/$script"
done
[[ -f "$SOURCE_AGENTS/release/RELEASE.template.md" ]] && cp "$SOURCE_AGENTS/release/RELEASE.template.md" "$TARGET_AGENTS/release/RELEASE.template.md"
echo "  [synced] release tools"

# Sync libraries (bash + PowerShell modules)
for lib in utils.sh log.sh; do
  [[ -f "$SOURCE_AGENTS/lib/$lib" ]] && cp "$SOURCE_AGENTS/lib/$lib" "$TARGET_AGENTS/lib/$lib"
done
for lib in "$SOURCE_AGENTS/lib/"*.psm1; do
  [[ -f "$lib" ]] && cp "$lib" "$TARGET_AGENTS/lib/$(basename "$lib")"
done
echo "  [synced] libraries"

# Sync CLI entry point
[[ -f "$SOURCE_AGENTS/bin/ostwin" ]] && cp "$SOURCE_AGENTS/bin/ostwin" "$TARGET_AGENTS/bin/ostwin"
echo "  [synced] CLI entry point"

# Sync plan template (but NOT user plans)
[[ -f "$SOURCE_AGENTS/plans/PLAN.template.md" ]] && cp "$SOURCE_AGENTS/plans/PLAN.template.md" "$TARGET_AGENTS/plans/PLAN.template.md"
echo "  [synced] plan template"

# Sync dashboard from sibling directory
if [[ -d "$SOURCE_AGENTS/../dashboard" ]]; then
  echo "  [synced] dashboard"
  mkdir -p "$TARGET_AGENTS/dashboard"
  rsync -a --delete "$SOURCE_AGENTS/../dashboard/" "$TARGET_AGENTS/dashboard/"
fi

# Check for new config keys in source that target is missing
if [[ -f "$SOURCE_AGENTS/config.json" && -f "$TARGET_AGENTS/config.json" ]]; then
  SOURCE_KEYS=$(grep -oE '"[^"]+"\s*:' "$SOURCE_AGENTS/config.json" | sort -u)
  TARGET_KEYS=$(grep -oE '"[^"]+"\s*:' "$TARGET_AGENTS/config.json" | sort -u)
  NEW_KEYS=$(comm -23 <(echo "$SOURCE_KEYS") <(echo "$TARGET_KEYS"))
  if [[ -n "$NEW_KEYS" ]]; then
    echo ""
    echo "  [NOTICE] Source config.json has new keys not in your project config:"
    echo "$NEW_KEYS" | while read -r key; do
      echo "    $key"
    done
    echo "  Review $SOURCE_AGENTS/config.json and update your config manually."
  fi
fi

# Make all scripts executable
find "$TARGET_AGENTS" -name "*.sh" -exec chmod +x {} \;
chmod +x "$TARGET_AGENTS/bin/ostwin" 2>/dev/null || true

echo ""
echo "  [OK] Framework synced to $TARGET_AGENTS/"
echo ""
echo "  Preserved:"
echo "    - .agents/plans/ (your plans)"
echo "    - .agents/.env (your secrets)"
echo "    - .agents/config.json (your config)"
echo ""
