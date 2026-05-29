#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# start-channels.sh — Channel connector install + launch (Telegram, Discord, Slack)
#
# Provides: install_channels, start_channels
#
# Requires: lib.sh, check-deps.sh (check_node),
#           globals: INSTALL_DIR, SOURCE_DIR, SCRIPT_DIR
# ──────────────────────────────────────────────────────────────────────────────

# Guard against double-sourcing
[[ -n "${_START_CHANNELS_SH_LOADED:-}" ]] && return 0
_START_CHANNELS_SH_LOADED=1

# ─── install_channels ────────────────────────────────────────────────────────
# Installs channel connector Node.js dependencies.

_ensure_channel_pnpm_build_approvals() {
  local chan_dir="$1"
  local workspace="$chan_dir/pnpm-workspace.yaml"

  if [[ ! -f "$workspace" ]]; then
    cat > "$workspace" <<'YAML'
allowBuilds:
  '@discordjs/opus': true
  esbuild: true
YAML
    return
  fi

  if ! grep -qE '^[[:space:]]*allowBuilds:' "$workspace"; then
    cat >> "$workspace" <<'YAML'

allowBuilds:
  '@discordjs/opus': true
  esbuild: true
YAML
    return
  fi

  _set_pnpm_allow_build "$workspace" "^[[:space:]]*'?@discordjs/opus'?[[:space:]]*:" "  '@discordjs/opus': true"
  _set_pnpm_allow_build "$workspace" "^[[:space:]]*esbuild[[:space:]]*:" "  esbuild: true"
}

_set_pnpm_allow_build() {
  local workspace="$1"
  local key_regex="$2"
  local line="$3"
  local tmp="${workspace}.tmp.$$"

  if grep -qE "$key_regex" "$workspace"; then
    awk -v key_regex="$key_regex" -v line="$line" '
      $0 ~ key_regex { print line; next }
      { print }
    ' "$workspace" > "$tmp" && mv "$tmp" "$workspace"
  else
    awk -v line="$line" '
      { print }
      !inserted && $0 ~ /^[[:space:]]*allowBuilds:/ {
        print line
        inserted = 1
      }
    ' "$workspace" > "$tmp" && mv "$tmp" "$workspace"
  fi
}

install_channels() {
  # Install in ~/.ostwin/bot/ (primary) and source repo (for development)
  local bot_dirs=()
  
  # Primary: installed bot directory
  if [[ -f "$INSTALL_DIR/bot/package.json" ]]; then
    bot_dirs+=("$INSTALL_DIR/bot")
  fi
  
  # Secondary: source repo for development
  for candidate in \
    "${SOURCE_DIR}/bot" \
    "${SCRIPT_DIR}/../bot"; do
    if [[ -d "$candidate" ]] && [[ -f "$candidate/package.json" ]]; then
      local src_bot
      src_bot="$(cd "$candidate" && pwd)"
      # Skip if same as installed location
      [[ "$src_bot" == "$INSTALL_DIR/bot" ]] || bot_dirs+=("$src_bot")
      break
    fi
  done

  if [[ ${#bot_dirs[@]} -eq 0 ]]; then
    warn "channel connector dir (bot/) not found — skipping"
    info "Expected at bot/package.json relative to the repo root or $INSTALL_DIR/bot/"
    return
  elif ! check_node; then
    warn "Node.js not found — cannot install channel connectors"
    info "Install Node.js and re-run"
    return
  elif ! command -v pnpm &>/dev/null; then
    warn "pnpm not found — cannot install channel connectors"
    info "Install pnpm and re-run"
    return
  fi

  for CHAN_DIR in "${bot_dirs[@]}"; do
    local start_time
    start_time=$(get_now)
    step "Installing channel dependencies in $CHAN_DIR with pnpm..."
    _ensure_channel_pnpm_build_approvals "$CHAN_DIR"
    # shellcheck disable=SC2015
    (cd "$CHAN_DIR" && pnpm install) \
      && ok_time "Channel dependencies installed" "$(print_duration "$start_time")" \
      || warn "Channel dependency install failed"

    # tsx should come from bot/package.json devDependencies after install.
    if [[ ! -f "$CHAN_DIR/node_modules/.bin/tsx" ]]; then
      warn "tsx not found after pnpm install"
    else
      ok "tsx available in $CHAN_DIR"
    fi
  done

  ok "Channel connector ready"
  info "Start with: ostwin channel connect <platform>"
}

# ─── start_channels ─────────────────────────────────────────────────────────
# Starts channel connectors in the background.

start_channels() {
  if [[ -z "${CHAN_DIR:-}" ]]; then
    return
  fi

  local env_file="$INSTALL_DIR/.env"
  local project_root_env
  project_root_env="$(cd "$CHAN_DIR/.." && pwd)/.env"
  # shellcheck disable=SC1090
  [[ -f "$env_file" ]] && { set -a; source "$env_file"; set +a; }
  # shellcheck disable=SC1090
  [[ -f "$project_root_env" ]] && { set -a; source "$project_root_env"; set +a; }

  local chan_pid_file="$INSTALL_DIR/.agents/channel.pid"
  if [[ -f "$chan_pid_file" ]]; then
    local old_pid
    old_pid=$(cat "$chan_pid_file" 2>/dev/null || true)
    if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
      step "Stopping previous channel process (PID $old_pid)..."
      kill "$old_pid" 2>/dev/null || true; sleep 1
    fi
  fi

  if [[ -n "${DISCORD_TOKEN:-}" ]] && [[ -n "${DISCORD_CLIENT_ID:-}" ]]; then
    step "Registering Discord slash commands..."
    # shellcheck disable=SC2015
    (cd "$CHAN_DIR" && npx tsx src/deploy-commands.ts 2>/dev/null) \
      && ok "Discord commands registered" || warn "Discord command registration failed (non-critical)"
  fi

  mkdir -p "$INSTALL_DIR/logs"
  step "Starting channels from $CHAN_DIR..."
  (
    cd "$CHAN_DIR" || exit
    # shellcheck disable=SC1090
    [[ -f "$project_root_env" ]] && { set -a; source "$project_root_env"; set +a; }
    nohup npm start > "$INSTALL_DIR/logs/channel.log" 2>&1 &
    echo $! > "$chan_pid_file"
    echo "$!"
  ) | { read -r chan_pid; ok "Channels started (PID $chan_pid) — log: $INSTALL_DIR/logs/channel.log"; }

  # shellcheck disable=SC2015
  [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] && ok "Telegram: enabled" || info "Telegram: disabled (set TELEGRAM_BOT_TOKEN)"
  # shellcheck disable=SC2015
  [[ -n "${DISCORD_TOKEN:-}" ]] && ok "Discord: enabled" || info "Discord: disabled (set DISCORD_TOKEN)"
  # shellcheck disable=SC2015
  [[ -n "${SLACK_BOT_TOKEN:-}" ]] && ok "Slack: enabled" || info "Slack: disabled (set SLACK_BOT_TOKEN)"
}
