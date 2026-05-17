"""Centralized configuration for the Agentic Memory system.

Loads defaults from ``config.default.json`` (shipped with the package).

Config file resolution order (later wins):
    1. config.default.json  — bundled package defaults
    2. <project_root>/.agents/config.json  — project-level settings
    3. ~/.ostwin/.agents/config.json  — user-level dashboard settings

Note: Environment variable overrides have been disabled. All settings will
be managed via the backend in future versions.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).resolve().parent


@dataclass
class LLMConfig:
    """LLM configuration.

    Defaults match ``config.default.json`` so there is a single source of truth.
    Valid backends: ``"ollama"``, ``"gemini"``, ``"openai"``, ``"openai-compatible"``,
    ``"anthropic"``, or any provider supported by ``dashboard.llm_client``.

    When ``backend`` is ``"openai-compatible"``, ``compatible_url`` provides the
    API endpoint URL and ``compatible_key`` provides an optional API key.
    """
    backend: str = "openai-compatible"
    model: str = "google-vertex/gemini-3-flash-preview"
    compatible_url: str = ""
    compatible_key: str = ""


@dataclass
class EmbeddingConfig:
    """Embedding configuration.

    Defaults match ``config.default.json`` so there is a single source of truth.
    Valid backends: ``"ollama"``, ``"gemini"``, ``"openai-compatible"``.

    When ``backend`` is ``"openai-compatible"``, ``compatible_url`` provides the
    API endpoint URL and ``compatible_key`` provides an optional API key.
    """

    backend: str = "openai-compatible"
    model: str = "gemini-embedding-2"
    compatible_url: str = ""
    compatible_key: str = ""


@dataclass
class VectorConfig:
    backend: str = "zvec"


@dataclass
class SearchConfig:
    similarity_weight: float = 0.8
    decay_half_life_days: float = 30.0


@dataclass
class EvolutionConfig:
    max_links: int = 3
    context_aware: bool = True
    context_aware_tree: bool = False


@dataclass
class SyncConfig:
    auto_sync: bool = True
    auto_sync_interval: int = 60  # seconds
    conflict_resolution: str = "last_modified"  # "last_modified" or "llm"


@dataclass
class MemoryConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    vector: VectorConfig = field(default_factory=VectorConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    evolution: EvolutionConfig = field(default_factory=EvolutionConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    disabled_tools: List[str] = field(default_factory=list)


def _load_json_defaults() -> dict:
    """Load defaults from config.default.json if it exists."""
    config_path = _CONFIG_DIR / "config.default.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}





def _find_project_root() -> Optional[Path]:
    """Find the project root by looking for .git or .agents directory.

    Walks up from current working directory to find the project root.
    Returns None if no project root is found.
    """
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".git").exists() or (parent / ".agents").exists():
            return parent
    return None


def _load_json_config(config_path: Path) -> dict:
    """Load and parse a JSON config file, returning empty dict on failure."""
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("Failed to load config from %s: %s", config_path, e)
        return {}


def _extract_memory_settings(raw: dict) -> dict:
    """Extract and map memory settings from a flat config schema.

    The config has a flat ``memory`` key with settings like:
        { "memory": { "llm_backend": "ollama", "llm_model": "...", ... } }

    Returns a nested dict matching the shape of ``config.default.json``.
    """
    flat = raw.get("memory", {})
    if not isinstance(flat, dict) or not flat:
        return {}

    # Map the flat dashboard keys → nested config.default.json shape.
    result: dict = {}
    if flat.get("llm_backend") or flat.get("llm_model") or flat.get("llm_compatible_url") or flat.get("llm_compatible_key"):
        result["llm"] = {}
        if flat.get("llm_backend"):
            result["llm"]["backend"] = flat["llm_backend"]
        if flat.get("llm_model"):
            result["llm"]["model"] = flat["llm_model"]
        if flat.get("llm_compatible_url"):
            result["llm"]["compatible_url"] = flat["llm_compatible_url"]
        if flat.get("llm_compatible_key"):
            result["llm"]["compatible_key"] = flat["llm_compatible_key"]

    if flat.get("embedding_backend") or flat.get("embedding_model") or flat.get("embedding_compatible_url") or flat.get("embedding_compatible_key"):
        result["embedding"] = {}
        if flat.get("embedding_backend"):
            result["embedding"]["backend"] = flat["embedding_backend"]
        if flat.get("embedding_model"):
            result["embedding"]["model"] = flat["embedding_model"]
        if flat.get("embedding_compatible_url"):
            result["embedding"]["compatible_url"] = flat["embedding_compatible_url"]
        if flat.get("embedding_compatible_key"):
            result["embedding"]["compatible_key"] = flat["embedding_compatible_key"]

    if flat.get("vector_backend"):
        result["vector"] = {"backend": flat["vector_backend"]}

    if "context_aware" in flat:
        result.setdefault("evolution", {})["context_aware"] = flat["context_aware"]
    if "context_aware_tree" in flat:
        result.setdefault("evolution", {})["context_aware_tree"] = flat["context_aware_tree"]
    if "max_links" in flat:
        result.setdefault("evolution", {})["max_links"] = int(flat["max_links"])

    if "auto_sync" in flat:
        result.setdefault("sync", {})["auto_sync"] = flat["auto_sync"]
    # Accept both old name (auto_sync_interval) and new name (sync_interval_s)
    sync_interval = flat.get("sync_interval_s") or flat.get("auto_sync_interval")
    if sync_interval is not None:
        result.setdefault("sync", {})["auto_sync_interval"] = int(sync_interval)
    if "conflict_resolution" in flat:
        result.setdefault("sync", {})["conflict_resolution"] = flat["conflict_resolution"]

    # Accept both old name (ttl_days) and new name (decay_half_life_days)
    decay = flat.get("decay_half_life_days") or flat.get("ttl_days")
    if decay is not None:
        result.setdefault("search", {})["decay_half_life_days"] = float(decay)
    if "similarity_weight" in flat:
        result.setdefault("search", {})["similarity_weight"] = float(flat["similarity_weight"])

    # Pool settings — passed through to pool_config.py
    pool = {}
    if "pool_idle_timeout_s" in flat:
        pool["idle_timeout_s"] = int(flat["pool_idle_timeout_s"])
    if "pool_max_instances" in flat:
        pool["max_instances"] = int(flat["pool_max_instances"])
    if "pool_eviction_policy" in flat:
        pool["eviction_policy"] = flat["pool_eviction_policy"]
    if "pool_sync_interval_s" in flat:
        pool["sync_interval_s"] = int(flat["pool_sync_interval_s"])
    if pool:
        result["pool"] = pool

    return result


def _load_system_settings() -> dict:
    """Load memory settings from dashboard/system config files.

    Resolution order (later wins):
      1. Project-level config: ``<project_root>/.agents/config.json``
      2. User-level config: ``~/.ostwin/.agents/config.json`` (dashboard UI settings)

    This function reads files fresh on every call so the MCP server always
    reflects the latest configuration without a restart.

    Returns a nested dict matching the shape of ``config.default.json`` so it
    can be merged directly into the defaults dict.
    """
    result: dict = {}

    # Layer 1: Project-level config (if running in a project context)
    project_root = _find_project_root()
    if project_root:
        project_config_path = project_root / ".agents" / "config.json"
        project_raw = _load_json_config(project_config_path)
        project_settings = _extract_memory_settings(project_raw)
        for section_key in ("llm", "embedding", "vector", "search", "evolution", "sync", "pool"):
            if section_key in project_settings:
                result.setdefault(section_key, {}).update(project_settings[section_key])

    # Layer 2: User-level config (dashboard settings)
    user_config_path = Path.home() / ".ostwin" / ".agents" / "config.json"
    user_raw = _load_json_config(user_config_path)
    user_settings = _extract_memory_settings(user_raw)
    for section_key in ("llm", "embedding", "vector", "search", "evolution", "sync", "pool"):
        if section_key in user_settings:
            result.setdefault(section_key, {}).update(user_settings[section_key])

    return result


def load_config() -> MemoryConfig:
    """Build a MemoryConfig by merging multiple config sources.

    Resolution order (later wins):
      1. ``config.default.json``  — bundled package defaults
      2. ``<project_root>/.agents/config.json``  — project-level settings
      3. ``~/.ostwin/.agents/config.json``  — user-level dashboard settings

    All config files are re-read on every call so the MCP server always
    reflects the latest configuration without a restart.
    """
    d = _load_json_defaults()

    # Layer 2 & 3: merge project and user settings on top of defaults
    sys_settings = _load_system_settings()
    for section_key in ("llm", "embedding", "vector", "search", "evolution", "sync", "pool"):
        if section_key in sys_settings:
            d.setdefault(section_key, {}).update(sys_settings[section_key])

    llm_d = d.get("llm", {})
    embedding_d = d.get("embedding", {})
    vector_d = d.get("vector", {})
    search_d = d.get("search", {})
    evo_d = d.get("evolution", {})
    sync_d = d.get("sync", {})

    config = MemoryConfig(
        llm=LLMConfig(
            backend=llm_d.get("backend", "openai-compatible"),
            model=llm_d.get("model", "google-vertex/gemini-3-flash-preview"),
            compatible_url=llm_d.get("compatible_url", ""),
            compatible_key=llm_d.get("compatible_key", ""),
        ),
        embedding=EmbeddingConfig(
            backend=embedding_d.get("backend", "openai-compatible"),
            model=embedding_d.get("model", "google-vertex/gemini-embedding-001"),
            compatible_url=embedding_d.get("compatible_url", ""),
            compatible_key=embedding_d.get("compatible_key", ""),
        ),
        vector=VectorConfig(
            backend=vector_d.get("backend", "zvec"),
        ),
        search=SearchConfig(
            similarity_weight=search_d.get("similarity_weight", 0.8),
            decay_half_life_days=search_d.get("decay_half_life_days", 30.0),
        ),
        evolution=EvolutionConfig(
            max_links=evo_d.get("max_links", 3),
            context_aware=evo_d.get("context_aware", True),
            context_aware_tree=evo_d.get("context_aware_tree", False),
        ),
        sync=SyncConfig(
            auto_sync=sync_d.get("auto_sync", True),
            auto_sync_interval=sync_d.get("auto_sync_interval", 60),
            conflict_resolution=sync_d.get("conflict_resolution", "last_modified"),
        ),
        disabled_tools=d.get("disabled_tools", []),
    )
    return config
