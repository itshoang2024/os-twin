#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# install-files.sh — File installation, rsync, MCP seeding, symlinks, migrations
#
# Provides: install_files, compute_build_hash
#
# Requires: lib.sh, versions.conf, detect-os.sh (OS),
#           check-deps.sh, globals: INSTALL_DIR, SCRIPT_DIR, SOURCE_DIR,
#           VENV_DIR, PYTHON_CMD
# ──────────────────────────────────────────────────────────────────────────────

# Guard against double-sourcing
[[ -n "${_INSTALL_FILES_SH_LOADED:-}" ]] && return 0
_INSTALL_FILES_SH_LOADED=1

# Installer scripts dir for Python helpers
_INSTALLER_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/scripts" 2>/dev/null && pwd || echo "")"

install_files() {
  step "Installing OS Twin to $INSTALL_DIR..."
  mkdir -p "$INSTALL_DIR/.agents"

  # Sync SCRIPT_DIR contents (agents, scripts, config) — skip runtime state
  # NOTE: MCP config files are excluded to preserve user's installed extensions and config
  # User plans live in $INSTALL_DIR/.agents/plans/ — do NOT overwrite them
  # with whatever happens to be in the source repo's plans/ directory.
  # PLAN.template.md is seeded separately below if missing.
  # NEVER sync: docs/, node_modules/
  # Skip if already exists (don't override): config.json.
  # Role definitions are source-controlled and must always be refreshed by a
  # local build; _sync_builtin_roles below force-syncs roles/* into ostwin home.
  local _rsync_excludes=(
    --exclude='.venv/' --exclude='*.pid' --exclude='dashboard.pid'
    --exclude='logs/' --exclude='__pycache__/' --exclude='*.pyc'
    --exclude='mcp/config.json' --exclude='mcp/.env.mcp'
    --exclude='plans/'
    --exclude='docs/'
    --exclude='node_modules/'
  )
  local _find_excludes=(-not -name 'mcp' -not -name 'plans' -not -name 'docs' -not -name 'node_modules' -not -name '.')

  if [[ -f "$INSTALL_DIR/.agents/config.json" ]]; then
    _rsync_excludes+=(--exclude='/config.json')
    _find_excludes+=(-not -name 'config.json')
  fi
  rsync -a "${_rsync_excludes[@]}" \
    "$SCRIPT_DIR/" "$INSTALL_DIR/.agents/" 2>/dev/null || {
      # rsync fallback to cp (exclude mcp/ and plans/ manually)
      find "$SCRIPT_DIR" -maxdepth 1 "${_find_excludes[@]}" \
        -exec cp -r {} "$INSTALL_DIR/.agents/" \; 2>/dev/null || true
    }

  # Seed plans/ on first install (or if PLAN.template.md is missing) — never overwrite
  mkdir -p "$INSTALL_DIR/.agents/plans"
  if [[ ! -f "$INSTALL_DIR/.agents/plans/PLAN.template.md" ]] \
     && [[ -f "$SCRIPT_DIR/plans/PLAN.template.md" ]]; then
    cp "$SCRIPT_DIR/plans/PLAN.template.md" "$INSTALL_DIR/.agents/plans/PLAN.template.md"
  fi

  # ── MCP: seed config on first install, never overwrite ─────────────────────
  _seed_mcp_config

  # ── Symlink ~/.ostwin/mcp -> ~/.ostwin/.agents/mcp ────────────────────────
  _setup_mcp_symlink

  # ── MCP: migrate legacy mcp-config.json → config.json ─────────────────────
  _migrate_mcp_config

  # ── Dashboard: always override from source repo ───────────────────────────
  _sync_dashboard

  # ── Bot: sync channel connector bot ───────────────────────────────────────
  _sync_bot

  # ── Built-in roles: always override from this checkout ────────────────────
  _sync_builtin_roles

  # ── Contributed roles ─────────────────────────────────────────────────────
  _load_contributed_roles

  # Make scripts executable
  find "$INSTALL_DIR/.agents" -name "*.sh" -exec chmod +x {} \;
  chmod +x "$INSTALL_DIR/.agents/bin/ostwin" 2>/dev/null || true

  ok "Files installed"
}

# ─── Internal helpers ────────────────────────────────────────────────────────

_seed_mcp_config() {
  # Source of truth file was renamed mcp-config.json → config.json during the
  # OpenCode migration (April 2026). Honor either name in the source repo.
  # Both config.json and mcp-config.json are gitignored (they contain resolved
  # env vars on the dev machine), so on a fresh clone only mcp-builtin.json
  # (which IS tracked by git) is available as a seed.
  local seed_src=""
  if [[ -f "$SCRIPT_DIR/mcp/mcp-builtin.json" ]]; then
    seed_src="$SCRIPT_DIR/mcp/mcp-builtin.json"
  elif [[ -f "$SCRIPT_DIR/mcp/config.json" ]]; then
    seed_src="$SCRIPT_DIR/mcp/config.json"
  elif [[ -f "$SCRIPT_DIR/mcp/mcp-config.json" ]]; then
    seed_src="$SCRIPT_DIR/mcp/mcp-config.json"
  fi
  if [[ ! -f "$INSTALL_DIR/.agents/mcp/config.json" ]]; then
    if [[ -n "$seed_src" ]]; then
      step "Seeding mcp/config.json (first install)..."
      mkdir -p "$INSTALL_DIR/.agents/mcp"
      cp "$seed_src" "$INSTALL_DIR/.agents/mcp/config.json"
      ok "mcp/config.json seeded from mcp-builtin.json"
    else
      warn "No mcp-builtin.json found in $SCRIPT_DIR/mcp/ — skipping seed"
    fi
  else
    # Re-install - preserve existing config, merge new built-in servers
    # Always update the builtin template so new built-in servers are available
    if [[ -f "$seed_src" ]]; then
      cp "$seed_src" "$INSTALL_DIR/.agents/mcp/mcp-builtin.json"
    fi
    # Always update catalog so new packages are available
    if [[ -f "$SCRIPT_DIR/mcp/mcp-catalog.json" ]]; then
      cp "$SCRIPT_DIR/mcp/mcp-catalog.json" "$INSTALL_DIR/.agents/mcp/mcp-catalog.json"
    fi
    # Merge new built-in servers into config.json (never overwrite existing)
    local mcp_cfg="$INSTALL_DIR/.agents/mcp/config.json"
    local mcp_builtin="$INSTALL_DIR/.agents/mcp/mcp-builtin.json"
    if [[ -f "$mcp_cfg" ]] && [[ -f "$mcp_builtin" ]]; then
      # Prefer the managed venv python (exists on re-installs); fall back to system python
      local _merge_py="$VENV_DIR/bin/python"
      [[ -x "$_merge_py" ]] || _merge_py="${PYTHON_CMD:-python3}"
      "$_merge_py" "${_INSTALLER_SCRIPTS_DIR}/merge_mcp_builtin.py" \
        "$mcp_cfg" "$mcp_builtin" \
        && ok "Merged new built-in MCP servers" || true
    fi
    # Sync MCP server scripts (channel-server.py, warroom-server.py, etc.)
    for f in "$SCRIPT_DIR"/mcp/*.py "$SCRIPT_DIR"/mcp/*.sh "$SCRIPT_DIR"/mcp/requirements.txt; do
      [[ -f "$f" ]] && cp "$f" "$INSTALL_DIR/.agents/mcp/"
    done
    rm -f \
      "$INSTALL_DIR/.agents/mcp/obscura-browser-server.py" \
      "$INSTALL_DIR/.agents/mcp/test_obscura_browser.py"
    ok "mcp/ preserved (scripts + catalog updated, new servers merged)"
  fi
}

_setup_mcp_symlink() {
  local mcp_link="$INSTALL_DIR/mcp"
  local mcp_real="$INSTALL_DIR/.agents/mcp"
  if [[ -L "$mcp_link" ]]; then
    # Already a symlink — update if target changed
    if [[ "$(readlink "$mcp_link")" != "$mcp_real" ]]; then
      ln -sfn "$mcp_real" "$mcp_link"
    fi
  elif [[ -d "$mcp_link" ]]; then
    # Legacy real directory — migrate: merge any user files, then replace with symlink
    step "Migrating $mcp_link to symlink..."
    for f in "$mcp_link"/*; do
      [[ -f "$f" ]] && [[ ! -f "$mcp_real/$(basename "$f")" ]] && cp "$f" "$mcp_real/"
    done
    rm -rf "$mcp_link"
    ln -s "$mcp_real" "$mcp_link"
    ok "Migrated $mcp_link -> .agents/mcp (symlink)"
  else
    ln -s "$mcp_real" "$mcp_link"
  fi
}

_migrate_mcp_config() {
  local installed_mcp_dir="$INSTALL_DIR/.agents/mcp"
  if [[ -f "$installed_mcp_dir/mcp-config.json" && ! -f "$installed_mcp_dir/config.json" ]]; then
    step "Migrating mcp-config.json → config.json..."
    mv "$installed_mcp_dir/mcp-config.json" "$installed_mcp_dir/config.json"
    ok "Renamed mcp-config.json → config.json"
  elif [[ -f "$installed_mcp_dir/mcp-config.json" && -f "$installed_mcp_dir/config.json" ]]; then
    # Both exist — remove legacy, config.json takes precedence
    rm -f "$installed_mcp_dir/mcp-config.json"
    ok "Removed legacy mcp-config.json (config.json exists)"
  fi
}

_sync_dashboard() {
  local dash_src=""
  local repo_root=""
  for candidate in \
    "${SOURCE_DIR}/dashboard" \
    "${SCRIPT_DIR}/../dashboard" \
    "${SCRIPT_DIR}/dashboard"; do
    if [[ -n "$candidate" ]] && [[ -f "$candidate/api.py" ]]; then
      dash_src="$(cd "$candidate" && pwd)"
      repo_root="$(cd "$dash_src/.." && pwd)"
      break
    fi
  done

  if [[ -n "$dash_src" ]]; then
    step "Syncing dashboard from $dash_src (override)..."
    mkdir -p "$INSTALL_DIR/dashboard"
    # Use incremental rsync with --delete instead of rm -rf + full copy.
    # Exclude node_modules (588MB) and frontend source files — only the
    # pre-built output in fe/out/ is needed at runtime.
    # Preserve any legacy dashboard-local virtualenv on the receiver. Current
    # installs use $INSTALL_DIR/.venv, but deleting dashboard/.venv during rsync
    # can create noisy rsync receiver-delete warnings when files
    # are in use.
    rsync -a --delete \
      --filter='P .venv/***' \
      --filter='P venv/***' \
      --exclude='.venv/' \
      --exclude='venv/' \
      --exclude='node_modules/' \
      --exclude='fe/src/' \
      --exclude='fe/.next/' \
      --exclude='fe/.turbo/' \
      --exclude='__pycache__/' --exclude='*.pyc' --exclude='.DS_Store' \
      "$dash_src/" "$INSTALL_DIR/dashboard/"
    ok "Dashboard → $INSTALL_DIR/dashboard/"

    # Sync provider_urls.json (dashboard/llm_client.py reads it from $INSTALL_DIR/)
    if [[ -n "$repo_root" ]] && [[ -f "$repo_root/provider_urls.json" ]]; then
      cp "$repo_root/provider_urls.json" "$INSTALL_DIR/provider_urls.json"
      ok "provider_urls.json → $INSTALL_DIR/provider_urls.json"
    fi
  else
    warn "Dashboard source not found — dashboard/ not updated"
    info "Pass the repo root: ./install.sh --source-dir /path/to/agent-os"
  fi
}

_sync_bot() {
  local bot_src=""
  for candidate in \
    "${SOURCE_DIR}/bot" \
    "${SCRIPT_DIR}/../bot" \
    "${SCRIPT_DIR}/bot"; do
    if [[ -n "$candidate" ]] && [[ -f "$candidate/package.json" ]]; then
      bot_src="$(cd "$candidate" && pwd)"
      break
    fi
  done

  if [[ -n "$bot_src" ]]; then
    step "Syncing bot from $bot_src..."
    mkdir -p "$INSTALL_DIR/bot"
    # Exclude node_modules and build artifacts
    rsync -a --delete \
      --exclude='node_modules/' \
      --exclude='dist/' \
      --exclude='coverage/' \
      --exclude='.pytest_cache/' \
      --exclude='logs/' \
      --exclude='__pycache__/' --exclude='*.pyc' --exclude='.DS_Store' \
      "$bot_src/" "$INSTALL_DIR/bot/"
    ok "Bot → $INSTALL_DIR/bot/"
  else
    info "Bot source not found — bot/ not synced (optional)"
  fi
}

_sync_builtin_roles() {
  local roles_src="$SCRIPT_DIR/roles"
  local roles_dst="$INSTALL_DIR/.agents/roles"

  if [[ ! -d "$roles_src" ]]; then
    warn "Built-in roles source not found — roles/ not synced"
    return 0
  fi

  step "Syncing built-in roles to $roles_dst (override)..."
  mkdir -p "$roles_dst"
  rsync -a --delete \
    --exclude='__pycache__/' --exclude='*.pyc' --exclude='.DS_Store' \
    "$roles_src/" "$roles_dst/" 2>/dev/null || {
      rm -rf "$roles_dst"
      mkdir -p "$roles_dst"
      cp -R "$roles_src"/. "$roles_dst/"
    }
  ok "Built-in roles → $roles_dst/"
}

_load_contributed_roles() {
  local contributes_roles=""
  for candidate in \
    "${SOURCE_DIR}/contributes/roles" \
    "${SCRIPT_DIR}/../contributes/roles"; do
    if [[ -d "$candidate" ]]; then
      contributes_roles="$(cd "$candidate" && pwd)"
      break
    fi
  done
  if [[ -n "$contributes_roles" ]]; then
    step "Syncing contributed roles..."
    mkdir -p "$INSTALL_DIR/.agents/roles"
    local synced=0
    for role_dir in "$contributes_roles"/*/; do
      [[ -d "$role_dir" ]] || continue
      local role_name
      role_name="$(basename "$role_dir")"
      local target_role="$INSTALL_DIR/.agents/roles/$role_name"
      mkdir -p "$target_role"
      rsync -a --delete \
        --exclude='__pycache__/' --exclude='*.pyc' --exclude='.DS_Store' \
        "$role_dir" "$target_role/" 2>/dev/null || {
          rm -rf "$target_role"
          mkdir -p "$target_role"
          cp -R "$role_dir". "$target_role/"
        }
      synced=$((synced + 1))
    done
    ok "$synced contributed role(s) synced"
  fi
}

# ─── Build hash ──────────────────────────────────────────────────────────────

compute_build_hash() {
  step "Computing build hash..."

  # Prefer shasum (macOS), fall back to sha256sum (Linux)
  local sha_cmd="shasum -a 256"
  if ! command -v shasum &>/dev/null; then
    sha_cmd="sha256sum"
  fi

  local hash
  # shellcheck disable=SC2086  # sha_cmd intentionally word-splits ("shasum -a 256")
  hash=$(
    find "$INSTALL_DIR" \
      -type f \
      ! -path "$INSTALL_DIR/.venv/*" \
      ! -path "*/.venv/*" \
      ! -path "$INSTALL_DIR/.zvec/*" \
      ! -path "$INSTALL_DIR/.memory/*" \
      ! -path "$INSTALL_DIR/.war-rooms/*" \
      ! -path "$INSTALL_DIR/projects/*" \
      ! -path "$INSTALL_DIR/logs/*" \
      ! -path "$INSTALL_DIR/node_modules/*" \
      ! -path "*/node_modules/*" \
      ! -path "*/__pycache__/*" \
      ! -name "*.pid" \
      ! -name ".env" \
      ! -name ".build-hash" \
      -print0 \
      | sort -z \
      | xargs -0 $sha_cmd \
      | $sha_cmd \
      | cut -c1-8
  )
  echo "$hash" > "$INSTALL_DIR/.build-hash"
  ok "Build hash: $hash"
}
