"""
OpenCode config sync.

Keeps two files aligned with the dashboard vault:

1. ``~/.ostwin/.opencode/opencode.json`` -- ``provider`` block for
   OpenAI-compatible providers (gemini, byteplus).
2. ``~/.local/share/opencode/auth.json`` -- ``{"type":"api","key":"…"}``
   entries for native providers (anthropic, openai, azure, xai, …), while
   preserving native OpenCode OAuth sessions such as OpenAI subscription auth.

Some providers (e.g. Azure) use **both** auth.json *and* ENV vars.
ENV-only providers (AWS Bedrock) are not synced here -- the user
manages those env vars directly.

Sync is triggered:
* Automatically when a vault secret in the ``providers`` scope is
  stored or deleted.
* Manually via ``POST /api/settings/opencode/sync``.

Both syncs are **additive / merge-only**: they never remove keys
from the target files that they didn't write.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from dashboard.lib.opencode_paths import get_managed_opencode_config_path

from .models_registry import (
    AUTH_JSON_PROVIDERS,
    OPENCODE_PROVIDERS,
    OpenCodeProviderDef,
    build_opencode_models,
)

logger = logging.getLogger(__name__)

OPENCODE_CONFIG_PATH = get_managed_opencode_config_path()
AUTH_JSON_PATH = Path.home() / ".local" / "share" / "opencode" / "auth.json"
OPENCODE_SCHEMA = "https://opencode.ai/config.json"


# ── Result types ──────────────────────────────────────────────────────


@dataclass
class TargetResult:
    """Outcome for a single target file."""

    synced: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    path: str = ""
    error: Optional[str] = None


@dataclass
class SyncResult:
    """Outcome of the full sync (both targets combined)."""

    synced: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    path: str = ""  # primary path (opencode.json)
    error: Optional[str] = None
    # Per-target breakdown
    opencode_json: Optional[TargetResult] = None
    auth_json: Optional[TargetResult] = None


# ── Public API ────────────────────────────────────────────────────────


def sync_opencode_config(
    *,
    vault=None,
    settings=None,
    config_path: Optional[Path] = None,
    auth_path: Optional[Path] = None,
) -> SyncResult:
    """Sync vault keys to both opencode.json and auth.json.

    Parameters
    ----------
    vault : SettingsVault, optional
    settings : MasterSettings, optional
    config_path : Path, optional   -- override for opencode.json
    auth_path : Path, optional     -- override for auth.json
    """
    if vault is None:
        from .vault import get_vault

        vault = get_vault()
    if settings is None:
        from .resolver import get_settings_resolver

        settings = get_settings_resolver().get_master_settings()

    oc = _sync_opencode_json(vault, settings, config_path or OPENCODE_CONFIG_PATH)
    aj = _sync_auth_json(vault, settings, auth_path or AUTH_JSON_PATH)

    # Merge into a flat SyncResult for backward compat
    all_synced = oc.synced + aj.synced
    all_removed = oc.removed + aj.removed
    all_skipped = oc.skipped + aj.skipped
    errors = [e for e in [oc.error, aj.error] if e]

    return SyncResult(
        synced=all_synced,
        removed=all_removed,
        skipped=all_skipped,
        path=oc.path,
        error="; ".join(errors) if errors else None,
        opencode_json=oc,
        auth_json=aj,
    )


# ── opencode.json sync (OpenAI-compatible providers) ─────────────────


def _sync_opencode_json(vault, settings, target: Path) -> TargetResult:
    synced: List[str] = []
    removed: List[str] = []
    skipped: List[str] = []

    existing = _load_json(target, skeleton={"$schema": OPENCODE_SCHEMA})
    provider_block: Dict[str, Any] = existing.get("provider", {})

    for name, pdef in OPENCODE_PROVIDERS.items():
        should_sync = _should_sync_provider(name, pdef, settings, vault=vault)

        if not should_sync:
            if name in provider_block:
                del provider_block[name]
                removed.append(name)
            else:
                skipped.append(name)
            continue

        api_key: Optional[str] = None
        if pdef.requires_api_key:
            try:
                api_key = vault.get(pdef.vault_scope, pdef.vault_key)
            except Exception as exc:
                logger.warning(
                    "Vault read failed for %s/%s: %s",
                    pdef.vault_scope,
                    pdef.vault_key,
                    exc,
                )
                skipped.append(name)
                continue

            if not api_key:
                if name in provider_block:
                    del provider_block[name]
                    removed.append(name)
                else:
                    skipped.append(name)
                continue

        options = _resolve_options(name, pdef, settings, api_key=api_key)
        if options is None:
            # Required config missing (e.g. Vertex without project_id).
            if name in provider_block:
                del provider_block[name]
                removed.append(name)
            else:
                skipped.append(name)
            continue

        enabled_models = _resolve_enabled_models(name, settings)
        models = build_opencode_models(pdef, enabled_models=enabled_models)

        provider_block[name] = {
            "options": options,
            "models": models,
        }
        synced.append(name)

    existing["$schema"] = OPENCODE_SCHEMA
    if provider_block:
        existing["provider"] = provider_block
    elif "provider" in existing:
        del existing["provider"]

    try:
        _write_json(target, existing)
    except Exception as exc:
        return TargetResult(
            skipped=list(OPENCODE_PROVIDERS),
            path=str(target),
            error=str(exc),
        )

    return TargetResult(
        synced=synced, removed=removed, skipped=skipped, path=str(target)
    )


# ── auth.json sync (native API-key providers) ────────────────────────


def _sync_auth_json(vault, settings, target: Path) -> TargetResult:
    synced: List[str] = []
    removed: List[str] = []
    skipped: List[str] = []

    existing = _load_json(target, skeleton={})

    # 1) Sync providers with explicit registry definitions
    for name, adef in AUTH_JSON_PROVIDERS.items():
        provider_settings = getattr(settings.providers, name, None)
        if name == "openai" and getattr(provider_settings, "auth_mode", None) == "codex_oauth":
            skipped.append(name)
            continue

        try:
            api_key = vault.get(adef.vault_scope, adef.vault_key)
        except Exception as exc:
            logger.warning(
                "Vault read failed for %s/%s: %s", adef.vault_scope, adef.vault_key, exc
            )
            skipped.append(name)
            continue

        auth_json_key = adef.auth_json_key
        existing_entry = existing.get(auth_json_key)
        if _is_oauth_entry(existing_entry):
            skipped.append(name)
            continue

        if not api_key:
            if (
                auth_json_key in existing
                and isinstance(existing.get(auth_json_key), dict)
                and existing[auth_json_key].get("type") == "api"
            ):
                del existing[adef.auth_json_key]
                removed.append(name)
            else:
                skipped.append(name)
            continue

        existing[auth_json_key] = {
            "type": "api",
            "key": api_key,
        }
        synced.append(name)

    # 2) Sync any additional vault providers not in the registry.
    #    This allows dynamically-added providers (via AddProviderModal)
    #    to appear in auth.json without a hardcoded definition.
    _SKIP_DYNAMIC = {
        # Already handled above or via opencode.json provider block
        *AUTH_JSON_PROVIDERS.keys(),
        *OPENCODE_PROVIDERS.keys(),
        # Providers that authenticate via env vars / service accounts,
        # not auth.json API keys
        "google",
        "google_service_account",
    }
    try:
        vault_keys = vault.list_keys("providers")
    except Exception as exc:
        logger.warning("Failed to list vault provider keys: %s", exc)
        vault_keys = {}

    for vault_key in vault_keys:
        if vault_key in _SKIP_DYNAMIC:
            continue
        try:
            api_key = vault.get("providers", vault_key)
        except Exception as exc:
            logger.warning("Vault read failed for providers/%s: %s", vault_key, exc)
            skipped.append(vault_key)
            continue

        existing_entry = existing.get(vault_key)
        if _is_oauth_entry(existing_entry):
            skipped.append(vault_key)
            continue

        if not api_key:
            if vault_key in existing:
                del existing[vault_key]
                removed.append(vault_key)
            else:
                skipped.append(vault_key)
            continue

        existing[vault_key] = {
            "type": "api",
            "key": api_key,
        }
        synced.append(vault_key)

    try:
        _write_json(target, existing)
    except Exception as exc:
        return TargetResult(
            skipped=list(AUTH_JSON_PROVIDERS),
            path=str(target),
            error=str(exc),
        )

    return TargetResult(
        synced=synced, removed=removed, skipped=skipped, path=str(target)
    )


# ── Internal helpers ──────────────────────────────────────────────────


def _should_sync_provider(
    name: str,
    pdef: OpenCodeProviderDef,
    settings,
    vault=None,
) -> bool:
    """Determine whether a provider should be synced to opencode.json."""
    if name == "gemini":
        google = settings.providers.google
        if google is not None:
            if not google.enabled:
                return False
            if google.deployment_mode == "vertex":
                return False
            return True
        if vault is not None:
            try:
                return vault.get(pdef.vault_scope, pdef.vault_key) is not None
            except Exception:
                pass
        return True

    if name in ("google-vertex", "google-vertex-anthropic"):
        google = settings.providers.google
        if google is None:
            return False
        if not google.enabled:
            return False
        return google.deployment_mode == "vertex"

    if name == "byteplus":
        bp = settings.providers.byteplus
        if bp is not None:
            return bp.enabled
        if vault is not None:
            try:
                return vault.get(pdef.vault_scope, pdef.vault_key) is not None
            except Exception:
                pass
        return True

    return False


def _resolve_enabled_models(name: str, settings) -> Optional[list]:
    """Return the enabled_models allowlist from settings, or None for all."""
    if name == "gemini":
        google = settings.providers.google
        if google and google.enabled_models:
            return google.enabled_models
    elif name == "byteplus":
        bp = settings.providers.byteplus
        if bp and bp.enabled_models:
            return bp.enabled_models
    return None


def _resolve_base_url(name: str, pdef: OpenCodeProviderDef, settings) -> str:
    """Return the base_url from settings if set, otherwise the default."""
    if name == "gemini":
        google = settings.providers.google
        if google and google.base_url:
            return google.base_url
    elif name == "byteplus":
        bp = settings.providers.byteplus
        if bp and bp.base_url:
            return bp.base_url
    return pdef.base_url


def _resolve_options(
    name: str,
    pdef: OpenCodeProviderDef,
    settings,
    *,
    api_key: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Build the options block for an opencode.json provider entry.

    Returns ``None`` when required config is missing (caller will skip/remove
    the provider). Returns a dict otherwise.

    Discriminated by ``pdef.auth_strategy``:
    * ``"api_key"`` (default) -- ``{"apiKey": ..., "baseURL": ...}``
    * ``"vertex"``            -- ``{"project": ..., "location": ...}``
    """
    if pdef.auth_strategy == "vertex":
        google = settings.providers.google
        if google is None:
            return None
        project = google.project_id or ""
        if not project:
            # Vertex requires a project. Without one, opencode would fail at
            # request time anyway -- skip cleanly instead.
            return None
        return {
            "project": project,
            "location": google.vertex_location or "global",
        }

    # Default: openai-compatible HTTP shim.
    return {
        "apiKey": api_key,
        "baseURL": _resolve_base_url(name, pdef, settings),
    }


def _load_json(path: Path, *, skeleton: Dict[str, Any]) -> Dict[str, Any]:
    """Load existing JSON or return a skeleton."""
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read %s, starting fresh", path)
    return dict(skeleton)


def _is_oauth_entry(entry: Any) -> bool:
    """Return whether an auth.json entry is managed by OpenCode OAuth."""
    return isinstance(entry, dict) and entry.get("type") == "oauth"


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    """Atomically write a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        os.replace(str(tmp), str(path))
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
