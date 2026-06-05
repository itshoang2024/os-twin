#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# mcp-extension.sh — MCP Extension Manager for Ostwin
#
# Install, list, remove, and sync MCP server extensions.
# Extensions can be installed by name (from mcp-catalog.json) or by git URL.
#
# MCP config is per-project only: $PROJECT/.agents/mcp/config.json
# Catalog + builtins come from global ~/.ostwin/mcp/
#
# Usage:
#   mcp-extension.sh install <name|git-url> [--name NAME] [--branch BRANCH]
#   mcp-extension.sh list
#   mcp-extension.sh catalog
#   mcp-extension.sh remove <name>
#   mcp-extension.sh sync
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ─── Resolve paths ───────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Find INSTALL_DIR: prefer ~/.ostwin if it exists, otherwise use SCRIPT_DIR parent
if [[ -d "$HOME/.ostwin/mcp" ]]; then
  INSTALL_DIR="$HOME/.ostwin"
else
  INSTALL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

# Catalog + builtins always come from global install
CATALOG_FILE="$HOME/.ostwin/.agents/mcp/mcp-catalog.json"
BUILTIN_FILE="$HOME/.ostwin/.agents/mcp/mcp-builtin.json"
# Dev mode fallbacks
[[ ! -f "$CATALOG_FILE" ]] && [[ -f "$SCRIPT_DIR/mcp-catalog.json" ]] && CATALOG_FILE="$SCRIPT_DIR/mcp-catalog.json"
[[ ! -f "$BUILTIN_FILE" ]] && [[ -f "$SCRIPT_DIR/mcp-builtin.json" ]] && BUILTIN_FILE="$SCRIPT_DIR/mcp-builtin.json"

# Project-local paths — set after --project-dir is parsed (see MAIN)
MCP_DIR=""
EXTENSIONS_DIR=""
EXTENSIONS_FILE=""
CONFIG_FILE="$HOME/.ostwin/.agents/mcp/config.json"
PROJECT_DIR=""

# Python: use activated venv (ostwin sources activate), fallback to system
PYTHON="$(command -v python 2>/dev/null || echo python3)"

# Trigger vault hook (non-fatal — vault is lazy-loaded per subcommand)
"$PYTHON" -c "
import sys
sys.path.append('$SCRIPT_DIR')
try:
    from vault import get_vault
    get_vault()
except Exception:
    pass
" 2>/dev/null || true

# ─── Colors ──────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
info() { echo -e "  ${DIM}$1${NC}"; }
step() { echo -e "  ${CYAN}→${NC} $1"; }

# ─── Helpers ─────────────────────────────────────────────────────────────────

# Resolve project dir → set all project-local paths
apply_project_dir() {
  PROJECT_DIR="$(cd "$PROJECT_DIR" 2>/dev/null && pwd || echo "$PROJECT_DIR")"
  MCP_DIR="$PROJECT_DIR/.agents/mcp"
  EXTENSIONS_DIR="$MCP_DIR/extensions"
  EXTENSIONS_FILE="$HOME/.ostwin/mcp/extensions.json"
  # CONFIG_FILE is global: $HOME/.ostwin/.agents/mcp/config.json
}

ensure_dirs() {
  mkdir -p "$EXTENSIONS_DIR"
  mkdir -p "$(dirname "$EXTENSIONS_FILE")"
  if [[ ! -f "$EXTENSIONS_FILE" ]]; then
    echo '{"extensions":[]}' > "$EXTENSIONS_FILE"
  fi
}

ensure_global_config_file() {
  mkdir -p "$(dirname "$CONFIG_FILE")"
  if [[ -f "$CONFIG_FILE" ]]; then
    return
  fi
  if [[ -f "$BUILTIN_FILE" ]]; then
    cp "$BUILTIN_FILE" "$CONFIG_FILE"
  else
    echo '{"mcp":{}}' > "$CONFIG_FILE"
  fi
}

catalog_field() {
  local pkg="$1" field="$2"
  "$PYTHON" -c "
import json, sys
with open('$CATALOG_FILE') as f:
    catalog = json.load(f)
pkg = catalog.get('packages', {}).get('$pkg')
if not pkg:
    sys.exit(1)
val = pkg.get('$field', '')
if isinstance(val, dict):
    print(json.dumps(val))
elif isinstance(val, list):
    print(json.dumps(val))
else:
    print(val)
" 2>/dev/null
}

is_in_catalog() {
  local name="$1"
  "$PYTHON" -c "
import json, sys
with open('$CATALOG_FILE') as f:
    catalog = json.load(f)
if '$name' in catalog.get('packages', {}):
    sys.exit(0)
sys.exit(1)
" 2>/dev/null
}

is_installed() {
  local name="$1"
  [[ -f "$EXTENSIONS_FILE" ]] || return 1
  "$PYTHON" -c "
import json, sys
with open('$EXTENSIONS_FILE') as f:
    data = json.load(f)
for ext in data.get('extensions', []):
    if ext.get('name') == '$name':
        sys.exit(0)
sys.exit(1)
" 2>/dev/null
}

# ─── INSTALL ─────────────────────────────────────────────────────────────────

cmd_install() {
  local target=""
  local opt_name="" opt_branch="" opt_env="" opt_headers=""
  local build_type="auto"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --name)        opt_name="$2"; shift 2 ;;
      --branch)      opt_branch="$2"; shift 2 ;;
      --env)         opt_env="$2"; shift 2 ;;
      --http)        build_type="http"; target="$2"; shift 2 ;;
      --header)      opt_headers="${opt_headers:-} $2"; shift 2 ;;
      --project-dir) shift 2 ;;  # already handled globally
      -*)            warn "Unknown option: $1"; shift ;;
      *)             target="$1"; shift ;;
    esac
  done

  if [[ -z "$target" ]]; then
    fail "Usage: ostwin mcp install <name|git-url> [--name NAME] [--branch BRANCH] [--http URL]"
    exit 1
  fi

  ensure_dirs

  local name="" repo="" branch="" config_json=""

  if [[ "${build_type:-}" == "http" ]]; then
    repo="$target"
    name="${opt_name:-$(echo "$repo" | awk -F/ '{print $3}' | tr '.' '-')}"
    branch="main"
    config_json="{\"type\": \"remote\", \"url\": \"$repo\", \"headers\": {}}"
    # Parse headers: --header "X-Key=Val"
    if [[ -n "${opt_headers:-}" ]]; then
      for h in $opt_headers; do
        k="${h%%=*}"
        v="${h#*=}"
        config_json=$(echo "$config_json" | "$PYTHON" -c "import json, sys; c=json.load(sys.stdin); c['headers']['$k']='$v'; print(json.dumps(c))")
      done
    fi
    info "Installing HTTP MCP server: $repo"
  elif [[ "$target" == http* ]] || [[ "$target" == git@* ]] || [[ "$target" == *.git ]]; then
    repo="$target"
    name="${opt_name:-$(basename "$repo" .git)}"
    branch="${opt_branch:-main}"
    build_type="auto"
    config_json=""
    info "Installing from git URL: $repo"
  else
    name="$target"
    build_type="auto"
    if ! is_in_catalog "$name"; then
      fail "Package '$name' not found in catalog."
      echo ""
      info "Available packages:"
      cmd_catalog
      echo ""
      info "Or install from a git URL:"
      info "  ostwin mcp install https://github.com/org/repo.git --name my-mcp"
      exit 1
    fi
    repo=$(catalog_field "$name" "repo")
    branch="${opt_branch:-$(catalog_field "$name" "branch")}"
    build_type=$(catalog_field "$name" "build_type")
    config_json=$(catalog_field "$name" "config")
    info "Installing from catalog: $name"
  fi

  if [[ "$build_type" == "http" ]]; then
    ext_path=""
  else
    if is_installed "$name"; then
      warn "'$name' is already installed."
      info "To reinstall: ostwin mcp remove $name && ostwin mcp install $name"
      exit 0
    fi
    ext_path="$EXTENSIONS_DIR/$name"
  fi

  # ── Clone (skip for npx/http extensions) ──
  if [[ "$build_type" != "npx" ]] && [[ "$build_type" != "http" ]]; then
    step "Cloning $repo (branch: $branch)..."
    if ! git clone --depth 1 --branch "$branch" "$repo" "$ext_path" 2>/dev/null; then
      if ! git clone --depth 1 "$repo" "$ext_path" 2>/dev/null; then
        fail "Failed to clone $repo"
        exit 1
      fi
    fi
    ok "Cloned to $ext_path"
  fi

  # ── Auto-detect build type ──
  if [[ "$build_type" == "auto" ]]; then
    if [[ -f "$ext_path/package.json" ]]; then
      build_type="node"
    elif [[ -f "$ext_path/requirements.txt" ]] || [[ -f "$ext_path/setup.py" ]] || [[ -f "$ext_path/pyproject.toml" ]]; then
      build_type="python"
    else
      build_type="none"
    fi
    info "Auto-detected build type: $build_type"
  fi

  # ── Build ──
  case "$build_type" in
    npx)
      [[ -d "$ext_path" ]] && rm -rf "$ext_path"
      info "npx-based extension — no build required (fetched on demand)"
      ;;
    node)
      if ! command -v node &>/dev/null; then
        fail "Node.js is required but not installed."
        rm -rf "$ext_path"
        exit 1
      fi
      local js_pm=""
      if [[ ( -f "$ext_path/bun.lockb" || -f "$ext_path/bun.lock" ) ]] && command -v bun &>/dev/null; then
        js_pm="bun"
      elif command -v npm &>/dev/null; then
        js_pm="npm"
      elif command -v bun &>/dev/null; then
        js_pm="bun"
      else
        fail "bun or npm is required but neither is installed."
        rm -rf "$ext_path"
        exit 1
      fi

      step "Building ($js_pm install && $js_pm run build)..."
      if (
        cd "$ext_path"
        case "$js_pm" in
          bun)
            if [[ -f bun.lockb || -f bun.lock ]]; then
              bun install --frozen-lockfile 2>/dev/null || bun install
            else
              bun install
            fi
            ;;
          npm)
            if [[ -f package-lock.json || -f npm-shrinkwrap.json ]]; then
              npm ci 2>/dev/null || npm install
            else
              npm install
            fi
            ;;
        esac
        grep -q '"build"' package.json 2>/dev/null && { "$js_pm" run build 2>/dev/null || "$js_pm" run build; }
      ); then
        ok "Build complete"
      else
        fail "Build failed"
        rm -rf "$ext_path"
        exit 1
      fi
      ;;
    python)
      step "Installing Python dependencies..."
      [[ -f "$ext_path/requirements.txt" ]] && {
        "$PYTHON" -m pip install --quiet -r "$ext_path/requirements.txt" 2>/dev/null || \
        "$PYTHON" -m pip install --user -r "$ext_path/requirements.txt"
      }
      ok "Python deps installed"
      ;;
    none|http) info "No build step required" ;;
    *)    warn "Unknown build type: $build_type — skipping build" ;;
  esac

  # ── Resolve config from repo JSON if not from catalog ──
  if [[ -z "$config_json" ]] && [[ "$build_type" != "http" ]]; then
    step "Scanning for MCP server declaration in repo..."
    config_json=$("$PYTHON" -c "
import json, os, glob, sys
ext_path = '$ext_path'
name = '$name'
candidates = []
for f in ['google-vertex/gemini-extension.json', 'config.json', 'mcp-config.json']:
    p = os.path.join(ext_path, f)
    if os.path.isfile(p): candidates.append(p)
for p in sorted(glob.glob(os.path.join(ext_path, '*.json'))):
    if p not in candidates: candidates.append(p)
for p in sorted(glob.glob(os.path.join(ext_path, '*', '*.json'))):
    if p not in candidates: candidates.append(p)
for filepath in candidates:
    try:
        with open(filepath) as f:
            data = json.load(f)
        # Support both OpenCode format ('mcp') and legacy ('mcpServers')
        servers = data.get('mcp', data.get('mcpServers', {}))
        if servers:
            cfg = servers.get(name, list(servers.values())[0])
            print(json.dumps(cfg))
            sys.exit(0)
    except: continue
print('{}')
" 2>/dev/null)

    if [[ "$config_json" != "{}" ]] && [[ -n "$config_json" ]]; then
      ok "Found MCP server declaration"
    else
      warn "No MCP server declaration found"
      config_json='{}'
    fi
  fi

  # Resolve placeholders → absolute paths
  local abs_ext_path="" abs_project_dir
  if [[ -n "$ext_path" ]]; then
    abs_ext_path="$(cd "$ext_path" 2>/dev/null && pwd || echo "$ext_path")"
  fi
  abs_project_dir="$(cd "$PROJECT_DIR" 2>/dev/null && pwd || echo "$PROJECT_DIR")"
  config_json=$(echo "$config_json" | sed "s|{env:extensionPath}|$abs_ext_path|g; s|{env:AGENT_DIR}|$INSTALL_DIR|g; s|{env:PROJECT_DIR}|$abs_project_dir|g; s|\${extensionPath}|$abs_ext_path|g; s|\${AGENT_DIR}|$INSTALL_DIR|g; s|\${PROJECT_DIR}|$abs_project_dir|g")

  # ── Merge --env file if provided ──
  if [[ -n "$opt_env" ]] && [[ -f "$opt_env" ]]; then
    step "Merging environment variables from $opt_env..."
    config_json=$(echo "$config_json" | "$PYTHON" -c "
import json, sys
config = json.load(sys.stdin) if True else {}
env_dict = config.get('environment', {})
with open('$opt_env') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        k, v = line.split('=', 1)
        env_dict[k.strip()] = v.strip().strip('\"').strip(\"'\")
if env_dict: config['environment'] = env_dict
print(json.dumps(config))
" 2>/dev/null || echo "$config_json")
    ok "Environment variables merged"
  fi

  # ── Register in extensions.json ──
  local now
  now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Detect potential secrets
detected_secrets=$(CONFIG_JSON="$config_json" "$PYTHON" - <<PYEOF
import json, sys, re, os
config = json.loads(os.environ.get('CONFIG_JSON', '{}'))
server_name = '$name'

def is_secret(val):
    if not isinstance(val, str): return False
    if re.match(r'^[A-Za-z0-9_-]{20,}$', val): return True
    if any(p in val for p in ['AIza', 'sk-', 'shpat_', 'ghp_']): return True
    return False

secrets = []
def scan_dict(d):
    for k, v in d.items():
        if isinstance(v, dict): scan_dict(v)
        elif is_secret(v): secrets.append((k, v))

if 'environment' in config: scan_dict(config['environment'])
if 'headers' in config: scan_dict(config['headers'])

for k, v in secrets:
    print(f'{k}={v}')
PYEOF
)

if [[ -n "$detected_secrets" ]]; then
  echo ""
  warn "Detected potential secrets in configuration."
  for line in $detected_secrets; do
    key="${line%%=*}"
    val="${line#*=}"
    echo -n "  Store '$key' in secure vault? [Y/n] "
    read -r response
    if [[ "$response" =~ ^[Yy] ]] || [[ -z "$response" ]]; then
      # Store in vault and update config_json
      "$PYTHON" - <<PYEOF
import sys, json
try:
    from vault import get_vault
except ImportError:
    sys.path.append('$SCRIPT_DIR')
    from vault import get_vault
get_vault().set('$name', '$key', '$val')
PYEOF

      config_json=$(CONFIG_JSON="$config_json" "$PYTHON" - <<PYEOF
import json, sys, os
config = json.loads(os.environ.get('CONFIG_JSON', '{}'))
server_name = '$name'
key = '$key'

def replace_in_dict(d):
    if key in d: d[key] = f'\${{vault:{server_name}/{key}}}'
    for v in d.values():
        if isinstance(v, dict): replace_in_dict(v)

if 'environment' in config: replace_in_dict(config['environment'])
if 'headers' in config: replace_in_dict(config['headers'])
print(json.dumps(config))
PYEOF
)
      ok "Stored '$key' in vault and updated config."
    fi
  done
  echo ""
fi

  "$PYTHON" - <<PYEOF
import json
with open('$EXTENSIONS_FILE') as f:
    data = json.load(f)
data['extensions'].append({
    'name': '$name', 'repo': '$repo', 'branch': '$branch',
    'build_type': '$build_type', 'installed_at': '$now',
    'path': '$abs_ext_path', 'config': $config_json
})
with open('$EXTENSIONS_FILE', 'w') as f:
    json.dump(data, f, indent=2)
PYEOF
  ok "Registered in extensions.json"

  cmd_sync_quiet
  ok "config.json updated"

  echo ""
  echo -e "  ${GREEN}${BOLD}✅ '$name' installed successfully!${NC}"
  echo ""
  info "Extension path: $abs_ext_path"
  info "Run 'ostwin mcp list' to see all installed extensions."
}

# ─── LIST ────────────────────────────────────────────────────────────────────

cmd_list() {
  "$PYTHON" - <<PYEOF
import json, os, sys, re

# Show builtin servers
builtin_file = '$BUILTIN_FILE'
try:
    from vault import get_vault
except ImportError:
    sys.path.append('$SCRIPT_DIR')
    from vault import get_vault
vault = get_vault()

def check_vault_status(config, server_name):
    # Regex to match \${vault:server/key}
    pattern = re.compile(r"\\\$\{vault:([^/]+)/([^}]+)\}")
    status = []
    
    def scan(obj):
        if isinstance(obj, dict):
            for v in obj.values(): scan(v)
        elif isinstance(obj, list):
            for v in obj: scan(v)
        elif isinstance(obj, str):
            for match in pattern.finditer(obj):
                s, k = match.groups()
                val = vault.get(s, k)
                status.append((k, val is not None))

    scan(config)
    return status

if os.path.isfile(builtin_file):
    with open(builtin_file) as f:
        d = json.load(f)
        builtins = d.get('mcp', d.get('mcpServers', {}))
    if builtins:
        print(f'  Builtin servers ({len(builtins)}):')
        print()
        for name, cfg in builtins.items():
            cmd = cfg.get('command', ['?'])
            if isinstance(cmd, list): cmd = ' '.join(cmd)
            vault_info = check_vault_status(cfg, name)
            cred_status = ""
            if vault_info:
                parts = []
                for key, exists in vault_info:
                    icon = "\033[32m✓\033[0m" if exists else "\033[31m✗\033[0m"
                    parts.append(f"{key} {icon}")
                cred_status = "  " + "  ".join(parts)
            print(f'    \033[1m{name}\033[0m  \033[2m(builtin)\033[0m{cred_status}')
            print(f'      command: {cmd}')
            print()

# Show installed extensions
ext_file = '$EXTENSIONS_FILE'
if not os.path.isfile(ext_file):
    print('  No extensions installed.')
    sys.exit(0)

with open(ext_file) as f:
    exts = json.load(f).get('extensions', [])

if not exts:
    print('  No extensions installed.')
    print('  Run: ostwin mcp install <name>')
else:
    print(f'  Installed extensions ({len(exts)}):')
    print()
    for ext in exts:
        name = ext.get("name","?")
        config = ext.get("config",{})
        vault_info = check_vault_status(config, name)
        cred_status = ""
        if vault_info:
            parts = []
            for key, exists in vault_info:
                icon = "\033[32m✓\033[0m" if exists else "\033[31m✗\033[0m"
                parts.append(f"{key} {icon}")
            cred_status = "  " + "  ".join(parts)
        print(f'    \033[1m{name}\033[0m{cred_status}')
        print(f'      repo:       {ext.get("repo","?")}')
        print(f'      build_type: {ext.get("build_type","?")}')
        print(f'      installed:  {ext.get("installed_at","?")}')
        cmd = config.get('command', ['?'])
        if isinstance(cmd, list): cmd = ' '.join(cmd)
        print(f'      command:    {cmd}')
        print()
PYEOF
}

# ─── CATALOG ─────────────────────────────────────────────────────────────────

cmd_catalog() {
  if [[ ! -f "$CATALOG_FILE" ]]; then
    fail "Catalog file not found: $CATALOG_FILE"
    exit 1
  fi
  "$PYTHON" -c "
import json, os
with open('$CATALOG_FILE') as f:
    catalog = json.load(f)
installed_names = set()
if os.path.isfile('$EXTENSIONS_FILE'):
    with open('$EXTENSIONS_FILE') as f:
        installed_names = {e['name'] for e in json.load(f).get('extensions', [])}
pkgs = catalog.get('packages', {})
print(f'  MCP Extension Catalog v{catalog.get(\"catalog_version\", \"?\")}')
print(f'  {len(pkgs)} package(s) available:')
print()
for name, spec in pkgs.items():
    status = '\033[32m[installed]\033[0m' if name in installed_names else ''
    print(f'    \033[1m{name}\033[0m  {status}')
    print(f'      {spec.get(\"description\",\"\")}')
    print(f'      build: {spec.get(\"build_type\",\"?\")}  |  repo: {spec.get(\"repo\",\"?\")}')
    print()
print('  Install with: ostwin mcp install <name>')
"
}

# ─── REMOVE ──────────────────────────────────────────────────────────────────

cmd_remove() {
  local name="${1:-}"
  [[ -z "$name" ]] && { fail "Usage: ostwin mcp remove <name>"; exit 1; }
  is_installed "$name" || { fail "'$name' is not installed."; exit 1; }

  local ext_path
  ext_path=$("$PYTHON" -c "
import json
with open('$EXTENSIONS_FILE') as f:
    data = json.load(f)
for ext in data.get('extensions', []):
    if ext.get('name') == '$name': print(ext.get('path', '')); break
")

  "$PYTHON" -c "
import json
with open('$EXTENSIONS_FILE') as f:
    data = json.load(f)
data['extensions'] = [e for e in data['extensions'] if e.get('name') != '$name']
with open('$EXTENSIONS_FILE', 'w') as f:
    json.dump(data, f, indent=2)
"
  ok "Removed from extensions.json"

  [[ -n "$ext_path" ]] && [[ -d "$ext_path" ]] && { rm -rf "$ext_path"; ok "Deleted $ext_path"; }

  cmd_sync_quiet
  ok "config.json updated"
  echo ""
  echo -e "  ${GREEN}✅ '$name' removed.${NC}"
}

# ─── SYNC ────────────────────────────────────────────────────────────────────

cmd_sync_quiet() {
  mkdir -p "$(dirname "$CONFIG_FILE")"

  # validate_mcp.py lives in the global install, not project-local
  local mcp_module_dir="$HOME/.ostwin/.agents/mcp"
  [[ -f "$mcp_module_dir/validate_mcp.py" ]] || mcp_module_dir="$SCRIPT_DIR"

  "$PYTHON" -c "
import json, sys, os

sys.path.insert(0, '$mcp_module_dir')
from validate_mcp import normalize_mcp_config, merge_mcp_configs

# Load builtin config (may be legacy mcpServers format)
builtin_raw = {}
try:
    with open('$BUILTIN_FILE') as f:
        builtin_raw = json.load(f)
except FileNotFoundError: pass

# Load extensions
extensions = {}
try:
    with open('$EXTENSIONS_FILE') as f:
        data = json.load(f)
    for ext in data.get('extensions', []):
        name = ext.get('name')
        config = ext.get('config', {})
        if name and config: extensions[name] = config
except FileNotFoundError: pass

# Normalize builtin (handles mcpServers, shell vars, etc.)
normalized_builtin = normalize_mcp_config(builtin_raw)

# Merge: builtin → extensions (extensions override builtin)
merged_servers = {**normalized_builtin, **extensions}

with open('$CONFIG_FILE', 'w') as f:
    json.dump({'mcp': merged_servers}, f, indent=2)
    f.write('\n')
"
  # Resolve {env:AGENT_DIR} and {env:PROJECT_DIR} → absolute paths
  local abs_project_dir
  abs_project_dir="$(cd "$PROJECT_DIR" 2>/dev/null && pwd || echo "$PROJECT_DIR")"
  local env_mcp_file
  env_mcp_file="$(dirname "$CONFIG_FILE")/.env.mcp"

  export AGENT_DIR="$INSTALL_DIR"
  export PROJECT_DIR="$abs_project_dir"

  "$PYTHON" - <<PYEOF
import json, os, re, shlex

config_file = '$CONFIG_FILE'
env_mcp_file = '$env_mcp_file'
project_dir = '$abs_project_dir'

# Resolve {env:AGENT_DIR} and {env:PROJECT_DIR} in config.json
with open(config_file) as f:
    raw = f.read()
raw = raw.replace('{env:AGENT_DIR}', '$INSTALL_DIR')
raw = raw.replace('{env:PROJECT_DIR}', '$abs_project_dir')
with open(config_file, 'w') as f:
    f.write(raw)

# Load .env.mcp for vault-derived secrets
env_extra = {}
if os.path.exists(env_mcp_file):
    with open(env_mcp_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, _, v = line.partition('=')
            env_extra[k.strip()] = v.strip()
env_all = {**os.environ, **env_extra}

def resolve_env_refs(text):
    return re.sub(r'\{env:(\w+)\}', lambda m: env_all.get(m.group(1), m.group(0)), text)

def split_command_text(command):
    stripped = command.strip()
    if not stripped:
        return []
    try:
        return shlex.split(stripped)
    except ValueError:
        return stripped.split()

def normalize_local_command(command):
    if isinstance(command, str):
        return split_command_text(command)
    if isinstance(command, list) and len(command) == 1 and isinstance(command[0], str):
        return split_command_text(command[0])
    return command

# Write .opencode/opencode.json
# - command arrays: resolve ALL {env:*} to literal paths
# - environment/headers: RESOLVE {env:*} to literal values from current env (drop only if unresolved)
with open(config_file) as f:
    config = json.load(f)

import shutil
python_abs = shutil.which('python') or shutil.which('python3') or 'python'

env_ref_pattern = re.compile(r'\{env:\w+\}')
resolved_mcp = {}
for name, cfg in config.get('mcp', {}).items():
    out = {}
    is_local = cfg.get('type') == 'local' or ('command' in cfg and cfg.get('type') != 'remote')
    for key, val in cfg.items():
        if key == 'command' and is_local:
            val = normalize_local_command(val)
            resolved_cmd = []
            if isinstance(val, list):
                for i, c in enumerate(val):
                    if isinstance(c, str):
                        c = resolve_env_refs(c)
                        if i == 0 and c in ('python', 'python3'):
                            c = python_abs
                    resolved_cmd.append(c)
                out[key] = resolved_cmd
            else:
                out[key] = val
        elif key in ('environment', 'headers') and isinstance(val, dict):
            resolved_env = {}
            for k, v in val.items():
                if isinstance(v, str):
                    rv = resolve_env_refs(v)
                    # Only drop if still unresolved (env var not in current env)
                    if env_ref_pattern.search(rv):
                        continue
                    resolved_env[k] = rv
                else:
                    resolved_env[k] = v
            if resolved_env:
                out[key] = resolved_env
        elif key == 'url' and isinstance(val, str):
            out[key] = resolve_env_refs(val)
        else:
            out[key] = val
    resolved_mcp[name] = out

opencode_dir = os.path.join(project_dir, '.opencode')
os.makedirs(opencode_dir, exist_ok=True)
opencode_file = os.path.join(opencode_dir, 'opencode.json')

# Build permission ruleset that allows access to the parent directory of the project.
parent_dir = os.path.dirname(project_dir.rstrip('/'))

# Inject opencode agent definitions for every ostwin role.
# OpenCode looks up agents by name when --agent is passed; if missing it
# falls back to the default 'build' agent. Generating agent definitions here
# avoids the "agent X not found" warning and lets each role have its own model.
agents = {}
ostwin_config_path = os.path.join(os.path.expanduser('~'), '.ostwin', '.agents', 'config.json')
if os.path.exists(ostwin_config_path):
    try:
        with open(ostwin_config_path) as f:
            ostwin_cfg = json.load(f)
        for role_name, role_cfg in ostwin_cfg.items():
            if not isinstance(role_cfg, dict) or 'default_model' not in role_cfg:
                continue
            agents[role_name] = {
                'mode': 'primary',
                'model': role_cfg['default_model'],
                'description': role_cfg.get('description', f'{role_name} agent'),
            }
            for inst_name, inst_cfg in role_cfg.get('instances', {}).items():
                full_name = f'{role_name}-{inst_name}'
                agents[full_name] = {
                    'mode': 'primary',
                    'model': inst_cfg.get('default_model', role_cfg['default_model']),
                    'description': inst_cfg.get('display_name', f'{role_name} {inst_name}'),
                }
    except (json.JSONDecodeError, OSError):
        pass

# Also pull in roles from ~/.ostwin/.agents/roles/<name>/role.json (covers
# dynamically-created roles like database-architect that aren't in config.json)
roles_dir = os.path.join(os.path.expanduser('~'), '.ostwin', '.agents', 'roles')
if os.path.isdir(roles_dir):
    for role_name in os.listdir(roles_dir):
        if role_name.startswith('_') or role_name in agents:
            continue
        role_json = os.path.join(roles_dir, role_name, 'role.json')
        if not os.path.exists(role_json):
            continue
        try:
            with open(role_json) as f:
                rj = json.load(f)
            model = rj.get('model') or rj.get('default_model')
            if not model:
                continue
            agents[role_name] = {
                'mode': 'primary',
                'model': model,
                'description': rj.get('description', f'{role_name} agent'),
            }
        except (json.JSONDecodeError, OSError):
            pass

opencode_config = {
    "\$schema": "https://opencode.ai/config.json",
    "mcp": resolved_mcp,
    "permission": {
        "external_directory": {
            f"{parent_dir}/*": "allow",
            f"{parent_dir}/**": "allow",
            f"{os.path.expanduser('~')}/.ostwin/*": "allow",
            f"{os.path.expanduser('~')}/.ostwin/**": "allow",
        },
    },
}
if agents:
    opencode_config["agent"] = agents

with open(opencode_file, 'w') as f:
    json.dump(opencode_config, f, indent=2)
    f.write('\n')
PYEOF
}

cmd_sync() {
  step "Syncing config.json (builtin + extensions)..."
  cmd_sync_quiet
  ok "config.json rebuilt"
  "$PYTHON" -c "
import json
with open('$CONFIG_FILE') as f:
    servers = json.load(f).get('mcp', {})
print(f'  {len(servers)} server(s) in config.json:')
for name in servers:
    cmd = servers[name].get('command', ['?'])
    if isinstance(cmd, list): cmd = ' '.join(cmd)
    print(f'    • {name} ({cmd})')
"
}

# ─── INIT PROJECT ────────────────────────────────────────────────────────────

cmd_init_project() {
  local project_dir="${1:-}"
  [[ -z "$project_dir" ]] && { fail "Usage: mcp-extension.sh init-project <project-dir>"; exit 1; }

  local project_mcp="$project_dir/.agents/mcp"
  mkdir -p "$project_mcp"

  [[ ! -f "$project_mcp/extensions.json" ]] && echo '{"extensions":[]}' > "$project_mcp/extensions.json"
  [[ -f "$CATALOG_FILE" ]] && cp "$CATALOG_FILE" "$project_mcp/mcp-catalog.json"
  [[ -f "$BUILTIN_FILE" ]] && cp "$BUILTIN_FILE" "$project_mcp/mcp-builtin.json"

  # Copy extension manager script (skip if same file)
  local self_script dest_script
  self_script="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
  dest_script="$project_mcp/mcp-extension.sh"
  [[ "$(realpath "$self_script" 2>/dev/null)" != "$(realpath "$dest_script" 2>/dev/null)" ]] && cp "$self_script" "$dest_script"
  chmod +x "$dest_script"

  local project_config="$project_mcp/config.json"
  if [[ ! -f "$project_config" ]]; then
    [[ -f "$BUILTIN_FILE" ]] && cp "$BUILTIN_FILE" "$project_config" || echo '{"mcp":{}}' > "$project_config"
  fi

  ok "Project MCP scaffolded at $project_mcp"
}

# ─── CREDENTIALS ─────────────────────────────────────────────────────────────

cmd_credentials() {
  local sub="${1:-}"
  shift || true

  case "$sub" in
    set)
      local server="${1:-}"
      local key="${2:-}"
      [[ -z "$server" ]] || [[ -z "$key" ]] && { fail "Usage: ostwin mcp credentials set <server> <key>"; exit 1; }
      echo -n "Enter value for $server/$key: "
      read -rs value
      echo ""
      "$PYTHON" -c "
import sys, os
try:
    from vault import get_vault
except ImportError:
    sys.path.append('$SCRIPT_DIR')
    from vault import get_vault
get_vault().set('$server', '$key', '$value')
"
      ok "Stored $server/$key in vault."
      ;;
    list)
      local server="${1:-}"
      "$PYTHON" -c "
import sys, os, json
try:
    from vault import get_vault
except ImportError:
    sys.path.append('$SCRIPT_DIR')
    from vault import get_vault
vault = get_vault()
server = '$server'

# If server is provided, list keys for that server
# If not, try to list all servers from config or extensions
servers = []
if server:
    servers = [server]
else:
    if os.path.exists('$EXTENSIONS_FILE'):
        with open('$EXTENSIONS_FILE') as f:
            servers = [e['name'] for e in json.load(f).get('extensions', [])]
    if os.path.exists('$BUILTIN_FILE'):
        with open('$BUILTIN_FILE') as f:
            bd = json.load(f)
            servers.extend(bd.get('mcp', bd.get('mcpServers', {})).keys())
    servers = sorted(list(set(servers)))

for s in servers:
    keys = vault.list_keys(s)
    if keys or server:
        print(f'  {s}:')
        for k in keys:
            print(f'    • {k}  \033[32m✓ set\033[0m')
        if not keys:
            print(f'    (no credentials set)')
"
      ;;
    delete)
      local server="${1:-}"
      local key="${2:-}"
      [[ -z "$server" ]] || [[ -z "$key" ]] && { fail "Usage: ostwin mcp credentials delete <server> <key>"; exit 1; }
      "$PYTHON" -c "
import sys, os
try:
    from vault import get_vault
except ImportError:
    sys.path.append('$SCRIPT_DIR')
    from vault import get_vault
get_vault().delete('$server', '$key')
"
      ok "Deleted $server/$key from vault."
      ;;
    *)
      fail "Usage: ostwin mcp credentials <set|list|delete> [args]"
      exit 1
      ;;
  esac
}

# ─── MIGRATE ─────────────────────────────────────────────────────────────────

cmd_migrate() {
  ensure_global_config_file
  step "Scanning for plaintext secrets in $CONFIG_FILE..."
  "$PYTHON" -c "
import json, sys, os, re
try:
    from vault import get_vault
except ImportError:
    sys.path.append('$SCRIPT_DIR')
    from vault import get_vault

config_file = '$CONFIG_FILE'
if not os.path.exists(config_file):
    print(f'  Config file not found: {config_file}')
    sys.exit(0)

with open(config_file) as f:
    config = json.load(f)

vault = get_vault()
changed = False

def is_secret(val):
    if not isinstance(val, str): return False
    if '\${vault:' in val: return False
    # Heuristic: looks like a token or API key
    if re.match(r'^[A-Za-z0-9_-]{20,}$', val): return True
    if any(p in val for p in ['AIza', 'sk-', 'shpat_', 'ghp_']): return True
    return False

def process_dict(d, server_name):
    global changed
    for k, v in d.items():
        if isinstance(v, dict):
            process_dict(v, server_name)
        elif is_secret(v):
            print(f'  Found secret in {server_name}/{k} -> moving to vault')
            vault.set(server_name, k, v)
            d[k] = f'\${{vault:{server_name}/{k}}}'
            changed = True

for server_name, server_cfg in config.get('mcp', {}).items():
    if 'environment' in server_cfg: process_dict(server_cfg['environment'], server_name)
    if 'headers' in server_cfg: process_dict(server_cfg['headers'], server_name)

if changed:
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)
    print('  Migration complete. Config updated with vault references.')
else:
    print('  No plaintext secrets found.')
"
}

# ─── TEST ────────────────────────────────────────────────────────────────────

cmd_test() {
  local server_name="${1:-}"
  if [[ "$server_name" == "--all" ]]; then
    server_name=""
  fi

  ensure_global_config_file

  export _SCRIPT_DIR="$SCRIPT_DIR"
  export _CONFIG_FILE="$CONFIG_FILE"
  export _BUILTIN_FILE="$BUILTIN_FILE"
  export _INSTALL_DIR="$INSTALL_DIR"
  export _PROJECT_DIR="$PROJECT_DIR"
  export _SERVER_NAME="$server_name"

  step "Testing MCP connectivity..."
  "$PYTHON" - <<'PYEOF'
import json, sys, os
script_dir = os.environ.get("_SCRIPT_DIR")
config_file = os.environ.get("_CONFIG_FILE")
builtin_file = os.environ.get("_BUILTIN_FILE")
agent_dir = os.environ.get("_INSTALL_DIR")
project_dir = os.environ.get("_PROJECT_DIR")
target_server = os.environ.get("_SERVER_NAME")

sys.path.append(script_dir)
try:
    from vault import get_vault
    from config_resolver import ConfigResolver
    from mcp_test import test_http_server, test_stdio_server
except ImportError as e:
    print(f"  ✗ Import error: {e}")
    sys.exit(1)

if not os.path.exists(config_file):
    print(f'  ✗ Config file not found: {config_file}')
    sys.exit(1)

with open(config_file) as f:
    config = json.load(f)

# Also load builtins to test everything
if os.path.exists(builtin_file):
    with open(builtin_file) as f:
        builtins_raw = f.read()
        builtins_raw = builtins_raw.replace('{env:AGENT_DIR}', agent_dir)
        builtins_raw = builtins_raw.replace('{env:PROJECT_DIR}', project_dir)
        bd = json.loads(builtins_raw)
        builtins = bd.get('mcp', bd.get('mcpServers', {}))
        config.setdefault('mcp', {}).update(builtins)

resolver = ConfigResolver()
servers = config.get('mcp', {})

if target_server and target_server not in servers:
    print(f'  ✗ Server not found in config: {target_server}')
    sys.exit(1)

test_list = [target_server] if target_server else sorted(servers.keys())

results = []
for name in test_list:
    cfg = servers[name]
    try:
        # Resolve vault refs for testing
        resolved_cfg = resolver.resolve_config(cfg)
        
        if resolved_cfg.get('type') == 'remote' or 'url' in resolved_cfg:
            res = test_http_server(resolved_cfg['url'], resolved_cfg.get('headers'))
        elif 'command' in resolved_cfg:
            cmd = resolved_cfg['command']
            if isinstance(cmd, list):
                executable = cmd[0] if cmd else ''
                cmd_args = cmd[1:] if len(cmd) > 1 else []
            else:
                executable = cmd
                cmd_args = []
            res = test_stdio_server(executable, cmd_args, resolved_cfg.get('environment'))
        else:
            res = {"status": "error", "message": "Unknown server type (no url or command)"}
            
        results.append((name, res))
    except Exception as e:
        results.append((name, {"status": "error", "message": str(e)}))

# Print results table
print(f"{'Server':<20} {'Status':<15} {'Details':<30}")
print("-" * 65)
for name, res in results:
    status_str = ""
    if res['status'] == 'connected':
        status_str = f"\033[32m✓ Connected\033[0m"
        details = f"{res.get('tools_count', 0)} tools"
        if res.get('version'): details += f" (v{res['version']})"
    else:
        status_str = f"\033[31m✗ {res['status'].capitalize()}\033[0m"
        details = res.get('message', 'Unknown error')
        
    print(f"{name:<20} {status_str:<25} {details:<30}")

PYEOF
}

# ─── COMPILE ─────────────────────────────────────────────────────────────────

cmd_compile() {
  local project_dir="${PROJECT_DIR:-$(pwd)}"
  ensure_global_config_file
  export _SCRIPT_DIR="$SCRIPT_DIR"
  export _CONFIG_FILE="$CONFIG_FILE"
  export _BUILTIN_FILE="$BUILTIN_FILE"
  export _PROJECT_DIR="$project_dir"
  # validate_mcp.py lives in the global install, not project-local
  local _mcp_module_dir="$HOME/.ostwin/.agents/mcp"
  [[ -f "$_mcp_module_dir/validate_mcp.py" ]] || _mcp_module_dir="$SCRIPT_DIR"
  export _MCP_MODULE_DIR="$_mcp_module_dir"

  step "Compiling MCP config for project at $project_dir..."

  "$PYTHON" - <<'PYEOF'
import json, sys, os
script_dir = os.environ.get("_SCRIPT_DIR")
home_config_file = os.environ.get("_CONFIG_FILE")
builtin_file = os.environ.get("_BUILTIN_FILE")

project_dir = os.environ.get("_PROJECT_DIR")

mcp_dir = os.path.join(project_dir, '.agents', 'mcp')
env_mcp_file = os.path.join(mcp_dir, '.env.mcp')
compiled_config_file = os.path.join(mcp_dir, 'config.json')

sys.path.append(script_dir)
try:
    from config_resolver import ConfigResolver
except ImportError as e:
    print(f"  ✗ Import error: {e}")
    sys.exit(1)

if not os.path.exists(home_config_file):
    os.makedirs(os.path.dirname(home_config_file), exist_ok=True)
    home_config = {"mcp": {}}
    with open(home_config_file, 'w') as f:
        json.dump(home_config, f, indent=2)
    print(f'  ✓ Created home config: {home_config_file}')

with open(home_config_file) as f:
    home_config = json.load(f)

builtin_config = {}
if os.path.exists(builtin_file):
    with open(builtin_file) as f:
        builtin_config = json.load(f)

# Normalize builtin config (handles legacy mcpServers, shell vars, etc.)
mcp_module_dir = os.environ.get("_MCP_MODULE_DIR", script_dir)
if mcp_module_dir not in sys.path:
    sys.path.insert(0, mcp_module_dir)
from validate_mcp import normalize_mcp_config
normalized_builtin = normalize_mcp_config(builtin_config)

# Merge order: builtin → home (each layer overrides the previous).
merged_builtin = {"mcp": {}}
merged_builtin["mcp"].update(normalized_builtin)

resolver = ConfigResolver()
compiled_config, env_vars = resolver.compile_config(home_config, merged_builtin, project_dir=project_dir)

# Ensure directory exists
os.makedirs(mcp_dir, exist_ok=True)

# Strip 'environment' from remote servers (OpenCode only supports it for local)
for name, cfg in compiled_config['mcp'].items():
    if cfg.get('type') == 'remote' and 'environment' in cfg:
        del cfg['environment']

# Write compiled config
with open(compiled_config_file, 'w') as f:
    json.dump(compiled_config, f, indent=2)
    f.write('\n')

# Write .env.mcp
with open(env_mcp_file, 'w') as f:
    f.write("# Generated by ostwin mcp compile - DO NOT COMMIT\n")
    for k, v in sorted(env_vars.items()):
        f.write(f"{k}={v}\n")

print(f'  ✓ Compiled {len(compiled_config["mcp"])} servers')
print(f'  ✓ Generated {compiled_config_file}')
print(f'  ✓ Generated {env_mcp_file}')
PYEOF

  # ── Resolve placeholders and write .opencode/opencode.json ──
  # OpenCode does NOT understand {env:VAR} — all placeholders must be resolved
  # to literal values before writing the final config.
  local abs_project_dir
  abs_project_dir="$(cd "$project_dir" 2>/dev/null && pwd || echo "$project_dir")"
  local env_mcp_file="$project_dir/.agents/mcp/.env.mcp"

  # Export known path vars so the Python resolver can find them
  export AGENT_DIR="$INSTALL_DIR"
  export PROJECT_DIR="$abs_project_dir"

  "$PYTHON" - <<PYEOF
import json, os, re, shlex

project_dir = '$abs_project_dir'
config_file = os.path.join(project_dir, '.agents', 'mcp', 'config.json')
env_mcp_file = '$env_mcp_file'

# Load .env.mcp (vault-derived secrets) into a lookup dict
env_extra = {}
if os.path.exists(env_mcp_file):
    with open(env_mcp_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, _, v = line.partition('=')
            env_extra[k.strip()] = v.strip()

# Build unified env: real env + .env.mcp overrides
env_all = {**os.environ, **env_extra}

def resolve_env_refs(text):
    """Replace ALL {env:VAR} with resolved values from environment."""
    def _repl(m):
        var = m.group(1)
        return env_all.get(var, m.group(0))
    return re.sub(r'\{env:(\w+)\}', _repl, text)

def split_command_text(command):
    stripped = command.strip()
    if not stripped:
        return []
    try:
        return shlex.split(stripped)
    except ValueError:
        return stripped.split()

def normalize_local_command(command):
    if isinstance(command, str):
        return split_command_text(command)
    if isinstance(command, list) and len(command) == 1 and isinstance(command[0], str):
        return split_command_text(command[0])
    return command

# 1. Resolve {env:AGENT_DIR} and {env:PROJECT_DIR} in config.json (internal copy)
with open(config_file) as f:
    raw = f.read()
raw = raw.replace('{env:AGENT_DIR}', '$INSTALL_DIR')
raw = raw.replace('{env:PROJECT_DIR}', '$abs_project_dir')
with open(config_file, 'w') as f:
    f.write(raw)

# 2. Write .opencode/opencode.json
# - command arrays: resolve ALL {env:*} to literal paths
# - environment/headers: STRIP {env:*} pass-throughs (server inherits parent env)
#   to avoid writing secrets (API keys, tokens) to disk
with open(config_file) as f:
    config = json.load(f)

import shutil

# Resolve bare "python" to absolute path (from activated venv) so OpenCode can find it
python_abs = shutil.which('python') or shutil.which('python3') or 'python'

env_ref_pattern = re.compile(r'\{env:\w+\}')
resolved_mcp = {}
for name, cfg in config.get('mcp', {}).items():
    out = {}
    is_local = cfg.get('type') == 'local' or ('command' in cfg and cfg.get('type') != 'remote')
    for key, val in cfg.items():
        if key == 'command' and is_local:
            # Resolve {env:*} and bare "python" to absolute paths
            val = normalize_local_command(val)
            resolved_cmd = []
            if isinstance(val, list):
                for i, c in enumerate(val):
                    if isinstance(c, str):
                        c = resolve_env_refs(c)
                        # Resolve bare executable (first element) to absolute path
                        if i == 0 and c in ('python', 'python3'):
                            c = python_abs
                    resolved_cmd.append(c)
                out[key] = resolved_cmd
            else:
                out[key] = val
        elif key in ('environment', 'headers') and isinstance(val, dict):
            # Resolve {env:*} to literal values; drop entries that stay unresolved
            resolved_env = {}
            for k, v in val.items():
                if isinstance(v, str):
                    rv = resolve_env_refs(v)
                    if env_ref_pattern.search(rv):
                        continue
                    resolved_env[k] = rv
                else:
                    resolved_env[k] = v
            if resolved_env:
                out[key] = resolved_env
        elif key == 'url' and isinstance(val, str):
            out[key] = resolve_env_refs(val)
        else:
            out[key] = val
    resolved_mcp[name] = out

opencode_dir = os.path.join(project_dir, '.opencode')
opencode_file = os.path.join(opencode_dir, 'opencode.json')
os.makedirs(opencode_dir, exist_ok=True)

parent_dir = os.path.dirname(project_dir.rstrip('/'))

# Inject opencode agent definitions for every ostwin role.
agents = {}
ostwin_config_path = os.path.join(os.path.expanduser('~'), '.ostwin', '.agents', 'config.json')
if os.path.exists(ostwin_config_path):
    try:
        with open(ostwin_config_path) as f:
            ostwin_cfg = json.load(f)
        for role_name, role_cfg in ostwin_cfg.items():
            if not isinstance(role_cfg, dict) or 'default_model' not in role_cfg:
                continue
            agents[role_name] = {
                'mode': 'primary',
                'model': role_cfg['default_model'],
                'description': role_cfg.get('description', f'{role_name} agent'),
            }
            for inst_name, inst_cfg in role_cfg.get('instances', {}).items():
                full_name = f'{role_name}-{inst_name}'
                agents[full_name] = {
                    'mode': 'primary',
                    'model': inst_cfg.get('default_model', role_cfg['default_model']),
                    'description': inst_cfg.get('display_name', f'{role_name} {inst_name}'),
                }
    except (json.JSONDecodeError, OSError):
        pass

roles_dir = os.path.join(os.path.expanduser('~'), '.ostwin', '.agents', 'roles')
if os.path.isdir(roles_dir):
    for role_name in os.listdir(roles_dir):
        if role_name.startswith('_') or role_name in agents:
            continue
        role_json = os.path.join(roles_dir, role_name, 'role.json')
        if not os.path.exists(role_json):
            continue
        try:
            with open(role_json) as f:
                rj = json.load(f)
            model = rj.get('model') or rj.get('default_model')
            if not model:
                continue
            agents[role_name] = {
                'mode': 'primary',
                'model': model,
                'description': rj.get('description', f'{role_name} agent'),
            }
        except (json.JSONDecodeError, OSError):
            pass

opencode_config = {
    "\$schema": "https://opencode.ai/config.json",
    "mcp": resolved_mcp,
    "permission": {
        "external_directory": {
            f"{parent_dir}/*": "allow",
            f"{parent_dir}/**": "allow",
            f"{os.path.expanduser('~')}/.ostwin/*": "allow",
            f"{os.path.expanduser('~')}/.ostwin/**": "allow",
        },
    },
}
if agents:
    opencode_config["agent"] = agents

with open(opencode_file, 'w') as f:
    json.dump(opencode_config, f, indent=2)
    f.write('\n')

# Warn about unresolved refs in command arrays
cmd_unresolved = []
for name, cfg in resolved_mcp.items():
    for c in cfg.get('command', []):
        if isinstance(c, str) and env_ref_pattern.search(c):
            cmd_unresolved.append(c)
if cmd_unresolved:
    print(f'  ⚠ Unresolved in commands (set these vars): {", ".join(sorted(set(cmd_unresolved)))}')

print(f'  ✓ Generated {opencode_file}')
PYEOF
}

# ─── HELP ────────────────────────────────────────────────────────────────────

cmd_help() {
  cat <<HELP
ostwin mcp — MCP Extension Manager (global registry)

Usage:
  ostwin mcp install <name>                Install from catalog by name
  ostwin mcp install <git-url> --name X    Install from git URL
  ostwin mcp install --http <url> --header H Install HTTP MCP server
  ostwin mcp list                          Show installed extensions
  ostwin mcp catalog                       Show available packages
  ostwin mcp remove <name>                 Uninstall an extension
  ostwin mcp sync                         Rebuild config.json
  ostwin mcp test [server|--all]          Test MCP server connectivity
  ostwin mcp compile                      Compile home config for project
  ostwin mcp credentials <set|list|delete> Manage credentials in vault
  ostwin mcp migrate                       Migrate secrets to vault
  ostwin mcp init-project <dir>           Scaffold per-project MCP directory

Options:
  --name NAME        Override extension name
  --branch BRANCH    Git branch to clone (default: main)
  --env PATH         .env file to inject into MCP config
  --http URL         Install an HTTP-based MCP server
  --header "K=V"     Add a header to HTTP MCP server (can be used multiple times)
  --project-dir DIR  Target project (auto-detected from cwd)

Examples:
  ostwin mcp catalog
  ostwin mcp install <git-url> --name custom-server
  ostwin mcp install --http https://stitch.googleapis.com/mcp --header "X-Goog-Api-Key=AIza..."
#
# Config format (OpenCode-compatible):
#   {"mcp": {"server-name": {"type": "local", "command": [...], "environment": {...}}}}
#   {"mcp": {"server-name": {"type": "remote", "url": "...", "headers": {...}}}}
  ostwin mcp credentials list
  ostwin mcp migrate
HELP
}

# ─── MAIN ────────────────────────────────────────────────────────────────────

# Parse global options
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir)
      PROJECT_DIR="$2"
      shift 2
      ;;
    *)
      break
      ;;
  esac
done

# Apply project dir → set all project-local paths
# Note: PROJECT_DIR is used for local extensions, but CONFIG_FILE is global
if [[ -z "$PROJECT_DIR" ]]; then
  if [[ -d "$(pwd)/.agents/mcp" ]]; then
    PROJECT_DIR="$(pwd)"
  else
    # Fallback to a default if not in a project
    PROJECT_DIR="$HOME/.ostwin"
  fi
fi
apply_project_dir

subcmd="${1:-help}"
[[ $# -gt 0 ]] && shift

case "$subcmd" in
  install)      cmd_install "$@" ;;
  list)         cmd_list ;;
  catalog)      cmd_catalog ;;
  remove)       cmd_remove "$@" ;;
  sync)         cmd_sync ;;
  test)         cmd_test "$@" ;;
  compile)      cmd_compile "$@" ;;
  credentials)  cmd_credentials "$@" ;;
  migrate)      cmd_migrate ;;
  init-project) cmd_init_project "$@" ;;
  -h|--help|help|"") cmd_help ;;
  *)
    fail "Unknown subcommand: $subcmd"
    cmd_help
    exit 0
    ;;
esac
