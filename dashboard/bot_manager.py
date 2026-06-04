"""
bot_manager.py — Manages the Bun-powered bot process lifecycle.

The dashboard spawns the bot as a child process so it can:
  1. Auto-start the bot when the dashboard starts.
  2. Restart the bot when channel configs change (channels.json).
  3. Expose status / restart endpoints without manual intervention.

The bot is launched through bot/package.json using Bun (`bun run start`).
"""

import asyncio
import logging
import os
import signal
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Resolve the bot directory.
# Priority: 1) ~/.ostwin/bot/ (installed)  2) relative to dashboard (dev)
_OSTWIN_HOME = Path.home() / ".ostwin"
_DASHBOARD_DIR = Path(__file__).parent

# Prefer installed bot location, fallback to source repo for development
if (_OSTWIN_HOME / "bot" / "package.json").exists():
    BOT_DIR = _OSTWIN_HOME / "bot"
else:
    BOT_DIR = _DASHBOARD_DIR.parent / "bot"

BOT_ENTRY = BOT_DIR / "src" / "index.ts"

# Maximum log lines kept in memory for the /api/bot/logs endpoint
_MAX_LOG_LINES = 500

# Debounce window — ignore duplicate restart requests within this period
_RESTART_DEBOUNCE_SECS = 2.0


def _is_ci() -> bool:
    return os.environ.get("CI", "").lower() in {"1", "true"}


def ensure_bot_dependencies(bot_dir: Optional[Path] = None) -> bool:
    """Install bot dependencies with Bun if node_modules is missing.

    Returns True if dependencies are available (already installed or just installed).
    Returns False if installation failed or Bun/package.json is unavailable.
    """
    target_dir = bot_dir or BOT_DIR
    node_modules = target_dir / "node_modules"

    if node_modules.exists():
        logger.debug("[BOT] node_modules already exists")
        return True

    if not (target_dir / "package.json").exists():
        logger.warning("[BOT] package.json not found in %s", target_dir)
        return False

    import subprocess

    bun = shutil.which("bun")
    if not bun:
        logger.error("[BOT] Bun not found; install Bun before starting the bot")
        return False

    has_bun_lock = (target_dir / "bun.lock").exists() or (target_dir / "bun.lockb").exists()
    cmd = [bun, "install"]
    if has_bun_lock:
        cmd.append("--frozen-lockfile")

    logger.info("[BOT] Installing dependencies with Bun in %s", target_dir)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        if result.returncode == 0:
            logger.info("[BOT] Dependencies installed successfully")
            return True

        if has_bun_lock and not _is_ci():
            logger.warning(
                "[BOT] Bun frozen lockfile install failed; retrying without --frozen-lockfile: %s",
                result.stderr,
            )
            retry = subprocess.run(
                [bun, "install"],
                cwd=str(target_dir),
                capture_output=True,
                text=True,
                timeout=300,
            )
            if retry.returncode == 0:
                logger.info("[BOT] Dependencies installed successfully")
                return True
            logger.error("[BOT] Dependency install failed: %s", retry.stderr)
            return False

        logger.error("[BOT] Dependency install failed: %s", result.stderr)
        return False
    except subprocess.TimeoutExpired:
        logger.error("[BOT] Dependency install timed out")
        return False
    except Exception as e:
        logger.error("[BOT] Dependency install error: %s", e)
        return False


class BotProcessManager:
    """Spawn, monitor, and restart the Node.js bot subprocess."""

    def __init__(self, bot_dir: Optional[Path] = None):
        self.bot_dir = bot_dir or BOT_DIR
        self._process: Optional[asyncio.subprocess.Process] = None
        self._log_lines: list[str] = []
        self._started_at: Optional[datetime] = None
        self._restart_task: Optional[asyncio.Task] = None
        self._reader_tasks: list[asyncio.Task] = []
        self._stopping = False

    # ── Public API ────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def status(self) -> dict:
        return {
            "running": self.is_running,
            "pid": self._process.pid if self._process else None,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "log_tail": self._log_lines[-20:],
        }

    async def start(self) -> bool:
        """Start the bot subprocess.  Returns True if launched."""
        if self.is_running:
            logger.info("[BOT] Already running (pid %s)", self._process.pid)
            return False

        # Ensure dependencies are installed in this manager's bot directory.
        loop = asyncio.get_running_loop()
        deps_ok = await loop.run_in_executor(None, lambda: ensure_bot_dependencies(self.bot_dir))
        if not deps_ok:
            logger.error("[BOT] Failed to install dependencies")
            return False

        bun_exe = self._find_bun()
        if bun_exe is None:
            logger.error("[BOT] Cannot find Bun — install Bun before starting the bot")
            return False

        entry = self.bot_dir / "src" / "index.ts"
        if not entry.exists():
            logger.error("[BOT] Entry point not found: %s", entry)
            return False

        env = {**os.environ}  # inherit current env (includes .env vars)

        # Build command: bun run start (bot/package.json start script)
        cmd = [bun_exe, "run", "start"]
        logger.info("[BOT] Starting bot process: %s", " ".join(cmd))
        self._log_lines.clear()
        self._stopping = False

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.bot_dir),
            env=env,
        )

        self._started_at = datetime.now(timezone.utc)
        self._append_log(f"[BOT] Started (pid {self._process.pid})")

        # Background readers for stdout / stderr
        self._reader_tasks = [
            asyncio.create_task(self._read_stream(self._process.stdout, "stdout")),
            asyncio.create_task(self._read_stream(self._process.stderr, "stderr")),
        ]

        # Monitor for unexpected exits
        asyncio.create_task(self._wait_for_exit())

        return True

    async def stop(self) -> bool:
        """Gracefully stop the bot.  Returns True if it was running."""
        if not self.is_running:
            return False

        self._stopping = True
        pid = self._process.pid
        self._append_log(f"[BOT] Stopping (pid {pid})...")

        try:
            self._process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(self._process.wait(), timeout=8)
            except asyncio.TimeoutError:
                logger.warning("[BOT] SIGTERM timed out — sending SIGKILL")
                self._process.kill()
                await self._process.wait()
        except ProcessLookupError:
            pass

        self._append_log(f"[BOT] Stopped (pid {pid})")
        self._cancel_readers()
        self._process = None
        return True

    async def restart(self) -> bool:
        """Stop then start.  Returns True on success."""
        self._append_log("[BOT] Restarting...")
        await self.stop()
        return await self.start()

    def schedule_restart(self) -> None:
        """Debounced restart — safe to call from sync code (e.g. channel save).

        Schedules a restart on the running event loop.  If called multiple
        times within _RESTART_DEBOUNCE_SECS, only the last one fires.
        """
        # Cancel any pending debounced restart
        if self._restart_task and not self._restart_task.done():
            self._restart_task.cancel()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("[BOT] No running event loop — cannot schedule restart")
            return

        self._restart_task = loop.create_task(self._debounced_restart())

    def get_logs(self, limit: int = 100) -> list[str]:
        return self._log_lines[-limit:]

    # ── Internals ─────────────────────────────────────────────────

    async def _debounced_restart(self) -> None:
        await asyncio.sleep(_RESTART_DEBOUNCE_SECS)
        logger.info("[BOT] Debounced restart firing")
        await self.restart()

    async def _read_stream(
        self,
        stream: Optional[asyncio.StreamReader],
        label: str,
    ) -> None:
        if stream is None:
            return
        try:
            async for raw_line in stream:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if line:
                    self._append_log(line)
                    # Forward to dashboard logger so it shows in console
                    logger.info("[BOT:%s] %s", label, line)
        except asyncio.CancelledError:
            pass

    async def _wait_for_exit(self) -> None:
        """Monitor the process; log unexpected crashes."""
        if self._process is None:
            return
        code = await self._process.wait()
        self._cancel_readers()
        if not self._stopping:
            self._append_log(f"[BOT] Process exited unexpectedly (code {code})")
            logger.warning("[BOT] Process exited with code %s", code)

    def _cancel_readers(self) -> None:
        for t in self._reader_tasks:
            if not t.done():
                t.cancel()
        self._reader_tasks.clear()

    def _append_log(self, line: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        entry = f"[{ts}] {line}"
        self._log_lines.append(entry)
        if len(self._log_lines) > _MAX_LOG_LINES:
            self._log_lines = self._log_lines[-_MAX_LOG_LINES:]

    def _find_bun(self) -> Optional[str]:
        """Locate the Bun executable used to run bot scripts."""
        return shutil.which("bun")
