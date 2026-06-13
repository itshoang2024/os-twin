"""Shared path helpers for Ostwin-managed OpenCode state."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def find_opencode() -> str | None:
    """Resolve the ``opencode`` CLI executable, returning its path or ``None``.

    Prefers ``PATH`` via :func:`shutil.which`, but falls back to the common
    npm-global install locations. This matters on Windows, where a long-running
    server process (started from an IDE, service, or GUI shell) often inherits a
    ``PATH`` that does **not** include ``%AppData%\\Roaming\\npm`` even though
    ``opencode`` is installed there as ``opencode.cmd`` / ``opencode.ps1``.
    """
    found = shutil.which("opencode")
    if found:
        return found

    candidates: list[Path] = []
    if sys.platform == "win32":
        names = ("opencode.cmd", "opencode.exe", "opencode.bat", "opencode.ps1", "opencode")
        roots = [
            os.environ.get("APPDATA", ""),  # -> %AppData%\Roaming\npm
            os.environ.get("ProgramFiles", ""),  # -> nodejs
        ]
        for root in roots:
            if not root:
                continue
            candidates.append(Path(root) / "npm")
            candidates.append(Path(root) / "nodejs")
    else:
        names = ("opencode",)
        candidates = [
            Path.home() / ".npm-global" / "bin",
            Path("/usr/local/bin"),
            Path("/usr/bin"),
            Path("/opt/homebrew/bin"),
        ]

    for directory in candidates:
        for name in names:
            candidate = directory / name
            if candidate.exists():
                return str(candidate)

    return None


def get_ostwin_home() -> Path:
    """Return the active Ostwin install directory."""
    default_home = Path.home() / ".ostwin"
    return Path(os.environ.get("OSTWIN_HOME", str(default_home))).expanduser()


def get_managed_opencode_config_path(ostwin_home: Path | None = None) -> Path:
    """Return the Ostwin-owned OpenCode config path."""
    root = ostwin_home or get_ostwin_home()
    return root / ".opencode" / "opencode.json"
