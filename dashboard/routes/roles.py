import json
import logging
import uuid
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from dashboard.models import Role, CreateRoleRequest
from dashboard.api_utils import AGENTS_DIR, PLANS_DIR, GLOBAL_ROLES_DIR
from dashboard.auth import get_current_user
import dashboard.global_state as global_state

router = APIRouter(tags=["roles"])
logger = logging.getLogger(__name__)

ROLES_CONFIG_FILE = GLOBAL_ROLES_DIR / "config.json"
ENGINE_CONFIG_FILE = AGENTS_DIR / "config.json"

PROVIDER_MAP = {
    "google-vertex": "Gemini",  # must precede "claude" to catch google-vertex-anthropic/*
    "gemini": "Gemini", "claude": "Claude", "anthropic": "Claude",
    "gpt": "GPT", "openai": "GPT", "o1": "GPT", "o3": "GPT", "o4": "GPT",
    "byteplus": "BytePlus", "seed": "BytePlus", "doubao": "BytePlus",
}


def _detect_provider(model_id: str) -> str:
    model_lower = model_id.lower()
    for prefix, provider in PROVIDER_MAP.items():
        if prefix in model_lower:
            return provider
    return "Gemini"



def _resolve_model_id(version: str) -> str:
    """Ensure a model ID is fully-qualified with a ``provider/model`` prefix.

    Roles can store bare model names like ``gemini-3-flash-preview`` when they
    were originally created from an opencode config that had stripped the
    provider prefix.  The opencode CLI requires the full ``provider/model``
    form, so we resolve the bare ID before invoking it.

    Resolution order
    ----------------
    1. IDs that already contain ``/`` are returned unchanged:
       e.g. ``google-vertex/gemini-3-flash-preview``, ``gemini/gemini-3-flash-preview``.
    2. Static fallback catalog (``_FALLBACK_CATALOG``) — covers the four
       legacy providers without touching any models.dev data.
    3. Dynamic configured_models catalog (built from models.dev at startup) —
       covers additional models from configured providers.  The raw models.dev
       JSON is never modified; we only read it for lookup.
    4. Native opencode providers (Anthropic, OpenAI, …) need no prefix;
       unknown bare IDs are passed through unchanged.
    """
    if "/" in version:
        return version  # already provider-qualified

    # ── Step 1: static fallback catalog ──────────────────────────────────
    try:
        from dashboard.lib.settings.models_registry import _FALLBACK_CATALOG
        for entries in _FALLBACK_CATALOG.values():
            for entry in entries:
                short = entry.id.split("/", 1)[-1] if "/" in entry.id else entry.id
                if short == version and entry.id != version:
                    logger.debug(
                        "_resolve_model_id: %r → static catalog %r", version, entry.id
                    )
                    return entry.id
    except Exception:
        pass

    # ── Step 2: dynamic configured_models (models.dev) ───────────────────
    # Models.dev raw data is never modified — we only use it for ID lookup.
    try:
        from dashboard.lib.settings.models_dev_loader import (
            get_configured_models,
            _read_google_deployment_mode,
        )
        configured = get_configured_models()
        for provider_id, pdata in configured.get("providers", {}).items():
            for mid in pdata.get("models", {}):
                # mid may already be qualified (companion provider prefix)
                short = mid.split("/", 1)[-1] if "/" in mid else mid
                if short != version and mid != version:
                    continue

                if "/" in mid:
                    # Companion model: already fully qualified in the catalog.
                    logger.debug(
                        "_resolve_model_id: %r → dynamic catalog (companion) %r",
                        version, mid,
                    )
                    return mid


                if provider_id == "google":
                    # opencode uses the custom 'gemini' provider block;
                    # vertex companion models already have google-vertex/ prefix.
                    mode = _read_google_deployment_mode()
                    if mode == "gemini":
                        qualified = f"gemini/{version}"
                        logger.debug(
                            "_resolve_model_id: %r → google/gemini mode %r",
                            version, qualified,
                        )
                        return qualified
                    # Vertex mode: bare google model IDs shouldn't appear here
                    # (companions are already prefixed), but pass through.
                    return version

                # Any other custom provider (gemini, byteplus, …): use its
                # provider_id as the opencode model prefix.
                qualified = f"{provider_id}/{version}"
                logger.debug(
                    "_resolve_model_id: %r → custom provider %r",
                    version, qualified,
                )
                return qualified
    except Exception:
        pass

    # Unknown bare ID (e.g. native Claude/OpenAI not in catalog):
    # pass through and let opencode decide.
    return version


def _read_role_json(role_name: str) -> dict:
    """Read individual role.json from disk (the engine's per-role definition)."""
    role_file = GLOBAL_ROLES_DIR / role_name / "role.json"
    if not role_file.exists():
        role_file = AGENTS_DIR / "roles" / role_name / "role.json"
        
    if role_file.exists():
        try:
            return json.loads(role_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _read_engine_config() -> dict:
    """Read the engine's global config.json."""
    if ENGINE_CONFIG_FILE.exists():
        try:
            return json.loads(ENGINE_CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def load_roles() -> List[Role]:
    roles_list = []
    loaded_names = set()
    
    # 1. Load from config.json cache if exists
    if ROLES_CONFIG_FILE.exists():
        with open(ROLES_CONFIG_FILE, "r") as f:
            try:
                data = json.load(f)
                roles_list = [Role(**r) for r in data]
                loaded_names = {r.name for r in roles_list}
            except: pass

    # 2. If config.json doesn't exist or is empty, bootstrap from registry.json
    if not roles_list:
        registry_file = GLOBAL_ROLES_DIR / "registry.json"
        if not registry_file.exists():
            registry_file = AGENTS_DIR / "roles" / "registry.json"
            
        if registry_file.exists():
            registry = json.loads(registry_file.read_text())
            engine_config = _read_engine_config()
            for r in registry.get("roles", []):
                name = r["name"]
                if name in loaded_names: continue
                role_json = _read_role_json(name)
                engine_role = engine_config.get(name, {})
                model = engine_role.get("default_model") or role_json.get("model") or r.get("default_model", "google-vertex/gemini-3-flash-preview")
                timeout = engine_role.get("timeout_seconds") or role_json.get("timeout_seconds") or role_json.get("timeout", r.get("timeout_seconds", 300))
                retries = engine_role.get("max_retries") or role_json.get("max_retries", r.get("max_retries", 3))
                instance_type = engine_role.get("instance_type") or role_json.get("instance_type") or r.get("instance_type", "worker")
                skill_refs = role_json.get("skill_refs", role_json.get("skills", []))
                mcp_refs = role_json.get("mcp_refs", [])
                description = role_json.get("description", r.get("description", ""))
                role_md_file = GLOBAL_ROLES_DIR / name / "ROLE.md"
                if not role_md_file.exists():
                    role_md_file = AGENTS_DIR / "roles" / name / "ROLE.md"
                instructions = ""
                if role_md_file.exists():
                    try:
                        instructions = role_md_file.read_text()
                    except OSError:
                        pass
                now = datetime.now(timezone.utc).isoformat()
                role = Role(
                    id=str(uuid.uuid4()),
                    name=name,
                    description=description,
                    instructions=instructions,
                    provider=_detect_provider(model).lower(),
                    version=model,
                    temperature=0.7,
                    budget_tokens_max=500000,
                    max_retries=retries,
                    timeout_seconds=timeout,
                    skill_refs=skill_refs,
                    mcp_refs=mcp_refs,
                    instance_type=instance_type,
                    system_prompt_override=None,
                    created_at=now,
                    updated_at=now
                )
                roles_list.append(role)
                loaded_names.add(name)

    # 3. Dynamically discover any other role directories
    added_new = False
    
    # Helper to scan a directory for valid role folders
    def _scan_dir_for_roles(base_dir: Path):
        nonlocal added_new
        if not base_dir.exists(): return
        engine_config = _read_engine_config()
        for child in base_dir.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                name = child.name
                if name not in loaded_names:
                    role_file = child / "role.json"
                    md_file = child / "ROLE.md"
                    if role_file.exists() or md_file.exists():
                        role_json = _read_role_json(name)
                        engine_role = engine_config.get(name, {})
                        model = engine_role.get("default_model") or role_json.get("model") or "google-vertex/gemini-3-flash-preview"
                        timeout = engine_role.get("timeout_seconds") or role_json.get("timeout_seconds") or role_json.get("timeout", 300)
                        retries = engine_role.get("max_retries") or role_json.get("max_retries", 3)
                        instance_type = engine_role.get("instance_type") or role_json.get("instance_type") or "worker"
                        skill_refs = role_json.get("skill_refs", role_json.get("skills", []))
                        mcp_refs = role_json.get("mcp_refs", [])
                        description = role_json.get("description", "")
                        
                        instructions = ""
                        # prefer global md file
                        actual_md = GLOBAL_ROLES_DIR / name / "ROLE.md"
                        if not actual_md.exists(): actual_md = md_file
                        if actual_md.exists():
                            try: instructions = actual_md.read_text()
                            except OSError: pass
                            
                        now = datetime.now(timezone.utc).isoformat()
                        role = Role(
                            id=str(uuid.uuid4()), name=name, description=description, instructions=instructions,
                            provider=_detect_provider(model).lower(), version=model, temperature=0.7,
                            budget_tokens_max=500000, max_retries=retries, timeout_seconds=timeout, skill_refs=skill_refs,
                            mcp_refs=mcp_refs, instance_type=instance_type, system_prompt_override=None, created_at=now, updated_at=now
                        )
                        roles_list.append(role)
                        loaded_names.add(name)
                        added_new = True

    _scan_dir_for_roles(GLOBAL_ROLES_DIR)
    _scan_dir_for_roles(AGENTS_DIR / "roles")

    if added_new or not ROLES_CONFIG_FILE.exists():
        save_roles(roles_list)
        
    return roles_list


def save_roles(roles: List[Role]):
    ROLES_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ROLES_CONFIG_FILE, "w") as f:
        json.dump([r.model_dump() for r in roles], f, indent=2)


def _sync_role_to_engine(role: Role):
    """Write role config back to engine files so the PowerShell runtime picks it up."""
    # Update engine's global config.json
    engine_config = _read_engine_config()
    if role.name not in engine_config:
        engine_config[role.name] = {}
    engine_config[role.name]["default_model"] = role.version
    engine_config[role.name]["timeout_seconds"] = role.timeout_seconds
    engine_config[role.name]["max_retries"] = role.max_retries
    engine_config[role.name]["instance_type"] = role.instance_type
    if role.skill_refs:
        engine_config[role.name]["skill_refs"] = role.skill_refs
    if role.mcp_refs:
        engine_config[role.name]["mcp_refs"] = role.mcp_refs
    try:
        ENGINE_CONFIG_FILE.write_text(json.dumps(engine_config, indent=2))
    except OSError as e:
        logger.warning("Failed to update engine config.json: %s", e)

    # Update individual role.json
    role_dir = GLOBAL_ROLES_DIR / role.name
    role_dir.mkdir(parents=True, exist_ok=True)
    role_file = role_dir / "role.json"
    role_json = _read_role_json(role.name)
    role_json["model"] = role.version
    role_json["skill_refs"] = role.skill_refs
    role_json["mcp_refs"] = role.mcp_refs
    role_json["timeout_seconds"] = role.timeout_seconds
    role_json["max_retries"] = role.max_retries
    role_json["instance_type"] = role.instance_type
    role_json["description"] = role.description
    try:
        role_file.write_text(json.dumps(role_json, indent=2))
    except OSError as e:
        logger.warning("Failed to update role.json for %s: %s", role.name, e)

    # Write ROLE.md
    if role.instructions:
        role_md_file = role_dir / "ROLE.md"
        try:
            role_md_file.write_text(role.instructions)
        except OSError as e:
            logger.warning("Failed to write ROLE.md for %s: %s", role.name, e)


def sync_roles_from_disk() -> dict:
    """Merge skill_refs and model from on-disk role.json files into dashboard config.
    Returns a summary of what was updated."""
    roles = load_roles()
    engine_config = _read_engine_config()
    updated = []
    for role in roles:
        role_json = _read_role_json(role.name)
        engine_role = engine_config.get(role.name, {})
        changed = False
        disk_skills = role_json.get("skill_refs", role_json.get("skills", []))
        if disk_skills and not role.skill_refs:
            role.skill_refs = disk_skills
            changed = True
        disk_model = engine_role.get("default_model") or role_json.get("model")
        if disk_model and disk_model != role.version:
            role.version = disk_model
            role.provider = _detect_provider(disk_model)
            changed = True
        disk_timeout = engine_role.get("timeout_seconds") or role_json.get("timeout_seconds") or role_json.get("timeout")
        if disk_timeout and disk_timeout != role.timeout_seconds:
            role.timeout_seconds = disk_timeout
            changed = True
        disk_retries = engine_role.get("max_retries") or role_json.get("max_retries")
        if disk_retries and disk_retries != role.max_retries:
            role.max_retries = disk_retries
            changed = True
        disk_instance_type = engine_role.get("instance_type") or role_json.get("instance_type")
        if disk_instance_type and disk_instance_type != role.instance_type:
            role.instance_type = disk_instance_type
            changed = True
        disk_description = role_json.get("description", "")
        if disk_description and disk_description != role.description:
            role.description = disk_description
            changed = True
        role_md_file = GLOBAL_ROLES_DIR / role.name / "ROLE.md"
        if not role_md_file.exists():
            role_md_file = AGENTS_DIR / "roles" / role.name / "ROLE.md"
        if role_md_file.exists():
            try:
                disk_instructions = role_md_file.read_text()
                if disk_instructions != role.instructions:
                    role.instructions = disk_instructions
                    changed = True
            except OSError:
                pass
        if changed:
            role.updated_at = datetime.now(timezone.utc).isoformat()
            updated.append(role.name)
    if updated:
        save_roles(roles)
        store = global_state.store
        if store:
            for role in roles:
                if role.name in updated:
                    store.index_role(
                        role_id=role.id, name=role.name, provider=role.provider,
                        version=role.version, temperature=role.temperature,
                        budget_tokens_max=role.budget_tokens_max, max_retries=role.max_retries,
                        timeout_seconds=role.timeout_seconds, skill_refs=role.skill_refs,
                        instance_type=role.instance_type,
                        system_prompt_override=role.system_prompt_override,
                        created_at=role.created_at, updated_at=role.updated_at,
                    )
    return {"synced": updated, "total": len(roles)}


@router.post("/api/roles/sync")
async def sync_roles_endpoint(user: dict = Depends(get_current_user)):
    """Re-sync dashboard roles from on-disk role.json and engine config.json."""
    return sync_roles_from_disk()


@router.get("/api/models/registry")
async def get_model_registry(user: dict = Depends(get_current_user)):
    """Get the available models, filtered by which providers are enabled.

    Uses the dynamic models.dev catalog (populated at server startup)
    filtered by providers configured in auth.json.  Falls back to the
    static catalog if no dynamic data is available.
    """
    from dashboard.lib.settings.models_registry import get_model_registry as _build

    try:
        return _build()
    except Exception:
        return _build()


@router.get("/api/models/configured")
async def get_configured_models(user: dict = Depends(get_current_user)):
    """Get the full configured models catalog.

    Returns the complete structured data from models.dev/api.json
    filtered by providers configured in auth.json and opencode.json.
    Includes provider metadata, logos, model costs, limits, etc.
    """
    from dashboard.lib.settings.models_dev_loader import get_configured_models as _get
    return _get()


@router.get("/api/models/providers")
async def get_configured_providers(user: dict = Depends(get_current_user)):
    """Get the list of configured providers from auth.json + opencode.json."""
    from dashboard.lib.settings.models_dev_loader import (
        get_configured_models,
        get_configured_providers as _get_providers,
    )
    configured = get_configured_models()
    providers_config = _get_providers()

    result = []
    for pid, pcfg in providers_config.items():
        provider_data = configured.get("providers", {}).get(pid, {})
        result.append({
            "id": pid,
            "name": provider_data.get("name", pid),
            "logo_url": provider_data.get("logo_url", f"https://models.dev/logos/{pid}.svg"),
            "model_count": len(provider_data.get("models", {})),
            "source": pcfg.get("source", ""),
            "has_key": pcfg.get("has_key", False),
            "doc": provider_data.get("doc", ""),
        })

    return {"providers": result}


@router.get("/api/models/available")
async def get_available_providers(user: dict = Depends(get_current_user)):
    """Get ALL providers from models.dev for the Add Provider browser.

    Returns every provider in the raw catalog, with a flag indicating
    whether it is already configured.
    """
    from dashboard.lib.settings.models_dev_loader import (
        get_available_providers as _get_all,
    )
    return {"providers": _get_all()}


@router.post("/api/models/reload")
async def reload_models(user: dict = Depends(get_current_user)):
    """Force re-fetch models from models.dev and rebuild configured_models.json."""
    from dashboard.lib.settings.models_dev_loader import (
        invalidate_cache,
        load_models_on_startup,
    )
    invalidate_cache()
    result = load_models_on_startup()
    provider_count = len(result.get("providers", {}))
    model_count = sum(
        len(p.get("models", {}))
        for p in result.get("providers", {}).values()
    )
    return {
        "status": "ok",
        "providers": provider_count,
        "models": model_count,
        "loaded_at": result.get("loaded_at"),
    }


@router.get("/api/roles", response_model=List[Role])
async def list_roles(user: dict = Depends(get_current_user)):
    return load_roles()


@router.get("/api/roles/search")
async def search_roles(
    q: str = Query(..., description="Semantic search query"),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    store = global_state.store
    if not store:
        raise HTTPException(status_code=503, detail="Vector store not available")
    return store.search_roles(q, limit=limit)


@router.post("/api/roles", response_model=Role, status_code=status.HTTP_201_CREATED)
async def create_role(req: CreateRoleRequest, user: dict = Depends(get_current_user)):
    roles = load_roles()
    if any(r.name == req.name for r in roles):
        raise HTTPException(status_code=400, detail="Role name already exists")

    now = datetime.now(timezone.utc).isoformat()
    new_role = Role(
        id=str(uuid.uuid4()),
        **req.model_dump(),
        created_at=now,
        updated_at=now
    )
    roles.append(new_role)
    save_roles(roles)
    _sync_role_to_engine(new_role)

    store = global_state.store
    if store:
        store.index_role(
            role_id=new_role.id,
            name=new_role.name,
            provider=new_role.provider,
            version=new_role.version,
            temperature=new_role.temperature,
            budget_tokens_max=new_role.budget_tokens_max,
            max_retries=new_role.max_retries,
            timeout_seconds=new_role.timeout_seconds,
            skill_refs=new_role.skill_refs,
            instance_type=new_role.instance_type,
            system_prompt_override=new_role.system_prompt_override,
            created_at=new_role.created_at,
            updated_at=new_role.updated_at,
        )

    return new_role


@router.put("/api/roles/{role_id}", response_model=Role)
async def update_role(role_id: str, req: CreateRoleRequest, user: dict = Depends(get_current_user)):
    roles = load_roles()
    for i, r in enumerate(roles):
        if r.id == role_id:
            # Check name uniqueness if changed
            if r.name != req.name and any(other.name == req.name for other in roles if other.id != role_id):
                raise HTTPException(status_code=400, detail="Role name already exists")
            
            # Propagate name change to plans if needed
            old_name = r.name
            new_name = req.name
            if old_name != new_name:
                plans_dir = PLANS_DIR
                if plans_dir.exists():
                    for f in plans_dir.glob("*.roles.json"):
                        try:
                            config = json.loads(f.read_text())
                            if old_name in config:
                                config[new_name] = config.pop(old_name)
                                f.write_text(json.dumps(config, indent=2))
                        except Exception:
                            pass
            
            updated_role = Role(
                id=role_id,
                **req.model_dump(),
                created_at=r.created_at,
                updated_at=datetime.now(timezone.utc).isoformat()
            )
            roles[i] = updated_role
            save_roles(roles)
            _sync_role_to_engine(updated_role)

            store = global_state.store
            if store:
                store.index_role(
                    role_id=updated_role.id,
                    name=updated_role.name,
                    provider=updated_role.provider,
                    version=updated_role.version,
                    temperature=updated_role.temperature,
                    budget_tokens_max=updated_role.budget_tokens_max,
                    max_retries=updated_role.max_retries,
                    timeout_seconds=updated_role.timeout_seconds,
                    skill_refs=updated_role.skill_refs,
                    instance_type=updated_role.instance_type,
                    system_prompt_override=updated_role.system_prompt_override,
                    created_at=updated_role.created_at,
                    updated_at=updated_role.updated_at,
                )

            return updated_role

    raise HTTPException(status_code=404, detail="Role not found")


@router.patch("/api/roles/by-name/{role_name}", response_model=Role)
async def patch_role_by_name(
    role_name: str,
    body: Dict[str, Any] = Body(...),
    user: dict = Depends(get_current_user),
):
    """Patch a role's settings by name.

    Persists to the dashboard roles cache (primary store) and syncs
    to role.json + engine config.json (secondary file storage).

    Accepted body fields:
      - default_model / model: the model version string
    """
    roles = load_roles()
    role = next((r for r in roles if r.name == role_name), None)
    if not role:
        raise HTTPException(status_code=404, detail=f"Role '{role_name}' not found")

    changed = False

    # Accept both 'default_model' (settings UI convention) and 'model' (role.json convention)
    model = body.get("default_model") or body.get("model")
    if model and model != role.version:
        role.version = model
        role.provider = _detect_provider(model)
        changed = True

    timeout = body.get("timeout_seconds") or body.get("timeout")
    if timeout is not None and timeout != role.timeout_seconds:
        role.timeout_seconds = int(timeout)
        changed = True

    retries = body.get("max_retries")
    if retries is not None and retries != role.max_retries:
        role.max_retries = int(retries)
        changed = True

    instance_type = body.get("instance_type")
    if instance_type and instance_type != role.instance_type:
        role.instance_type = instance_type
        changed = True

    if not changed:
        return role

    role.updated_at = datetime.now(timezone.utc).isoformat()

    # Primary: persist to dashboard roles cache
    save_roles(roles)

    # Secondary: sync to file storage (role.json + engine config.json)
    _sync_role_to_engine(role)

    # Update vector store index if available
    store = global_state.store
    if store:
        store.index_role(
            role_id=role.id, name=role.name, provider=role.provider,
            version=role.version, temperature=role.temperature,
            budget_tokens_max=role.budget_tokens_max, max_retries=role.max_retries,
            timeout_seconds=role.timeout_seconds, skill_refs=role.skill_refs,
            instance_type=role.instance_type,
            system_prompt_override=role.system_prompt_override,
            created_at=role.created_at, updated_at=role.updated_at,
        )

    return role


@router.get("/api/roles/{role_id}", response_model=Role)
async def get_role(role_id: str, user: dict = Depends(get_current_user)):
    roles = load_roles()
    role = next((r for r in roles if r.id == role_id), None)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return role


@router.get("/api/roles/{role_id}/dependencies")
async def get_role_dependencies(role_id: str, user: dict = Depends(get_current_user)):
    """Check where this role is used in war-rooms and plans."""
    roles = load_roles()
    role = next((r for r in roles if r.id == role_id), None)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    from dashboard.api_utils import WARROOMS_DIR
    active_warrooms = []
    inactive_warrooms = []
    plans = []
    
    # Check war-rooms
    if WARROOMS_DIR.exists():
        for room_dir in WARROOMS_DIR.glob("room-*"):
            if room_dir.is_dir():
                config_file = room_dir / "config.json"
                status_file = room_dir / "status"
                if config_file.exists():
                    try:
                        with open(config_file, "r") as f:
                            config = json.load(f)
                            candidates = config.get("assignment", {}).get("candidate_roles", [])
                            if role.name in candidates:
                                status = status_file.read_text().strip() if status_file.exists() else "unknown"
                                room_info = {"id": room_dir.name, "status": status}
                                if status not in ["passed", "failed", "signoff"]:
                                    active_warrooms.append(room_info)
                                else:
                                    inactive_warrooms.append(room_info)
                    except Exception:
                        pass
    
    # Check plans
    plans_dir = PLANS_DIR
    if plans_dir.exists():
        for f in plans_dir.glob("*.roles.json"):
            try:
                config = json.loads(f.read_text())
                if role.name in config:
                    plans.append(f.name.replace(".roles.json", ""))
            except Exception:
                pass
            
    return {
        "active_warrooms": active_warrooms,
        "inactive_warrooms": inactive_warrooms,
        "plans": plans
    }


@router.delete("/api/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: str, force: bool = False, user: dict = Depends(get_current_user)):
    roles = load_roles()
    role_to_delete = next((r for r in roles if r.id == role_id), None)
    if not role_to_delete:
        raise HTTPException(status_code=404, detail="Role not found")
    
    deps = await get_role_dependencies(role_id, user)
    
    if len(deps["active_warrooms"]) > 0:
        raise HTTPException(
            status_code=409, 
            detail=f"Cannot delete — this role is actively used by {len(deps['active_warrooms'])} war-rooms."
        )
    
    if not force and (len(deps["inactive_warrooms"]) > 0 or len(deps["plans"]) > 0):
        # We'll rely on the frontend to ask for force=true if there are only inactive/plan refs
        raise HTTPException(
            status_code=412, # Precondition Failed
            detail="Role has inactive references. Use force=true to delete anyway."
        )

    # Actually delete from plans if force=true
    if force:
        plans_dir = PLANS_DIR
        if plans_dir.exists():
            for f in plans_dir.glob("*.roles.json"):
                try:
                    config = json.loads(f.read_text())
                    if role_to_delete.name in config:
                        del config[role_to_delete.name]
                        f.write_text(json.dumps(config, indent=2))
                except Exception: pass
    
    roles = [r for r in roles if r.id != role_id]
    save_roles(roles)

    store = global_state.store
    if store:
        store.delete_role(role_id)

    return



@router.post("/api/models/{version:path}/test")
async def test_model_connection(version: str, user: dict = Depends(get_current_user)):
    """Test model connectivity by running: opencode run "just say YES" --model <version>.

    Uses the original opencode subprocess — the same CLI the agent runtime uses.
    Parses the raw output for known error signatures and returns structured
    diagnostics so the UI can show actionable information instead of raw logs.
    """
    import re
    import shutil
    import subprocess
    import time

    opencode = shutil.which("opencode")
    if not opencode:
        return {
            "status": "fail",
            "category": "install",
            "error": "opencode CLI not found on PATH",
            "fix": "Run: npm install -g opencode",
        }

    resolved_version = _resolve_model_id(version)
    logger.info("test_model_connection: %r → resolved %r", version, resolved_version)

    cmd = [opencode, "run", "just say YES", "--model", resolved_version, "--dir", "/tmp"]

    def _strip_ansi(text: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*[mGKHF]", "", text)

    def _run() -> tuple[int, str, str]:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            env={**__import__("os").environ},
        )
        return (
            result.returncode,
            _strip_ansi(result.stdout.strip()),
            _strip_ansi(result.stderr.strip()),
        )

    def _diagnose(returncode: int, stdout: str, stderr: str) -> dict:
        """Parse opencode output and return structured diagnostic fields."""
        combined = (stderr + "\n" + stdout).lower()
        raw = (stderr + "\n" + stdout).strip()
        raw_snippet = raw[-600:] if len(raw) > 600 else raw

        if "generic_string_invalid_too_long" in combined:
            return {
                "category": "protocol",
                "error": "A tool/skill description exceeds Gemini's 1,024-character limit (GENERIC_STRING_INVALID_TOO_LONG)",
                "fix": "This is a known protocol error. The fix requires sanitising skill descriptions — check with the team for the latest patch.",
                "raw_output": raw_snippet,
            }
        if any(k in combined for k in ("unauthenticated", "api key", "api_key", "401", "403", "invalid credentials")):
            provider = resolved_version.split("/")[0] if "/" in resolved_version else "unknown"
            fix = "Use Settings -> Provider Config to sign in with Google or upload a service-account JSON file, then verify GOOGLE_CLOUD_PROJECT is set." if "vertex" in resolved_version.lower() or "google" in resolved_version.lower() \
                else f"Check Settings → Providers → {provider}: ensure your API key is saved and valid."
            return {"category": "auth", "error": "Authentication failed", "fix": fix, "raw_output": raw_snippet}
        if "not found" in combined and ("model" in combined or "404" in combined):
            return {
                "category": "model",
                "error": f"Model not found: {resolved_version}",
                "fix": "Check the model ID. Use Settings → Models to browse available models.",
                "raw_output": raw_snippet,
            }
        if any(k in combined for k in ("quota", "rate limit", "429", "resource_exhausted")):
            return {"category": "quota", "error": "Rate limit or quota exceeded", "fix": "Wait and retry, or check your provider quota dashboard.", "raw_output": raw_snippet}
        if any(k in combined for k in ("connection refused", "econnrefused", "network", "timeout", "unreachable")):
            return {"category": "network", "error": "Cannot reach the provider endpoint", "fix": "Check your internet connection, firewall, or VPN settings.", "raw_output": raw_snippet}
        if "permission" in combined and ("denied" in combined or "iam" in combined):
            return {"category": "auth", "error": "Permission denied", "fix": "Grant the 'Vertex AI User' IAM role in Google Cloud Console.", "raw_output": raw_snippet}

        # Unknown — surface the raw output so the user can see the actual error
        return {
            "category": "unknown",
            "error": raw_snippet or "opencode exited with no output",
            "fix": f"Run manually for full output:\n  {' '.join(cmd)}",
            "raw_output": raw_snippet,
        }

    start = time.time()
    try:
        returncode, stdout, stderr = await asyncio.get_event_loop().run_in_executor(None, _run)
        latency = int((time.time() - start) * 1000)

        if returncode == 0 and "YES" in (stdout or "").upper():
            return {"status": "ok", "latency_ms": latency, "output": stdout[-200:], "resolved_model": resolved_version}

        diag = _diagnose(returncode, stdout, stderr)
        logger.warning(
            "test_model_connection failed: version=%r resolved=%r rc=%d category=%s error=%r",
            version, resolved_version, returncode, diag.get("category"), diag.get("error"),
        )
        return {"status": "fail", "latency_ms": latency, "resolved_model": resolved_version, **diag}

    except subprocess.TimeoutExpired:
        latency = int((time.time() - start) * 1000)
        logger.warning("test_model_connection timed out: version=%r resolved=%r", version, resolved_version)
        return {"status": "fail", "latency_ms": latency, "category": "timeout", "error": "opencode did not respond within 60s", "fix": "The provider may be slow or unreachable. Try again."}
    except Exception as exc:
        latency = int((time.time() - start) * 1000)
        logger.warning("test_model_connection error: version=%r resolved=%r error=%r", version, resolved_version, str(exc))
        return {"status": "fail", "latency_ms": latency, "category": "unknown", "error": str(exc), "fix": "Check the dashboard server logs for the full stack trace."}
