import json
import logging
import shutil
from pathlib import Path
from typing import Dict, Any
from dashboard.api_utils import (
    AGENTS_DIR, SKILLS_DIRS, get_plan_roles_config,
    parse_skill_md
)
from dashboard.routes.plans import _resolve_room_dir

logger = logging.getLogger(__name__)

class EpicSkillsManager:
    @staticmethod
    def get_role_instructions(role_name: str) -> str:
        role_dir = AGENTS_DIR / "roles" / role_name
        role_md = role_dir / "ROLE.md"
        if role_md.exists():
            content = role_md.read_text()
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    return parts[2].strip()
            return content.strip()
        return f"You are a {role_name}."

    @staticmethod
    def get_skill_content(skill_name: str) -> str:
        for sdir in SKILLS_DIRS:
            # Skill might be in a subdirectory or direct
            # Try direct first
            skill_dir = sdir / skill_name
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                data = parse_skill_md(skill_dir)
                if data and data.get("enabled", True):
                    return data["content"]
                return ""
            
            # Try searching in subdirs (rglob)
            for smd in sdir.rglob("SKILL.md"):
                if smd.parent.name == skill_name:
                    data = parse_skill_md(smd.parent)
                    if data and data.get("enabled", True):
                        return data["content"]
                    return ""
        return ""

    @staticmethod
    def sync_room_skills(room_dir: Path, plan_id: str):
        """Inject plan-level skill_refs into a warroom's config.json."""
        config_file = room_dir / "config.json"
        if not config_file.exists():
            return

        try:
            config = json.loads(config_file.read_text())
        except (json.JSONDecodeError, OSError):
            return

        if "skill_refs" in config:
            return

        assigned_role = config.get("assignment", {}).get("assigned_role", "")
        if not assigned_role:
            return

        plan_config = get_plan_roles_config(plan_id)
        role_config = plan_config.get(assigned_role, {})

        skill_refs = set(role_config.get("skill_refs", []))
        skill_refs.update(plan_config.get("attached_skills", []))

        # Filter out globally disabled skills
        from dashboard.api_utils import build_skills_list
        all_enabled_skills = {s.name for s in build_skills_list(include_disabled=False)}
        skill_refs = {s for s in skill_refs if s in all_enabled_skills}

        disabled = set(role_config.get("disabled_skills", []))
        skill_refs -= disabled

        if skill_refs:
            config["skill_refs"] = sorted(skill_refs)
            config_file.write_text(json.dumps(config, indent=2))

    @staticmethod
    def inject_room_assets(room_dir: Path, plan_id: str, epic_ref: str) -> None:
        """Copy relevant assets into a war room's assets/ directory and write manifest into TASKS.md."""
        from dashboard.routes.plans import (
            list_epic_assets, _plan_assets_dir,
        )

        assets = list_epic_assets(plan_id, epic_ref, validate=False)
        if not assets:
            return

        src_dir = _plan_assets_dir(plan_id)
        dest_dir = room_dir / "assets"
        dest_dir.mkdir(parents=True, exist_ok=True)

        LARGE_FILE_THRESHOLD = 10 * 1024 * 1024  # 10 MB

        injected = []
        for asset in assets:
            src_file = src_dir / asset["filename"]
            if not src_file.exists():
                logger.warning("Asset file missing, skipping: %s", src_file)
                continue
            dest_file = dest_dir / asset["filename"]
            file_size = src_file.stat().st_size
            if file_size > LARGE_FILE_THRESHOLD:
                # Symlink large files to save disk space
                try:
                    dest_file.symlink_to(src_file.resolve())
                    logger.info("Symlinked large asset (%d bytes): %s", file_size, src_file.name)
                except OSError:
                    # Fallback to copy if symlink fails (e.g. cross-device)
                    shutil.copy2(src_file, dest_file)
                    logger.info("Copied large asset (symlink failed): %s", src_file.name)
            else:
                shutil.copy2(src_file, dest_file)
            injected.append(asset)

        if not injected:
            return

        # Write manifest into TASKS.md
        tasks_file = room_dir / "TASKS.md"
        manifest_lines = [
            "\n## Available Assets\n",
            "The following files are available in the `assets/` directory.\n",
            "| Filename | Type | Description | Path |",
            "| --- | --- | --- | --- |",
        ]
        for asset in injected:
            fname = asset.get("original_name", asset["filename"])
            atype = asset.get("asset_type", "unspecified")
            desc = asset.get("description", "")
            path = str(dest_dir / asset["filename"])
            manifest_lines.append(f"| {fname} | {atype} | {desc} | `{path}` |")

        manifest = "\n".join(manifest_lines) + "\n"

        if tasks_file.exists():
            content = tasks_file.read_text()
            content = content.rstrip() + "\n" + manifest
            tasks_file.write_text(content)
        else:
            tasks_file.write_text(manifest)

    @staticmethod
    def build_asset_context(plan_id: str, epic_ref: str) -> str:
        """Build a text block describing available assets for inclusion in system prompts."""
        from dashboard.routes.plans import list_epic_assets

        assets = list_epic_assets(plan_id, epic_ref, validate=False)
        if not assets:
            return ""

        lines = ["# Available Assets\n"]
        for asset in assets:
            fname = asset.get("original_name", asset["filename"])
            atype = asset.get("asset_type", "unspecified")
            desc = asset.get("description", "")
            line = f"- **{fname}** ({atype})"
            if desc:
                line += f" — {desc}"
            lines.append(line)

        return "\n".join(lines)

    @classmethod
    def resolve_config(cls, plan_id: str, task_ref: str, role_name: str) -> Dict[str, Any]:
        from dashboard.lib.settings import get_settings_resolver
        
        resolver = get_settings_resolver()
        resolution = resolver.resolve_role(role_name, plan_id=plan_id, task_ref=task_ref)
        
        room_dir = _resolve_room_dir(plan_id, task_ref)
        room_brief = ""
        if room_dir:
            brief_file = room_dir / "brief.md"
            if brief_file.exists():
                room_brief = brief_file.read_text()
        
        merged = {
            "model": resolution.effective.get("default_model", "google-vertex/gemini-3-flash-preview"),
            "temperature": resolution.effective.get("temperature", 0.7),
            "skill_refs": resolution.effective.get("skill_refs", []),
            "system_prompt_override": resolution.effective.get("system_prompt_override", ""),
            "brief": room_brief
        }
        return merged

    @classmethod
    def generate_system_prompt(cls, plan_id: str, task_ref: str, role_name: str) -> str:
        config = cls.resolve_config(plan_id, task_ref, role_name)
        role_instr = cls.get_role_instructions(role_name)
        
        skills_instr = []
        for skill_name in config["skill_refs"]:
            content = cls.get_skill_content(skill_name)
            if content:
                skills_instr.append(f"## Skill: {skill_name}\n\n{content}")
        
        prompt = []
        prompt.append(f"# Role: {role_name}\n")
        prompt.append(role_instr)
        
        if config["brief"]:
            prompt.append("\n# Current Epic Context\n")
            prompt.append(config["brief"])
            
        if skills_instr:
            prompt.append("\n# Available Skills\n")
            prompt.extend(skills_instr)

        # EPIC-004: Inject asset context
        asset_context = cls.build_asset_context(plan_id, task_ref)
        if asset_context:
            prompt.append("\n" + asset_context)

        override_text = config.get("system_prompt_override")
        if override_text and str(override_text).strip():
            prompt.append("\n# System Prompt Override\n")
            prompt.append(str(override_text).strip())

        return "\n\n".join(prompt)
