#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# sync-skills.sh — Scan OSTWIN_HOME for SKILL.md files and register them
#                  with the dashboard vector store.
#
# Usage:
#   sync-skills.sh                          # Scan ~/.ostwin for skills
#   sync-skills.sh --install-from /path     # Copy skills from a project dir
#                                           # into ~/.ostwin/.agents/skills/roles/...
#                                           # then sync
#
# Environment:
#   OSTWIN_HOME        Override install dir (default: ~/.ostwin)
#   DASHBOARD_PORT     Dashboard port (default: 3366)
#   OSTWIN_API_KEY     Dashboard authentication key
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ─── Configuration ────────────────────────────────────────────────────────────

OSTWIN_HOME="${OSTWIN_HOME:-$HOME/.ostwin}"
DASHBOARD_PORT="${DASHBOARD_PORT:-3366}"
DASHBOARD_URL="http://localhost:${DASHBOARD_PORT}"
OSTWIN_API_KEY="${OSTWIN_API_KEY:-}"
INSTALL_FROM=""

# ─── Colors ───────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

ok()   { echo -e "    ${GREEN}[OK]${NC} $1"; }
warn() { echo -e "    ${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "    ${RED}[FAIL]${NC} $1"; }
info() { echo -e "    ${DIM}$1${NC}"; }
step() { echo -e "  ${CYAN}→${NC} $1"; }
ok_time() { echo -e "    ${GREEN}[OK]${NC} $1 ${DIM}($2)${NC}"; }

get_now() {
  date +%s
}

print_duration() {
  local start=$1
  local end
  end=$(get_now)
  echo "$((end - start))s"
}

# ─── Load .env ────────────────────────────────────────────────────────────────

if [[ -f "$OSTWIN_HOME/.env" ]]; then
  path_before_env="$PATH"
  set -a
  # shellcheck source=/dev/null
  source "$OSTWIN_HOME/.env"
  set +a
  export PATH="$path_before_env"
  hash -r 2>/dev/null || true
  OSTWIN_API_KEY="${OSTWIN_API_KEY:-}"
fi

# ─── Argument Parsing ────────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-from)
      INSTALL_FROM="$2"
      shift 2
      ;;
    --port)
      DASHBOARD_PORT="$2"
      DASHBOARD_URL="http://localhost:${DASHBOARD_PORT}"
      shift 2
      ;;
    --home)
      OSTWIN_HOME="$2"
      shift 2
      ;;
    --help|-h)
      echo "Usage: sync-skills.sh [--install-from DIR] [--port PORT] [--home DIR]"
      echo ""
      echo "  --install-from DIR   Copy skills from DIR into ~/.ostwin/.agents/skills/ first"
      echo "  --port PORT          Dashboard port (default: 3366)"
      echo "  --home DIR           Override OSTWIN_HOME (default: ~/.ostwin)"
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# ─── Build curl auth args ────────────────────────────────────────────────────

CURL_AUTH=()
if [[ -n "$OSTWIN_API_KEY" ]]; then
  CURL_AUTH=(-H "X-API-Key: ${OSTWIN_API_KEY}")
fi

# ─── Utility ──────────────────────────────────────────────────────────────────

extract_skill_meta() {
  local skill_md="$1"
  awk '
    BEGIN { name=""; desc=""; tags="[]"; in_yaml=0; key=""; val=""; block_style=0; }
    /^---$/ { 
      if (in_yaml == 0) { in_yaml=1; next; } else { in_yaml=0; exit; } 
    }
    {
      if (in_yaml == 1) {
        # Handle continuation of block scalar (indented lines)
        if (block_style == 1) {
          if ($0 ~ /^[ \t]+/) {
            line = $0; sub(/^[ \t]+/, "", line);
            if (desc == "") desc = line; else desc = desc " " line;
            next;
          } else {
            block_style = 0; # End of block
          }
        }

        # Match key: value
        if ($0 ~ /^[a-z_]+:[ \t]*/) {
          key = $1; sub(/:$/, "", key);
          val = $0; sub(/^[a-z_]+:[ \t]*/, "", val);
          
          if (key == "name") { name = val; }
          else if (key == "tags") { tags = val; }
          else if (key == "description") {
            if (val ~ /^[>|]/) {
              block_style = 1; # Start capturing block
            } else {
              desc = val;
            }
          }
        }
      }
    }
    END {
      # Strip outer quotes from name and desc
      gsub(/^["\047]|["\047]$/, "", name);
      gsub(/^["\047]|["\047]$/, "", desc);
      if (tags == "" || tags == "null") tags="[]";
      
      # Escape single quotes for use in eval
      gsub(/'\''/, "'\''\\'\'''\''", name);
      gsub(/'\''/, "'\''\\'\'''\''", desc);
      gsub(/'\''/, "'\''\\'\'''\''", tags);
      printf "skill_name_meta='\''%s'\''; skill_desc_meta='\''%s'\''; skill_tags_meta='\''%s'\'';\n", name, desc, tags;
    }
  ' "$skill_md" | tr -d '\r'
}

# ─── Part 2: Install skills from a project directory ─────────────────────────

install_from_dir() {
  local source_dir="$1"
  local dest_base="$OSTWIN_HOME/.agents/skills"
  local copied=0
  local start_time
  start_time=$(get_now)

  step "Scanning $source_dir for SKILL.md files..."

  # Walk source for SKILL.md files
  while IFS= read -r skill_md; do
    local skill_dir
    skill_dir="$(dirname "$skill_md")"
    local skill_name
    skill_name="$(basename "$skill_dir")"

    # Skip nested SKILL.md files that live inside another skill's tree
    # (e.g. develop-ui/references/animation-modify/SKILL.md).
    # The parent skill's cp -r already copies them.
    local _parent="$skill_dir"
    local _is_nested=false
    while [[ "$_parent" != "$source_dir" && "$_parent" != "/" ]]; do
      _parent="$(dirname "$_parent")"
      if [[ -f "$_parent/SKILL.md" ]]; then
        _is_nested=true
        break
      fi
    done
    if $_is_nested; then
      continue
    fi

    eval "$(extract_skill_meta "$skill_md")"
    if [[ -n "$skill_name_meta" ]]; then
       skill_name="$skill_name_meta"
    fi

    # Determine role and category from path structure
    # Expected: */roles/{role}/{skill_name_dir}/SKILL.md
    # or:       */global/{skill_name_dir}/SKILL.md
    local rel_from_source
    rel_from_source="${skill_dir#"$source_dir"/}"

    local dest_dir=""
    if [[ "$rel_from_source" =~ roles/([^/]+)/([^/]+)$ ]]; then
      local role="${BASH_REMATCH[1]}"
      dest_dir="$dest_base/roles/$role/$skill_name"
    elif [[ "$rel_from_source" =~ global/([^/]+)$ ]]; then
      dest_dir="$dest_base/global/$skill_name"
    else
      # Fallback: infer role from YAML frontmatter tags
      local first_tag=""
      if [[ "$skill_tags_meta" == \[*\] ]]; then
        first_tag=$(echo "$skill_tags_meta" | tr -d '[]' | cut -d',' -f1 | awk '{$1=$1};1')
      elif [[ -n "$skill_tags_meta" && "$skill_tags_meta" != "[]" ]]; then
        first_tag=$(echo "$skill_tags_meta" | cut -d',' -f1 | awk '{$1=$1};1')
      fi

      if [[ -n "$first_tag" ]]; then
        dest_dir="$dest_base/roles/$first_tag/$skill_name"
      else
        dest_dir="$dest_base/global/$skill_name"
      fi
    fi

    if [[ -z "$dest_dir" ]]; then
      warn "Could not determine destination for $skill_md — skipping"
      continue
    fi

    # Skip if source and destination are the same directory
    local resolved_src resolved_dst
    resolved_src="$(cd "$skill_dir" 2>/dev/null && pwd)"
    resolved_dst="$(mkdir -p "$dest_dir" && cd "$dest_dir" 2>/dev/null && pwd)"
    if [[ "$resolved_src" == "$resolved_dst" ]]; then
      info "  $skill_name (already in place)"
      ((copied++)) || true
      continue
    fi

    # Copy the entire skill directory (overwrite)
    mkdir -p "$dest_dir"
    cp -r "$skill_dir"/* "$dest_dir/" 2>/dev/null || cp -r "$skill_dir"/. "$dest_dir/"
    info "  $skill_name → ${dest_dir#"$OSTWIN_HOME"/}"
    ((copied++)) || true
  done < <(find "$source_dir" -name "SKILL.md" -type f 2>/dev/null)

  if [[ $copied -gt 0 ]]; then
    ok_time "$copied skill(s) copied to $dest_base" "$(print_duration "$start_time")"
  else
    warn "No SKILL.md files found in $source_dir"
  fi
}

# ─── Part 1: Scan OSTWIN_HOME and register via API ──────────────────────────

sync_home_skills() {
  local skills_base="$OSTWIN_HOME/.agents/skills"
  local start_time
  start_time=$(get_now)
  step "Scanning $skills_base for SKILL.md files..."

  local total=0
  local installed=0
  local failed=0

  local search_dirs=()
  [[ -d "$skills_base/roles" ]] && search_dirs+=("$skills_base/roles")
  [[ -d "$skills_base/global" ]] && search_dirs+=("$skills_base/global")

  if [[ ${#search_dirs[@]} -eq 0 ]]; then
    warn "No skills directories found in $skills_base"
    return
  fi

  while IFS= read -r skill_md; do
    local skill_dir
    skill_dir="$(dirname "$skill_md")"
    local skill_name
    skill_name="$(basename "$skill_dir")"
    ((total++)) || true

    local payload
    payload=$("${OSTWIN_PYTHON:-python3}" -c 'import json, sys; print(json.dumps({"path": sys.argv[1]}))' "$skill_dir" 2>/dev/null || true)
    if [[ -z "$payload" ]]; then
      payload=$(python3 -c 'import json, sys; print(json.dumps({"path": sys.argv[1]}))' "$skill_dir" 2>/dev/null || true)
    fi
    if [[ -z "$payload" ]]; then
      warn "Could not build install payload for $skill_name"
      ((failed++)) || true
      continue
    fi

    local install_result=""
    install_result=$(curl -sf -X POST \
      -H "Content-Type: application/json" \
      ${CURL_AUTH[@]+"${CURL_AUTH[@]}"} \
      --data "$payload" \
      "${DASHBOARD_URL}/api/skills/install" 2>&1) || true

    if [[ -n "$install_result" ]] && echo "$install_result" | grep -q '"status":"installed"' 2>/dev/null; then
      ((installed++)) || true
    else
      info "  X $skill_name"
      ((failed++)) || true
    fi
  done < <(find "${search_dirs[@]}" \
           -name "SKILL.md" -type f \
           -not -path "*/.git/*" \
           -not -path "*/node_modules/*" \
           -not -path "*/__pycache__/*" \
           2>/dev/null)

  if [[ "$total" -eq 0 ]]; then
    warn "No SKILL.md files found in $skills_base"
    return
  fi

  ok "$installed/$total skill(s) registered via API"
  if [[ "$failed" -gt 0 ]]; then
    warn "$failed skill(s) failed — dashboard may not be reachable"
  fi

  # Final vector sync is best-effort. The skills API can register skills from
  # disk even when the optional vector store is not initialized.
  step "Finalizing vector store sync..."
  local sync_result=""
  sync_result=$(curl -sf -X POST ${CURL_AUTH[@]+"${CURL_AUTH[@]}"} \
    "${DASHBOARD_URL}/api/skills/sync" 2>&1) || true

  if [[ -n "$sync_result" ]] && echo "$sync_result" | grep -q '"synced_count"' 2>/dev/null; then
    local synced_count added_count updated_count removed_count
    synced_count=$(echo "$sync_result" | grep -o '"synced_count":[0-9]*' | grep -o '[0-9]*' || echo "0")
    added_count=$(echo "$sync_result" | grep -o '"added":\[[^]]*\]' | tr ',' '\n' | grep -c '"' || echo "0")
    updated_count=$(echo "$sync_result" | grep -o '"updated":\[[^]]*\]' | tr ',' '\n' | grep -c '"' || echo "0")
    removed_count=$(echo "$sync_result" | grep -o '"removed":\[[^]]*\]' | tr ',' '\n' | grep -c '"' || echo "0")
    ok "Vector store synced: $synced_count changed ($added_count added, $updated_count updated, $removed_count removed)"
  else
    info "Vector store sync skipped — store may be unavailable"
  fi
}

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

echo ""
echo -e "  ${BOLD}Skills Sync${NC}"
echo ""

# If --install-from was specified, copy skills first
if [[ -n "$INSTALL_FROM" ]]; then
  # Resolve to absolute path
  if [[ ! "$INSTALL_FROM" = /* ]]; then
    INSTALL_FROM="$(cd "$INSTALL_FROM" 2>/dev/null && pwd)"
  fi

  if [[ ! -d "$INSTALL_FROM" ]]; then
    fail "Source directory not found: $INSTALL_FROM"
    exit 1
  fi

  install_from_dir "$INSTALL_FROM"
  echo ""
fi

# Always sync home skills with the dashboard
sync_home_skills
echo ""
