"""
Canonical model registry.

Single source of truth for every model the platform knows about.
The ``get_model_registry()`` function returns the catalog filtered
by which providers are actually enabled in the current settings.

The catalog is populated dynamically from ``models.dev/api.json``
(fetched at server startup) and filtered by which providers the user
has configured in ``~/.local/share/opencode/auth.json`` and
the Ostwin-managed opencode.json.

A static fallback catalog is kept for the four legacy providers
(Anthropic, OpenAI, Google/Gemini, BytePlus) so the system works
even if models.dev is unreachable and no cache exists.

Provider mapping for OpenCode sync
-----------------------------------
Only providers that require a custom ``provider`` block in
the Ostwin-managed opencode.json are listed here.  Providers
natively supported by OpenCode (Anthropic, OpenAI) are excluded.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ── Provider auth types ───────────────────────────────────────────────


class ProviderAuthType(str, enum.Enum):
    """How a provider authenticates with OpenCode.

    A provider can use multiple types (e.g. Azure uses both AUTH_JSON
    and ENV for different credentials).
    """

    AUTH_JSON = "auth_json"  # ~/.local/share/opencode/auth.json
    OPENAI_COMPATIBLE = (
        "openai_compatible"  # Ostwin-managed opencode.json provider block
    )
    ENV = "env"  # environment variables only


# ── Model entry ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ModelEntry:
    id: str
    label: str
    context_window: str
    tier: str
    mode: Optional[str] = None  # 'gemini' | 'vertex' for Google models


# ── Static fallback catalog ──────────────────────────────────────────
# Used only when models.dev is unreachable AND no cached models exist.

_FALLBACK_CATALOG: Dict[str, List[ModelEntry]] = {
    "Claude": [
        ModelEntry("claude-opus-4-6", "Claude Opus 4.6", "200K", "flagship"),
        ModelEntry("claude-sonnet-4-6", "Claude Sonnet 4.6", "200K", "balanced"),
        ModelEntry("claude-haiku-4-5", "Claude Haiku 4.5", "200K", "fast"),
    ],
    "GPT": [
        ModelEntry("gpt-4.1", "GPT-4.1", "1M", "flagship"),
        ModelEntry("gpt-4.1-mini", "GPT-4.1 Mini", "1M", "fast"),
        ModelEntry("o3", "o3", "200K", "reasoning"),
        ModelEntry("o4-mini", "o4-mini", "200K", "reasoning"),
    ],
    # Only google-vertex/* and google-vertex-anthropic/* are kept here.
    # Gemini API-mode models (gemini/*) come exclusively from the live
    # models.dev dynamic catalog so they are never stale or bare-ID-qualified.
    "Gemini": [
        ModelEntry(
            "google-vertex/gemini-3.1-pro-preview",
            "Vertex Gemini 3.1 Pro",
            "1M",
            "flagship",
            mode="vertex",
        ),
        ModelEntry(
            "google-vertex/gemini-3-flash-preview",
            "Vertex Gemini 3 Flash",
            "1M",
            "balanced",
            mode="vertex",
        ),
        ModelEntry(
            "google-vertex/gemini-3-flash-lite-preview",
            "Vertex Gemini 3 Flash Lite",
            "1M",
            "fast",
            mode="vertex",
        ),
        ModelEntry(
            "google-vertex-anthropic/claude-sonnet-4-6@default",
            "Vertex Claude Sonnet 4.6",
            "200K",
            "balanced",
            mode="vertex",
        ),
        ModelEntry(
            "google-vertex-anthropic/claude-haiku-4-5@20251001",
            "Vertex Claude Haiku 4.5",
            "200K",
            "fast",
            mode="vertex",
        ),
        ModelEntry(
            "google-vertex/zai-org/glm-5-maas",
            "Vertex GLM-5 MaaS",
            "128K",
            "balanced",
            mode="vertex",
        ),
    ],
    "BytePlus": [
        ModelEntry("byteplus/seed-2-0-pro-260328", "Seed 2.0 Pro", "256K", "flagship"),
        ModelEntry(
            "byteplus/seed-2-0-lite-260228", "Seed 2.0 Lite", "256K", "balanced"
        ),
        ModelEntry("byteplus/seed-2-0-mini-260215", "Seed 2.0 Mini", "256K", "fast"),
        ModelEntry("byteplus/seed-1-8-251228", "Seed 1.8", "256K", "balanced"),
        ModelEntry("byteplus/glm-4-7-251222", "GLM-4 7B", "256K", "balanced"),
        ModelEntry(
            "byteplus/deepseek-v3-2-251201", "DeepSeek V3.2", "128K", "balanced"
        ),
        ModelEntry("byteplus/seed-1-6-250915", "Seed 1.6 Vision", "256K", "vision"),
        ModelEntry("byteplus/seed-1-6-flash-250715", "Seed 1.6 Flash", "256K", "fast"),
    ],
}

# Alias for backward compatibility
_CATALOG = _FALLBACK_CATALOG


def get_full_catalog() -> Dict[str, List[ModelEntry]]:
    """Return the unfiltered static fallback catalog (for internal use / tests)."""
    return _FALLBACK_CATALOG


def get_model_registry(
    *,
    google_enabled: bool = True,
    google_mode: str = "vertex",
    google_models: Optional[List[str]] = None,
    byteplus_enabled: bool = True,
    byteplus_models: Optional[List[str]] = None,
    anthropic_enabled: bool = True,
    anthropic_models: Optional[List[str]] = None,
    openai_enabled: bool = True,
    openai_models: Optional[List[str]] = None,
) -> Dict[str, List[dict]]:
    """Return the model registry filtered by enabled providers and models.

    First tries to use the dynamic models.dev catalog.  Falls back to
    the static ``_FALLBACK_CATALOG`` if no dynamic data is available.

    Each ``*_models`` parameter is an allowlist of model IDs.  When
    ``None`` or empty, **all** models for that provider are included.

    Returns the same dict-of-lists format the ``/api/models/registry``
    endpoint has always served, so callers don't need to change.
    """
    # Build the registry by merging dynamic (models.dev + custom) with
    # the static fallback.  Dynamic entries always win.
    registry: Dict[str, List[dict]] = {}

    # Map: dynamic display-name → static legacy name it replaces.
    # Also map lowercase provider-id → static name so that custom
    # providers like "byteplus" supersede static "BytePlus".
    _DYNAMIC_REPLACES_STATIC: Dict[str, str] = {
        "OpenAI": "GPT",
        "Anthropic": "Claude",
        "Google": "Gemini",
    }
    _PID_REPLACES_STATIC: Dict[str, str] = {
        "byteplus": "BytePlus",
        "gemini": "Gemini",
        "google": "Gemini",
        "openai": "GPT",
        "anthropic": "Claude",
    }

    # 1. Try dynamic models from models.dev + custom
    dynamic: Dict[str, List[dict]] = {}
    try:
        from .models_dev_loader import get_model_registry_from_configured

        dynamic = get_model_registry_from_configured() or {}
    except Exception as exc:
        logger.debug("Dynamic model registry unavailable: %s", exc)

    # 2. Build static fallback
    static = _get_static_registry(
        google_enabled=google_enabled,
        google_mode=google_mode,
        google_models=google_models,
        byteplus_enabled=byteplus_enabled,
        byteplus_models=byteplus_models,
        anthropic_enabled=anthropic_enabled,
        anthropic_models=anthropic_models,
        openai_enabled=openai_enabled,
        openai_models=openai_models,
    )

    # 3. Determine which static keys are superseded
    superseded: Set[str] = set()
    for dyn_name in dynamic:
        # Check display-name mapping
        legacy = _DYNAMIC_REPLACES_STATIC.get(dyn_name)
        if legacy:
            superseded.add(legacy)
        # Check provider-id mapping (dyn_name may be a raw pid like "byteplus")
        legacy = _PID_REPLACES_STATIC.get(dyn_name.lower())
        if legacy:
            superseded.add(legacy)
        # If the dynamic key is identical to a static key, it wins
        if dyn_name in static:
            superseded.add(dyn_name)

    # Also check provider_id inside the model entries
    for models in dynamic.values():
        for m in models:
            pid = m.get("provider_id", "")
            legacy = _PID_REPLACES_STATIC.get(pid)
            if legacy:
                superseded.add(legacy)

    for name, models in static.items():
        if name not in superseded:
            registry[name] = models

    # 4. Add dynamic entries
    registry.update(dynamic)

    return registry


def _get_static_registry(
    *,
    google_enabled: bool = True,
    google_mode: str = "vertex",  # kept for API compat; fallback is always vertex
    google_models: Optional[List[str]] = None,
    byteplus_enabled: bool = True,
    byteplus_models: Optional[List[str]] = None,
    anthropic_enabled: bool = True,
    anthropic_models: Optional[List[str]] = None,
    openai_enabled: bool = True,
    openai_models: Optional[List[str]] = None,
) -> Dict[str, List[dict]]:
    """Static fallback registry builder.

    All Google entries are ``google-vertex/*`` or ``google-vertex-anthropic/*``.
    Gemini API-mode models are intentionally absent here; they come from the
    live models.dev dynamic catalog instead.
    """
    registry: Dict[str, List[dict]] = {}

    def _to_dict(m: ModelEntry) -> dict:
        d: dict = {
            "id": m.id,
            "label": m.label,
            "context_window": m.context_window,
            "tier": m.tier,
        }
        if m.mode:
            d["mode"] = m.mode
        return d

    def _filter(
        entries: List[ModelEntry], allowlist: Optional[List[str]]
    ) -> List[dict]:
        if allowlist:
            allow_set = set(allowlist)
            return [_to_dict(m) for m in entries if m.id in allow_set]
        return [_to_dict(m) for m in entries]

    # Claude
    if anthropic_enabled:
        models = _filter(_FALLBACK_CATALOG["Claude"], anthropic_models)
        if models:
            registry["Claude"] = models

    # GPT
    if openai_enabled:
        models = _filter(_FALLBACK_CATALOG["GPT"], openai_models)
        if models:
            registry["GPT"] = models

    # Gemini (Vertex only) -- all entries are already google-vertex/* or
    # google-vertex-anthropic/*; no mode filter needed.
    if google_enabled:
        models = _filter(_FALLBACK_CATALOG["Gemini"], google_models)
        if models:
            registry["Gemini"] = models

    # BytePlus
    if byteplus_enabled:
        models = _filter(_FALLBACK_CATALOG["BytePlus"], byteplus_models)
        if models:
            registry["BytePlus"] = models

    return registry


# ── OpenCode provider definitions ─────────────────────────────────────
# These define how to map dashboard providers -> opencode.json
# ``provider`` block.  Only providers that need a custom opencode
# provider entry are listed.


@dataclass(frozen=True)
class OpenCodeProviderDef:
    """Describes how to write a provider block in opencode.json."""

    opencode_key: str  # key under "provider" in opencode.json
    vault_scope: str  # vault scope for the API key
    vault_key: str  # vault key for the API key
    base_url: str  # baseURL for the openai-compatible shim (empty for non-HTTP providers like Vertex)
    npm_package: str = "@ai-sdk/openai-compatible"
    # map of model_id -> {"npm": ..., "name": ...}
    # populated dynamically from the catalog
    registry_filter_provider: str = ""  # provider key in _CATALOG
    registry_filter_mode: Optional[str] = None  # mode filter (e.g. "gemini")
    model_name_prefix: str = ""  # prefix for model name in opencode (e.g. "gemini:")
    # When set, only catalog entries whose id starts with this prefix are
    # included. Lets multiple providers share one registry_filter_provider
    # bucket (e.g. google-vertex/* vs google-vertex-anthropic/* under "Gemini").
    id_prefix: str = ""
    # When False, sync skips the api_key vault fetch. Used by Vertex AI,
    # which authenticates via ADC / service account rather than an API key.
    requires_api_key: bool = True
    # Discriminator for the options block builder: "api_key" (default) writes
    # {"apiKey": ..., "baseURL": ...}; "vertex" writes {"project", "location"}.
    auth_strategy: str = "api_key"


OPENCODE_PROVIDERS: Dict[str, OpenCodeProviderDef] = {
    "gemini": OpenCodeProviderDef(
        opencode_key="gemini",
        vault_scope="providers",
        vault_key="google",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        registry_filter_provider="Gemini",
        registry_filter_mode="gemini",
        model_name_prefix="gemini:",
    ),
    "byteplus": OpenCodeProviderDef(
        opencode_key="byteplus",
        vault_scope="providers",
        vault_key="byteplus",
        base_url="https://ark.ap-southeast.bytepluses.com/api/v3",
        registry_filter_provider="BytePlus",
        registry_filter_mode=None,
        model_name_prefix="byteplus:",
    ),
    "google-vertex": OpenCodeProviderDef(
        opencode_key="google-vertex",
        vault_scope="providers",
        vault_key="google",
        base_url="",
        npm_package="@ai-sdk/google-vertex",
        registry_filter_provider="Gemini",
        registry_filter_mode="vertex",
        model_name_prefix="google-vertex:",
        id_prefix="google-vertex/",
        requires_api_key=False,
        auth_strategy="vertex",
    ),
    "google-vertex-anthropic": OpenCodeProviderDef(
        opencode_key="google-vertex-anthropic",
        vault_scope="providers",
        vault_key="google",
        base_url="",
        npm_package="@ai-sdk/google-vertex",
        registry_filter_provider="Gemini",
        registry_filter_mode="vertex",
        model_name_prefix="google-vertex-anthropic:",
        id_prefix="google-vertex-anthropic/",
        requires_api_key=False,
        auth_strategy="vertex",
    ),
}


# ── auth.json provider definitions ────────────────────────────────────
# Providers whose API key is written to
# ``~/.local/share/opencode/auth.json`` as ``{"type":"api","key":"..."}``


@dataclass(frozen=True)
class AuthJsonProviderDef:
    """Maps a vault key to an auth.json entry."""

    auth_json_key: str  # key in auth.json (e.g. "anthropic")
    vault_scope: str  # vault scope
    vault_key: str  # vault key
    auth_types: frozenset  # which auth mechanisms this provider uses


AUTH_JSON_PROVIDERS: Dict[str, AuthJsonProviderDef] = {
    "anthropic": AuthJsonProviderDef(
        auth_json_key="anthropic",
        vault_scope="providers",
        vault_key="anthropic",
        auth_types=frozenset({ProviderAuthType.AUTH_JSON}),
    ),
    "openai": AuthJsonProviderDef(
        auth_json_key="openai",
        vault_scope="providers",
        vault_key="openai",
        auth_types=frozenset({ProviderAuthType.AUTH_JSON}),
    ),
    "azure": AuthJsonProviderDef(
        auth_json_key="azure",
        vault_scope="providers",
        vault_key="azure",
        auth_types=frozenset({ProviderAuthType.AUTH_JSON, ProviderAuthType.ENV}),
    ),
    "xai": AuthJsonProviderDef(
        auth_json_key="xai",
        vault_scope="providers",
        vault_key="xai",
        auth_types=frozenset({ProviderAuthType.AUTH_JSON}),
    ),
    "deepseek": AuthJsonProviderDef(
        auth_json_key="deepseek",
        vault_scope="providers",
        vault_key="deepseek",
        auth_types=frozenset({ProviderAuthType.AUTH_JSON}),
    ),
    "openrouter": AuthJsonProviderDef(
        auth_json_key="openrouter",
        vault_scope="providers",
        vault_key="openrouter",
        auth_types=frozenset({ProviderAuthType.AUTH_JSON}),
    ),
    "moonshotai": AuthJsonProviderDef(
        auth_json_key="moonshotai",
        vault_scope="providers",
        vault_key="moonshotai",
        auth_types=frozenset({ProviderAuthType.AUTH_JSON}),
    ),
    "lmstudio": AuthJsonProviderDef(
        auth_json_key="lmstudio",
        vault_scope="providers",
        vault_key="lmstudio",
        auth_types=frozenset({ProviderAuthType.AUTH_JSON}),
    ),
    "zai": AuthJsonProviderDef(
        auth_json_key="zai",
        vault_scope="providers",
        vault_key="zai",
        auth_types=frozenset({ProviderAuthType.AUTH_JSON}),
    ),
}


def build_opencode_models(
    provider_def: OpenCodeProviderDef,
    enabled_models: Optional[List[str]] = None,
) -> Dict[str, dict]:
    """Build the ``models`` dict for an opencode.json provider block.

    Derives model entries from the canonical catalog so they never drift.

    Parameters
    ----------
    enabled_models : list[str], optional
        Allowlist of model IDs.  When ``None`` or empty, all models
        for the provider are included.
    """
    catalog_entries = _CATALOG.get(provider_def.registry_filter_provider, [])
    allow_set = set(enabled_models) if enabled_models else None

    models: Dict[str, dict] = {}
    for entry in catalog_entries:
        # Apply mode filter if set
        if (
            provider_def.registry_filter_mode
            and entry.mode != provider_def.registry_filter_mode
        ):
            continue

        # Apply id-prefix filter if set. Lets multiple providers share one
        # catalog bucket (e.g. google-vertex/* vs google-vertex-anthropic/*).
        if provider_def.id_prefix and not entry.id.startswith(
            provider_def.id_prefix
        ):
            continue

        # Apply allowlist
        if allow_set and entry.id not in allow_set:
            continue

        # The model key in opencode.json is the short id (after the prefix)
        # e.g. "gemini/gemini-3-flash-preview" -> "gemini-3-flash-preview"
        short_id = entry.id.split("/", 1)[-1] if "/" in entry.id else entry.id

        models[short_id] = {
            "npm": provider_def.npm_package,
            "name": f"{provider_def.model_name_prefix}{short_id}",
        }

    return models
