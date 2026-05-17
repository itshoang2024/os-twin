#!/usr/bin/env python3
"""Validate MCP server configs against the OpenCode MCP spec.

Usage:
  # Validate a config file:
  python validate_mcp.py config.json

  # Validate a single server inline:
  python validate_mcp.py --server '{"type":"local","command":["npx","-y","my-mcp"]}'

  # Validate and output the cleaned config (valid servers only):
  python validate_mcp.py config.json --output validated.json

Spec reference: https://opencode.ai/docs/mcp-servers

Local servers (type: "local"):
  - Required: type, command (non-empty array of strings), environment (dict)
  - Optional: enabled (bool), timeout (number, ms)

Remote servers (type: "remote"):
  - Required: type, url (non-empty string)
  - Auth:     headers (dict with auth token) or oauth (dict/false)
  - Optional: enabled (bool), timeout (number, ms)
"""
import argparse
import json
import re
import sys


# ─── Normalization (legacy → OpenCode format) ────────────────────────────────


def _convert_shell_vars(text):
    """Convert shell ${VAR} and ${VAR:-default} syntax to OpenCode {env:VAR}.

    - ${VAR}            → {env:VAR}
    - ${VAR:-default}   → the literal default value (with nested ${} resolved)
    """
    if not isinstance(text, str):
        return text

    # First pass: resolve ${VAR:-default} — use the default value.
    # Must handle nested braces (e.g. ${X:-${HOME}/path}).
    # Walk character-by-character to find the matching closing brace.
    result = []
    i = 0
    while i < len(text):
        if text[i:i+2] == '${':
            # Find the variable name
            j = i + 2
            while j < len(text) and (text[j].isalnum() or text[j] == '_'):
                j += 1
            var_name = text[i+2:j]

            if j < len(text) and text[j:j+2] == ':-':
                # ${VAR:-default} — extract default with brace balancing
                k = j + 2
                depth = 1
                while k < len(text) and depth > 0:
                    if text[k] == '{':
                        depth += 1
                    elif text[k] == '}':
                        depth -= 1
                    if depth > 0:
                        k += 1
                default_val = text[j+2:k]
                # Recursively resolve any nested ${VAR} in the default
                result.append(_convert_shell_vars(default_val))
                i = k + 1
            elif j < len(text) and text[j] == '}':
                # Simple ${VAR} → {env:VAR}
                result.append('{env:' + var_name + '}')
                i = j + 1
            else:
                # Malformed, pass through
                result.append(text[i])
                i += 1
        elif text[i] == '$' and i + 1 < len(text) and re.match(r'[A-Z_]', text[i+1]):
            # Bare $VAR → {env:VAR}
            j = i + 1
            while j < len(text) and (text[j].isalnum() or text[j] == '_'):
                j += 1
            var_name = text[i+1:j]
            result.append('{env:' + var_name + '}')
            i = j
        else:
            result.append(text[i])
            i += 1

    return ''.join(result)


def normalize_mcp_server(name, cfg):
    """Normalize a single MCP server config from any legacy format to OpenCode.

    Handles:
      - mcpServers format (command as string, args array, env key, httpUrl)
      - Shell variable syntax (${VAR}, ${VAR:-default})
      - Missing type field (inferred from command/url/httpUrl)

    Returns a new dict in OpenCode format. Does NOT validate — call
    validate_mcp_server() on the result.
    """
    if not isinstance(cfg, dict):
        return cfg

    out = {}

    # --- Infer type ---
    if 'type' in cfg:
        out['type'] = cfg['type']
    elif 'httpUrl' in cfg or ('url' in cfg and 'command' not in cfg):
        out['type'] = 'remote'
    elif 'command' in cfg:
        out['type'] = 'local'

    # --- command: string → array, merge with args ---
    cmd = cfg.get('command')
    args = cfg.get('args', [])
    if isinstance(cmd, str):
        # Split string command into array (e.g. "npx -y foo" → ["npx","-y","foo"])
        cmd = cmd.split()
    if isinstance(cmd, list):
        # Merge args into command
        if isinstance(args, list) and args:
            cmd = cmd + args
        # Convert shell vars in each element
        cmd = [_convert_shell_vars(c) for c in cmd]
        out['command'] = cmd

    # --- url / httpUrl ---
    url = cfg.get('url') or cfg.get('httpUrl')
    if url:
        out['url'] = _convert_shell_vars(url)

    # --- environment / env ---
    if 'environment' in cfg:
        env = cfg['environment']
    elif 'env' in cfg:
        env = cfg['env']
    else:
        env = None
    if isinstance(env, dict):
        out['environment'] = {
            k: _convert_shell_vars(v) if isinstance(v, str) else v
            for k, v in env.items()
        }

    # --- headers ---
    headers = cfg['headers'] if 'headers' in cfg else None
    if isinstance(headers, dict):
        out['headers'] = {
            k: _convert_shell_vars(v) if isinstance(v, str) else v
            for k, v in headers.items()
        }

    # --- Pass through oauth, enabled, timeout ---
    for key in ('oauth', 'enabled', 'timeout'):
        if key in cfg:
            out[key] = cfg[key]

    return out


def normalize_mcp_config(raw_config):
    """Normalize a full MCP config from any format to OpenCode format.

    Handles:
      - "mcpServers" key (legacy) → "mcp" key (OpenCode)
      - Each server normalized via normalize_mcp_server()

    Args:
        raw_config: The raw parsed JSON config (top-level dict).

    Returns:
        dict of {server_name: normalized_server_config}
    """
    # Support both "mcp" and legacy "mcpServers" keys
    servers = raw_config.get('mcp', raw_config.get('mcpServers', {}))

    normalized = {}
    for name, cfg in servers.items():
        normalized[name] = normalize_mcp_server(name, cfg)

    return normalized


def merge_mcp_configs(*configs):
    """Merge multiple MCP config dicts, later configs override earlier ones.

    Each config can be in any format (legacy mcpServers or OpenCode mcp).
    All are normalized to OpenCode format before merging.

    Args:
        *configs: Raw parsed JSON config dicts.

    Returns:
        dict of {server_name: normalized_server_config} (merged, OpenCode format)
    """
    merged = {}
    for raw in configs:
        normalized = normalize_mcp_config(raw)
        merged.update(normalized)
    return merged


# ─── Validation ──────────────────────────────────────────────────────────────


def validate_mcp_server(name, cfg):
    """Validate an MCP server config against the OpenCode MCP spec.

    Args:
        name: Server name (used in error messages).
        cfg:  Server config dict.

    Returns:
        (is_valid, errors, warnings) where:
          - is_valid: bool — True if the server can be used.
          - errors:   list[str] — fatal issues (server will be skipped).
          - warnings: list[str] — non-fatal issues (server still usable).
    """
    errors = []
    warnings = []

    if not isinstance(cfg, dict):
        return False, ["not a valid server object (expected dict)"], []

    # --- type ---
    stype = cfg.get('type')
    if stype not in ('local', 'remote'):
        return False, [
            f"missing or invalid 'type': got {stype!r} "
            f"(must be 'local' or 'remote')"
        ], []

    # --- local ---
    if stype == 'local':
        # command: required, must be a non-empty list of strings
        cmd = cfg.get('command')
        if cmd is None:
            errors.append("missing 'command' (required for local servers)")
        elif not isinstance(cmd, list) or len(cmd) == 0:
            errors.append(
                f"'command' must be a non-empty array, "
                f"got {type(cmd).__name__}"
            )
        elif not all(isinstance(c, str) for c in cmd):
            errors.append("'command' array must contain only strings")

        # environment: required — server needs env vars to function
        env = cfg.get('environment')
        if env is None:
            errors.append(
                "missing 'environment' "
                "(required for local servers — API keys, paths, etc.)"
            )
        elif not isinstance(env, dict):
            errors.append(
                f"'environment' must be a dict, "
                f"got {type(env).__name__}"
            )

    # --- remote ---
    if stype == 'remote':
        # url: required
        url = cfg.get('url')
        if url is None:
            errors.append("missing 'url' (required for remote servers)")
        elif not isinstance(url, str) or not url.strip():
            errors.append(f"'url' must be a non-empty string, got {url!r}")

        # auth: must have headers (with auth token) or oauth config
        has_headers = (
            isinstance(cfg.get('headers'), dict) and len(cfg['headers']) > 0
        )
        has_oauth = 'oauth' in cfg and cfg['oauth'] is not False
        if not has_headers and not has_oauth:
            warnings.append(
                "no authentication configured — "
                "add 'headers' with auth token or 'oauth' config"
            )

    # --- optional fields type checks ---
    if 'timeout' in cfg:
        t = cfg['timeout']
        if not isinstance(t, (int, float)) or t <= 0:
            warnings.append(
                f"'timeout' should be a positive number (ms), got {t!r}"
            )

    if 'enabled' in cfg and not isinstance(cfg['enabled'], bool):
        warnings.append(
            f"'enabled' should be a boolean, "
            f"got {type(cfg['enabled']).__name__}"
        )

    return len(errors) == 0, errors, warnings


def build_opencode_config(validated_mcp, core_servers=None, privileged_agents=None):
    """Build the tools deny block and agent config for opencode.json.

    Global tools deny: blocks all MCP tools EXCEPT core servers.
    Core servers (channel, warroom, memory) are available to ALL agents
    by NOT being denied in the global tools block.

    Agent config: privileged agents (manager, architect, qa, audit,
    reporter) get ALL tools enabled.

    Args:
        validated_mcp:     dict of validated MCP server configs.
        core_servers:      set of server names available to all agents.
                           Default: {"channel", "warroom", "memory"}
        privileged_agents: list of agent names with access to ALL tools.
                           Default: ["manager", "architect", "qa",
                                     "audit", "reporter"]

    Returns:
        (tools_deny, agent_config) where:
          - tools_deny:    dict of {"<server>*": False} for non-core servers.
          - agent_config:  dict of {agent_name: {"tools": {"<server>*": True}}}
                           for each privileged agent.
    """
    if core_servers is None:
        core_servers = {"channel", "warroom", "memory", "ostwin"}
    if privileged_agents is None:
        privileged_agents = [
            "manager", "architect", "qa", "audit", "reporter"
        ]

    # Global: deny non-core servers (core servers available to all agents)
    tools_deny = {}
    for name in validated_mcp:
        if name not in core_servers:
            tools_deny[f"{name}*"] = False

    # Per-agent: privileged agents get ALL tools enabled
    all_tools = {f"{name}*": True for name in validated_mcp}
    agent_config = {}
    for agent in privileged_agents:
        agent_config[agent] = {"tools": dict(all_tools)}

    return tools_deny, agent_config


def validate_mcp_config(mcp_block):
    """Validate all servers in an MCP config block.

    Args:
        mcp_block: dict of {server_name: server_config}.

    Returns:
        (validated, skipped_names, all_results) where:
          - validated:     dict of valid servers (with enabled=True added).
          - skipped_names: list of server names that failed validation.
          - all_results:   list of (name, is_valid, errors, warnings).
    """
    validated = {}
    skipped = []
    results = []

    for name, cfg in mcp_block.items():
        is_valid, errors, warnings = validate_mcp_server(name, cfg)
        results.append((name, is_valid, errors, warnings))

        if is_valid:
            cfg['enabled'] = True
            validated[name] = cfg
        else:
            skipped.append(name)

    return validated, skipped, results


def main():
    parser = argparse.ArgumentParser(
        description='Validate MCP server configs against the OpenCode spec'
    )
    parser.add_argument(
        'config', nargs='?',
        help='Path to MCP config.json file (with "mcp": {...} block)',
    )
    parser.add_argument(
        '--server', type=str, default=None,
        help='Validate a single server as inline JSON string',
    )
    parser.add_argument(
        '--output', type=str, default=None,
        help='Write validated config (valid servers only) to this file',
    )
    args = parser.parse_args()

    if args.server:
        # Validate a single inline server
        try:
            cfg = json.loads(args.server)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON: {e}", file=sys.stderr)
            sys.exit(1)

        is_valid, errors, warnings = validate_mcp_server("inline", cfg)
        for w in warnings:
            print(f"  [WARN] {w}")
        if is_valid:
            print("  [OK] Server config is valid")
        else:
            for e in errors:
                print(f"  [ERROR] {e}")
            sys.exit(1)
        return

    if not args.config:
        parser.print_help()
        sys.exit(1)

    # Validate a full config file (supports both mcp and legacy mcpServers)
    with open(args.config) as f:
        source = json.load(f)

    # Normalize from any format before validating
    mcp_block = normalize_mcp_config(source)

    if not mcp_block:
        print("No MCP servers found in config")
        sys.exit(0)

    validated, skipped, results = validate_mcp_config(mcp_block)

    # Print results
    passed = 0
    warned = 0
    failed = 0
    for name, is_valid, errors, warnings in results:
        if is_valid and not warnings:
            print(f"  [OK]    {name}")
            passed += 1
        elif is_valid and warnings:
            print(f"  [WARN]  {name}")
            for w in warnings:
                print(f"          - {w}")
            warned += 1
        else:
            print(f"  [FAIL]  {name}")
            for e in errors:
                print(f"          - {e}")
            failed += 1

    print(f"\n  {passed} passed, {warned} warnings, {failed} failed "
          f"(out of {len(results)} servers)")

    # Write validated output if requested
    if args.output and validated:
        output = {"mcp": validated}
        with open(args.output, 'w') as f:
            json.dump(output, f, indent=2)
            f.write('\n')
        print(f"  Wrote {len(validated)} valid server(s) to {args.output}")

    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
