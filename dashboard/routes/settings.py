"""
Settings API Routes -- Unified settings management with event broadcasting.

All endpoints are protected by get_current_user.
Mutation endpoints broadcast 'settings_updated' events via Broadcaster.
Vault endpoints NEVER return secret values, only is_set status.
"""

import json
import logging
import os
import sys
import subprocess
from pathlib import Path as FSPath
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query, Body, Path, Request, Response
from pydantic import BaseModel, ValidationError

import base64
from dashboard.auth import get_current_user
from dashboard.global_state import broadcaster
import dashboard.global_state as global_state
from dashboard.models import MasterSettings, EffectiveResolution, KnowledgeSettings
from dashboard.lib.settings import get_settings_resolver
from dashboard.lib.settings.vault import get_vault
from dashboard.lib.settings.opencode_sync import sync_opencode_config, SyncResult
from dashboard.lib.settings.google_oauth import (
    start_oauth,
    exchange_code,
    get_oauth_status,
    OAuthSession,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ── Request / Response Models ──────────────────────────────────────────


class VaultValueRequest(BaseModel):
    value: str


class VaultStatusResponse(BaseModel):
    is_set: bool


class VaultScopeResponse(BaseModel):
    keys: Dict[str, VaultStatusResponse]


class VaultInfoResponse(BaseModel):
    """Exposes which vault backend is active and its health."""

    backend: str
    healthy: bool
    message: str
    details: Dict[str, str]


class TargetSyncDetail(BaseModel):
    """Per-target detail (opencode.json or auth.json)."""

    synced: List[str] = []
    removed: List[str] = []
    skipped: List[str] = []
    path: str = ""
    error: Optional[str] = None


class OpenCodeSyncResponse(BaseModel):
    """Result of syncing provider keys to opencode.json + auth.json."""

    synced: List[str]
    removed: List[str]
    skipped: List[str]
    path: str
    error: Optional[str] = None
    opencode_json: Optional[TargetSyncDetail] = None
    auth_json: Optional[TargetSyncDetail] = None


# ── Read Endpoints ─────────────────────────────────────────────────────


@router.get("", response_model=MasterSettings)
async def get_master_settings(
    user: dict = Depends(get_current_user),
):
    """Get master settings with vault refs preserved as ${vault:...} strings.

    Never dereferences vault refs.  Returns the raw config structure.
    """
    resolver = get_settings_resolver()
    print("Resolver.get_master_settings():", resolver.get_master_settings())
    return resolver.get_master_settings()


@router.get("/effective", response_model=EffectiveResolution)
async def get_effective_settings(
    role: str = Query(..., description="Role to resolve settings for"),
    plan_id: Optional[str] = Query(None, description="Plan ID for plan-level override"),
    task_ref: Optional[str] = Query(None, description="Task ref for room-level override"),
    user: dict = Depends(get_current_user),
):
    """Get effective settings for a role with provenance.

    Resolves vault refs but masks secrets as ***.
    """
    resolver = get_settings_resolver()
    return resolver.resolve_role(
        role,
        plan_id=plan_id,
        task_ref=task_ref,
        masked=True,
    )


@router.get("/schema")
async def get_settings_schema(
    user: dict = Depends(get_current_user),
):
    """Get JSON schema for MasterSettings (for dynamic frontend forms)."""
    return MasterSettings.model_json_schema()


# ── Master Agent Model ────────────────────────────────────────────────
# These routes must be defined BEFORE PUT /{namespace} to avoid being shadowed
# by the wildcard route.


class MasterModelRequest(BaseModel):
    model: str
    provider: Optional[str] = None


class MasterModelResponse(BaseModel):
    model: str
    provider: Optional[str] = None


@router.get("/master-model", response_model=MasterModelResponse)
async def get_master_model(
    user: dict = Depends(get_current_user),
):
    """Get the current master agent model configuration."""
    from dashboard.master_agent import get_master_config

    config = get_master_config()
    return MasterModelResponse(model=config.model, provider=config.provider)


@router.put("/master-model", response_model=MasterModelResponse)
async def set_master_model(
    request: MasterModelRequest,
    user: dict = Depends(get_current_user),
):
    """Set the master agent model configuration.

    Persists the choice to ``.agents/config.json`` under
    ``runtime.master_agent_model`` (combined ``provider/model`` format, which
    ``set_master_model`` re-parses on next startup) so the selection survives
    a dashboard restart.
    """
    from dashboard.master_agent import (
        format_master_model,
        get_master_config,
        set_master_model as _set_model,
    )

    _set_model(request.model, request.provider)
    config = get_master_config()

    # Persist via the shared SettingsResolver so the value re-appears after a
    # process restart. Use the canonical "provider/model" form when a provider
    # is known, otherwise the bare model id -- both shapes are accepted by
    # set_master_model() on the load side.
    persisted_value = format_master_model(config.model, config.provider)
    try:
        get_settings_resolver().patch_namespace(
            "runtime", {"master_agent_model": persisted_value}
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SETTINGS] Failed to persist master_agent_model: %s", exc)

    return MasterModelResponse(model=config.model, provider=config.provider)


# ── Mutation Endpoints ─────────────────────────────────────────────────

_VALID_NAMESPACES = frozenset(
    {
        "providers",
        "roles",
        "runtime",
        "memory",
        "channels",
        "autonomy",
        "observability",
        "knowledge",
    }
)


# ── Typed Knowledge Settings (ADR-15) ──────────────────────────────────
#
# Defined BEFORE the generic ``PUT /{namespace}`` so FastAPI matches the
# typed routes first. The generic route still handles ``PUT /knowledge``
# with a free-form payload (it remains in ``_VALID_NAMESPACES``), but
# external clients (the FE settings panel) should prefer these typed
# endpoints because they get full Pydantic validation + a stable response
# shape.


@router.get("/knowledge", response_model=KnowledgeSettings)
async def get_knowledge_settings(
    user: dict = Depends(get_current_user),
):
    """Get the current knowledge-service settings (ADR-15).

    Returns ``KnowledgeSettings`` with empty strings for any unset override
    (callers should treat empty as "use the env-var / hardcoded default").
    """
    settings = get_settings_resolver().get_master_settings()
    return settings.knowledge


@router.put("/knowledge", response_model=KnowledgeSettings)
async def put_knowledge_settings(
    payload: KnowledgeSettings = Body(..., description="New knowledge settings"),
    user: dict = Depends(get_current_user),
):
    """Replace the knowledge-service settings (ADR-15).

    Persisted to ``.agents/config.json`` under the ``knowledge`` key.
    Broadcasts a ``settings_updated`` event so the FE settings panel can
    react live.  Invalidates the running KnowledgeService's model cache so
    the new settings take effect on the next LLM/embedding call without a
    dashboard restart.
    """
    resolver = get_settings_resolver()
    data = payload.model_dump(mode="json")
    # knowledge_embedding_dimension is read-only (fixed from OSTWIN_EMBEDDING_DIM).
    # Strip it from the payload so users cannot persist a conflicting value.
    data.pop("knowledge_embedding_dimension", None)
    resolver.patch_namespace("knowledge", data)

    # Invalidate cached LLM / embedder so next call picks up new settings.
    # Best-effort: never let invalidation failure break the settings save.
    try:
        from dashboard.routes.knowledge import _get_service  # noqa: WPS433

        svc = _get_service()
        if hasattr(svc, "invalidate_model_cache"):
            svc.invalidate_model_cache()

        # Clear ALL embedding singletons so settings take effect immediately
        # (Plan 014: unified embedding config)
        import dashboard.ai as _ai_mod

        _ai_mod._embedder = None
        if hasattr(_ai_mod, "_embedder_cache"):
            _ai_mod._embedder_cache.clear()

        try:
            from dashboard.knowledge.graph.index import kuzudb

            kuzudb._embedder_singleton = None
        except Exception:
            pass

        try:
            from dashboard.llm_client import _embedding_cache

            _embedding_cache.clear()
        except Exception:
            pass

    except Exception as exc:  # noqa: BLE001
        logger.debug("Knowledge model cache invalidation skipped: %s", exc)

    # Flag config reload for the MCP memory server — knowledge embedding
    # settings affect the memory system's embedding pipeline.
    _flag_memory_config_reload()

    await broadcaster.broadcast(
        "settings_updated",
        {
            "namespace": "knowledge",
            "settings": payload.model_dump(mode="json"),
        },
    )
    return payload


# ── Ollama Integration Endpoints ────────────────────────────────────────


class OllamaHealthResponse(BaseModel):
    running: bool
    model_exists: bool


class OllamaPullRequest(BaseModel):
    model: str


@router.get("/ollama/health", response_model=OllamaHealthResponse)
async def get_ollama_health(
    model: str = Query(..., description="Model name to check (e.g. llama3.2)"),
    user: dict = Depends(get_current_user),
):
    """Check if Ollama is running and if the requested model is pulled."""
    from ollama import AsyncClient, ResponseError
    import httpx

    resolver = get_settings_resolver()
    master = resolver.get_master_settings()
    cfg = master.providers.ollama if master.providers else None
    base_url = (
        cfg.base_url if cfg and cfg.base_url else os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    ).rstrip("/")

    try:
        client = AsyncClient(host=base_url)
        response = await client.list()

        models = [m.model for m in response.models] if hasattr(response, "models") else []

        # Ollama models often have ":latest" suffix.
        # If the user asks for "llama3.2", check if it exists
        model_exists = any(m == model or m == f"{model}:latest" for m in models)

        return OllamaHealthResponse(running=True, model_exists=model_exists)
    except (ResponseError, httpx.RequestError, ConnectionError):
        return OllamaHealthResponse(running=False, model_exists=False)


@router.get("/ollama/models")
async def list_ollama_models(
    user: dict = Depends(get_current_user),
):
    """List all installed Ollama models."""
    from ollama import AsyncClient, ResponseError
    import httpx

    resolver = get_settings_resolver()
    master = resolver.get_master_settings()
    cfg = master.providers.ollama if master.providers else None
    base_url = (
        cfg.base_url if cfg and cfg.base_url else os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    ).rstrip("/")

    try:
        client = AsyncClient(host=base_url)
        response = await client.list()

        models = []
        for m in response.models:
            raw_name = m.model
            if not raw_name:
                continue

            display_name = raw_name
            if display_name.endswith(":latest"):
                display_name = display_name[: -len(":latest")]

            # Use details attribute to determine if embed model
            details = getattr(m, "details", None)
            families = details.families if details and hasattr(details, "families") else []

            is_embed = (
                "bert" in families
                or "nomic-bert" in families
                or "embed" in display_name.lower()
                or "e5" in display_name.lower()
                or "bge" in display_name.lower()
            )

            models.append({"raw_name": raw_name, "display_name": display_name, "is_embed": is_embed})

        return {"models": models}
    except (ResponseError, httpx.RequestError, ConnectionError):
        return {"models": []}


@router.post("/ollama/pull")
async def pull_ollama_model(
    request: OllamaPullRequest = Body(...),
    user: dict = Depends(get_current_user),
):
    """Stream model pull progress from Ollama."""
    from ollama import AsyncClient, ResponseError
    from fastapi.responses import StreamingResponse
    import json
    import httpx

    async def stream_generator():
        model_name = request.model

        resolver = get_settings_resolver()
        master = resolver.get_master_settings()
        cfg = master.providers.ollama if master.providers else None
        base_url = (
            cfg.base_url if cfg and cfg.base_url else os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        ).rstrip("/")

        client = AsyncClient(host=base_url)
        try:
            async for progress in await client.pull(model_name, stream=True):
                # The python client returns a dict with status, digest, total, completed
                yield json.dumps(progress) + "\n"
        except (ResponseError, httpx.ConnectError, ConnectionError) as e:
            yield json.dumps({"error": f"Ollama connection error: {str(e)}"}) + "\n"
        except Exception as e:
            yield json.dumps({"error": f"An error occurred: {str(e)}"}) + "\n"

    return StreamingResponse(stream_generator(), media_type="application/x-ndjson")


@router.put("/{namespace}")
async def patch_global_namespace(
    namespace: str = Path(..., description="Namespace to patch"),
    value: Dict[str, Any] = Body(..., description="Settings to apply"),
    user: dict = Depends(get_current_user),
):
    """Patch a global namespace in config.json."""
    if namespace not in _VALID_NAMESPACES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid namespace '{namespace}'. Must be one of: {sorted(_VALID_NAMESPACES)}",
        )

    if namespace == "runtime" and "master_agent_model" in value:
        from dashboard.master_agent import format_master_model

        value = dict(value)
        if value["master_agent_model"]:
            value["master_agent_model"] = format_master_model(value["master_agent_model"])

    resolver = get_settings_resolver()
    try:
        resolver.patch_namespace(namespace, value)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    if namespace == "runtime" and "master_agent_model" in value:
        from dashboard.master_agent import set_master_model

        if value["master_agent_model"]:
            set_master_model(value["master_agent_model"])

    # Restart the bot process when channel config changes so it
    # picks up the new credentials / enabled flags on next boot.
    if namespace == "channels":
        _notify_bot_restart()

    # Sync Vertex AI env vars to ~/.ostwin/.env when provider config changes.
    if namespace == "providers":
        _sync_vertex_env(value)

    # Flag config reload for the MCP memory server when memory settings change.
    if namespace == "memory":
        _flag_memory_config_reload()

    await broadcaster.broadcast(
        "settings_updated",
        {
            "namespace": namespace,
            "settings": value,
        },
    )
    return {"status": "ok"}


@router.put("/plan/{plan_id}/role/{role}")
async def patch_plan_role(
    plan_id: str = Path(..., description="Plan ID"),
    role: str = Path(..., description="Role name"),
    value: Dict[str, Any] = Body(..., description="Settings to apply"),
    user: dict = Depends(get_current_user),
):
    """Patch plan-level role override."""
    resolver = get_settings_resolver()
    resolver.patch_plan_role(plan_id, role, value)

    await broadcaster.broadcast(
        "settings_updated",
        {
            "namespace": "plan",
            "plan_id": plan_id,
            "role": role,
            "settings": value,
        },
    )
    return {"status": "ok"}


@router.put("/room/{plan_id}/{task_ref}/role/{role}")
async def patch_room_role(
    plan_id: str = Path(..., description="Plan ID"),
    task_ref: str = Path(..., description="Task reference"),
    role: str = Path(..., description="Role name"),
    value: Dict[str, Any] = Body(..., description="Settings to apply"),
    user: dict = Depends(get_current_user),
):
    """Patch room-level role override."""
    resolver = get_settings_resolver()
    resolver.patch_room_role(plan_id, task_ref, role, value)

    await broadcaster.broadcast(
        "settings_updated",
        {
            "namespace": "room",
            "plan_id": plan_id,
            "task_ref": task_ref,
            "role": role,
            "settings": value,
        },
    )
    return {"status": "ok"}


@router.post("/reset/{namespace}")
async def reset_namespace(
    namespace: str = Path(..., description="Namespace to reset"),
    user: dict = Depends(get_current_user),
):
    """Reset namespace to defaults."""
    resolver = get_settings_resolver()
    resolver.reset_namespace(namespace)

    await broadcaster.broadcast(
        "settings_updated",
        {
            "namespace": namespace,
            "action": "reset",
        },
    )
    return {"status": "ok"}


# ── Provider Test Endpoint ─────────────────────────────────────────────


@router.post("/test/{provider}")
async def test_provider_connection(
    provider: str = Path(
        ...,
        description="Provider name (openai, anthropic, google, or custom name)",
    ),
    user: dict = Depends(get_current_user),
):
    """Test provider connection.  Returns latency_ms on success."""
    from dashboard.routes.roles import test_model_connection

    if provider == "google":
        try:
            resolver = get_settings_resolver()
            master = resolver.get_master_settings()
            google_cfg = master.providers.google
            mode = (google_cfg.deployment_mode or "gemini") if google_cfg else "gemini"
        except Exception:
            mode = "gemini"
        test_model = "google-vertex/gemini-3-flash-preview" if mode == "vertex" else "gemini/gemini-3-flash-preview"
    else:
        _map = {
            "openai": "gpt-4o",
            "anthropic": "claude-3-5-sonnet-20241022",
            "byteplus": "byteplus/seed-2-0-pro-260328",
        }
        test_model = _map.get(provider, provider)

    return await test_model_connection(test_model, user=user)


# ── Vault Management Endpoints ─────────────────────────────────────────


@router.get("/vault/status", response_model=VaultInfoResponse)
async def vault_status(
    user: dict = Depends(get_current_user),
):
    """Return the active vault backend type and its health status."""
    vault = get_vault()
    health = vault.health()
    return VaultInfoResponse(
        backend=health.backend_type,
        healthy=health.healthy,
        message=health.message,
        details=health.details,
    )


@router.post("/vault/{scope}/{key}", response_model=VaultStatusResponse)
async def store_vault_secret(
    scope: str = Path(..., description="Vault scope (e.g., 'providers')"),
    key: str = Path(..., description="Secret key"),
    request: VaultValueRequest = Body(..., description="Secret value"),
    user: dict = Depends(get_current_user),
):
    """Store a secret in the vault.

    Accepts secret via POST body only.
    Returns ``{is_set: true}`` on success.
    NEVER returns the secret value.

    When *scope* is ``providers``, automatically syncs the opencode.json
    config so the CLI picks up the new key immediately.
    """
    vault = get_vault()
    vault.set(scope, key, request.value)

    # Auto-sync opencode.json when a provider key changes
    if scope == "providers":
        _try_opencode_sync()
        _sync_provider_key_to_env(key, request.value)
        # When the service-account JSON or Google API key changes,
        # re-run the Vertex env sync so GOOGLE_APPLICATION_CREDENTIALS
        # and related env vars are kept up-to-date in ~/.ostwin/.env.
        if key in ("google_service_account", "google"):
            _try_vertex_env_sync()

    return VaultStatusResponse(is_set=True)


@router.get("/vault/{scope}", response_model=VaultScopeResponse)
async def list_vault_keys(
    scope: str = Path(..., description="Vault scope to list"),
    user: dict = Depends(get_current_user),
):
    """List all keys in a vault scope with status.

    Returns ``{key: {is_set: bool}}`` map.  NEVER returns secret values.
    """
    vault = get_vault()
    keys_data = vault.list_keys(scope)

    keys = {key: VaultStatusResponse(is_set=data.get("is_set", False)) for key, data in keys_data.items()}
    return VaultScopeResponse(keys=keys)


@router.delete("/vault/{scope}/{key}")
async def delete_vault_secret(
    scope: str = Path(..., description="Vault scope"),
    key: str = Path(..., description="Secret key to delete"),
    user: dict = Depends(get_current_user),
):
    """Delete a secret from the vault.  Returns 404 if not found."""
    vault = get_vault()
    deleted = vault.delete(scope, key)
    if not deleted:
        raise HTTPException(status_code=404, detail="Secret not found")

    # Auto-sync opencode.json when a provider key is removed
    if scope == "providers":
        _try_opencode_sync()
        # Comment out the corresponding env var in ~/.ostwin/.env
        env_var = _PROVIDER_ENV_MAP.get(key)
        if env_var:
            try:
                _remove_env_vars({env_var})
                os.environ.pop(env_var, None)
                logger.info("[SETTINGS] Removed %s from .env and os.environ", env_var)
            except Exception as exc:
                logger.warning("[SETTINGS] Failed to remove %s from .env: %s", env_var, exc)

    return {"status": "deleted"}


# ── Vault Migration Endpoint ──────────────────────────────────────────


@router.post("/vault/migrate")
async def migrate_secrets_to_vault(
    dry_run: bool = Query(False, description="Preview changes without writing"),
    user: dict = Depends(get_current_user),
):
    """Move plaintext secrets from ~/.ostwin/.env into the vault."""
    cmd = [sys.executable, "-m", "dashboard.scripts.migrate_secrets_to_vault"]
    if dry_run:
        cmd.append("--dry-run")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


# ── OpenCode Config Sync ──────────────────────────────────────────────


@router.post("/opencode/sync", response_model=OpenCodeSyncResponse)
async def sync_opencode(
    user: dict = Depends(get_current_user),
):
    """Sync provider keys + models to ~/.config/opencode/opencode.json.

    Only gemini (non-vertex) and byteplus are synced -- other providers
    are handled natively by OpenCode via env vars.
    """
    result = sync_opencode_config()

    def _target_detail(t):
        if t is None:
            return None
        return TargetSyncDetail(
            synced=t.synced,
            removed=t.removed,
            skipped=t.skipped,
            path=t.path,
            error=t.error,
        )

    return OpenCodeSyncResponse(
        synced=result.synced,
        removed=result.removed,
        skipped=result.skipped,
        path=result.path,
        error=result.error,
        opencode_json=_target_detail(result.opencode_json),
        auth_json=_target_detail(result.auth_json),
    )


# ── Google OAuth2 Flow ─────────────────────────────────────────────────


class OAuthStartRequest(BaseModel):
    project_id: str = ""


@router.post("/google/oauth/start")
async def google_oauth_start(
    response: Response,
    request: OAuthStartRequest = Body(default_factory=OAuthStartRequest),
    user: dict = Depends(get_current_user),
):
    """Start Google OAuth2 flow for Vertex AI authentication.

    Returns an ``authorization_url`` the frontend should open in a new tab.
    After the user authenticates, Google redirects to our callback endpoint.
    """
    # Build callback URL based on the current request origin
    callback_path = "/api/settings/google/oauth/callback"
    try:
        # Prioritize BASE_URL (set by user) over the internal OSTWIN_BASE_URL
        base_url = os.environ.get("BASE_URL") or os.environ.get("OSTWIN_BASE_URL", "http://localhost:3366")
        redirect_uri = f"{base_url}{callback_path}"
    except Exception:
        redirect_uri = f"http://localhost:3366{callback_path}"

    result = start_oauth(
        redirect_uri=redirect_uri,
        project_id=request.project_id,
    )

    # Store session data in a cookie for persistence across Cloud Run instances
    session: OAuthSession = result.pop("session")
    session_json = json.dumps(session.to_dict())
    session_b64 = base64.b64encode(session_json.encode()).decode()

    # Force secure=True on Cloud Run (even if internal protocol is http)
    is_cloud = os.environ.get("K_SERVICE") is not None

    # Set a temporary cookie (expires in 10 mins)
    response.set_cookie(
        key="ostwin_oauth_session",
        value=session_b64,
        httponly=True,
        max_age=600,
        samesite="lax",
        secure=True if is_cloud else ("https" in redirect_uri),
        path="/",  # EXPLICIT PATH is required for redirects to work
    )

    return result


@router.get("/google/oauth/callback")
async def google_oauth_callback(
    request: Request,
    response: Response,
    code: str = Query(..., description="Authorization code from Google"),
    state: str = Query(..., description="State parameter for CSRF protection"),
    error: Optional[str] = Query(None, description="Error from Google"),
):
    """Handle Google OAuth2 callback.

    This endpoint is called by Google after the user authenticates.
    It exchanges the auth code for tokens and saves them as ADC.
    Returns an HTML page that closes the popup window.
    """
    if error:
        return _oauth_result_page(success=False, message=f"Google returned error: {error}")

    # Recover session data from the cookie
    session_b64 = request.cookies.get("ostwin_oauth_session")
    if not session_b64:
        return _oauth_result_page(success=False, message="No pending OAuth session found in cookie. Please try again.")

    try:
        session_json = base64.b64decode(session_b64).decode()
        session_data = json.loads(session_json)
        session = OAuthSession.from_dict(session_data)

        result = exchange_code(code=code, state=state, session=session)

        # Sync Vertex env vars now that we have ADC
        _try_vertex_env_sync()

        # Clear the session cookie
        response.delete_cookie("ostwin_oauth_session")

        page = _oauth_result_page(
            success=True,
            message=f"Authenticated as {result.get('email', 'unknown')}",
            email=result.get("email"),
        )
        # We need to set the cookie deletion on the HTML response too
        page.delete_cookie("ostwin_oauth_session")
        return page
    except (ValueError, RuntimeError) as exc:
        return _oauth_result_page(success=False, message=str(exc))


@router.get("/google/oauth/status")
async def google_oauth_check(
    user: dict = Depends(get_current_user),
):
    """Check Google OAuth2 / ADC authentication status."""
    return get_oauth_status()


def _oauth_result_page(
    success: bool,
    message: str,
    email: Optional[str] = None,
) -> "HTMLResponse":
    """Return a minimal HTML page that posts the result back and closes."""
    from starlette.responses import HTMLResponse

    status = "success" if success else "error"
    icon = "check_circle" if success else "error"
    color = "#16a34a" if success else "#dc2626"

    html = f"""<!DOCTYPE html>
<html><head><title>Google OAuth</title>
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined" rel="stylesheet"/>
<style>
  body {{ font-family: system-ui, sans-serif; display: flex; align-items: center;
         justify-content: center; min-height: 100vh; margin: 0; background: #f8fafc; }}
  .card {{ text-align: center; padding: 3rem; background: white; border-radius: 12px;
           box-shadow: 0 1px 3px rgba(0,0,0,0.1); max-width: 400px; }}
  .icon {{ font-size: 48px; color: {color}; }}
  .msg {{ margin-top: 1rem; font-size: 14px; color: #334155; }}
  .sub {{ margin-top: 0.5rem; font-size: 12px; color: #94a3b8; }}
</style></head>
<body>
<div class="card">
  <span class="material-symbols-outlined icon">{icon}</span>
  <p class="msg">{message}</p>
  <p class="sub">This window will close automatically.</p>
</div>
<script>
  // Notify the opener (dashboard settings page) about the result
  if (window.opener) {{
    window.opener.postMessage({{
      type: 'google_oauth_result',
      status: '{status}',
      email: {json.dumps(email) if email else "null"},
    }}, '*');
  }}
  setTimeout(() => window.close(), 2000);
</script>
</body></html>"""
    return HTMLResponse(content=html)


def _notify_bot_restart() -> None:
    """Schedule a debounced bot restart after channel-related config changes."""
    if global_state.bot_manager is not None:
        logger.info("[SETTINGS] Channel config changed — scheduling bot restart")
        global_state.bot_manager.schedule_restart()
    else:
        logger.debug("[SETTINGS] No bot_manager — skipping restart signal")


_MEMORY_CONFIG_DIRTY_FLAG = FSPath.home() / ".ostwin" / ".agents" / ".memory_config_dirty"


def _flag_memory_config_reload() -> None:
    """Write a sentinel file that tells the MCP memory server to reload config.

    The MCP server checks for this flag (cheap ``stat()``) on every
    ``get_memory()`` call instead of re-parsing the full config.json
    every time.  When the flag is detected the server reloads config
    and deletes the file.
    """
    try:
        _MEMORY_CONFIG_DIRTY_FLAG.parent.mkdir(parents=True, exist_ok=True)
        _MEMORY_CONFIG_DIRTY_FLAG.write_text("1")
        logger.info("[SETTINGS] Flagged memory config reload: %s", _MEMORY_CONFIG_DIRTY_FLAG)
    except Exception as exc:
        logger.warning("[SETTINGS] Failed to write memory config flag: %s", exc)


def _try_opencode_sync() -> None:
    """Best-effort sync -- never let a sync failure break vault ops."""
    try:
        result = sync_opencode_config()
        if result.error:
            logger.warning("opencode sync error: %s", result.error)
        elif result.synced or result.removed:
            logger.info(
                "opencode sync: synced=%s removed=%s",
                result.synced,
                result.removed,
            )
            from dashboard.master_agent import reset_master_client

            reset_master_client()
    except Exception as exc:
        logger.warning("opencode sync failed: %s", exc)


# ── Vertex AI env-var sync ─────────────────────────────────────────────

_OSTWIN_DIR = FSPath.home() / ".ostwin"
_ENV_FILE = _OSTWIN_DIR / ".env"
_SA_FILE = _OSTWIN_DIR / "google-service-account.json"

# Env vars managed by this sync — never conflate with vault-managed keys.
_VERTEX_ENV_KEYS = {
    "GOOGLE_CLOUD_PROJECT",
    "VERTEX_LOCATION",
    "GOOGLE_APPLICATION_CREDENTIALS",
}

# Map vault provider keys -> env-var names that should be synced to ~/.ostwin/.env.
# When a provider secret is stored via the vault endpoint, the corresponding
# env var is upserted into the .env file so that processes reading the file
# (litellm, plan_agent, etc.) pick up the key immediately.
_PROVIDER_ENV_MAP: Dict[str, str] = {
    "google": "GOOGLE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openai_compatible": "OPENAI_COMPATIBLE_API_KEY",
}


def _sync_vertex_env(providers_value: Dict[str, Any]) -> None:
    """Sync Google Vertex AI settings to ~/.ostwin/.env and os.environ.

    Called whenever the ``providers`` namespace is patched or when a
    related vault secret changes.

    Handles two auth modes:

    * **service_account** (default) — writes the service-account JSON to
      disk and sets ``GOOGLE_APPLICATION_CREDENTIALS`` in ``.env``.
    * **oauth** — relies on Application Default Credentials (ADC) at
      ``~/.config/gcloud/application_default_credentials.json``.
      ``GOOGLE_APPLICATION_CREDENTIALS`` is *removed* from ``.env`` so
      the SDK falls through to ADC auto-discovery.

    In both modes ``GOOGLE_CLOUD_PROJECT`` and ``VERTEX_LOCATION`` are
    always written.

    When Google is switched away from vertex mode, all three env vars
    are commented out and the on-disk service-account file is deleted.
    """
    try:
        google = providers_value.get("google") or {}
        mode = google.get("deployment_mode", "gemini")

        if mode == "vertex":
            project_id = google.get("project_id", "")
            location = google.get("vertex_location") or "global"
            auth_mode = google.get("vertex_auth_mode") or "service_account"

            env_updates: Dict[str, str] = {}

            # Always write project + location (even if empty — _upsert
            # skips empty values, which is fine as a guard).
            if project_id:
                env_updates["GOOGLE_CLOUD_PROJECT"] = project_id
            if location:
                env_updates["VERTEX_LOCATION"] = location

            if auth_mode == "oauth":
                # OAuth / ADC mode — do NOT set GOOGLE_APPLICATION_CREDENTIALS.
                # The Google SDK auto-discovers ADC from the well-known path.
                _remove_env_vars({"GOOGLE_APPLICATION_CREDENTIALS"})
                os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
                # Clean up on-disk SA file if leftover from a previous mode
                if _SA_FILE.exists():
                    _SA_FILE.unlink()
                logger.info("[SETTINGS] Vertex auth_mode=oauth — using ADC auto-discovery")
            else:
                # service_account mode — write SA file + env var
                try:
                    from dashboard.lib.settings.vault import get_vault

                    vault = get_vault()
                    sa_json = vault.get("providers", "google_service_account")
                    if sa_json:
                        sa_json = _decode_if_hex(sa_json)
                        _OSTWIN_DIR.mkdir(parents=True, exist_ok=True)
                        _SA_FILE.write_text(sa_json)
                        env_updates["GOOGLE_APPLICATION_CREDENTIALS"] = str(_SA_FILE)
                        logger.info("[SETTINGS] Wrote service-account JSON to %s", _SA_FILE)
                except Exception as exc:
                    logger.warning(
                        "[SETTINGS] Could not extract service-account from vault: %s",
                        exc,
                    )

            if env_updates:
                _upsert_env_vars(env_updates)

            # Also set in the running process so litellm picks them up
            for k, v in env_updates.items():
                if v:
                    os.environ[k] = v

            logger.info(
                "[SETTINGS] Vertex env synced: project=%s location=%s auth=%s",
                project_id,
                location,
                auth_mode,
            )
        else:
            # Switching away from vertex — clean up
            _remove_env_vars(_VERTEX_ENV_KEYS)
            for k in _VERTEX_ENV_KEYS:
                os.environ.pop(k, None)
            # Remove the on-disk service-account file
            if _SA_FILE.exists():
                _SA_FILE.unlink()
            logger.info("[SETTINGS] Vertex env vars removed (mode=%s)", mode)

    except Exception as exc:
        logger.warning("[SETTINGS] Vertex env sync failed: %s", exc)


def _parse_env_file() -> list[dict]:
    """Parse ~/.ostwin/.env into structured entries (reuses system.py format)."""
    if not _ENV_FILE.exists():
        return []
    entries: list[dict] = []
    for line in _ENV_FILE.read_text().splitlines():
        stripped = line.strip()
        if not stripped:
            entries.append({"type": "blank"})
        elif stripped.startswith("#") and "=" in stripped:
            rest = stripped.lstrip("# ").strip()
            key, _, value = rest.partition("=")
            entries.append(
                {
                    "type": "var",
                    "key": key.strip(),
                    "value": value.strip(),
                    "enabled": False,
                }
            )
        elif stripped.startswith("#"):
            entries.append({"type": "comment", "text": stripped})
        elif "=" in stripped:
            key, _, value = stripped.partition("=")
            entries.append(
                {
                    "type": "var",
                    "key": key.strip(),
                    "value": value.strip(),
                    "enabled": True,
                }
            )
        else:
            entries.append({"type": "comment", "text": stripped})
    return entries


def _serialize_env_file(entries: list[dict]) -> str:
    """Serialize structured entries back to .env format."""
    lines: list[str] = []
    for e in entries:
        t = e.get("type", "comment")
        if t == "blank":
            lines.append("")
        elif t == "comment":
            lines.append(e.get("text", ""))
        elif t == "var":
            key = e.get("key", "")
            value = e.get("value", "")
            if e.get("enabled", True):
                lines.append(f"{key}={value}")
            else:
                lines.append(f"# {key}={value}")
    return "\n".join(lines) + "\n"


def _upsert_env_vars(updates: Dict[str, str]) -> None:
    """Upsert env vars into ~/.ostwin/.env.  Creates the file if needed."""
    entries = _parse_env_file()
    existing_keys = {e.get("key"): i for i, e in enumerate(entries) if e.get("type") == "var"}

    for key, value in updates.items():
        if not value:
            continue
        if key in existing_keys:
            idx = existing_keys[key]
            entries[idx]["value"] = value
            entries[idx]["enabled"] = True
        else:
            # Append with a section header on first vertex var
            if not any(e.get("text", "").startswith("# ── Vertex AI") for e in entries):
                entries.append({"type": "blank"})
                entries.append(
                    {
                        "type": "comment",
                        "text": "# ── Vertex AI (managed by dashboard) ────────────────────────────────",
                    }
                )
            entries.append({"type": "var", "key": key, "value": value, "enabled": True})

    _OSTWIN_DIR.mkdir(parents=True, exist_ok=True)
    _ENV_FILE.write_text(_serialize_env_file(entries))


def _remove_env_vars(keys_to_remove: set[str]) -> None:
    """Comment out env vars from ~/.ostwin/.env."""
    if not _ENV_FILE.exists():
        return
    entries = _parse_env_file()
    changed = False
    for e in entries:
        if e.get("type") == "var" and e.get("key") in keys_to_remove and e.get("enabled"):
            e["enabled"] = False
            changed = True
    if changed:
        _ENV_FILE.write_text(_serialize_env_file(entries))


def _sync_provider_key_to_env(vault_key: str, secret: str) -> None:
    """Write a provider API key to ~/.ostwin/.env when it's stored via vault.

    Only known provider keys (google, anthropic, openai) are synced.
    This ensures that processes reading the .env file (litellm,
    plan_agent, etc.) see the updated key without a manual edit.
    """
    env_var = _PROVIDER_ENV_MAP.get(vault_key)
    if not env_var or not secret:
        return
    try:
        _upsert_env_vars({env_var: secret})
        os.environ[env_var] = secret
        logger.info("[SETTINGS] Synced %s to .env and os.environ", env_var)
    except Exception as exc:
        logger.warning("[SETTINGS] Failed to sync %s to .env: %s", env_var, exc)


def _try_vertex_env_sync() -> None:
    """Re-run Vertex env sync using current provider settings.

    Called after a vault secret change (e.g. service-account upload or
    Google API key update) so that ~/.ostwin/.env stays consistent with
    the current deployment mode.
    """
    try:
        from dashboard.lib.settings.resolver import get_settings_resolver

        resolver = get_settings_resolver()
        master = resolver.get_master_settings()
        providers_dict = master.providers.model_dump(exclude_none=True) if master.providers else {}
        _sync_vertex_env(providers_dict)
    except Exception as exc:
        logger.warning("[SETTINGS] Vertex env re-sync failed: %s", exc)


def _decode_if_hex(value: str) -> str:
    """Decode a hex-encoded string back to UTF-8 if applicable.

    macOS Keychain (``security find-generic-password -w``) returns
    multiline or binary-ish values as a hex string (no ``0x`` prefix).
    This helper detects that pattern and decodes it; plain-text values
    pass through unchanged.
    """
    stripped = value.strip()
    # Quick heuristic: hex strings are all [0-9a-fA-F] with even length
    if len(stripped) > 2 and len(stripped) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in stripped):
        try:
            decoded = bytes.fromhex(stripped).decode("utf-8")
            # Sanity-check: if the decoded content looks like JSON, use it
            if decoded.strip().startswith("{"):
                return decoded
        except (ValueError, UnicodeDecodeError):
            pass
    return value
