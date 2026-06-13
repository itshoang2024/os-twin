import json
import re
import shutil
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from dashboard.models import Role


DEFAULT_MODEL = "google-vertex/gemini-3-flash-preview"
DEFAULT_CREATED_AT = "1970-01-01T00:00:00+00:00"

PROVIDER_MAP = {
    "google-vertex": "gemini",
    "gemini": "gemini",
    "claude": "claude",
    "anthropic": "claude",
    "gpt": "gpt",
    "openai": "gpt",
    "o1": "gpt",
    "o3": "gpt",
    "o4": "gpt",
    "byteplus": "custom",
    "seed": "custom",
    "doubao": "custom",
}


def detect_provider(model_id: str) -> str:
    model_lower = (model_id or "").lower()
    for marker, provider in PROVIDER_MAP.items():
        if marker in model_lower:
            return provider
    return "gemini"


def stable_role_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "role"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def file_timestamp(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return DEFAULT_CREATED_AT


class RoleProjectionWriter:
    """Writes generated compatibility files from canonical Role objects."""

    def __init__(self, roles_config_file: Path, engine_config_file: Path):
        self.roles_config_file = roles_config_file
        self.engine_config_file = engine_config_file

    def write_all(self, roles: Iterable[Role]) -> None:
        role_list = list(roles)
        self.write_dashboard_config(role_list)
        self.write_engine_config(role_list)

    def write_dashboard_config(self, roles: Iterable[Role]) -> None:
        self.roles_config_file.parent.mkdir(parents=True, exist_ok=True)
        self.roles_config_file.write_text(
            json.dumps([role.model_dump() for role in roles], indent=2),
            encoding="utf-8",
        )

    def write_engine_config(self, roles: Iterable[Role]) -> None:
        config = read_json(self.engine_config_file)
        if not isinstance(config, dict):
            config = {}

        role_names = {role.name for role in roles}
        stale_role_keys = [
            key
            for key, value in config.items()
            if key not in role_names
            and isinstance(value, dict)
            and {
                "default_model",
                "timeout_seconds",
                "max_retries",
                "instance_type",
                "skill_refs",
                "mcp_refs",
            }.intersection(value.keys())
        ]
        for key in stale_role_keys:
            config.pop(key, None)

        for role in roles:
            entry = config.get(role.name)
            if not isinstance(entry, dict):
                entry = {}
            entry["default_model"] = role.version
            entry["timeout_seconds"] = role.timeout_seconds
            entry["max_retries"] = role.max_retries
            entry["instance_type"] = role.instance_type
            entry["skill_refs"] = role.skill_refs
            entry["mcp_refs"] = role.mcp_refs or []
            config[role.name] = entry

        self.engine_config_file.parent.mkdir(parents=True, exist_ok=True)
        self.engine_config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")


class RoleRepository:
    """Reads canonical role folders and writes role projections explicitly."""

    def __init__(
        self,
        *,
        global_roles_dir: Path,
        project_roles_dir: Path,
        roles_config_file: Path,
        engine_config_file: Path,
        opencode_agents_dir: Optional[Path] = None,
    ):
        self.global_roles_dir = global_roles_dir
        self.project_roles_dir = project_roles_dir
        self.roles_config_file = roles_config_file
        self.engine_config_file = engine_config_file
        self.opencode_agents_dir = opencode_agents_dir or Path.home() / ".config" / "opencode" / "agents"
        self.projections = RoleProjectionWriter(roles_config_file, engine_config_file)

    def list_roles(self) -> List[Role]:
        legacy_roles = self._read_legacy_config_roles()
        legacy_by_name = {role.name: role for role in legacy_roles}
        registry_by_name = self._read_registry_roles()

        roles_by_name: "OrderedDict[str, Role]" = OrderedDict()
        self._merge_roles(
            roles_by_name,
            self._read_role_root(self.project_roles_dir, legacy_by_name, registry_by_name),
        )
        self._merge_roles(
            roles_by_name,
            self._read_role_root(self.global_roles_dir, legacy_by_name, registry_by_name),
        )

        # Backward compatibility: old dashboard versions stored edited role values
        # only in config.json. Keep those values visible, but never write them
        # during a read. POST /api/roles/sync migrates them into role folders.
        self._merge_roles(roles_by_name, legacy_roles)

        return sorted(roles_by_name.values(), key=lambda role: role.name.lower())

    def write_role(self, role: Role) -> None:
        role_dir = self.global_roles_dir / role.name
        role_dir.mkdir(parents=True, exist_ok=True)
        role_file = role_dir / "role.json"
        role_file.write_text(json.dumps(self._role_to_role_json(role), indent=2), encoding="utf-8")
        (role_dir / "ROLE.md").write_text(role.instructions or "", encoding="utf-8")
        self.write_opencode_agent(role)

    def delete_role(self, role: Role) -> None:
        role_dir = self.global_roles_dir / role.name
        if role_dir.exists() and role_dir.is_dir():
            shutil.rmtree(role_dir)
        self.delete_opencode_agent(role)

    def write_opencode_agent(self, role: Role) -> None:
        """Sync ROLE.md content into OpenCode's agent markdown format.

        The dashboard's canonical editable role body is ``ROLE.md``. OpenCode,
        however, discovers agents from ``.opencode/agents/<name>.md`` where the
        markdown body is the agent prompt and frontmatter carries runtime
        metadata. Keeping this projection in the repository write path ensures
        every create/update/sync that saves role content also refreshes the
        OpenCode agent prompt.
        """
        self.opencode_agents_dir.mkdir(parents=True, exist_ok=True)
        agent_file = self.opencode_agents_dir / f"{stable_role_id(role.name)}.md"
        existing_content = agent_file.read_text(encoding="utf-8") if agent_file.exists() else None
        agent_file.write_text(self._render_opencode_agent_markdown(role, existing_content), encoding="utf-8")

    def delete_opencode_agent(self, role: Role) -> None:
        agent_file = self.opencode_agents_dir / f"{stable_role_id(role.name)}.md"
        try:
            agent_file.unlink()
        except FileNotFoundError:
            pass

    def save_projections(self, roles: Iterable[Role]) -> None:
        self.projections.write_all(roles)

    def sync_from_disk(self) -> dict:
        roles = self.list_roles()
        for role in roles:
            self.write_role(role)
        self.save_projections(roles)
        return {"synced": [role.name for role in roles], "total": len(roles)}

    def _read_legacy_config_roles(self) -> List[Role]:
        data = read_json(self.roles_config_file)
        if not isinstance(data, list):
            return []

        roles = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                roles.append(Role(**item))
            except Exception:
                continue
        return roles

    def _read_registry_roles(self) -> Dict[str, dict]:
        registry = read_json(self.global_roles_dir / "registry.json")
        if not isinstance(registry, dict):
            registry = read_json(self.project_roles_dir / "registry.json")
        if not isinstance(registry, dict):
            return {}

        result = {}
        for item in registry.get("roles", []):
            if isinstance(item, dict) and item.get("name"):
                result[item["name"]] = item
        return result

    def _read_role_root(
        self,
        root: Path,
        legacy_by_name: Dict[str, Role],
        registry_by_name: Dict[str, dict],
    ) -> List[Role]:
        if not root.exists():
            return []

        roles = []
        for child in sorted(root.iterdir(), key=lambda path: path.name.lower()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if not (child / "role.json").exists() and not (child / "ROLE.md").exists():
                continue
            role = self._read_role_folder(child, legacy_by_name, registry_by_name)
            if role:
                roles.append(role)
        return roles

    def _read_role_folder(
        self,
        role_dir: Path,
        legacy_by_name: Dict[str, Role],
        registry_by_name: Dict[str, dict],
    ) -> Optional[Role]:
        role_json = read_json(role_dir / "role.json")
        if role_json is None:
            role_json = {}
        if not isinstance(role_json, dict):
            return None

        name = role_json.get("name") or role_dir.name
        legacy = legacy_by_name.get(name)
        registry = registry_by_name.get(name, {})

        model = (
            role_json.get("version")
            or role_json.get("model")
            or role_json.get("default_model")
            or (legacy.version if legacy else None)
            or registry.get("default_model")
            or DEFAULT_MODEL
        )
        role_md_file = role_dir / "ROLE.md"
        instructions = (
            role_md_file.read_text(encoding="utf-8")
            if role_md_file.exists()
            else role_json.get("instructions")
            or (legacy.instructions if legacy else "")
        )
        timestamp_source = role_md_file if role_md_file.exists() else role_dir / "role.json"
        updated_at = (
            role_json.get("updated_at")
            or (legacy.updated_at if legacy else None)
            or file_timestamp(timestamp_source)
        )
        created_at = (
            role_json.get("created_at")
            or (legacy.created_at if legacy else None)
            or updated_at
        )

        return Role(
            id=role_json.get("id") or (legacy.id if legacy else stable_role_id(name)),
            name=name,
            description=role_json.get("description")
            or registry.get("description")
            or (legacy.description if legacy else ""),
            instructions=instructions,
            provider=(
                role_json.get("provider")
                or detect_provider(model)
            ).lower(),
            version=model,
            temperature=role_json.get("temperature")
            if role_json.get("temperature") is not None
            else (legacy.temperature if legacy else 0.7),
            budget_tokens_max=role_json.get("budget_tokens_max")
            or (legacy.budget_tokens_max if legacy else 500000),
            max_retries=role_json.get("max_retries")
            or (legacy.max_retries if legacy else registry.get("max_retries", 3)),
            timeout_seconds=role_json.get("timeout_seconds")
            or role_json.get("timeout")
            or (legacy.timeout_seconds if legacy else registry.get("timeout_seconds", 300)),
            skill_refs=role_json.get("skill_refs")
            or role_json.get("skills")
            or (legacy.skill_refs if legacy else []),
            mcp_refs=role_json.get("mcp_refs")
            or (legacy.mcp_refs if legacy else []),
            instance_type=role_json.get("instance_type")
            or (legacy.instance_type if legacy else registry.get("instance_type", "worker")),
            system_prompt_override=role_json.get("system_prompt_override")
            if role_json.get("system_prompt_override") is not None
            else (legacy.system_prompt_override if legacy else None),
            created_at=created_at,
            updated_at=updated_at,
        )

    @staticmethod
    def _merge_roles(target: "OrderedDict[str, Role]", roles: Iterable[Role]) -> None:
        for role in roles:
            target[role.name] = role

    @staticmethod
    def _role_to_role_json(role: Role) -> dict:
        return {
            "id": role.id,
            "name": role.name,
            "description": role.description,
            "model": role.version,
            "provider": role.provider,
            "temperature": role.temperature,
            "budget_tokens_max": role.budget_tokens_max,
            "max_retries": role.max_retries,
            "timeout_seconds": role.timeout_seconds,
            "skill_refs": role.skill_refs,
            "mcp_refs": role.mcp_refs or [],
            "instance_type": role.instance_type,
            "system_prompt_override": role.system_prompt_override,
            "created_at": role.created_at,
            "updated_at": role.updated_at,
        }

    @staticmethod
    def _render_opencode_agent_markdown(role: Role, existing_content: Optional[str] = None) -> str:
        frontmatter = RoleRepository._extract_frontmatter(existing_content)
        frontmatter.update({
            "name": json.dumps(stable_role_id(role.name), ensure_ascii=False),
            "description": json.dumps(role.description or f"Ostwin role: {role.name}", ensure_ascii=False),
            "mode": json.dumps("all"),
            "model": json.dumps(role.version, ensure_ascii=False),
            "temperature": json.dumps(role.temperature),
        })
        lines = ["---"]
        for key, value in frontmatter.items():
            lines.append(f"{key}: {value}")
        lines.extend(["---", "", role.instructions or ""])
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _extract_frontmatter(content: Optional[str]) -> Dict[str, str]:
        """Return existing OpenCode agent frontmatter, preserving unknown keys.

        Existing global agents may contain metadata that is not represented by
        the dashboard role model, such as ``tags`` or ``trust_level``. Preserve
        those keys while updating the OpenCode runtime fields and prompt body.
        """
        if not content or not content.startswith("---\n"):
            return {}
        end = content.find("\n---", 4)
        if end == -1:
            return {}

        frontmatter: Dict[str, str] = {}
        for raw_line in content[4:end].splitlines():
            if not raw_line.strip() or raw_line.lstrip().startswith("#") or ":" not in raw_line:
                continue
            key, value = raw_line.split(":", 1)
            key = key.strip()
            if key:
                frontmatter[key] = value.strip()
        return frontmatter
