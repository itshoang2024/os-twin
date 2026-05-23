#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# setup-path.sh — PATH configuration, shell RC detection
#
# Provides: setup_path
#
# Requires: lib.sh, globals: INSTALL_DIR
# ──────────────────────────────────────────────────────────────────────────────

# Guard against double-sourcing
[[ -n "${_SETUP_PATH_SH_LOADED:-}" ]] && return 0
_SETUP_PATH_SH_LOADED=1

setup_path() {
  step "Configuring PATH..."

  local shell_name
  shell_name=$(basename "${SHELL:-/bin/bash}")

  local brew_prefix=""
  if command -v brew &>/dev/null; then
    brew_prefix=$(brew --prefix 2>/dev/null || echo "/opt/homebrew")
  fi

  # Configure ALL common shells, not just current one
  # This ensures env vars are available regardless of which shell user opens
  local all_rcs=()
  [[ -f "$HOME/.zshrc" ]] && all_rcs+=("$HOME/.zshrc")
  [[ -f "$HOME/.bashrc" ]] && all_rcs+=("$HOME/.bashrc")
  [[ -f "$HOME/.profile" ]] && all_rcs+=("$HOME/.profile")
  [[ -f "$HOME/.config/fish/config.fish" ]] && all_rcs+=("$HOME/.config/fish/config.fish")

  # If no RC files exist, create the one for current shell
  if [[ ${#all_rcs[@]} -eq 0 ]]; then
    case "$shell_name" in
      zsh)  all_rcs+=("$HOME/.zshrc") ;;
      bash) all_rcs+=("$HOME/.bashrc") ;;
      fish) mkdir -p "$HOME/.config/fish"; all_rcs+=("$HOME/.config/fish/config.fish") ;;
      *)    all_rcs+=("$HOME/.profile") ;;
    esac
    touch "${all_rcs[0]}"
  fi

  for shell_rc in "${all_rcs[@]}"; do
    local rc_name=$(basename "$shell_rc")
    local is_fish=false
    [[ "$rc_name" == "config.fish" ]] && is_fish=true

    local path_line
    if $is_fish; then
      path_line="set -gx PATH $INSTALL_DIR/.agents/bin $HOME/.local/bin \$PATH"
    else
      path_line="export PATH=\"$INSTALL_DIR/.agents/bin:$HOME/.local/bin:\$PATH\""
    fi

    # Add PATH if not present (match the actual bin path, not just "ostwin" string)
    if grep -qF "$INSTALL_DIR/.agents/bin" "$shell_rc" 2>/dev/null; then
      ok "PATH already in $rc_name"
    else
      {
        echo ""
        echo "# Ostwin CLI (Agent OS)"
        echo "$path_line"
      } >> "$shell_rc"
      ok "Added PATH to $rc_name"
    fi

    # Add .env sourcing
    local env_source_line
    if $is_fish; then
      env_source_line="test -f $INSTALL_DIR/.env && set -gx (grep -v '^#' $INSTALL_DIR/.env | grep -v '^$' | string split -m1 '=') >/dev/null"
    else
      env_source_line="[[ -f $INSTALL_DIR/.env ]] && source $INSTALL_DIR/.env"
    fi

    if grep -qF "$INSTALL_DIR/.env" "$shell_rc" 2>/dev/null; then
      ok ".env sourcing already in $rc_name"
    else
      {
        echo ""
        echo "# Ostwin environment (API keys, config)"
        echo "$env_source_line"
      } >> "$shell_rc"
      ok "Added .env sourcing to $rc_name"
    fi

    # Add brew paths if available
    if [[ -n "$brew_prefix" ]]; then
      local brew_line
      if $is_fish; then
        brew_line="set -gx PATH ${brew_prefix}/bin ${brew_prefix}/sbin \$PATH"
      else
        brew_line="export PATH=\"${brew_prefix}/bin:${brew_prefix}/sbin:\$PATH\""
      fi
      if ! grep -qF "${brew_prefix}/bin" "$shell_rc" 2>/dev/null; then
        {
          echo ""
          echo "# Homebrew (added by Ostwin)"
          echo "$brew_line"
        } >> "$shell_rc"
        ok "Added brew paths to $rc_name"
      fi
    fi
  done

  # Export for current session
  export PATH="$INSTALL_DIR/.agents/bin:$HOME/.local/bin:$PATH"

  # Add brew paths if available (for opencode and other brew packages)
  if [[ -n "$brew_prefix" ]]; then
    export PATH="${brew_prefix}/bin:${brew_prefix}/sbin:$PATH"
  fi

  # Source .env for current session (immediate availability without restart)
  if [[ -f "$INSTALL_DIR/.env" ]]; then
    local path_before_env="$PATH"
    # shellcheck disable=SC1090
    source "$INSTALL_DIR/.env"
    export PATH="$path_before_env"
    ok "Sourced .env for current session"
  fi

  # Refresh command hash (shell caches command locations)
  hash -r 2>/dev/null || rehash 2>/dev/null || true

  local primary_rc
  case "$shell_name" in
    zsh)  primary_rc="$HOME/.zshrc" ;;
    bash) primary_rc="$HOME/.bashrc" ;;
    fish) primary_rc="$HOME/.config/fish/config.fish" ;;
    *)    primary_rc="$HOME/.profile" ;;
  esac
  info "Run 'source $primary_rc' or open a new terminal to apply changes"
}
