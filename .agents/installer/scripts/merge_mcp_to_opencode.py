#!/usr/bin/env python3
"""Normalize, validate, and merge MCP servers into OpenCode config.

Usage: python merge_mcp_to_opencode.py <mcp_source> <opencode_file> <mcp_module_dir>

Normalizes from any format (legacy mcpServers, shell ${VAR}, etc.) to OpenCode.
Validates each server against the OpenCode MCP spec.
Ensures each server has "enabled": true.
Builds a "tools" deny block: "<server>*": false for each server.
Preserves existing user settings (theme, model, keybinds).
"""

import json
import os
import re
import shutil
import sys
from copy import deepcopy


def main(mcp_source: str, opencode_file: str, mcp_module_dir: str) -> None:
    # Import from the shared module (.agents/mcp/validate_mcp.py)
    sys.path.insert(0, mcp_module_dir)
    from validate_mcp import (
        normalize_mcp_config,
        validate_mcp_config,
        build_opencode_config,
    )

    # Read the MCP source config (may be OpenCode or legacy format)
    with open(mcp_source) as f:
        source = json.load(f)

    # Normalize: legacy mcpServers → mcp, shell ${VAR} → {env:VAR},
    #            string command → array, env → environment, httpUrl → url
    normalized = normalize_mcp_config(source)

    # Validate against OpenCode spec
    validated_mcp, skipped_names, results = validate_mcp_config(normalized)

    for name, is_valid, errors, warnings in results:
        for w in warnings:
            print(f"    [WARN] '{name}': {w}", file=sys.stderr)
        if not is_valid:
            for e in errors:
                print(f"    [ERROR] '{name}': {e} — skipping", file=sys.stderr)

    # Resolve bare "python" and {env:*} in command arrays to absolute paths.
    # OSTWIN_VENV_DIR / OSTWIN_INSTALL_DIR are passed from patch-mcp.sh.
    venv_dir = os.environ.get("OSTWIN_VENV_DIR", "")
    install_dir = os.environ.get("OSTWIN_INSTALL_DIR", "")
    # OSTWIN_PYTHON is later used inside MCP command arrays. Resolve it with
    # the platform-specific venv layout before placeholders are expanded.
    if venv_dir:
        if sys.platform == "win32":
            ostwin_python = os.path.join(venv_dir, "Scripts", "python.exe")
        else:
            ostwin_python = os.path.join(venv_dir, "bin", "python")
    else:
        ostwin_python = ""
    if not ostwin_python or not os.path.isfile(ostwin_python):
        ostwin_python = shutil.which("python") or shutil.which("python3") or "python"

    _env_ref = re.compile(r"\{env:(\w+)\}")
    _env_known = {
        "AGENT_DIR": install_dir,
        "OSTWIN_PYTHON": ostwin_python,
    }

    def _resolve_env_ref(m):
        """Resolve {env:VAR} → known override → process env → leave as-is."""
        var = m.group(1)
        return _env_known.get(var, os.environ.get(var, m.group(0)))

    def _resolve_command(cmd):
        """Resolve bare python and {env:*} refs in command arrays."""
        if not isinstance(cmd, list) or not cmd:
            return cmd
        resolved = []
        for i, c in enumerate(cmd):
            if isinstance(c, str):
                c = _env_ref.sub(_resolve_env_ref, c)
                # Resolve bare python to venv path
                if i == 0 and c in ("python", "python3"):
                    c = ostwin_python
            resolved.append(c)
        return resolved

    for _name, _cfg in validated_mcp.items():
        if "command" in _cfg:
            _cfg["command"] = _resolve_command(_cfg["command"])

    # Resolve {env:*} in environment blocks via known overrides → process env,
    # then drop any entries still containing unresolved placeholders.
    for _name, _cfg in validated_mcp.items():
        _envblock = _cfg.get("environment")
        if isinstance(_envblock, dict):
            resolved_env = {}
            for k, v in _envblock.items():
                if isinstance(v, str):
                    v = _env_ref.sub(_resolve_env_ref, v)
                if not (isinstance(v, str) and _env_ref.search(v)):
                    resolved_env[k] = v
            _cfg["environment"] = resolved_env

    # Resolve {env:*} in headers (for remote servers like knowledge)
    for _name, _cfg in validated_mcp.items():
        _hdrs = _cfg.get("headers")
        if isinstance(_hdrs, dict):
            resolved_hdrs = {}
            for k, v in _hdrs.items():
                if isinstance(v, str):
                    v = _env_ref.sub(_resolve_env_ref, v)
                if not (isinstance(v, str) and _env_ref.search(v)):
                    resolved_hdrs[k] = v
            _cfg["headers"] = resolved_hdrs

    # Resolve {env:*} in headers (for remote servers like knowledge)
    for _name, _cfg in validated_mcp.items():
        _hdrs = _cfg.get("headers")
        if isinstance(_hdrs, dict):
            resolved_hdrs = {}
            for k, v in _hdrs.items():
                if isinstance(v, str):
                    v = _env_ref.sub(
                        lambda m: _env_known.get(
                            m.group(1), os.environ.get(m.group(1), m.group(0))
                        ),
                        v,
                    )
                if not (isinstance(v, str) and _env_ref.search(v)):
                    resolved_hdrs[k] = v
            _cfg["headers"] = resolved_hdrs

    # Build tools deny + agent config:
    #   - Global tools deny: blocks all MCP tools EXCEPT core servers
    #     (channel, warroom, memory are available to ALL agents)
    #   - Agent config: privileged agents (manager, architect, qa, audit,
    #     reporter) get ALL tools enabled
    tools_deny, agent_config = build_opencode_config(validated_mcp)

    # Load existing opencode.json if present (preserve user settings)
    existing = {}
    if os.path.exists(opencode_file):
        try:
            with open(opencode_file) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, ValueError):
            existing = {}
    original_existing = deepcopy(existing)

    # Merge: replace only the managed keys (mcp, tools, agent)
    existing["$schema"] = "https://opencode.ai/config.json"
    existing["mcp"] = validated_mcp
    existing["tools"] = tools_deny
    existing["agent"] = agent_config

    if existing == original_existing:
        print(f"    OpenCode MCP config already up to date at {opencode_file}")
        return

    with open(opencode_file, "w") as f:
        json.dump(existing, f, indent=2)
        f.write("\n")

    core_count = len(
        [n for n in validated_mcp if n in {"channel", "warroom", "memory", "ostwin"}]
    )
    print(f"    Merged {len(validated_mcp)} MCP server(s) into {opencode_file}")
    if skipped_names:
        print(
            f"    Skipped {len(skipped_names)} invalid server(s): {', '.join(skipped_names)}"
        )
    print(f"    Tools deny block: {len(tools_deny)} server(s) globally disabled")
    print(
        f"    Core servers (channel/warroom/memory): {core_count} available to all agents"
    )
    print(
        f"    Agent config: {len(agent_config)} privileged agent(s) with full tool access"
    )


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(
            f"Usage: {sys.argv[0]} <mcp_source> <opencode_file> <mcp_module_dir>",
            file=sys.stderr,
        )
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
