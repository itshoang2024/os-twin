import os
import sys
import multiprocessing

# ── macOS fork safety — MUST run before ANY C extension loads ──
# Without this, Python's default `fork` start method triggers
# "MallocStackLogging: can't turn off malloc stack logging" on macOS
# when multiprocessing spawns child processes after tokenizers/PyTorch
# have initialised background threads (common during graph extraction).
os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
try:
    multiprocessing.set_start_method("spawn", force=True)
except RuntimeError:
    pass  # Already set by another module

import asyncio
import time
import json
import uvicorn
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# ── Load ~/.ostwin/.env early ──
# This makes the dashboard self-contained: it works whether started via
# `ostwin dashboard` (which already sources .env) or directly via `python api.py`.
# NOTE: This is a one-time bootstrap load.  For live hot-reload when the
# .env file is edited at runtime, see dashboard/env_watcher.py which is
# started as an async task in startup_all().
_env_file = Path.home() / ".ostwin" / ".env"
if _env_file.is_file():
    try:
        from dotenv import load_dotenv

        load_dotenv(_env_file, override=False)
    except ImportError:
        # Manual fallback — only set vars not already in the environment
        with _env_file.open() as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line or _line.startswith("#"):
                    continue
                if "=" in _line:
                    _k, _, _v = _line.partition("=")
                    _k = _k.strip()
                    _v = _v.strip().strip("\"'")
                    if _k and _k not in os.environ:
                        os.environ[_k] = _v

# Add the project root and dashboard dir to sys.path
_dashboard_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_dashboard_dir)
if _root not in sys.path:
    sys.path.insert(0, _root)
if _dashboard_dir not in sys.path:
    sys.path.insert(0, _dashboard_dir)

from dashboard.api_utils import (
    PROJECT_ROOT,
    WARROOMS_DIR,
    USE_FE,
    FE_OUT_DIR,
)
from dashboard.frontend_fallback import resolve_frontend_file
from dashboard.tasks import startup_all

# --- Route Imports ---
# Heavy libraries (torch, langchain) are now lazy-loaded inside these routes
# so direct imports here translate to < 2s total dashboard boot time.
from dashboard.routes import (
    ai, agent_costs, auth, system, mcp, threads, plans, rooms, skills,
    roles, memory, amem, channels, command, tunnel,
    files, settings, engagement, knowledge, memory_mcp, chat
)

# Configure logging — file + console
# All dashboard logs are written to ~/.ostwin/dashboard/debug.log (DEBUG level)
# Console output stays at INFO to keep the terminal clean.
_log_dir = Path.home() / ".ostwin" / "dashboard"
_log_dir.mkdir(parents=True, exist_ok=True)
_log_file = _log_dir / "debug.log"

from logging.handlers import RotatingFileHandler

_file_handler = RotatingFileHandler(
    str(_log_file), maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s")
)

_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(
    logging.Formatter("%(levelname)-8s  %(name)s  %(message)s")
)

# Attach handlers directly — basicConfig is a no-op if any import already
# triggered default logging configuration before this line.
_root = logging.getLogger()
_root.setLevel(logging.INFO)
# Silence noisy httpx/httpcore request logging (connection pools, redirects, etc.)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
if _file_handler not in _root.handlers:
    _root.addHandler(_file_handler)
if _console_handler not in _root.handlers:
    _root.addHandler(_console_handler)

logger = logging.getLogger(__name__)
logger.info("Dashboard log file: %s", _log_file)

# --- App + lifespan ----------------------------------------------------
is_dev = (
    os.environ.get("NODE_ENV") == "development"
    or os.environ.get("OSTWIN_DEV_MODE") == "1"
)

# We need to drive the FastMCP streamable-HTTP app's lifespan from the
# parent FastAPI app, otherwise the FastMCP session manager's task group
# never starts and the first POST to /api/knowledge/mcp/* dies with
# ``RuntimeError: Task group is not initialized. Make sure to use run().``
#
# FastAPI/Starlette do NOT propagate lifespans to mounted sub-apps, so we
# wire it in explicitly here. The MCP app reference is filled in further
# down (after we mount it) via ``_register_mcp_lifespan()``.
_mcp_lifespan_app: "object | None" = None


def _register_mcp_lifespan(mcp_app) -> None:
    """Called from the MCP mount block to hand the app to the lifespan ctx."""
    global _mcp_lifespan_app
    _mcp_lifespan_app = mcp_app


@asynccontextmanager
async def app_lifespan(_app):
    # --- Startup ---
    # Install the dedicated heavy-ops thread pool as the default executor
    # so asyncio.to_thread() routes CPU/IO-heavy work here instead of the
    # tiny default pool. Must happen after the event loop is running.
    loop = asyncio.get_running_loop()
    loop.set_default_executor(_heavy_executor)
    logger.info("Heavy-ops thread pool installed (size=%d)", _HEAVY_POOL_SIZE)

    # Migrated from the legacy @app.on_event("startup") handler. Using
    # create_task so the lifecycle doesn't block the server from accepting
    # connections.
    # Load the persisted master model but do NOT initialize the OpenCode client yet.
    # The client will be lazily initialized on the first brainstorm or chat call.
    try:
        from dashboard.master_agent import load_persisted_master_model

        load_persisted_master_model()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load persisted master model: %s", exc)

    asyncio.create_task(startup_all())
    
    # Start knowledge service background tasks (retention sweeper)
    try:
        from dashboard.routes.knowledge import _get_service
        service = _get_service()
        service.start_background()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to start knowledge background services: %s", exc)

    # Start Memory Pool MCP session manager (Plan 007)
    try:
        from dashboard.routes.memory_mcp import startup_knowledge as _start_pool
        await _start_pool()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to start memory pool MCP: %s", exc)

    # Drive the FastMCP app's own lifespan inside ours so its
    # ``session_manager.run()`` initialises the task group. Without this,
    # the first POST to /api/knowledge/mcp/* dies with "Task group is not initialized".
    #
    # IMPORTANT: ``StreamableHTTPSessionManager`` is single-use — it
    # raises ``RuntimeError`` on a second ``run()`` call. In production
    # the lifespan runs exactly once per process and the singleton is
    # fine. In tests, multiple ``TestClient(app)`` contexts re-enter our
    # lifespan and would crash on the second entry. We handle both:
    #
    #   1. Reset the spent session manager (no-op if not yet created).
    #   2. Re-resolve the FastMCP ASGI app so the next mount uses a fresh
    #      session manager bound to the new task group.
    #   3. Re-mount the fresh inner app onto the parent so dispatch keeps
    #      working through the rest of this lifespan window.
    if _mcp_lifespan_app is not None:
        try:
            from dashboard.knowledge.mcp_server import (  # noqa: WPS433
                get_mcp_app,
                reset_mcp_session_manager,
            )

            reset_mcp_session_manager()
            fresh_mcp_app = get_mcp_app()
            _replace_mounted_mcp_app(_app, fresh_mcp_app)
        except Exception as _exc:  # noqa: BLE001
            logger.warning("MCP lifespan refresh failed: %s", _exc)
            fresh_mcp_app = _mcp_lifespan_app

        async with fresh_mcp_app.router.lifespan_context(fresh_mcp_app):
            try:
                yield
            finally:
                await _shutdown_app()
    else:
        # MCP mount failed (logged at mount time); still drive shutdown.
        try:
            yield
        finally:
            await _shutdown_app()


def _replace_mounted_mcp_app(parent_app, fresh_mcp_app) -> None:
    """Swap the inner FastMCP ASGI app on the existing /api/knowledge/mcp mount.

    The parent FastAPI app's mount routes hold a reference to whatever was
    passed to ``app.mount(...)`` at startup. When we recreate the FastMCP
    app for a new lifespan, we need the existing mount to point at the new
    instance so request dispatch keeps working.

    The wrapped (auth) variant uses a Starlette wrapper containing
    ``Mount("/", app=_mcp_app)`` — so we walk into the wrapper to swap
    its inner mount as well.
    """
    from starlette.routing import Mount

    for route in parent_app.router.routes:
        if isinstance(route, Mount) and route.path == "/api/knowledge/mcp":
            existing = route.app
            # Direct mount (dev mode, no auth) — replace and we're done.
            if hasattr(existing, "router") and any(
                isinstance(r, Mount)
                for r in getattr(existing.router, "routes", [])
            ):
                # Wrapped variant: existing is a Starlette() with a
                # Mount("/", app=_mcp_app) inside.
                for inner in existing.router.routes:
                    if isinstance(inner, Mount) and inner.path == "":
                        inner.app = fresh_mcp_app
                        return
            # Plain direct mount.
            route.app = fresh_mcp_app
            return


async def _shutdown_app() -> None:
    """Shutdown logic — migrated from the legacy on_event("shutdown") handler."""
    from dashboard.tunnel import stop_tunnel

    stop_tunnel()

    # Stop the bot process if it was started.
    import dashboard.global_state as gs

    if gs.bot_manager and gs.bot_manager.is_running:
        await gs.bot_manager.stop()
    
    # Shutdown knowledge service (stop retention sweeper, release caches)
    try:
        from dashboard.routes.knowledge import _get_service
        service = _get_service()
        service.shutdown()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to shutdown knowledge service: %s", exc)

    # Shutdown Memory Pool MCP (Plan 007)
    try:
        from dashboard.routes.memory_mcp import shutdown_knowledge as _stop_pool
        await _stop_pool()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to shutdown memory pool MCP: %s", exc)


app = FastAPI(
    title="OS Twin Command Center", 
    version="0.1.0", 
    lifespan=app_lifespan,
    debug=is_dev
)

# --- WebSocket ---
from fastapi import WebSocket, WebSocketDisconnect
from dashboard.ws_router import manager


@app.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_json({"event": "connected", "timestamp": "now"})
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    import time

                    await websocket.send_json(
                        {
                            "type": "pong",
                            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        }
                    )
            except Exception:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)


# --- Middleware ---
# SECURITY: Restrict CORS in production to same-origin only.
# In dev mode, allow localhost origins for the Next.js dev server.
# Never use allow_origins=["*"] in production — it allows any website
# to make authenticated cross-origin requests to the API.
_cors_origins = (
    []  # Dev: empty list means use origin_regex instead
    if is_dev
    else []  # Production: no explicit origins; rely on same-origin via proxy
)
_cors_origin_regex = (
    r"https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    if is_dev
    else None  # Production: no cross-origin access
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex,
    allow_credentials=is_dev,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
)

# --- Performance: Dedicated thread pool for CPU/IO-heavy operations --------
# The default asyncio executor has limited threads (min(32, cpu+4)).
# Knowledge/memory operations (embedding, graph queries, LLM calls, file I/O)
# are both CPU-bound and IO-bound. A larger dedicated pool prevents saturation
# that would block the event loop and starve other request handlers.
_HEAVY_POOL_SIZE = int(os.environ.get("OSTWIN_HEAVY_POOL_SIZE", "16"))
_heavy_executor = ThreadPoolExecutor(
    max_workers=_HEAVY_POOL_SIZE,
    thread_name_prefix="heavy-ops",
)
# The executor is installed as the default in app_lifespan() after the
# event loop starts. We cannot call asyncio.get_event_loop() here at
# module-import time because no loop exists yet.


# P1-10: Rate limiter disabled by default.
# To enable, set RATE_LIMIT_ENABLED=1 (e.g., 100 requests per window).
_RATE_LIMIT_ENABLED = os.environ.get("RATE_LIMIT_ENABLED", "").lower() in ("1", "true", "yes")
_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 100

if _RATE_LIMIT_ENABLED:
    from collections import defaultdict
    _rate_limit_store: dict[str, list[float]] = defaultdict(list)

    @app.middleware("http")
    async def rate_limit_middleware(request, call_next):
        """Rate limiting middleware — blocks IPs exceeding request threshold."""
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        _rate_limit_store[client_ip] = [
            t for t in _rate_limit_store[client_ip] if now - t < _RATE_LIMIT_WINDOW
        ]
        if len(_rate_limit_store[client_ip]) >= _RATE_LIMIT_MAX:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please try again later."},
            )
        _rate_limit_store[client_ip].append(now)
        response = await call_next(request)
        return response


# --- Request Timeout Middleware -----------------------------------------------
# Prevents a single hung LLM/embedding call from occupying a handler forever.
# Default: 120 seconds (enough for long imports, but prevents infinite hangs).
# Set to 0 to disable.
_REQUEST_TIMEOUT_S = int(os.environ.get("OSTWIN_REQUEST_TIMEOUT_S", "120"))


@app.middleware("http")
async def request_timeout_middleware(request: Request, call_next):
    """Enforce a per-request timeout to prevent indefinite hangs.

    Long-running operations (knowledge import, embedding, LLM calls) should
    run in thread executors so they don't block the event loop. This middleware
    is a safety net that returns 504 if a handler exceeds the timeout.

    Set OSTWIN_REQUEST_TIMEOUT_S=0 to disable.
    """
    if _REQUEST_TIMEOUT_S <= 0:
        return await call_next(request)
    try:
        return await asyncio.wait_for(call_next(request), timeout=_REQUEST_TIMEOUT_S)
    except asyncio.TimeoutError:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=504,
            content={"detail": f"Request timed out after {_REQUEST_TIMEOUT_S}s"},
        )


# --- Concurrency Limiter Middleware -------------------------------------------
# Limits in-flight heavy requests to prevent resource exhaustion under load.
# When the limit is reached, new requests get 503 immediately rather than
# queuing and consuming memory.
_MAX_CONCURRENT_REQUESTS = int(os.environ.get("OSTWIN_MAX_CONCURRENT", "50"))
_concurrency_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)


@app.middleware("http")
async def concurrency_limit_middleware(request: Request, call_next):
    """Limit concurrent in-flight requests to prevent resource exhaustion."""
    # Skip lightweight endpoints (health checks, static assets)
    path = request.url.path
    if path.startswith("/_next") or path in ("/api/health", "/api/ws"):
        return await call_next(request)

    if _concurrency_semaphore.locked():
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"detail": "Server is at capacity. Please retry later."},
        )
    async with _concurrency_semaphore:
        return await call_next(request)

# --- Routes ---
# (removed importlib logic for ws_router)
app.include_router(auth.router)
app.include_router(engagement.router)
app.include_router(threads.router)
app.include_router(plans.router)
app.include_router(rooms.router)
app.include_router(system.router)
app.include_router(mcp.router)
app.include_router(skills.router)
app.include_router(roles.router)
app.include_router(memory.router)
app.include_router(amem.router)
app.include_router(channels.router)
app.include_router(command.router)
app.include_router(tunnel.router)
app.include_router(files.router)
app.include_router(settings.router)
app.include_router(knowledge.router)  # EPIC-001: /api/knowledge/* REST API
app.include_router(ai.router)         # Plan 006: /api/ai/* unified gateway
app.include_router(agent_costs.router) # Plan 015: /api/ai/agent-costs
app.include_router(chat.router)         # /api/chat — OpenCode session-backed chat

# --- MCP endpoint (knowledge) -------------------------------------------
# Mounted as a sub-app at /api/knowledge/mcp via FastMCP's streamable-HTTP
# transport. The /api/knowledge prefix keeps the MCP endpoint inside the
# REST API namespace, freeing the bare /mcp path for the frontend SPA page
# (the MCP server registry UI at fe/src/app/mcp/page.tsx).
# Lazy: importing dashboard.knowledge.mcp_server does NOT pull kuzu / zvec /
# anthropic — those load on the first tool call.
# Auth: when OSTWIN_API_KEY is set AND OSTWIN_DEV_MODE != "1", a Starlette
# middleware enforces ``Authorization: Bearer <key>``. Otherwise (dev mode,
# or no key configured) anonymous access is allowed — the MCP transport's
# own JSON-RPC handshake still validates message structure.
try:
    from dashboard.knowledge.mcp_server import get_mcp_app

    _mcp_app = get_mcp_app()

    # Register the inner FastMCP app so app_lifespan() can drive its
    # ``session_manager.run()`` lifecycle. This is the fix for the
    # "Task group is not initialized" RuntimeError. The auth wrapper below
    # is transparent to the lifespan — only the inner app has the
    # FastMCP-specific lifespan_context.
    _register_mcp_lifespan(_mcp_app)

    if (
        os.environ.get("OSTWIN_DEV_MODE") != "1"
        and os.environ.get("OSTWIN_API_KEY")
    ):
        from starlette.applications import Starlette
        from starlette.middleware import Middleware
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse
        from starlette.routing import Mount

        _expected_token = f"Bearer {os.environ.get('OSTWIN_API_KEY')}"

        class _MCPBearerAuth(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):  # type: ignore[override]
                if request.headers.get("authorization") != _expected_token:
                    return JSONResponse(
                        {"error": "unauthorized", "code": "UNAUTHORIZED"},
                        status_code=401,
                    )
                return await call_next(request)

        wrapped_mcp = Starlette(
            routes=[Mount("/", app=_mcp_app)],
            middleware=[Middleware(_MCPBearerAuth)],
        )
        app.mount("/api/knowledge/mcp", wrapped_mcp)
        logger.info("Knowledge MCP server mounted at /api/knowledge/mcp (auth required)")
    else:
        app.mount("/api/knowledge/mcp", _mcp_app)
        if os.environ.get("OSTWIN_DEV_MODE") == "1":
            _port = os.environ.get("DASHBOARD_PORT", "3366")
            logger.info(
                "Knowledge MCP server live at http://localhost:%s/api/knowledge/mcp (dev mode, no auth)",
                _port,
            )
        else:
            logger.info(
                "Knowledge MCP server mounted at /api/knowledge/mcp (no auth — OSTWIN_API_KEY unset)"
            )
except Exception as _mcp_exc:
    logger.warning("Failed to mount knowledge MCP server: %s", _mcp_exc)

# --- Memory Pool MCP over Streamable HTTP (Plan 007) ---
# Mount before the static frontend catch-all so /api/memory-pool/* is handled
# by the MCP ASGI app, not the SPA fallback.
app.mount("/api/memory-pool", memory_mcp.knowledge_mcp_app)

# --- Static Frontend Serving ---
# Hybrid approach:
#   1. StaticFiles for /_next (JS/CSS/media assets — fast, cacheable)
#   2. Catch-all route for HTML pages with SPA fallback
#      (handles unknown plan IDs not pre-rendered at build time)
from fastapi.responses import FileResponse

if USE_FE:
    if (FE_OUT_DIR / "_next").exists():
        app.mount(
            "/_next",
            StaticFiles(directory=str(FE_OUT_DIR / "_next")),
            name="fe_next_static",
        )

    @app.api_route("/", methods=["GET", "HEAD"])
    async def fe_index():
        return FileResponse(str(FE_OUT_DIR / "index.html"))

    @app.api_route("/{path:path}", methods=["GET", "HEAD"])
    async def fe_catch_all(path: str):
        # Never serve SPA HTML for /api/* paths — let those routes/mounts
        # handle them. The knowledge MCP server is mounted at
        # /api/knowledge/mcp which is already covered by this prefix check,
        # so the bare /mcp path is free to be served as the frontend SPA
        # page (the MCP server registry UI).
        if path.startswith("api/"):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail=f"Route not found: /{path}")
        return FileResponse(str(resolve_frontend_file(FE_OUT_DIR, path)))


# --- Lifecycle ---
# NOTE: The legacy @app.on_event("startup") and @app.on_event("shutdown")
# handlers were migrated into ``app_lifespan`` (above) when we switched to
# the lifespan= constructor arg. FastAPI ignores on_event handlers when a
# lifespan context manager is passed to the FastAPI() constructor.


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ostwin Dashboard")
    parser.add_argument("--port", type=int, default=3366, help="Port to listen on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument(
        "--project-dir", default=None, help="Project directory to monitor"
    )
    parser.add_argument(
        "--reindex", action="store_true", help="Force full re-index of vector store"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.environ.get("OSTWIN_WORKERS", "1")),
        help="Number of uvicorn worker processes (default: 1, env: OSTWIN_WORKERS)",
    )
    args = parser.parse_args()

    if args.project_dir:
        os.environ["OSTWIN_PROJECT_DIR"] = os.path.abspath(args.project_dir)
        # We need to manually update these for the print statements since they were imported early
        PROJECT_ROOT = Path(args.project_dir)
        WARROOMS_DIR = PROJECT_ROOT / ".war-rooms"

    if args.reindex:
        os.environ["OSTWIN_REINDEX"] = "true"

    os.environ.setdefault("DASHBOARD_PORT", str(args.port))

    print("⬡ OS Twin Command Center (Modular)")
    print(f"  Project:   {args.project_dir or PROJECT_ROOT}")
    print(f"  War-rooms: {WARROOMS_DIR}")
    print(f"  Workers:   {args.workers}")
    print(f"  Heavy pool: {_HEAVY_POOL_SIZE} threads")
    print(f"  Timeout:   {_REQUEST_TIMEOUT_S}s")
    print(f"  Max concurrent: {_MAX_CONCURRENT_REQUESTS}")

    # --- Debug / Reload logic for PyCharm ---
    # log_level = "debug" if we are in dev mode OR a debugger is attached
    log_level = "info"
    if is_dev or sys.gettrace() is not None:
        log_level = "debug"

    # Hot reload is great for dev, but bad for PyCharm Debugger (spawns workers)
    # We only enable it if in dev mode AND no debugger is attached.
    use_reload = is_dev and sys.gettrace() is None

    # Multi-worker mode: use gunicorn-style prefork for production scaling.
    # Workers > 1 requires the import-string form so uvicorn can fork.
    # Note: with >1 worker, in-memory state (rate limits, semaphores) is
    # per-process. For shared state, use Redis or an external store.
    if args.workers > 1 and not use_reload:
        uvicorn.run(
            "api:app",
            host=args.host,
            port=args.port,
            workers=args.workers,
            log_level=log_level,
            timeout_keep_alive=30,  # Close idle connections after 30s
            limit_concurrency=_MAX_CONCURRENT_REQUESTS,
        )
    elif use_reload:
        # Use import string for reload support
        uvicorn.run("api:app", host=args.host, port=args.port, reload=True, log_level=log_level)
    else:
        # Use app object for direct process debugging (best for PyCharm)
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level=log_level,
            timeout_keep_alive=30,
        )
