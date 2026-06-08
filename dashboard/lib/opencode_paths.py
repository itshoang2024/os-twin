"""Shared path helpers for Ostwin-managed OpenCode state."""

from __future__ import annotations

import os
from pathlib import Path


def get_ostwin_home() -> Path:
    """Return the active Ostwin install directory."""
    default_home = Path.home() / ".ostwin"
    return Path(os.environ.get("OSTWIN_HOME", str(default_home))).expanduser()


def get_managed_opencode_config_path(ostwin_home: Path | None = None) -> Path:
    """Return the Ostwin-owned OpenCode config path."""
    root = ostwin_home or get_ostwin_home()
    return root / ".opencode" / "opencode.json"


def get_user_opencode_config_path() -> Path:
    """Return the user's global OpenCode config path."""
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / "opencode" / "opencode.json"
    return Path.home() / ".config" / "opencode" / "opencode.json"


def get_project_opencode_config_path(project_dir: Path) -> Path:
    """Return a project's OpenCode config path."""
    return project_dir.expanduser() / ".opencode" / "opencode.json"
