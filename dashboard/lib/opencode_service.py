"""Single source of truth for managing the ``opencode serve`` subprocess.

The dashboard, the installer, and any auto-start daemon all go through
this module — there is exactly one place that knows how to start, stop,
restart, or inspect the opencode-serve process.

CLI usage (the installer's bash wrapper invokes this)::

    python -m dashboard.lib.opencode_service {start|stop|restart|status}

Python API (the dashboard's settings routes use this)::

    from dashboard.lib.opencode_service import restart_async
    restart_async()   # bounce on credential change, non-blocking

Responsibilities consolidated here (previously split across bash):
* Load ``.env`` + ``.env.sh`` from both ``~/.ostwin`` and the managed
  ``opencode_server`` project directory.
* Normalise Vertex env aliases (``GOOGLE_CLOUD_PROJECT`` ↔
  ``GOOGLE_VERTEX_PROJECT`` and ``VERTEX_LOCATION`` ↔
  ``GOOGLE_VERTEX_LOCATION``).
* Isolate the Google Cloud SDK fallback (``CLOUDSDK_CONFIG``).
* Generate opencode tool stubs into the project dir.
* Detect opencode-serve processes safely (by inspecting ``ps args=``)
  and never kill unrelated PIDs that happen to listen on the same port.
* Health-check ``/global/health`` with optional BasicAuth.
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

INSTALL_DIR = Path(os.environ.get("OSTWIN_HOME", str(Path.home() / ".ostwin")))
PID_FILE = INSTALL_DIR / "opencode.pid"
LOG_FILE = INSTALL_DIR / "logs" / "opencode-server.log"
SERVER_DIR = INSTALL_DIR / "opencode_server"
ENV_FILE = INSTALL_DIR / ".env"
ENV_SH_FILE = INSTALL_DIR / ".env.sh"

DEFAULT_BASE_URL = "http://127.0.0.1:4096"
OPENCODE_DISABLE_CLAUDE_CODE = "1"

# Serialize concurrent restarts so two credential changes can't race-spawn.
_restart_lock = threading.Lock()


# ── Process discovery ─────────────────────────────────────────────────


def _read_pid() -> Optional[int]:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _ps_args(pid: int) -> str:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    return result.stdout.strip()


def _is_opencode_serve_process(pid: int) -> bool:
    """True iff PID's command line invokes ``opencode serve``.

    Mirrors the bash ``_is_opencode_serve_process`` helper so we never
    SIGTERM an unrelated process (SSH tunnel, dev server, etc.) that
    happens to listen on the configured port.
    """
    args = _ps_args(pid)
    return "opencode" in args and "serve" in args


def _opencode_listen_pids(port: int) -> list[int]:
    """Return PIDs holding ``LISTEN`` on ``port`` via ``lsof``."""
    try:
        result = subprocess.run(
            ["lsof", f"-tiTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    pids: list[int] = []
    for token in result.stdout.split():
        try:
            pids.append(int(token.strip()))
        except ValueError:
            continue
    return pids


def _host_port() -> Tuple[str, int]:
    url = os.environ.get("OPENCODE_BASE_URL", DEFAULT_BASE_URL)
    parsed = urlparse(url)
    return parsed.hostname or "127.0.0.1", parsed.port or 4096


# ── Env composition ───────────────────────────────────────────────────


def _candidate_env_files(project_dir: Path) -> list[Path]:
    """Files loaded in order; later entries override earlier ones."""
    return [
        ENV_FILE,
        ENV_SH_FILE,
        project_dir / ".env",
        project_dir / ".env.sh",
        project_dir / ".agents" / ".env",
        project_dir / ".agents" / ".env.sh",
    ]


def _load_env_via_bash(project_dir: Path) -> dict[str, str]:
    """Source all candidate env files in bash and capture the resulting env.

    Using bash is intentional: ``.env.sh`` files may contain shell logic
    (conditionals, ``export`` statements, command substitution) that a
    pure-Python parser cannot evaluate safely.  Plain ``KEY=value``
    ``.env`` files also work because we use ``set -a`` so unprefixed
    assignments still get exported.
    """
    parts = ["set -a"]
    for f in _candidate_env_files(project_dir):
        if f.exists():
            parts.append(f"source {shlex.quote(str(f))} 2>/dev/null || true")
    parts.append("env -0")
    script = "; ".join(parts)

    # Start the bash subshell with the parent's env so existing values
    # survive even when no file overrides them.
    try:
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.warning("[OPENCODE_SERVICE] bash env load failed: %s", exc)
        return dict(os.environ)

    env: dict[str, str] = {}
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        try:
            decoded = record.decode("utf-8")
        except UnicodeDecodeError:
            continue
        key, _, value = decoded.partition("=")
        if key:
            env[key] = value
    return env or dict(os.environ)


def _normalize_vertex_aliases(env: dict[str, str]) -> None:
    """Mirror GOOGLE_CLOUD_PROJECT ↔ GOOGLE_VERTEX_PROJECT and locations."""
    pairs = (
        ("GOOGLE_CLOUD_PROJECT", "GOOGLE_VERTEX_PROJECT"),
        ("VERTEX_LOCATION", "GOOGLE_VERTEX_LOCATION"),
    )
    for a, b in pairs:
        va, vb = env.get(a), env.get(b)
        if va and not vb:
            env[b] = va
        elif vb and not va:
            env[a] = vb


def _isolate_cloudsdk_fallback(env: dict[str, str]) -> None:
    """Point CLOUDSDK_CONFIG at an empty dir.

    Without this, the Google SDKs used by opencode-serve fall back to
    the host's ``~/.config/gcloud`` and may pick up an unrelated account.
    """
    isolated = INSTALL_DIR / "google" / "empty-sdk-config"
    try:
        isolated.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.debug("[OPENCODE_SERVICE] could not create %s: %s", isolated, exc)
        return
    env["CLOUDSDK_CONFIG"] = str(isolated)


def _build_child_env(project_dir: Path) -> dict[str, str]:
    env = _load_env_via_bash(project_dir)
    _normalize_vertex_aliases(env)
    _isolate_cloudsdk_fallback(env)
    env["OSTWIN_PROJECT_DIR"] = str(project_dir)
    # Always disable Claude Code skill loading for every opencode child process.
    # This is intentionally forced after loading user env files so local overrides
    # cannot re-enable Claude Code skills for the managed runtime.
    env["OPENCODE_DISABLE_CLAUDE_CODE"] = OPENCODE_DISABLE_CLAUDE_CODE
    return env


# ── Tool generation ───────────────────────────────────────────────────


def _generate_opencode_tools(env: dict[str, str], project_dir: Path) -> None:
    """Best-effort generation of the opencode tool stubs into ``project_dir``."""
    venv_py = INSTALL_DIR / ".venv" / "bin" / "python"
    py = str(venv_py) if venv_py.exists() else shutil.which("python3")
    if not py:
        logger.debug("[OPENCODE_SERVICE] no python interpreter; skipping tool gen")
        return
    try:
        subprocess.run(
            [
                py,
                "-m",
                "dashboard.opencode_tools",
                "--project-root",
                str(project_dir),
                "--dashboard-port",
                env.get("DASHBOARD_PORT", "3366"),
            ],
            env=env,
            cwd=str(project_dir),
            timeout=30,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("[OPENCODE_SERVICE] tool generation skipped: %s", exc)


# ── Public API ────────────────────────────────────────────────────────


def stop(timeout: float = 3.0) -> bool:
    """Stop the running opencode-serve, if any.

    Returns True when a process was stopped, False otherwise.  Also
    sweeps any *other* opencode-serve processes listening on the
    configured port (e.g. orphaned by a previous crash).  Never touches
    a PID whose command line is not ``opencode serve``.
    """
    stopped_any = False
    host, port = _host_port()

    targets: set[int] = set()
    pid = _read_pid()
    if pid is not None and _is_alive(pid):
        targets.add(pid)
    for p in _opencode_listen_pids(port):
        if _is_opencode_serve_process(p):
            targets.add(p)

    for target in targets:
        if not _is_opencode_serve_process(target):
            continue
        try:
            os.killpg(os.getpgid(target), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(target, signal.SIGTERM)
            except ProcessLookupError:
                continue

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and _is_alive(target):
            time.sleep(0.1)

        if _is_alive(target):
            try:
                os.killpg(os.getpgid(target), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    os.kill(target, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        stopped_any = True
        logger.info("[OPENCODE_SERVICE] Stopped opencode-serve PID=%s", target)

    if PID_FILE.exists():
        try:
            PID_FILE.unlink()
        except OSError:
            pass

    return stopped_any


def start() -> Optional[int]:
    """Spawn ``opencode serve`` with a freshly-composed env.

    Returns the new PID, or ``None`` if opencode is not installed or
    the subprocess could not be launched.  Caller is responsible for
    calling :func:`stop` first if a previous instance may be running;
    use :func:`restart` to do both atomically.
    """
    if not shutil.which("opencode"):
        logger.warning("[OPENCODE_SERVICE] opencode CLI not on PATH — skipping start")
        return None

    SERVER_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    host, port = _host_port()
    env = _build_child_env(SERVER_DIR)

    _generate_opencode_tools(env, SERVER_DIR)

    log_handle = open(LOG_FILE, "a")
    try:
        proc = subprocess.Popen(
            ["opencode", "serve", "--hostname", host, "--port", str(port)],
            cwd=str(SERVER_DIR),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except (OSError, ValueError) as exc:
        log_handle.close()
        logger.error("[OPENCODE_SERVICE] failed to spawn opencode serve: %s", exc)
        return None
    finally:
        log_handle.close()

    PID_FILE.write_text(str(proc.pid))
    logger.info(
        "[OPENCODE_SERVICE] Started opencode-serve PID=%s on %s:%s",
        proc.pid,
        host,
        port,
    )
    return proc.pid


def wait_for_health(timeout: float = 30.0) -> bool:
    """Poll ``/global/health`` until opencode-serve answers or ``timeout``."""
    import httpx

    host, port = _host_port()
    url = f"http://{host}:{port}/global/health"
    auth = None
    pwd = os.environ.get("OPENCODE_SERVER_PASSWORD")
    if pwd:
        user = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
        auth = httpx.BasicAuth(user, pwd)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with httpx.Client(timeout=2.0, auth=auth) as client:
                resp = client.get(url)
                if resp.status_code < 500:
                    return True
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    return False


def restart(*, health_timeout: float = 30.0) -> Optional[int]:
    """Stop + start, blocking until the new process is healthy."""
    with _restart_lock:
        stop()
        pid = start()
        if pid is None:
            return None
        if not wait_for_health(timeout=health_timeout):
            logger.warning(
                "[OPENCODE_SERVICE] opencode-serve did not become healthy within %.0fs",
                health_timeout,
            )
        # Reset cached SDK client so the next chat reconnects.
        try:
            from dashboard.master_agent import reset_master_client

            reset_master_client()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[OPENCODE_SERVICE] reset_master_client failed: %s", exc)
        return pid


def restart_async() -> None:
    """Fire-and-forget restart on a background daemon thread.

    Used from HTTP request handlers — the user's request returns
    immediately while opencode-serve bounces in the background.
    """

    def _runner() -> None:
        try:
            restart()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[OPENCODE_SERVICE] background restart failed: %s", exc)

    threading.Thread(target=_runner, name="opencode-restart", daemon=True).start()


def status() -> dict:
    """Return a summary of the current opencode-serve state."""
    host, port = _host_port()
    pid = _read_pid()
    alive = bool(pid and _is_alive(pid))
    return {
        "pid": pid,
        "alive": alive,
        "is_opencode_serve": alive and _is_opencode_serve_process(pid) if pid else False,
        "host": host,
        "port": port,
        "log_file": str(LOG_FILE),
    }


# ── CLI ───────────────────────────────────────────────────────────────


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="opencode_service")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("start", help="Spawn opencode serve (blocks on health check)")
    sub.add_parser("stop", help="Stop the running opencode-serve")
    sub.add_parser("restart", help="Stop + start with a fresh env")
    sub.add_parser("status", help="Print the current state")

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.cmd == "start":
        pid = start()
        if pid is None:
            return 1
        return 0 if wait_for_health(timeout=30.0) else 1

    if args.cmd == "stop":
        return 0 if stop() else 0  # idempotent: missing is not an error

    if args.cmd == "restart":
        return 0 if restart(health_timeout=30.0) else 1

    if args.cmd == "status":
        info = status()
        for k, v in info.items():
            print(f"{k}: {v}")
        return 0 if info["alive"] else 1

    return 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
