#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# install-deps.sh — Dependency installers
#
# Provides: install_brew, install_uv, install_python, install_pwsh,
#           install_node, install_opencode, install_agent_browser,
#           install_chrome_devtools, install_pester
#
# Requires: lib.sh, versions.conf, detect-os.sh (OS, ARCH, PKG_MGR),
#           check-deps.sh (check_uv, check_brew, check_opencode,
#           check_agent_browser, check_chrome_devtools)
# ──────────────────────────────────────────────────────────────────────────────

# Guard against double-sourcing
[[ -n "${_INSTALL_DEPS_SH_LOADED:-}" ]] && return 0
_INSTALL_DEPS_SH_LOADED=1

# ─── Homebrew ────────────────────────────────────────────────────────────────

install_brew() {
  step "Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  # Add to current session
  if [[ -f /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -f /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

# ─── uv ──────────────────────────────────────────────────────────────────────

install_uv() {
  step "Installing uv (fast Python package manager)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # Add to current session
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  if ! check_uv; then
    fail "uv installation failed"
    exit 1
  fi
  local uv_ver
  uv_ver=$(uv --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
  ok "uv $uv_ver installed"
}

# ─── Python ──────────────────────────────────────────────────────────────────

install_python() {
  local py_ver="${PYTHON_INSTALL_VERSION:-3.12}"
  case "$OS" in
    macos)
      if check_uv; then
        step "Installing Python $py_ver via uv..."
        uv python install "$py_ver"
      elif check_brew; then
        step "Installing Python $py_ver via Homebrew..."
        brew install "python@$py_ver"
      else
        fail "Cannot install Python: neither uv nor brew available"
        exit 1
      fi
      ;;
    linux)
      case "$PKG_MGR" in
        apt)
          step "Installing Python 3 via apt..."
          sudo apt-get update -qq
          sudo apt-get install -y -qq python3 python3-venv python3-pip
          ;;
        dnf|yum)
          step "Installing Python 3 via $PKG_MGR..."
          sudo "$PKG_MGR" install -y python3 python3-pip
          ;;
        pacman)
          step "Installing Python 3 via pacman..."
          sudo pacman -S --noconfirm python python-pip
          ;;
        zypper)
          step "Installing Python 3 via zypper..."
          sudo zypper install -y python3 python3-pip
          ;;
        *)
          # Try uv as last resort (no sudo needed)
          if check_uv; then
            step "Installing Python $py_ver via uv (no sudo)..."
            uv python install "$py_ver"
          else
            fail "Cannot install Python: no supported package manager found"
            echo "    Please install Python ${MIN_PYTHON_VERSION:-3.10}+ manually and re-run."
            exit 1
          fi
          ;;
      esac
      ;;
  esac
}

# ─── PowerShell ──────────────────────────────────────────────────────────────

install_pwsh() {
  local pwsh_ver="${PWSH_INSTALL_VERSION:-7.4.7}"
  case "$OS" in
    macos)
      # Try Homebrew first, fall back to direct tar.gz install
      if check_brew; then
        step "Installing PowerShell via Homebrew..."
        if brew install powershell/tap/powershell 2>/dev/null; then
          return
        fi
        warn "Homebrew formula failed — falling back to direct install"
      fi

      # Direct install from GitHub release (no sudo needed)
      local arch_tag
      arch_tag=$( [[ "$ARCH" == "arm64" ]] && echo "osx-arm64" || echo "osx-x64" )
      local url="https://github.com/PowerShell/PowerShell/releases/download/v${pwsh_ver}/powershell-${pwsh_ver}-${arch_tag}.tar.gz"

      step "Installing PowerShell ${pwsh_ver} from GitHub (${arch_tag})..."
      local pwsh_dir="$HOME/.local/powershell/7"
      mkdir -p "$pwsh_dir" "$HOME/.local/bin"
      curl -sSL "$url" -o /tmp/powershell.tar.gz
      tar -xzf /tmp/powershell.tar.gz -C "$pwsh_dir"
      chmod +x "$pwsh_dir/pwsh"
      ln -sf "$pwsh_dir/pwsh" "$HOME/.local/bin/pwsh"
      rm -f /tmp/powershell.tar.gz
      export PATH="$HOME/.local/bin:$PATH"
      ok "PowerShell ${pwsh_ver} installed to $pwsh_dir"
      ;;
    linux)
      case "$PKG_MGR" in
        apt)
          step "Installing PowerShell via Microsoft APT repository..."
          # Install prerequisites
          sudo apt-get update -qq
          sudo apt-get install -y -qq wget apt-transport-https software-properties-common
          # Get Ubuntu/Debian version
          local distro_version
          # shellcheck disable=SC1091
          distro_version=$(. /etc/os-release && echo "$VERSION_ID")
          local distro_id
          # shellcheck disable=SC1091
          distro_id=$(. /etc/os-release && echo "$ID")
          # Register Microsoft repo
          local repo_url="https://packages.microsoft.com/config/${distro_id}/${distro_version}/packages-microsoft-prod.deb"
          wget -q "$repo_url" -O /tmp/packages-microsoft-prod.deb 2>/dev/null || {
            # Fallback: try snap
            step "APT repo not available, trying snap..."
            sudo snap install powershell --classic
            return
          }
          sudo dpkg -i /tmp/packages-microsoft-prod.deb
          rm -f /tmp/packages-microsoft-prod.deb
          sudo apt-get update -qq
          sudo apt-get install -y -qq powershell
          ;;
        dnf|yum)
          step "Installing PowerShell via Microsoft RPM repository..."
          local distro_version
          # shellcheck disable=SC1091
          distro_version=$(. /etc/os-release && echo "$VERSION_ID" | cut -d. -f1)
          sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc
          local repo_url="https://packages.microsoft.com/config/rhel/${distro_version}/prod.repo"
          sudo curl -sSL -o /etc/yum.repos.d/microsoft.repo "$repo_url"
          sudo "$PKG_MGR" install -y powershell
          ;;
        pacman)
          step "Installing PowerShell via AUR..."
          echo "    PowerShell is available via AUR: yay -S powershell-bin"
          echo "    Or snap: sudo snap install powershell --classic"
          return 1
          ;;
        *)
          step "Attempting snap install for PowerShell..."
          if command -v snap &>/dev/null; then
            sudo snap install powershell --classic
          else
            fail "Cannot install PowerShell: no supported method found"
            echo "    See: https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-linux"
            return 1
          fi
          ;;
      esac
      ;;
  esac
}

# ─── Node.js ─────────────────────────────────────────────────────────────────

install_node() {
  local node_ver="${NODE_VER:-v25.8.1}"
  step "Installing Node.js $node_ver..."
  local node_dir="$HOME/.local/node"
  mkdir -p "$node_dir" "$HOME/.local/bin"

  local os_type arch_type
  case "$OS" in
    macos) os_type="darwin" ;;
    linux) os_type="linux" ;;
  esac

  case "$ARCH" in
    arm64|aarch64) arch_type="arm64" ;;
    x86_64|amd64) arch_type="x64" ;;
    *) fail "Unsupported architecture for Node direct download: $ARCH"; exit 1 ;;
  esac

  local url="https://nodejs.org/dist/${node_ver}/node-${node_ver}-${os_type}-${arch_type}.tar.gz"
  step "Downloading from $url..."
  curl -sSL "$url" -o /tmp/node.tar.gz || { fail "Failed to download Node.js $node_ver"; exit 1; }
  tar -xzf /tmp/node.tar.gz -C "$node_dir" --strip-components=1
  ln -sf "$node_dir/bin/node" "$HOME/.local/bin/node"
  ln -sf "$node_dir/bin/npm" "$HOME/.local/bin/npm"
  ln -sf "$node_dir/bin/npx" "$HOME/.local/bin/npx"
  rm -f /tmp/node.tar.gz
  export PATH="$HOME/.local/bin:$PATH"
  ok "Node.js $node_ver installed to $node_dir"
}

# ─── opencode ────────────────────────────────────────────────────────────────

install_opencode() {
  step "Installing opencode..."
  local brew_installed=false

  # Ensure paths are available before install
  ensure_brew_paths

  # Preferred: brew (macOS and Linux, always up to date)
  if command -v brew &>/dev/null; then
    if brew install anomalyco/tap/opencode 2>&1; then
      brew_installed=true
    elif brew upgrade anomalyco/tap/opencode 2>&1; then
      brew_installed=true
    else
      warn "brew install failed, falling back to official script"
    fi
  fi

  # Fallback: official install script
  if ! $brew_installed; then
    if curl -fsSL https://opencode.ai/install | bash; then
      # Official script installs to ~/.local/bin
      export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    else
      fail "opencode installation failed"
      return 1
    fi
  fi

  # Refresh command hash and paths
  ensure_brew_paths

  # Verify
  if check_opencode; then
    local oc_ver
    oc_ver=$(opencode --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "installed")
    ok "opencode $oc_ver installed"
  else
    # One more attempt with explicit paths
    local shell_name
    shell_name=$(basename "${SHELL:-/bin/bash}")
    local shell_rc="$HOME/.${shell_name}rc"
    warn "opencode installed but not immediately available in PATH"
    info "Will be available after: source $shell_rc (or open a new terminal)"
  fi
}

# ─── Chrome DevTools browser runtime ────────────────────────────────────────

install_chrome_devtools() {
  local existing
  existing=$(check_chrome_devtools 2>/dev/null || true)
  if [[ -n "$existing" ]]; then
    ok "chrome-devtools runtime already installed ($existing)"
    return 0
  fi

  local asset=""
  case "${OS}:${ARCH}" in
    linux:x86_64|linux:amd64)
      asset="obscura-x86_64-linux.tar.gz"
      ;;
    macos:arm64|macos:aarch64)
      asset="obscura-aarch64-macos.tar.gz"
      ;;
    macos:x86_64|macos:amd64)
      asset="obscura-x86_64-macos.tar.gz"
      ;;
    *)
      warn "No Chrome DevTools runtime asset configured for ${OS}/${ARCH}; chrome-devtools MCP will require manual runtime install"
      return 0
      ;;
  esac

  step "Installing Chrome DevTools browser runtime..."
  local bin_dir="$INSTALL_DIR/.agents/bin"
  local tmp_dir
  tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/ostwin-obscura.XXXXXX")
  local archive="$tmp_dir/$asset"
  local url="https://github.com/h4ckf0r0day/obscura/releases/latest/download/$asset"

  mkdir -p "$bin_dir"
  if ! curl -fsSL "$url" -o "$archive"; then
    warn "Chrome DevTools runtime download failed from $url"
    warn "chrome-devtools MCP will require manual runtime install"
    rm -rf "$tmp_dir"
    return 0
  fi

  if ! tar -xzf "$archive" -C "$tmp_dir"; then
    warn "Chrome DevTools runtime archive extraction failed"
    rm -rf "$tmp_dir"
    return 0
  fi

  local binary release_dir
  binary=$(find "$tmp_dir" -type f -name obscura 2>/dev/null | head -1)
  if [[ -z "$binary" ]]; then
    binary=$(find "$tmp_dir" -type f -name obscura.exe 2>/dev/null | head -1)
  fi
  if [[ -z "$binary" ]]; then
    warn "Chrome DevTools runtime binary not found in release archive"
    rm -rf "$tmp_dir"
    return 0
  fi

  release_dir="$(dirname "$binary")"
  find "$release_dir" -maxdepth 1 -type f \( -name 'obscura' -o -name 'obscura-worker' -o -name 'obscura.exe' -o -name 'obscura-worker.exe' \) \
    -exec cp {} "$bin_dir/" \;
  chmod +x "$bin_dir"/obscura* 2>/dev/null || true
  rm -rf "$tmp_dir"
  export PATH="$bin_dir:$PATH"
  ok "chrome-devtools runtime installed to $bin_dir"
}

# ─── agent-browser (Browser automation CLI) ─────────────────────────────────

_select_global_js_pm() {
  if command -v bun &>/dev/null; then
    echo "bun"
    return 0
  fi
  if command -v npm &>/dev/null; then
    echo "npm"
    return 0
  fi
  return 1
}

_add_js_global_bin_to_path() {
  local pm="$1"

  case "$pm" in
    bun)
      local bun_bin="${BUN_INSTALL:-$HOME/.bun}/bin"
      if [[ -d "$bun_bin" && ":$PATH:" != *":$bun_bin:"* ]]; then
        export PATH="$bun_bin:$PATH"
      fi
      ;;
    npm)
      local npm_prefix=""
      npm_prefix=$(npm config get prefix 2>/dev/null || true)
      if [[ -n "$npm_prefix" && "$npm_prefix" != "undefined" && "$npm_prefix" != "null" && -d "$npm_prefix/bin" && ":$PATH:" != *":$npm_prefix/bin:"* ]]; then
        export PATH="$npm_prefix/bin:$PATH"
      fi
      ;;
  esac
}

_install_global_js_package() {
  local pm="$1"
  local package_spec="$2"

  case "$pm" in
    bun)
      _add_js_global_bin_to_path bun
      bun add -g "$package_spec"
      ;;
    npm)
      npm install -g "$package_spec" 2>/dev/null || sudo npm install -g "$package_spec" 2>/dev/null
      _add_js_global_bin_to_path npm
      ;;
    *)
      return 1
      ;;
  esac
}

install_agent_browser() {
  if check_agent_browser; then
    local ab_ver
    ab_ver=$(agent-browser --version 2>&1 | head -1 || echo "installed")
    ok "agent-browser $ab_ver"
    return 0
  fi

  local js_pm=""
  js_pm="$(_select_global_js_pm || true)"
  if [[ -z "$js_pm" ]]; then
    warn "Skipping agent-browser — neither bun nor npm was found"
    return 0
  fi

  step "Installing agent-browser CLI with $js_pm..."
  if ! _install_global_js_package "$js_pm" "agent-browser@$AGENT_BROWSER_VERSION"; then
    if [[ "$js_pm" == "bun" && -n "$(command -v npm 2>/dev/null || true)" ]]; then
      warn "agent-browser bun install failed; retrying with npm"
      js_pm="npm"
      if ! _install_global_js_package "$js_pm" "agent-browser@$AGENT_BROWSER_VERSION"; then
        warn "agent-browser npm install failed; browser automation CLI will require manual install"
        return 0
      fi
    else
      warn "agent-browser $js_pm install failed; browser automation CLI will require manual install"
      return 0
    fi
  fi
  _add_js_global_bin_to_path "$js_pm"

  if check_agent_browser; then
    step "Running agent-browser post-install setup..."
    if ! agent-browser install 2>/dev/null; then
      warn "agent-browser install failed; CLI is installed but browser runtime may need manual setup"
    fi

    local ab_ver
    ab_ver=$(agent-browser --version 2>&1 | head -1 || echo "installed")
    ok "agent-browser $ab_ver installed"
  else
    warn "agent-browser installed but not immediately available in PATH"
  fi
}

# ─── Pester (PowerShell test framework) ──────────────────────────────────────

install_pester() {
  if ! command -v pwsh &>/dev/null; then
    warn "Skipping Pester — PowerShell not available"
    return
  fi
  step "Installing Pester (PowerShell test framework)..."
  # shellcheck disable=SC2016  # single quotes intentional: PowerShell syntax, not bash
  pwsh -NoProfile -Command '
    $installed = Get-Module -ListAvailable Pester | Where-Object { $_.Version.Major -ge 5 }
    if ($installed) {
      Write-Host "    [OK] Pester $($installed.Version) already installed"
    } else {
      Install-Module -Name Pester -Force -Scope CurrentUser -SkipPublisherCheck
      $ver = (Get-Module -ListAvailable Pester | Select-Object -First 1).Version
      Write-Host "    [OK] Pester $ver installed"
    }
  ' 2>/dev/null || warn "Pester installation failed (non-critical)"
}

# ─── Ollama (local LLM host CLI) ─────────────────────────────────────────────

install_ollama() {
  step "Installing Ollama (local LLM host)..."
  case "$OS" in
    macos)
      if check_brew; then
        brew install ollama
      else
        curl -fsSL https://ollama.com/install.sh | sh
      fi
      ;;
    linux)
      curl -fsSL https://ollama.com/install.sh | sh
      ;;
    *)
      fail "Cannot install Ollama on $(uname -s)"
      return 1
      ;;
  esac
  if check_ollama; then
    ok "Ollama installed"
  else
    warn "Ollama install script ran but 'ollama' not found in PATH"
    info "You may need to start a new terminal or install manually from https://ollama.com"
  fi
}
