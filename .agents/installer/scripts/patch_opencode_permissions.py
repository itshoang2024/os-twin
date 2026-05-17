#!/usr/bin/env python3
"""Patch OpenCode permissions for headless Ostwin OpenCode servers.

Usage: python patch_opencode_permissions.py <opencode_config_path>

Ensures the OpenCode config has permission.read and
permission.external_directory entries that let agents read files without
interactive prompts. This matters for ``opencode serve`` because there is no
terminal UI to answer pending permission requests.
"""

import json
import sys
import os
from copy import deepcopy


def patch_permissions(config_path: str) -> None:
    # Load existing config or start fresh
    if os.path.isfile(config_path):
        with open(config_path) as f:
            config = json.load(f)
    else:
        config = {"$schema": "https://opencode.ai/config.json"}
    original_config = deepcopy(config)

    # Ensure permission.read exists and allows all reads, including .env-style
    # files. Also allow external_directory so a server launched from the
    # dedicated opencode_server directory can still read project/plans files
    # elsewhere on the machine without waiting for an interactive approval.
    env_read_allow = {
        "*": "allow",
        "*.env": "allow",
        "*.env.*": "allow",
        "*.env.example": "allow",
    }
    perm = config.get("permission")
    if perm is None:
        config["permission"] = {}
        perm = config["permission"]
    if isinstance(perm, str):
        # e.g. "allow" — convert to dict, preserving intent
        config["permission"] = {"*": perm}
        perm = config["permission"]
    elif not isinstance(perm, dict):
        config["permission"] = {}
        perm = config["permission"]

    # Ensure "read" sub-key is a dict with .env allowed
    read_perm = perm.get("read") if isinstance(perm, dict) else None
    if isinstance(perm, dict):
        if isinstance(read_perm, str):
            perm["read"] = {
                "*": "allow",
                "*.env": "allow",
                "*.env.*": "allow",
                "*.env.example": "allow",
            }
        elif isinstance(read_perm, dict):
            read_perm["*"] = "allow"
            read_perm["*.env"] = "allow"
            read_perm["*.env.*"] = "allow"
            read_perm["*.env.example"] = "allow"
        else:
            perm["read"] = dict(env_read_allow)

        external_perm = perm.get("external_directory")
        if isinstance(external_perm, dict):
            external_perm["*"] = "allow"
        elif external_perm != "allow":
            perm["external_directory"] = {"*": "allow"}

    if config == original_config:
        print(f"    OpenCode permissions already up to date at {config_path}")
        return

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    print("    Permissions: read/external_directory → allow")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <opencode_config_path>", file=sys.stderr)
        sys.exit(1)
    patch_permissions(sys.argv[1])
