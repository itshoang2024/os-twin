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

_channel_ci_mode() {
  [[ "${CI:-}" == "1" || "${CI:-}" == "true" || "${CI:-}" == "TRUE" ]]
}

_select_channel_pm() {
  local project_dir="$1"

  if [[ ( -f "$project_dir/bun.lockb" || -f "$project_dir/bun.lock" ) ]] && command -v bun &>/dev/null; then
    echo "bun"
    return 0
  fi
  if [[ ( -f "$project_dir/package-lock.json" || -f "$project_dir/npm-shrinkwrap.json" ) ]] && command -v npm &>/dev/null; then
    echo "npm"
    return 0
  fi
  if command -v npm &>/dev/null; then
    echo "npm"
    return 0
  fi
  if command -v bun &>/dev/null; then
    echo "bun"
    return 0
  fi
  return 1
}

_install_channel_deps() {
  local pm="$1"
  local output=""

  case "$pm" in
    bun)
      if [[ -f bun.lockb || -f bun.lock ]]; then
        if output="$(bun install --frozen-lockfile 2>&1)"; then
          [[ -n "$output" ]] && printf '%s\n' "$output"
          return 0
        fi
        if ! _channel_ci_mode; then
          warn "bun lockfile is out of date; retrying without --frozen-lockfile"
          [[ -n "$output" ]] && printf '%s\n' "$output" >&2
          bun install
          return $?
        fi
        [[ -n "$output" ]] && printf '%s\n' "$output" >&2
        return 1
      fi
      bun install
      ;;
    npm)
      if [[ -f package-lock.json || -f npm-shrinkwrap.json ]]; then
        if output="$(npm ci 2>&1)"; then
          [[ -n "$output" ]] && printf '%s\n' "$output"
          return 0
        fi
        if ! _channel_ci_mode; then
          warn "npm lockfile install failed; retrying with npm install"
          [[ -n "$output" ]] && printf '%s\n' "$output" >&2
          npm install
          return $?
        fi
        [[ -n "$output" ]] && printf '%s\n' "$output" >&2
        return 1
      fi
      npm install --no-package-lock
      ;;
    *)
      return 1
      ;;
  esac
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
  fi

  for CHAN_DIR in "${bot_dirs[@]}"; do
    local channel_pm=""
    channel_pm="$(_select_channel_pm "$CHAN_DIR" || true)"
    if [[ -z "$channel_pm" ]]; then
      warn "No JavaScript package manager (bun/npm) found — cannot install channel connectors in $CHAN_DIR"
      info "Install bun or npm and re-run"
      continue
    fi

    local start_time
    start_time=$(get_now)
    step "Installing channel dependencies in $CHAN_DIR with $channel_pm..."
    # shellcheck disable=SC2015
    (cd "$CHAN_DIR" && _install_channel_deps "$channel_pm") \
      && ok_time "Channel dependencies installed" "$(print_duration "$start_time")" \
      || warn "Channel dependency install failed"

    # tsx should come from bot/package.json devDependencies after install.
    if [[ ! -f "$CHAN_DIR/node_modules/.bin/tsx" ]]; then
      warn "tsx not found after $channel_pm install"
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
