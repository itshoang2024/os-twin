import json
import logging
import os
import re
import threading
from typing import Any, Dict, Optional, List
from pathlib import Path
from copy import deepcopy

from dashboard.models import (
    MasterSettings,
    EffectiveResolution,
    RoleSettings,
    RuntimeSettings,
    MemorySettings,
    AutonomySettings,
    ObservabilitySettings,
    ProvidersNamespace,
    ChannelsNamespace,
    KnowledgeSettings,
)
from dashboard.api_utils import AGENTS_DIR, PROJECT_ROOT
from .vault import get_vault

logger = logging.getLogger(__name__)

VAULT_REF_PATTERN = re.compile(r"\$\{vault:([^/]+)/([^}]+)\}")
RUNTIME_MANAGER_KEYS = (
    "poll_interval_seconds",
    "max_concurrent_rooms",
    "max_engineer_retries",
    "state_timeout_seconds",
    "auto_approve_tools",
    "dynamic_pipelines",
)
RUNTIME_RUNTIME_KEYS = ("master_agent_model",)


def _default_config_path() -> Path:
    """Resolve the active settings file at runtime.

    The source checkout contains a project-local ``.agents/config.json`` used
    by tests and fixtures, but the dashboard's user-facing settings live under
    ``~/.ostwin/.agents/config.json`` unless a project dir/config path is
    explicitly supplied.
    """
    explicit_config = os.environ.get("OSTWIN_CONFIG_PATH")
    if explicit_config:
        return Path(explicit_config).expanduser()

    explicit_project = os.environ.get("OSTWIN_PROJECT_DIR")
    if explicit_project:
        return Path(explicit_project).expanduser() / ".agents" / "config.json"

    global_config = Path.home() / ".ostwin" / ".agents" / "config.json"
    if global_config.exists():
        return global_config

    return AGENTS_DIR / "config.json"


class SettingsResolver:
    """Unified settings resolver with vault integration and role overrides.
    
    Loads settings from .agents/config.json and supports:
    - Global settings (top-level keys in config.json)
    - Role-level defaults
    - Plan-level role overrides
    - Room-level role overrides
    - Vault secret references (${vault:scope/key})
    - Secret masking for safe display
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or _default_config_path()
        self.vault = get_vault()
        self._cache: Optional[Dict[str, Any]] = None
    
    def load_config(self) -> Dict[str, Any]:
        """Load config from disk, with caching."""
        if self._cache is None:
            if self.config_path.exists():
                self._cache = json.loads(self.config_path.read_text())
            else:
                self._cache = {}
        return deepcopy(self._cache)
    
    def save_config(self, config: Dict[str, Any]) -> None:
        """Save config to disk atomically and invalidate cache."""
        self._atomic_write_json(self.config_path, config)
        self._cache = None

    @staticmethod
    def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
        """Write JSON atomically via tmp + rename."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        try:
            tmp_path.write_text(json.dumps(data, indent=2))
            os.replace(str(tmp_path), str(path))
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise
    
    def get_master_settings(self) -> MasterSettings:
        """Get master settings (vault refs preserved as strings, never dereferenced)."""
        config = self.load_config()
        
        # Extract and convert to MasterSettings
        providers = self._extract_providers(config)
        roles = self._extract_roles(config)
        runtime = self._extract_runtime(config)
        memory = self._extract_memory(config)
        channels = self._extract_channels(config)
        autonomy = self._extract_autonomy(config)
        observability = self._extract_observability(config)
        knowledge = self._extract_knowledge(config)
        
        return MasterSettings(
            providers=providers,
            roles=roles,
            runtime=runtime,
            memory=memory,
            channels=channels,
            autonomy=autonomy,
            observability=observability,
            knowledge=knowledge,
        )
    
    def resolve_role(
        self,
        role: str,
        plan_id: Optional[str] = None,
        task_ref: Optional[str] = None,
        masked: bool = False,
    ) -> EffectiveResolution:
        """Resolve effective settings for a role with overrides.
        
        Resolution order (later overrides earlier):
        1. Built-in role defaults
        2. Global role config (config.json)
        3. Plan-level role override
        4. Room-level role override
        
        skill_refs and disabled_skills are merged as unions across layers.
        All other fields use last-write-wins.
        
        Args:
            role: Role name (e.g., 'engineer', 'qa')
            plan_id: Optional plan ID for plan-level override
            task_ref: Optional task reference for room-level override
            masked: If True, mask secrets as ***
            
        Returns:
            EffectiveResolution with effective settings and provenance
        """
        effective: Dict[str, Any] = {}
        provenance: Dict[str, str] = {}
        
        # 1. Built-in defaults
        from dashboard.constants import ROLE_DEFAULTS
        defaults = ROLE_DEFAULTS.get(role, {})
        for key, value in defaults.items():
            effective[key] = value
            provenance[key] = "default"
        
        # 2. Global role config
        config = self.load_config()
        global_role_config = config.get(role, {})
        for key, value in global_role_config.items():
            if key in ["instances"]:  # Skip non-settings keys
                continue
            if key in ("skill_refs", "disabled_skills"):
                effective[key] = list(set(effective.get(key, []) + value))
            else:
                effective[key] = value
            provenance[key] = "global"
        
        # 3. Plan-level override (from {plan_id}.roles.json — flat structure)
        if plan_id:
            plan_config = self._load_plan_config(plan_id)
            plan_role_config = plan_config.get(role, {})
            # Also pick up plan-level attached_skills
            attached_skills = plan_config.get("attached_skills", [])
            for key, value in plan_role_config.items():
                if key in ("skill_refs", "disabled_skills"):
                    effective[key] = list(set(effective.get(key, []) + value))
                else:
                    effective[key] = value
                provenance[key] = f"plan:{plan_id}"
            if attached_skills:
                effective["skill_refs"] = list(
                    set(effective.get("skill_refs", []) + attached_skills)
                )
                provenance.setdefault("skill_refs", f"plan:{plan_id}")
        
        # 4. Room-level override
        if plan_id and task_ref:
            room_config = self._load_room_config(plan_id, task_ref)
            room_role_config = room_config.get("role_config", {}).get(role, {})
            for key, value in room_role_config.items():
                if key in ("skill_refs", "disabled_skills"):
                    effective[key] = list(set(effective.get(key, []) + value))
                else:
                    effective[key] = value
                provenance[key] = f"room:{task_ref}"
        
        # 5. Filter skill_refs: remove disabled, keep only globally enabled
        if "skill_refs" in effective:
            effective["skill_refs"] = self._filter_skill_refs(effective)
        
        # 6. Dereference vault refs
        effective = self._resolve_vault_refs(effective, mask=masked)
        
        return EffectiveResolution(
            effective=effective,
            provenance=provenance,
        )
    
    @staticmethod
    def _filter_skill_refs(effective: Dict[str, Any]) -> List[str]:
        """Filter skill_refs: union minus disabled, intersect with enabled."""
        try:
            from dashboard.api_utils import build_skills_list
            all_enabled = {s.name for s in build_skills_list(include_disabled=False)}
        except Exception:
            all_enabled = None
        
        refs = set(effective.get("skill_refs", []))
        disabled = set(effective.get("disabled_skills", []))
        refs -= disabled
        
        if all_enabled is not None:
            refs = {s for s in refs if s in all_enabled}
        
        return sorted(refs)
    
    def patch_namespace(self, namespace: str, value: Dict[str, Any]) -> None:
        """Patch a global namespace in config.
        
        Args:
            namespace: Namespace to patch (e.g., 'runtime', 'autonomy')
            value: New values to merge
        """
        config = self.load_config()
        if namespace == "runtime":
            self._patch_runtime_namespace(config, value)
        else:
            if namespace not in config:
                config[namespace] = {}
            config[namespace].update(value)
        self.save_config(config)
    
    def patch_plan_role(
        self, plan_id: str, role: str, value: Dict[str, Any]
    ) -> None:
        """Patch plan-level role override in {plan_id}.roles.json.
        
        Updates the role config directly under the role key (flat structure),
        matching the format used by update_plan_config in plans.py.
        
        Args:
            plan_id: Plan ID
            role: Role name
            value: Settings to patch
        """
        plan_config = self._load_plan_config(plan_id)
        if role not in plan_config:
            plan_config[role] = {}
        plan_config[role].update(value)
        self._save_plan_config(plan_id, plan_config)
    
    def patch_room_role(
        self, plan_id: str, task_ref: str, role: str, value: Dict[str, Any]
    ) -> None:
        """Patch room-level role override.
        
        Args:
            plan_id: Plan ID
            task_ref: Task reference
            role: Role name
            value: Settings to patch
        """
        room_config = self._load_room_config(plan_id, task_ref)
        if "role_config" not in room_config:
            room_config["role_config"] = {}
        if role not in room_config["role_config"]:
            room_config["role_config"][role] = {}
        room_config["role_config"][role].update(value)
        self._save_room_config(plan_id, task_ref, room_config)
    
    def reset_namespace(self, namespace: str) -> None:
        """Reset namespace to defaults.
        
        Args:
            namespace: Namespace to reset
        """
        config = self.load_config()
        if namespace == "runtime":
            self._reset_runtime_namespace(config)
        elif namespace in config:
            del config[namespace]
        self.save_config(config)

    def _patch_runtime_namespace(
        self,
        config: Dict[str, Any],
        value: Dict[str, Any],
    ) -> None:
        """Persist runtime settings using the manager-backed canonical schema."""
        current_runtime = self._extract_runtime(config).model_dump(mode="python")
        merged_runtime = {
            **current_runtime,
            **value,
        }
        validated_runtime = RuntimeSettings(**merged_runtime)

        manager_config = dict(config.get("manager") or {})
        for key in RUNTIME_MANAGER_KEYS:
            manager_config[key] = getattr(validated_runtime, key)
        config["manager"] = manager_config

        runtime_config = dict(config.get("runtime") or {})
        for key in RUNTIME_MANAGER_KEYS:
            runtime_config.pop(key, None)

        if validated_runtime.master_agent_model:
            runtime_config["master_agent_model"] = validated_runtime.master_agent_model
        else:
            runtime_config.pop("master_agent_model", None)

        if runtime_config:
            config["runtime"] = runtime_config
        else:
            config.pop("runtime", None)

    @staticmethod
    def _reset_runtime_namespace(config: Dict[str, Any]) -> None:
        """Reset the runtime view without deleting unrelated manager role settings."""
        manager_config = dict(config.get("manager") or {})
        for key in RUNTIME_MANAGER_KEYS:
            manager_config.pop(key, None)
        if manager_config:
            config["manager"] = manager_config
        else:
            config.pop("manager", None)

        runtime_config = dict(config.get("runtime") or {})
        for key in (*RUNTIME_MANAGER_KEYS, *RUNTIME_RUNTIME_KEYS):
            runtime_config.pop(key, None)
        if runtime_config:
            config["runtime"] = runtime_config
        else:
            config.pop("runtime", None)
    
    def _resolve_vault_refs(
        self, obj: Any, mask: bool = False
    ) -> Any:
        """Recursively resolve vault references.
        
        Fails gracefully: returns None + logs a warning when a secret is
        not set, never crashes the resolver.
        
        Args:
            obj: Object to resolve
            mask: If True, replace secrets with ***
            
        Returns:
            Resolved object with secrets replaced
        """
        if isinstance(obj, dict):
            return {k: self._resolve_vault_refs(v, mask) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._resolve_vault_refs(v, mask) for v in obj]
        elif isinstance(obj, str):
            match = VAULT_REF_PATTERN.search(obj)
            if match:
                scope, key = match.groups()
                try:
                    secret = self.vault.get(scope, key)
                except Exception:
                    logger.warning(
                        "Vault lookup failed for ${vault:%s/%s}", scope, key
                    )
                    return None
                if secret is None:
                    logger.warning(
                        "Vault reference not found: ${vault:%s/%s}", scope, key
                    )
                    return None
                if mask:
                    return "***" + secret[-3:] if len(secret) > 3 else "***"
                return obj.replace(match.group(0), secret)
        return obj
    
    def _extract_providers(self, config: Dict[str, Any]) -> ProvidersNamespace:
        """Extract providers namespace from config."""
        providers_data = config.get("providers", {})
        return ProvidersNamespace(**providers_data) if providers_data else ProvidersNamespace()
    
    def _extract_roles(self, config: Dict[str, Any]) -> Dict[str, RoleSettings]:
        """Extract roles namespace from config."""
        roles_data = {}
        for key, value in config.items():
            if isinstance(value, dict) and key not in [
                "providers", "runtime", "memory", "channels", 
                "autonomy", "observability", "knowledge", "version", "project_name"
            ]:
                # Check if it looks like a role config
                if any(k in value for k in ["default_model", "temperature", "timeout_seconds"]):
                    roles_data[key] = RoleSettings(**{
                        k: v for k, v in value.items()
                        if k in RoleSettings.model_fields
                    })
        return roles_data
    
    @staticmethod
    def _safe_model(model_cls, data: Dict[str, Any]):
        """Instantiate a Pydantic model, falling back to defaults on validation error."""
        if not data:
            return model_cls()
        try:
            return model_cls(**data)
        except Exception:
            # Filter to only known fields and retry; if still bad, return defaults
            known = set(model_cls.model_fields)
            filtered = {k: v for k, v in data.items() if k in known}
            try:
                return model_cls(**filtered)
            except Exception:
                logger.warning(
                    "Invalid config for %s, using defaults: %s",
                    model_cls.__name__, data,
                )
                return model_cls()

    def _extract_runtime(self, config: Dict[str, Any]) -> RuntimeSettings:
        """Extract runtime namespace from config."""
        runtime_data = dict(config.get("runtime", {}))
        manager_data = config.get("manager") or {}
        for key in RUNTIME_MANAGER_KEYS:
            if key in manager_data and manager_data[key] is not None:
                runtime_data[key] = manager_data[key]
        return self._safe_model(RuntimeSettings, runtime_data)
    
    def _extract_memory(self, config: Dict[str, Any]) -> MemorySettings:
        """Extract memory namespace from config.

        Handles backward compatibility: the legacy ``embedding_provider`` field
        is mapped to ``embedding_backend`` when ``embedding_backend`` is not set.
        """
        mem_data = dict(config.get("memory", {}))
        # Backward compat: embedding_provider → embedding_backend
        if not mem_data.get("embedding_backend") and mem_data.get("embedding_provider"):
            mem_data["embedding_backend"] = mem_data["embedding_provider"]
        return self._safe_model(MemorySettings, mem_data)
    
    def _extract_channels(self, config: Dict[str, Any]) -> ChannelsNamespace:
        """Extract channels namespace from config."""
        return self._safe_model(ChannelsNamespace, config.get("channels", {}))
    
    def _extract_autonomy(self, config: Dict[str, Any]) -> AutonomySettings:
        """Extract autonomy namespace from config."""
        return self._safe_model(AutonomySettings, config.get("autonomy", {}))
    
    def _extract_observability(self, config: Dict[str, Any]) -> ObservabilitySettings:
        """Extract observability namespace from config."""
        return self._safe_model(ObservabilitySettings, config.get("observability", {}))

    def _extract_knowledge(self, config: Dict[str, Any]) -> KnowledgeSettings:
        """Extract knowledge namespace from config (ADR-15)."""
        return self._safe_model(KnowledgeSettings, config.get("knowledge", {}))
    
    def _load_plan_config(self, plan_id: str) -> Dict[str, Any]:
        """Load per-plan role config from {plan_id}.roles.json in PLANS_DIR.
        
        Falls back to global config.json if the plan-specific file doesn't exist.
        The returned dict has role names as top-level keys (flat structure).
        """
        from dashboard.api_utils import PLANS_DIR
        roles_file = PLANS_DIR / f"{plan_id}.roles.json"
        if roles_file.exists():
            try:
                return json.loads(roles_file.read_text())
            except json.JSONDecodeError:
                pass
        # Fallback to global config
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {}
    
    def _save_plan_config(self, plan_id: str, config: Dict[str, Any]) -> None:
        """Save per-plan role config atomically to {plan_id}.roles.json in PLANS_DIR."""
        from dashboard.api_utils import PLANS_DIR
        roles_file = PLANS_DIR / f"{plan_id}.roles.json"
        self._atomic_write_json(roles_file, config)
    
    def _load_room_config(self, plan_id: str, task_ref: str) -> Dict[str, Any]:
        """Load room config from .war-rooms/{plan_id}/{task_ref}/config.json."""
        from dashboard.api_utils import WARROOMS_DIR
        config_file = WARROOMS_DIR / plan_id / task_ref / "config.json"
        if config_file.exists():
            return json.loads(config_file.read_text())
        return {}
    
    def _save_room_config(
        self, plan_id: str, task_ref: str, config: Dict[str, Any]
    ) -> None:
        """Save room config atomically."""
        from dashboard.api_utils import WARROOMS_DIR
        config_file = WARROOMS_DIR / plan_id / task_ref / "config.json"
        self._atomic_write_json(config_file, config)


_resolver_lock = threading.Lock()
_resolver_instance: Optional[SettingsResolver] = None


def get_settings_resolver() -> SettingsResolver:
    """Get (or create) the singleton resolver instance -- thread-safe."""
    global _resolver_instance
    if _resolver_instance is not None:
        return _resolver_instance
    with _resolver_lock:
        if _resolver_instance is None:
            _resolver_instance = SettingsResolver()
    return _resolver_instance


def reset_settings_resolver() -> None:
    """Reset the singleton (for testing)."""
    global _resolver_instance
    with _resolver_lock:
        _resolver_instance = None
