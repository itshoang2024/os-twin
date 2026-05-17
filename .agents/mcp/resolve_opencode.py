#!/usr/bin/env python3
"""Resolve MCP config placeholders and write opencode.json.

Shared resolution logic used by:
  - install.sh  (patch_mcp_config phase 3)
  - mcp-extension.sh  (cmd_sync_quiet + cmd_init_project compile)
  - ostwin mcp sync  (canonical sync — resolves servers + role permissions)

Usage:
  # Legacy resolve mode (backward-compatible):
  resolve_opencode.py <config_json> <output_dir> [--env-file <path>]

  # Full sync mode (resolves servers + generates agent permissions from roles):
  resolve_opencode.py sync [--config <path>] [--output <path>]
                           [--roles-dir <path>] [--env-file <path>]

Rules:
  - command arrays:      resolve ALL {env:*} to literal paths
  - headers:             resolve ALL {env:*}, strip still-unresolved entries
  - environment:         STRIP values containing {env:*} (secrets stay in parent env)
  - url strings:         resolve ALL {env:*} to literal values
  - bare python/python3: resolve to absolute path via shutil.which()

Agent Permission Rules (sync mode):
  - mcp_refs present & non-empty → allow listed servers, deny rest
  - mcp_refs missing or empty    → deny ALL servers (explicit opt-in required)
"""
import argparse
import json
import os
import re
import shutil
import sys


# ─── Env file loading ────────────────────────────────────────────────────────

def load_env_file(env_path):
    """Load a .env file into a dict (key=value lines, strips quotes)."""
    env = {}
    if not env_path or not os.path.exists(env_path):
        return env
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, _, v = line.partition('=')
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


# ─── Env ref resolution ──────────────────────────────────────────────────────

def resolve_env_refs(text, env_all):
    """Replace {env:VAR} placeholders with values from env_all."""
    return re.sub(
        r'\{env:(\w+)\}',
        lambda m: env_all.get(m.group(1), m.group(0)),
        text,
    )


def resolve_mcp_servers(servers, env_all):
    """Resolve a dict of MCP server configs, returning cleaned configs.

    - command arrays: resolve {env:*} and bare python to absolute paths
    - headers dicts: resolve {env:*}, strip still-unresolved entries
    - environment dicts: strip values containing {env:*}
    - url strings: resolve {env:*}
    """
    python_abs = shutil.which('python') or shutil.which('python3') or 'python'
    env_ref_pattern = re.compile(r'\{env:\w+\}')
    resolved = {}

    for name, cfg in servers.items():
        out = {}
        for key, val in cfg.items():
            if key == 'command' and isinstance(val, list):
                resolved_cmd = []
                for i, c in enumerate(val):
                    if isinstance(c, str):
                        c = resolve_env_refs(c, env_all)
                        if i == 0 and c in ('python', 'python3'):
                            c = python_abs
                    resolved_cmd.append(c)
                out[key] = resolved_cmd
            elif key == 'headers' and isinstance(val, dict):
                # Resolve {env:*} in header values, then strip still-unresolved
                resolved_headers = {}
                for k, v in val.items():
                    if isinstance(v, str):
                        v = resolve_env_refs(v, env_all)
                    if not (isinstance(v, str) and env_ref_pattern.search(v)):
                        resolved_headers[k] = v
                if resolved_headers:
                    out[key] = resolved_headers
            elif key == 'environment' and isinstance(val, dict):
                cleaned = {
                    k: v for k, v in val.items()
                    if not (isinstance(v, str) and env_ref_pattern.search(v))
                }
                if cleaned:
                    out[key] = cleaned
            elif key == 'url' and isinstance(val, str):
                out[key] = resolve_env_refs(val, env_all)
            else:
                out[key] = val
        resolved[name] = out

    return resolved


# ─── Global config loading ───────────────────────────────────────────────────

def load_global_opencode_config():
    """Load the user's global opencode config, if any.

    Search order (first hit wins):
      1. $XDG_CONFIG_HOME/opencode/opencode.json
      2. ~/.config/opencode/opencode.json
      3. ~/.config/opencode/config.json

    Returns a dict (possibly empty) with the parsed top-level config.
    Used to seed fresh project opencode.json files so that
    provider/model/permission/agent definitions are inherited rather
    than silently dropped when ostwin sets OPENCODE_CONFIG (which makes
    opencode skip its own global lookup).
    """
    candidates = []
    xdg = os.environ.get('XDG_CONFIG_HOME')
    if xdg:
        candidates.append(os.path.join(xdg, 'opencode', 'opencode.json'))
    home = os.environ.get('HOME') or os.path.expanduser('~')
    if home:
        candidates.append(os.path.join(home, '.config', 'opencode', 'opencode.json'))
        candidates.append(os.path.join(home, '.config', 'opencode', 'config.json'))
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    print(f"  Inherited global opencode config from {path}", file=sys.stderr)
                    return data
            except (json.JSONDecodeError, ValueError, OSError) as exc:
                print(f"  Warning: failed to read {path}: {exc}", file=sys.stderr)
    return {}


# ─── Role scanning ───────────────────────────────────────────────────────────

def scan_roles(roles_dir):
    """Scan all role.json files under roles_dir.

    Returns a dict:
        {role_name: {"model": str, "description": str, "mcp_refs": list|None}}

    - mcp_refs is the list from role.json if present, or None if the key
      is missing entirely (distinguishes "field absent" from "field = []").
    """
    roles = {}
    if not os.path.isdir(roles_dir):
        print(f"  Warning: roles dir not found: {roles_dir}", file=sys.stderr)
        return roles

    for entry in sorted(os.listdir(roles_dir)):
        if entry.startswith('_') or entry.startswith('.'):
            continue
        role_json_path = os.path.join(roles_dir, entry, 'role.json')
        if not os.path.isfile(role_json_path):
            continue
        try:
            with open(role_json_path) as f:
                rj = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        model = rj.get('model') or rj.get('default_model')
        if not model:
            continue

        # mcp_refs: None means field is absent, [] means explicitly empty
        mcp_refs = rj.get('mcp_refs')  # returns None if key missing

        roles[entry] = {
            'model': model,
            'description': rj.get('description', f'{entry} agent'),
            'mcp_refs': mcp_refs,
        }

    return roles


def _permission_key(server_name):
    """Convert MCP server name to opencode permission glob key.

    Examples:
        "channel"         → "channel_*"
        "obscura-browser" → "obscura-browser_*"
    """
    return f"{server_name}_*"


# Infrastructure MCP servers that are ALWAYS allowed for every role.
# These are required for inter-agent communication (channel) and room state
# management (warroom). Without these, agents cannot post signals or update
# status, breaking the lifecycle state machine.
INFRA_MCP_SERVERS = {"channel", "warroom", "memory", "knowledge"}


def build_agent_permissions(roles, mcp_server_names):
    """Build per-agent permission blocks from roles and available MCP servers.

    For each role:
      - Infrastructure servers (channel, warroom): ALWAYS allow
      - If mcp_refs is a non-empty list: allow listed servers, deny the rest
      - If mcp_refs is [] or None (absent): deny ALL non-infra servers
      - ostwin_* tools: ALWAYS deny for war-room agents (only the ostwin
        master agent may access them; it has its own opencode.json config
        generated by dashboard.opencode_tools._opencode_config)

    Returns:
        {"role_name": {"permission": {"channel_*": "allow", ..., "ostwin_*": "deny"}}}
    """
    agents = {}
    server_names = sorted(mcp_server_names)

    for role_name, role_info in sorted(roles.items()):
        mcp_refs = role_info.get('mcp_refs')
        allowed = set(mcp_refs) if mcp_refs else set()

        permission = {}
        for srv in server_names:
            pkey = _permission_key(srv)
            if srv in INFRA_MCP_SERVERS:
                permission[pkey] = "allow"
            else:
                permission[pkey] = "allow" if srv in allowed else "deny"

        permission["ostwin_*"] = "deny"

        agents[role_name] = {
            "permission": permission,
        }

    return agents


def build_global_tools_deny(mcp_server_names):
    """Build top-level tools block that denies all MCP tools globally.

    Per-agent permissions override this. The glob pattern uses the
    server name with a trailing * to match all tools from that server.

    ostwin_* is always denied at the global level — only the ostwin
    master agent (configured via dashboard.opencode_tools._opencode_config)
    overrides this to allow.

    Returns:
        {"channel*": false, "warroom*": false, "ostwin_*": false, ...}
    """
    tools = {}
    for srv in sorted(mcp_server_names):
        tools[f"{srv}*"] = False
    tools["ostwin_*"] = False
    return tools


# ─── Unresolved placeholder check ────────────────────────────────────────────

def check_unresolved(resolved_mcp, strict=False):
    """Check for unresolved {env:*} refs and warn/error."""
    env_ref_pattern = re.compile(r'\{env:\w+\}')
    unresolved = []
    for name, cfg in resolved_mcp.items():
        for c in cfg.get('command', []):
            if isinstance(c, str) and env_ref_pattern.search(c):
                unresolved.append(f"{name}/command: {c}")
        for a in cfg.get('args', []):
            if isinstance(a, str) and env_ref_pattern.search(a):
                unresolved.append(f"{name}/args: {a}")
        url = cfg.get('url', '')
        if isinstance(url, str) and env_ref_pattern.search(url):
            unresolved.append(f"{name}/url: {url}")
        for k, v in cfg.get('environment', {}).items():
            if isinstance(v, str) and env_ref_pattern.search(v):
                unresolved.append(f"{name}/environment/{k}: {v}")
    if unresolved:
        msg = (
            f"  Unresolved placeholders (set these vars): "
            f"{', '.join(sorted(set(unresolved)))}"
        )
        if strict:
            print(f"  ERROR: {msg}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"  Warning: {msg}", file=sys.stderr)


# ─── Legacy resolve_and_write (backward-compatible) ──────────────────────────

def resolve_and_write(config_path, output_dir, env_file=None, merge=False,
                      strict=False):
    """Legacy entry point: load config, resolve, write opencode.json.

    Args:
        config_path: Path to MCP config.json source file.
        output_dir:  Directory to write opencode.json into.
        env_file:    Optional .env file for variable resolution.
        merge:       If True, only update the 'mcp' key in an existing
                     opencode.json, preserving user settings (theme, model,
                     keybinds, etc.). If the file doesn't exist, creates fresh.
        strict:      If True, exit with error when unresolved {env:*}
                     placeholders are detected. Default False (warn only).

    Returns the resolved MCP dict (useful for callers that need to add
    tools/agent blocks on top).
    """
    env_extra = load_env_file(env_file)
    env_all = {**os.environ, **env_extra}

    with open(config_path) as f:
        config = json.load(f)
    servers = config.get('mcp', config.get('mcpServers', {}))

    resolved_mcp = resolve_mcp_servers(servers, env_all)

    os.makedirs(output_dir, exist_ok=True)
    opencode_file = os.path.join(output_dir, 'opencode.json')

    if merge and os.path.exists(opencode_file):
        # Merge: preserve existing user settings, only replace managed keys
        with open(opencode_file) as f:
            try:
                existing = json.load(f)
            except (json.JSONDecodeError, ValueError):
                existing = {}
        existing["$schema"] = "https://opencode.ai/config.json"
        existing["mcp"] = resolved_mcp
        opencode_config = existing
    else:
        # Fresh create: seed from the user's global opencode.json so that
        # provider/model/permission/agent blocks survive into the project
        # config. Without this, ostwin's OPENCODE_CONFIG override hides the
        # user's global provider definitions from opencode at run time.
        opencode_config = load_global_opencode_config()
        # Drop any mcp block from the global config — the project's MCP
        # block is authoritative.
        opencode_config.pop('mcp', None)
        opencode_config["$schema"] = "https://opencode.ai/config.json"
        opencode_config["mcp"] = resolved_mcp

    with open(opencode_file, 'w') as f:
        json.dump(opencode_config, f, indent=2)
        f.write('\n')

    check_unresolved(resolved_mcp, strict)
    return resolved_mcp


# ─── Full sync (ostwin mcp sync) ─────────────────────────────────────────────

def sync(config_path, output_path, roles_dir, env_file=None, strict=False,
         dry_run=False):
    """Full MCP sync: resolve servers + generate agent permissions from roles.

    This is the canonical sync entry point used by `ostwin mcp sync`.

    Steps:
      1. Load & resolve MCP server configs (builtin + extensions)
      2. Scan roles_dir for all role.json files → extract mcp_refs
      3. Build per-agent permission blocks (allow/deny per MCP server)
      4. Build global tools deny block
      5. Merge into existing opencode.json (preserves provider/model/etc.)

    Args:
        config_path: Path to MCP config.json (builtin + extensions merged).
        output_path: Path to opencode.json to write.
        roles_dir:   Directory containing role subdirs with role.json files.
        env_file:    Optional .env file for variable resolution.
        strict:      If True, exit on unresolved {env:*} placeholders.
        dry_run:     If True, print JSON to stdout instead of writing.
    """
    # ── 1. Resolve MCP servers ──
    env_extra = load_env_file(env_file)
    env_all = {**os.environ, **env_extra}

    if os.path.isfile(config_path):
        with open(config_path) as f:
            config = json.load(f)
        servers = config.get('mcp', config.get('mcpServers', {}))
    else:
        # Fallback: load builtin config
        home = os.environ.get('HOME') or os.path.expanduser('~')
        builtin_path = os.path.join(home, '.ostwin', '.agents', 'mcp',
                                    'mcp-builtin.json')
        if os.path.isfile(builtin_path):
            with open(builtin_path) as f:
                builtin = json.load(f)
            servers = builtin.get('mcp', builtin.get('mcpServers', {}))
            print(f"  Config not found at {config_path}, using builtin: "
                  f"{builtin_path}", file=sys.stderr)
        else:
            print(f"  Error: no config found at {config_path}", file=sys.stderr)
            sys.exit(1)

    resolved_mcp = resolve_mcp_servers(servers, env_all)
    mcp_server_names = list(resolved_mcp.keys())

    print(f"  Resolved {len(mcp_server_names)} MCP server(s): "
          f"{', '.join(mcp_server_names)}", file=sys.stderr)

    # ── 2. Scan roles ──
    roles = scan_roles(roles_dir)
    print(f"  Scanned {len(roles)} role(s) from {roles_dir}", file=sys.stderr)

    roles_with_refs = {n: r for n, r in roles.items()
                       if r.get('mcp_refs') is not None}
    roles_with_allows = {n: r for n, r in roles_with_refs.items()
                         if r.get('mcp_refs')}
    roles_deny_all = {n: r for n, r in roles.items()
                      if not r.get('mcp_refs')}

    print(f"    {len(roles_with_allows)} role(s) with explicit MCP access",
          file=sys.stderr)
    print(f"    {len(roles_deny_all)} role(s) with deny-all (no mcp_refs)",
          file=sys.stderr)

    # ── 3. Build agent permissions ──
    agents = build_agent_permissions(roles, mcp_server_names)

    # ── 4. Build global tools deny ──
    tools = build_global_tools_deny(mcp_server_names)

    # ── 5. Assemble & merge ──
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Load existing config to preserve user settings (provider, model, etc.)
    existing = {}
    if os.path.isfile(output_path):
        try:
            with open(output_path) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, ValueError):
            existing = {}
    else:
        # Seed from global config
        existing = load_global_opencode_config()

    # Managed keys — overwritten by sync
    existing["$schema"] = "https://opencode.ai/config.json"
    existing["mcp"] = resolved_mcp
    existing["tools"] = tools
    existing["agent"] = agents

    # Preserve unmanaged keys: permission, provider, model, theme, etc.
    # (they stay in `existing` from the merge above)

    check_unresolved(resolved_mcp, strict)

    if dry_run:
        print(json.dumps(existing, indent=2))
        return existing

    with open(output_path, 'w') as f:
        json.dump(existing, f, indent=2)
        f.write('\n')

    print(f"  ✓ Written {output_path}", file=sys.stderr)
    print(f"    MCP servers: {len(mcp_server_names)}", file=sys.stderr)
    print(f"    Agent permissions: {len(agents)}", file=sys.stderr)

    # Print summary of allowed roles
    for role_name in sorted(agents.keys()):
        perms = agents[role_name].get('permission', {})
        allowed = [k.replace('_*', '') for k, v in perms.items() if v == 'allow']
        if allowed:
            print(f"    ✓ {role_name}: {', '.join(allowed)}",
                  file=sys.stderr)

    return existing


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    # Detect mode from first positional arg
    if len(sys.argv) > 1 and sys.argv[1] == 'sync':
        _main_sync(sys.argv[2:])
    else:
        _main_legacy(sys.argv[1:])


def _main_sync(argv):
    """Parse and run the 'sync' subcommand."""
    parser = argparse.ArgumentParser(
        prog='resolve_opencode.py sync',
        description='Full sync: resolve MCP servers + generate agent '
                    'permissions from role.json mcp_refs',
    )
    home = os.environ.get('HOME') or os.path.expanduser('~')
    default_config = os.path.join(home, '.ostwin', '.agents', 'mcp',
                                  'mcp-builtin.json')
    default_output = os.path.join(home, '.config', 'opencode', 'opencode.json')
    default_roles = os.path.join(home, '.ostwin', '.agents', 'roles')

    parser.add_argument(
        '--config', default=default_config,
        help=f'Path to MCP config.json (default: {default_config})',
    )
    parser.add_argument(
        '--output', default=default_output,
        help=f'Path to opencode.json output (default: {default_output})',
    )
    parser.add_argument(
        '--roles-dir', default=default_roles,
        help=f'Directory with role subdirs (default: {default_roles})',
    )
    parser.add_argument(
        '--env-file', default=None,
        help='Path to .env or .env.mcp file for variable resolution',
    )
    parser.add_argument(
        '--strict', action='store_true', default=False,
        help='Exit with error (code 1) if any {env:*} placeholders '
             'remain unresolved.',
    )
    parser.add_argument(
        '--dry-run', action='store_true', default=False,
        help='Print resolved JSON to stdout instead of writing to disk.',
    )
    args = parser.parse_args(argv)

    sync(
        config_path=args.config,
        output_path=args.output,
        roles_dir=args.roles_dir,
        env_file=args.env_file,
        strict=args.strict,
        dry_run=args.dry_run,
    )


def _main_legacy(argv):
    """Parse and run the legacy positional resolve mode."""
    parser = argparse.ArgumentParser(
        description='Resolve MCP config placeholders and write opencode.json'
    )
    parser.add_argument('config', help='Path to MCP config.json')
    parser.add_argument('output_dir', help='Directory for opencode.json output')
    parser.add_argument(
        '--env-file', default=None,
        help='Path to .env or .env.mcp file for variable resolution',
    )
    parser.add_argument(
        '--merge', action='store_true', default=False,
        help='Merge into existing opencode.json (only update mcp key, '
             'preserve user settings like theme/model/keybinds)',
    )
    parser.add_argument(
        '--strict', action='store_true', default=False,
        help='Exit with error (code 1) if any {env:*} placeholders '
             'remain unresolved after resolution. Default: warn only.',
    )
    args = parser.parse_args(argv)

    if not os.path.exists(args.config):
        print(f"Error: config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    resolve_and_write(args.config, args.output_dir, args.env_file, args.merge,
                      args.strict)


if __name__ == '__main__':
    main()
