"""
Models.dev loader -- fetch, filter, and cache model catalog.

On every server startup this module:

1. Fetches the full model catalog from ``https://models.dev/api.json``.
2. Reads ``~/.local/share/opencode/auth.json`` to discover which providers
   the user has API keys or OAuth sessions for.
3. Reads the Ostwin-managed opencode.json for any custom providers.
4. Filters the catalog to only include models from configured providers.
5. Writes the result to ``~/.ostwin/.agents/configured_models.json``
   so it can be served without re-fetching.

The ``get_configured_models()`` function returns the current in-memory
catalog (populated at startup or on demand).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.request
import urllib.error
import ollama
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from dashboard.lib.opencode_paths import (
    get_managed_opencode_config_path,
    get_user_opencode_config_path,
)

logger = logging.getLogger(__name__)

MODELS_DEV_URL = "https://models.dev/api.json"
MODELS_DEV_LOGO_URL = "https://models.dev/logos/{provider}.svg"

AUTH_JSON_PATH = Path.home() / ".local" / "share" / "opencode" / "auth.json"
OPENCODE_CONFIG_PATH = get_managed_opencode_config_path()
USER_OPENCODE_CONFIG_PATH = get_user_opencode_config_path()
CONFIGURED_MODELS_PATH = (
    Path.home() / ".ostwin" / ".agents" / "configured_models.json"
)

# Home-directory raw catalog cache.
_HOME_RAW_PATH = CONFIGURED_MODELS_PATH.parent / "models_dev_raw.json"


# In-memory cache
_cached_models: Optional[Dict[str, Any]] = None
_cached_timestamp: float = 0.0


# ── Public API ────────────────────────────────────────────────────────


def load_models_on_startup() -> Dict[str, Any]:
    """Fetch models.dev/api.json and build configured_models.json.

    Called during server startup.  Returns the configured models dict.
    """
    global _cached_models, _cached_timestamp

    raw_catalog = _fetch_models_dev()
    if raw_catalog is None:
        # Fallback: try reading from cached file
        raw_catalog = _read_cached_raw()
        if raw_catalog is None:
            logger.warning("[MODELS] No models catalog available (network failed and no disk cache) -- using empty catalog")
            _cached_models = {"providers": {}, "loaded_at": _iso_now()}
            return _cached_models
        logger.info("[MODELS] Network fetch failed, loaded raw catalog from disk cache")
    else:
        logger.info("[MODELS] Successfully fetched fresh catalog from models.dev")

    configured_providers = _read_configured_providers()
    configured = _build_configured_models(raw_catalog, configured_providers)

    # Persist to disk
    _write_json(CONFIGURED_MODELS_PATH, configured)

    _cached_models = configured
    _cached_timestamp = time.time()
    logger.info(
        "Models catalog loaded: %d providers, %d total models",
        len(configured.get("providers", {})),
        sum(len(p.get("models", {})) for p in configured.get("providers", {}).values()),
    )
    return configured


def rebuild_configured_models_from_cache() -> Dict[str, Any]:
    """Rebuild configured_models.json from the cached raw catalog.

    This is used after local auth changes, such as Codex OAuth login, where
    provider discovery changed but the full models.dev catalog does not need a
    network refetch.
    """
    global _cached_models, _cached_timestamp

    raw_catalog = _read_cached_raw()
    if raw_catalog is None:
        logger.warning("[MODELS] Cannot rebuild configured models: no raw catalog cache")
        _cached_models = {"providers": {}, "loaded_at": _iso_now()}
        _cached_timestamp = time.time()
        return _cached_models

    configured_providers = _read_configured_providers()
    configured = _build_configured_models(raw_catalog, configured_providers)
    _write_json(CONFIGURED_MODELS_PATH, configured)
    _cached_models = configured
    _cached_timestamp = time.time()
    logger.info(
        "Models catalog rebuilt from cache: %d providers, %d total models",
        len(configured.get("providers", {})),
        sum(len(p.get("models", {})) for p in configured.get("providers", {}).values()),
    )
    return configured


def get_configured_models() -> Dict[str, Any]:
    """Return the in-memory configured models.

    If not yet loaded (e.g. startup hasn't run), loads from disk cache
    or fetches fresh.
    """
    global _cached_models
    if _cached_models is not None:
        return _cached_models
    # Try disk cache first
    if CONFIGURED_MODELS_PATH.exists():
        try:
            _cached_models = json.loads(CONFIGURED_MODELS_PATH.read_text())
            return _cached_models
        except (json.JSONDecodeError, OSError):
            pass
    # Fall back to full load
    return load_models_on_startup()


def get_configured_providers() -> Dict[str, Any]:
    """Return the configured providers from settings, auth.json, opencode.json, and vault."""
    return _read_configured_providers()


def get_provider_logo_url(provider_id: str) -> str:
    """Return the logo URL for a provider."""
    return MODELS_DEV_LOGO_URL.format(provider=provider_id)


def get_model_registry_from_configured() -> Dict[str, List[dict]]:
    """Build the model registry dict in the format the frontend expects.

    Returns ``{provider_display_name: [model_dict, ...]}`` where each
    model_dict has keys: id, label, context_window, tier, provider_id,
    family, cost, logo_url.

    This replaces the old hardcoded ``_CATALOG`` in models_registry.py.
    """
    configured = get_configured_models()
    providers = configured.get("providers", {})

    registry: Dict[str, List[dict]] = {}

    for provider_id, provider_data in providers.items():
        display_name = provider_data.get("name", provider_id)
        models_map = provider_data.get("models", {})

        model_list: List[dict] = []
        for model_id, model_data in models_map.items():
            limit = model_data.get("limit", {})
            ctx = limit.get("context")
            ctx_str = _format_context_window(ctx) if ctx else ""

            cost = model_data.get("cost", {})

            registry_id = f"{provider_id}/{model_id}"

            model_entry = {
                "id": registry_id,
                "label": model_data.get("name", model_id),
                "context_window": ctx_str,
                "tier": _classify_tier(model_data),
                "provider_id": provider_id,
                "family": model_data.get("family", ""),
                "cost": cost,
                "logo_url": get_provider_logo_url(provider_id),
                "reasoning": model_data.get("reasoning", False),
                "tool_call": model_data.get("tool_call", False),
                "attachment": model_data.get("attachment", False),
                "source": model_data.get("source", "models.dev"),
            }
            model_list.append(model_entry)

        if model_list:
            registry[display_name] = model_list

    return registry


def get_available_providers() -> List[Dict[str, Any]]:
    """Return all providers from models.dev for the Add Provider browser.

    This intentionally uses the raw models.dev cache/catalog, not the
    configured-models cache, because the picker needs to show providers before
    they have been configured.
    """
    raw_catalog = _read_cached_raw()
    if raw_catalog is None:
        raw_catalog = _fetch_models_dev() or _read_cached_raw() or {}

    configured_ids = set(_read_configured_providers())
    result: List[Dict[str, Any]] = []
    for provider_id, provider_data in raw_catalog.items():
        if not isinstance(provider_data, dict):
            continue
        models = provider_data.get("models", {})
        if not isinstance(models, dict):
            models = {}
        env = provider_data.get("env", [])
        if not isinstance(env, list):
            env = []
        result.append(
            {
                "id": provider_id,
                "name": provider_data.get("name") or provider_id,
                "logo_url": get_provider_logo_url(provider_id),
                "model_count": len(models),
                "doc": provider_data.get("doc", ""),
                "env": env,
                "already_configured": provider_id in configured_ids,
            }
        )

    result.sort(key=lambda item: str(item.get("name", "")).lower())
    return result


@lru_cache(maxsize=1024)
def get_context_limit(provider_id: str, model_id: str) -> tuple[int, int]:
    """Return (context_limit, output_limit) for a given provider and model.

    If model_id contains a slash (e.g. "openai/gpt-4o"), it will be split.
    Uses @lru_cache for performance.

    Returns (0, 0) if not found.
    """

    if provider_id == "ollama":
        extra = show_ollama_model(model_id)
        ctx = extra.get("context_length") or 32768
        out = 2048
        return ctx, out

    if "/" in model_id:
        p_prefix, m_id = model_id.split("/", 1)
        if p_prefix:
            provider_id = p_prefix
            model_id = m_id

    configured = get_configured_models()
    provider_data = configured.get("providers", {}).get(provider_id)
    if not provider_data:
        return 0, 0

    model_data = provider_data.get("models", {}).get(model_id)
    if not model_data:
        return 0, 0

    limit = model_data.get("limit", {})
    ctx = limit.get("context", 0)
    out = limit.get("output", 0)

    return ctx, out


def count_tokens(messages: List[Dict[str, Any]], model: str = "gpt-4o") -> int:
    """Approximate token count for a list of messages.

    Uses tiktoken if available, falls back to character count heuristic.
    """
    try:
        import tiktoken

        try:
            encoding = tiktoken.encoding_for_model(model)
        except Exception:
            encoding = tiktoken.get_encoding("cl100k_base")

        n = 0
        for m in messages:
            n += 4  # overhead
            for k, v in m.items():
                if isinstance(v, str):
                    n += len(encoding.encode(v))
        n += 2  # priming
        return n
    except Exception:
        # Fallback: sum of string lengths / 4
        return sum(len(str(v)) for m in messages for v in m.values()) // 4


def _trim_text(text: str, max_chars: int) -> str:
    """Trim text to at most max_chars, preserving start of content."""
    if len(text) <= max_chars:
        return text
    if max_chars <= 0:
        return ""
    return text[:max_chars]


def truncate_messages(
    messages: List[Dict[str, Any]],
    context_limit: int,
    buffer_percent: float = 0.1,
    model: str = "gpt-4o",
) -> List[Dict[str, Any]]:
    """Truncate messages to fit within context_limit with a buffer (default 10%).

    Instead of removing messages, this trims message content from the tail
    so that the total token count fits within 90% of context_limit.
    System messages are preserved intact as long as possible; the last
    non-system message is trimmed first.
    """
    if context_limit <= 0:
        return messages

    target = int(context_limit * (1.0 - buffer_percent))
    result = [dict(m) for m in messages]

    total = count_tokens(result, model)
    if total <= target:
        return result

    # Strategy: trim from the end of the last non-system message content.
    # If that is still too large after trimming to empty, proceed to the
    # previous non-system message, and so on.
    non_system_indices = [i for i, m in enumerate(result) if m.get("role") != "system"]

    for idx in reversed(non_system_indices):
        if total <= target:
            break
        content = result[idx].get("content", "")
        if not isinstance(content, str) or not content:
            continue

        # Binary-search for the max content length that fits
        lo, hi = 0, len(content)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            result[idx]["content"] = content[:mid]
            if count_tokens(result, model) <= target:
                lo = mid
            else:
                hi = mid - 1

        result[idx]["content"] = content[:lo]
        total = count_tokens(result, model)

    # If still over (e.g. system message alone exceeds limit), trim it too
    if total > target:
        for idx, m in enumerate(result):
            if total <= target:
                break
            content = m.get("content", "")
            if not isinstance(content, str) or not content:
                continue
            lo, hi = 0, len(content)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                result[idx]["content"] = content[:mid]
                if count_tokens(result, model) <= target:
                    lo = mid
                else:
                    hi = mid - 1
            result[idx]["content"] = content[:lo]
            total = count_tokens(result, model)

    return result


# ── Ollama SDK Integration ──────────────────────────────────────────


@lru_cache(maxsize=1)
def list_ollama_models() -> List[Dict[str, Any]]:
    """List locally available Ollama models using the Python SDK (cached)."""
    try:
        resp = ollama.list()
        # resp.models is a list of Model objects
        result = []
        for m in getattr(resp, "models", []):
            details = getattr(m, "details", None)
            result.append(
                {
                    "model": m.model,
                    "modified_at": m.modified_at.isoformat() if m.modified_at else "",
                    "size": m.size,
                    "family": details.family if details else "",
                    "parameter_size": details.parameter_size if details else "",
                    "quantization_level": details.quantization_level if details else "",
                }
            )
        return result
    except Exception as exc:
        logger.debug("Failed to list Ollama models: %s", exc)
        return []


@lru_cache(maxsize=128)
def show_ollama_model(model_name: str) -> Dict[str, Any]:
    """Return detailed information about an Ollama model (cached).

    Extracts context length and other metadata from modelinfo if available.
    """
    try:
        resp = ollama.show(model_name)
        info = getattr(resp, "modelinfo", {})
        arch = info.get("general.architecture")
        ctx_len = 0
        if arch:
            ctx_len = info.get(f"{arch}.context_length", 0)

        return {
            "modelfile": getattr(resp, "modelfile", ""),
            "parameters": getattr(resp, "parameters", ""),
            "template": getattr(resp, "template", ""),
            "system": getattr(resp, "system", ""),
            "details": getattr(resp, "details", {}),
            "modelinfo": info,
            "context_length": ctx_len,
        }
    except Exception as exc:
        logger.debug("Failed to show Ollama model '%s': %s", model_name, exc)
        return {}


def truncate_messages_for_model(
    messages: List[Dict[str, Any]],
    provider: str,
    model: str,
    buffer_percent: float = 0.1,
) -> List[Dict[str, Any]]:
    """Truncate message content to fit within a model's context window.

    Orchestrates context-limit lookup (including Ollama SDK fallback) and
    delegates to :func:`truncate_messages` for the actual content trimming.

    Returns the input list unchanged when the context limit cannot be
    determined or the messages already fit.
    """
    clean_model = model
    if "/" in clean_model:
        clean_model = clean_model.split("/", 1)[1]

    ctx_limit, _ = get_context_limit(provider, clean_model)

    if ctx_limit <= 0 and provider == "ollama":
        info = show_ollama_model(clean_model)
        ctx_limit = info.get("context_length", 0)

    if ctx_limit <= 0:
        return messages

    return truncate_messages(messages, ctx_limit, buffer_percent=buffer_percent, model=clean_model)


def invalidate_cache() -> None:
    """Clear the in-memory cache, forcing a reload on next access."""
    global _cached_models, _cached_timestamp
    _cached_models = None
    _cached_timestamp = 0.0
    get_context_limit.cache_clear()
    list_ollama_models.cache_clear()
    show_ollama_model.cache_clear()
    _list_opencode_models.cache_clear()


# ── Internal helpers ──────────────────────────────────────────────────



def _fetch_models_dev() -> Optional[Dict[str, Any]]:
    """Fetch the full models catalog from models.dev."""
    logger.info("[MODELS] Fetching catalog from %s", MODELS_DEV_URL)
    try:
        req = urllib.request.Request(
            MODELS_DEV_URL,
            headers={
                "User-Agent": "ostwin-dashboard/1.0",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

            # ── Write to the home-directory cache ────────────────────────
            _write_json(_HOME_RAW_PATH, data)
            logger.info("Fetched models.dev catalog: %d providers", len(data))
            return data
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to fetch models.dev/api.json: %s", exc)
        return None


def _read_cached_raw() -> Optional[Dict[str, Any]]:
    """Read the raw models.dev cache from disk.

    The cache lives under ``~/.ostwin/.agents/models_dev_raw.json`` and is
    updated on successful network fetches. The repository no longer ships or
    mutates a project-level raw catalog.
    """
    if _HOME_RAW_PATH.exists():
        try:
            data = json.loads(_HOME_RAW_PATH.read_text())
            if data:  # non-empty dict is valid
                return data
        except (json.JSONDecodeError, OSError):
            pass

    return None


def _settings_config_paths() -> List[Path]:
    """Return settings config candidates in the same spirit as SettingsResolver."""
    explicit_config = os.environ.get("OSTWIN_CONFIG_PATH")
    if explicit_config:
        return [Path(explicit_config).expanduser()]

    paths: List[Path] = []
    explicit_project = os.environ.get("OSTWIN_PROJECT_DIR")
    if explicit_project:
        paths.append(Path(explicit_project).expanduser() / ".agents" / "config.json")
    else:
        paths.append(Path.home() / ".ostwin" / ".agents" / "config.json")

    try:
        from dashboard.api_utils import AGENTS_DIR

        paths.append(AGENTS_DIR / "config.json")
    except Exception:
        pass

    if explicit_project:
        paths.append(Path.home() / ".ostwin" / ".agents" / "config.json")

    deduped: List[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            deduped.append(path)
            seen.add(key)
    return deduped


def _read_settings_config() -> Dict[str, Any]:
    """Read the active dashboard settings config, if present."""
    for config_path in _settings_config_paths():
        if not config_path.exists():
            continue
        try:
            data = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read settings config %s: %s", config_path, exc)
            continue
        if isinstance(data, dict):
            return data
    return {}


def _read_settings_provider_entries() -> Dict[str, Dict[str, Any]]:
    """Return provider entries from .agents/config.json, including dynamic providers."""
    providers_data = _read_settings_config().get("providers", {})
    if not isinstance(providers_data, dict):
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    for provider_id, provider_cfg in providers_data.items():
        if provider_id == "custom" and isinstance(provider_cfg, dict):
            for custom_id, custom_cfg in provider_cfg.items():
                if isinstance(custom_cfg, dict):
                    result[custom_id] = custom_cfg
            continue
        if isinstance(provider_cfg, dict):
            result[provider_id] = provider_cfg
    return result


def _provider_config_disabled(provider_cfg: Dict[str, Any]) -> bool:
    """Return whether a provider config explicitly hides/disables a provider."""
    if provider_cfg.get("enabled") is False:
        return True
    # dismissed is a UI-only state for dynamically added providers. If a
    # first-class provider is explicitly enabled, a stale dismissed flag should
    # not remove it from the runtime model catalog.
    return provider_cfg.get("dismissed") is True and provider_cfg.get("enabled") is not True


def _settings_provider_info(
    provider_id: str,
    provider_cfg: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Build discovery metadata for a provider from dashboard settings."""
    if _provider_config_disabled(provider_cfg):
        return None

    provider_type = "local" if provider_id == "ollama" else "settings"
    info: Dict[str, Any] = {
        "type": provider_type,
        "source": "settings",
        "has_key": False,
    }

    if provider_id == "google":
        mode = provider_cfg.get("deployment_mode") or _read_google_deployment_mode()
        has_auth_hint = bool(
            provider_cfg.get("api_key_ref")
            or provider_cfg.get("project_id")
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        )
        if not has_auth_hint:
            return None
        info["has_key"] = True
        info["deployment_mode"] = mode
        return info

    if provider_id == "ollama":
        info["has_key"] = True
        return info

    has_auth_hint = bool(
        provider_cfg.get("api_key_ref")
        or provider_cfg.get("base_url")
        or provider_cfg.get("default_model")
        or provider_cfg.get("enabled_models")
    )
    if not has_auth_hint:
        return None
    info["has_key"] = bool(provider_cfg.get("api_key_ref"))
    return info


def _read_configured_providers() -> Dict[str, Dict[str, Any]]:
    """Read settings + auth.json + opencode.json + env vars + vault providers.

    Returns ``{provider_id: {type, source, has_key, ...}}``.
    """
    providers: Dict[str, Dict[str, Any]] = {}

    # 1. auth.json -- native providers. OpenCode stores ChatGPT/Codex login as
    #    ``type: oauth`` for the normal ``openai`` provider, not as a separate
    #    ``codex`` provider.
    if AUTH_JSON_PATH.exists():
        try:
            auth_data = json.loads(AUTH_JSON_PATH.read_text())
            for provider_id, entry in auth_data.items():
                if not isinstance(entry, dict):
                    continue
                auth_type = entry.get("type")
                if auth_type in {"api", "oauth"}:
                    if auth_type == "oauth":
                        has_key = bool(entry.get("access") or entry.get("refresh"))
                    else:
                        has_key = bool(entry.get("key"))
                    providers[provider_id] = {
                        "type": auth_type,
                        "source": "auth.json",
                        "has_key": has_key,
                    }
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read auth.json: %s", exc)

    # 2. opencode.json -- custom providers (provider block)
    for opencode_path in (OPENCODE_CONFIG_PATH, USER_OPENCODE_CONFIG_PATH):
        if not opencode_path.exists():
            continue
        try:
            oc_data = json.loads(opencode_path.read_text())
            for provider_id, entry in oc_data.get("provider", {}).items():
                if provider_id not in providers:
                    providers[provider_id] = {
                        "type": "custom",
                        "source": str(opencode_path),
                        "has_key": bool(entry.get("options", {}).get("apiKey")),
                    }
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read opencode.json %s: %s", opencode_path, exc)

    # 3. Dashboard settings -- provider cards persist here. This is the
    #    canonical source for runtime model selection, so do not require an
    #    opencode/auth side-effect before exposing those models.
    settings_entries = _read_settings_provider_entries()
    disabled_provider_ids = {
        provider_id
        for provider_id, provider_cfg in settings_entries.items()
        if _provider_config_disabled(provider_cfg)
    }
    for provider_id in disabled_provider_ids:
        providers.pop(provider_id, None)

    for provider_id, provider_cfg in settings_entries.items():
        if provider_id in disabled_provider_ids:
            continue
        info = _settings_provider_info(provider_id, provider_cfg)
        if info is None:
            continue
        existing = providers.get(provider_id)
        if existing is None:
            providers[provider_id] = info
        elif provider_id == "google":
            existing["deployment_mode"] = info.get("deployment_mode") or existing.get(
                "deployment_mode"
            )

    # 4. Env-based providers -- Google authenticates via env vars loaded
    #    from ~/.ostwin/.env, NOT via auth.json.  Detect it here.
    if "google" not in disabled_provider_ids:
        has_gcp = bool(os.environ.get("GOOGLE_CLOUD_PROJECT"))
        has_api_key = bool(os.environ.get("GOOGLE_API_KEY"))
        has_creds = bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
        if has_gcp or has_api_key or has_creds:
            providers["google"] = {
                "type": "env",
                "source": "env",
                "has_key": True,
                "deployment_mode": _read_google_deployment_mode(),
            }

    # 5. Vault -- catch any provider key stored via AddProviderModal that
    #    hasn't been synced to auth.json yet.  Keys like
    #    ``google_service_account`` are internal vault entries, not providers.
    _VAULT_SKIP = {"google_service_account"}
    try:
        from .vault import get_vault

        vault = get_vault()
        vault_keys = vault.list_keys("providers")
        for vault_key in vault_keys:
            if (
                vault_key in providers
                or vault_key in _VAULT_SKIP
                or vault_key in disabled_provider_ids
            ):
                continue
            providers[vault_key] = {
                "type": "api",
                "source": "vault",
                "has_key": True,
            }
    except Exception as exc:
        logger.debug("Vault provider discovery skipped: %s", exc)

    # 5. Always inject Google deployment mode if Google is present.
    # Because it dictates which companion catalogs to merge.
    if "google" in providers:
        providers["google"]["deployment_mode"] = _read_google_deployment_mode()

    return providers


def _read_google_deployment_mode() -> str:
    """Read the Google deployment mode from .agents/config.json.

    Returns ``"vertex"`` or ``"gemini"`` (default).
    """
    try:
        config = _read_settings_config()
        providers = config.get("providers", {})
        if isinstance(providers, dict):
            google = providers.get("google", {})
            if isinstance(google, dict):
                return google.get("deployment_mode", "vertex")
    except Exception:
        pass
    # If GOOGLE_CLOUD_PROJECT is set, assume vertex
    if os.environ.get("GOOGLE_CLOUD_PROJECT"):
        return "vertex"
    return "gemini"


# Companion providers keyed by (provider_id, deployment_mode).
# When Google is in Vertex mode, pull from google-vertex + google-vertex-anthropic.
# When Google is in Gemini mode, only the base "google" catalog is used.
_COMPANION_PROVIDERS: Dict[str, Dict[str, List[str]]] = {
    "google": {
        "vertex": ["google-vertex", "google-vertex-anthropic"],
        "gemini": [],  # base catalog only
    },
}


@lru_cache(maxsize=16)
def _list_opencode_models(provider_id: str) -> Set[str]:
    """Return model ids OpenCode actually exposes for a provider.

    models.dev can list API-key models that are not available through a user's
    OpenCode OAuth credential.  OpenAI Codex login is one such case.
    """
    env = os.environ.copy()
    env.pop("OPENCODE_CONFIG", None)
    try:
        result = subprocess.run(
            ["opencode", "models", provider_id],
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("Could not list OpenCode models for %s: %s", provider_id, exc)
        return set()

    if result.returncode != 0:
        logger.debug(
            "OpenCode model listing failed for %s: %s",
            provider_id,
            (result.stderr or result.stdout or "").strip(),
        )
        return set()

    models = {
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.lstrip().startswith(("┌", "│", "└", "●"))
    }
    short = {
        model.split("/", 1)[1]
        for model in models
        if model.startswith(f"{provider_id}/") and "/" in model
    }
    return models | short


def _filter_oauth_provider_models(
    provider_id: str,
    provider_cfg: Dict[str, Any],
    provider_entry: Dict[str, Any],
) -> None:
    if provider_id != "openai" or provider_cfg.get("type") != "oauth":
        return

    allowed = _list_opencode_models(provider_id)
    if not allowed:
        return

    provider_entry["models"] = {
        model_id: model_data
        for model_id, model_data in provider_entry["models"].items()
        if model_id in allowed or f"{provider_id}/{model_id}" in allowed
    }


def _build_configured_models(
    raw_catalog: Dict[str, Any],
    configured_providers: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Build configured_models from models.dev + opencode.json custom models.

    Two sources are merged per provider:

    1. **models.dev catalog** -- rich metadata (cost, limits, modalities).
       Each model is tagged ``"source": "models.dev"``.
    2. **opencode.json provider block** -- custom / manually-added models.
       Each model is tagged ``"source": "custom"``.  These appear even
       when the provider doesn't exist in models.dev at all.
    3. **Companion providers** -- e.g. when ``google`` is configured,
       models from ``google-vertex`` and ``google-vertex-anthropic`` in
       models.dev are also included (with prefixed IDs).

    Returns the structured configured_models.json content.
    """
    # Read the opencode.json provider block once
    custom_providers = _read_opencode_custom_providers()
    suppress_native_copilot = (
        "github-copilot" in configured_providers
        and "github-copilot-oauth" in configured_providers
        and "github-copilot-oauth" in custom_providers
    )
    visible_provider_ids = {
        provider_id
        for provider_id in configured_providers.keys()
        if not (suppress_native_copilot and provider_id == "github-copilot")
    }

    result: Dict[str, Any] = {
        "loaded_at": _iso_now(),
        "source": MODELS_DEV_URL,
        "configured_provider_ids": sorted(visible_provider_ids),
        "providers": {},
    }

    for provider_id, provider_cfg in configured_providers.items():
        if suppress_native_copilot and provider_id == "github-copilot":
            continue

        raw_provider = raw_catalog.get(provider_id)
        custom_block = custom_providers.get(provider_id)

        # Skip providers that exist in neither source
        if raw_provider is None and custom_block is None:
            logger.debug(
                "Provider '%s' configured in %s but not found in "
                "models.dev or opencode.json",
                provider_id,
                provider_cfg.get("source", "?"),
            )
            continue

        # Build provider metadata (prefer models.dev, fall back to custom)
        if raw_provider is not None:
            provider_entry: Dict[str, Any] = {
                "id": provider_id,
                "name": raw_provider.get("name", provider_id),
                "doc": raw_provider.get("doc", ""),
                "api": raw_provider.get("api", ""),
                "npm": raw_provider.get("npm", ""),
                "env": raw_provider.get("env", []),
                "logo_url": get_provider_logo_url(provider_id),
                "source": provider_cfg.get("source", ""),
                "models": {},
            }
        else:
            # Provider only exists in opencode.json
            base_url = (custom_block or {}).get("options", {}).get("baseURL", "")
            provider_entry = {
                "id": provider_id,
                "name": provider_id,
                "doc": "",
                "api": base_url,
                "npm": "",
                "env": [],
                "logo_url": get_provider_logo_url(provider_id),
                "source": "opencode.json",
                "models": {},
            }

        # Resolve companion providers.
        mode = provider_cfg.get("deployment_mode", "")
        companions_by_mode = _COMPANION_PROVIDERS.get(provider_id, {})
        companion_ids = companions_by_mode.get(mode, []) if mode else []
        if not companion_ids and isinstance(companions_by_mode, list):
            companion_ids = companions_by_mode

        # ── 1) Ingest models.dev base models ──────────────────────
        # Always include base models regardless of deployment mode.
        if raw_provider is not None:
            for model_id, model_data in raw_provider.get("models", {}).items():
                provider_entry["models"][model_id] = {
                    "id": model_id,
                    "name": model_data.get("name", model_id),
                    "family": model_data.get("family", ""),
                    "reasoning": model_data.get("reasoning", False),
                    "tool_call": model_data.get("tool_call", False),
                    "attachment": model_data.get("attachment", False),
                    "temperature": model_data.get("temperature", True),
                    "cost": model_data.get("cost", {}),
                    "limit": model_data.get("limit", {}),
                    "modalities": model_data.get("modalities", {}),
                    "knowledge": model_data.get("knowledge", ""),
                    "release_date": model_data.get("release_date", ""),
                    "source": "models.dev",
                }

        # ── 2) Emit companion providers as SEPARATE top-level entries
        # This ensures the UI groups them independently (e.g. "Google
        # Vertex AI" vs "Google") rather than merging everything under
        # one flat list.
        for companion_id in companion_ids:
            companion_raw = raw_catalog.get(companion_id)
            if companion_raw is None:
                continue
            companion_entry = {
                "id": companion_id,
                "name": companion_raw.get("name", companion_id),
                "doc": companion_raw.get("doc", ""),
                "api": companion_raw.get("api", ""),
                "npm": companion_raw.get("npm", ""),
                "env": companion_raw.get("env", []),
                "logo_url": get_provider_logo_url(provider_id),
                "source": "companion",
                "parent_provider": provider_id,
                "models": {},
            }
            for model_id, model_data in companion_raw.get("models", {}).items():
                companion_entry["models"][model_id] = {
                    "id": model_id,
                    "name": model_data.get("name", model_id),
                    "family": model_data.get("family", ""),
                    "reasoning": model_data.get("reasoning", False),
                    "tool_call": model_data.get("tool_call", False),
                    "attachment": model_data.get("attachment", False),
                    "temperature": model_data.get("temperature", True),
                    "cost": model_data.get("cost", {}),
                    "limit": model_data.get("limit", {}),
                    "modalities": model_data.get("modalities", {}),
                    "knowledge": model_data.get("knowledge", ""),
                    "release_date": model_data.get("release_date", ""),
                    "source": "models.dev",
                    "companion_provider": companion_id,
                }
            if companion_entry["models"]:
                result["providers"][companion_id] = companion_entry

        # ── 3) Merge custom models from opencode.json ─────────────
        if custom_block is not None:
            for model_key, model_def in custom_block.get("models", {}).items():
                # The opencode model key is the short id (e.g. "seed-2-0-pro-260328").
                # Build the full model id the same way opencode does:
                #   name field like "byteplus:seed-2-0-pro-260328"
                oc_name = model_def.get("name", model_key)
                # If the model already came from models.dev, skip it
                if model_key in provider_entry["models"]:
                    continue
                provider_entry["models"][model_key] = {
                    "id": model_key,
                    "name": oc_name,
                    "family": "",
                    "reasoning": False,
                    "tool_call": False,
                    "attachment": False,
                    "temperature": True,
                    "cost": {},
                    "limit": {},
                    "modalities": {},
                    "knowledge": "",
                    "release_date": "",
                    "source": "custom",
                }

        # ── 4) Merge local Ollama models if provider is ollama ────
        if provider_id == "ollama":
            local_models = list_ollama_models()
            for lm in local_models:
                m_id = lm["model"]
                if m_id not in provider_entry["models"]:
                    # Fetch extra details (context window) for local models
                    extra = show_ollama_model(m_id)
                    ctx_len = extra.get("context_length") or 32768

                    provider_entry["models"][m_id] = {
                        "id": m_id,
                        "name": m_id,
                        "family": lm.get("family", ""),
                        "reasoning": False,
                        "tool_call": True,  # Heuristic for Ollama models
                        "attachment": False,
                        "temperature": True,
                        "cost": {"input": 0, "output": 0},
                        "limit": {"context": ctx_len, "output": 4096},
                        "modalities": {"input": ["text"], "output": ["text"]},
                        "source": "ollama-local",
                        "size": lm.get("size"),
                        "parameter_size": lm.get("parameter_size"),
                        "quantization_level": lm.get("quantization_level"),
                    }

        _filter_oauth_provider_models(provider_id, provider_cfg, provider_entry)

        if provider_entry["models"]:
            result["providers"][provider_id] = provider_entry

    return result


def _read_opencode_custom_providers() -> Dict[str, Any]:
    """Read the ``provider`` block from opencode.json.

    Returns ``{provider_id: {options, models}}``.
    """
    providers: Dict[str, Any] = {}
    for opencode_path in (OPENCODE_CONFIG_PATH, USER_OPENCODE_CONFIG_PATH):
        if not opencode_path.exists():
            continue
        try:
            data = json.loads(opencode_path.read_text())
            provider_block = data.get("provider", {})
            if isinstance(provider_block, dict):
                providers.update(provider_block)
        except (json.JSONDecodeError, OSError):
            continue
    return providers


def _format_context_window(ctx: int) -> str:
    """Format token count to human-readable string."""
    if ctx >= 1_000_000:
        val = ctx / 1_000_000
        return f"{val:g}M"
    elif ctx >= 1_000:
        val = ctx / 1_000
        return f"{val:g}K"
    return str(ctx)


def _classify_tier(model_data: dict) -> str:
    """Classify a model into a tier based on its properties."""
    if model_data.get("reasoning"):
        return "reasoning"
    cost = model_data.get("cost", {})
    input_cost = cost.get("input", 0)
    if input_cost >= 10:
        return "flagship"
    elif input_cost >= 1:
        return "balanced"
    elif input_cost > 0:
        return "fast"
    return "unknown"


def _iso_now() -> str:
    """Return current UTC time as ISO string."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    """Atomically write a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, default=str) + "\n")
        os.replace(str(tmp), str(path))
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
