#!/usr/bin/env python3
"""Merge new built-in MCP servers into config.json (never overwrite existing).

Usage: python merge_mcp_builtin.py <config_path> <builtin_path>

Reads the built-in server definitions and adds any that don't already
exist in the user's config. Also updates environment blocks for existing
servers if they were previously empty.
"""

import json
import sys


def merge_builtin(cfg_path: str, builtin_path: str) -> None:
    with open(cfg_path) as f:
        config = json.load(f)
    with open(builtin_path) as f:
        builtin = json.load(f)

    cfg_servers = config.setdefault("mcp", config.get("mcpServers", {}))
    builtin_servers = builtin.get("mcp", builtin.get("mcpServers", {}))

    added = []
    updated = []
    for name, server in builtin_servers.items():
        if name not in cfg_servers:
            cfg_servers[name] = server
            added.append(name)
            continue

        existing = cfg_servers[name]
        if not isinstance(existing, dict) or not isinstance(server, dict):
            continue

        # Update transport type when builtin changes it (e.g. stdio → HTTP)
        if "type" in server and existing.get("type") != server["type"]:
            cfg_servers[name] = server
            updated.append(f"{name} (type: {existing.get('type')} → {server['type']})")
            continue

        # Update URL when builtin changes it
        if "url" in server and existing.get("url") != server.get("url"):
            existing["url"] = server["url"]
            # Also update headers if builtin has them
            if "headers" in server:
                existing["headers"] = server["headers"]
            updated.append(f"{name} (url)")
            continue

        if "environment" in server:
            env = existing.get("environment")
            if not isinstance(env, dict):
                existing["environment"] = server["environment"]
                updated.append(name)
            elif not env and server["environment"]:
                existing["environment"] = server["environment"]
                updated.append(name)

    if added or updated:
        with open(cfg_path, "w") as f:
            json.dump(config, f, indent=2)
            f.write("\n")
        parts = []
        if added:
            parts.append(f"added {len(added)} new server(s): {', '.join(added)}")
        if updated:
            parts.append(
                f"updated {len(updated)} existing server(s): {', '.join(updated)}"
            )
        print(f"    {'; '.join(parts)}")
    else:
        print("    All built-in servers already present")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(
            f"Usage: {sys.argv[0]} <config_path> <builtin_path>", file=sys.stderr
        )
        sys.exit(1)
    merge_builtin(sys.argv[1], sys.argv[2])
