import json
import shutil
import logging
import re
import asyncio
import httpx
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Dict, Any
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from dashboard.models import (
    Skill,
    SkillInstallRequest,
    SkillSyncResponse,
    SkillCreateRequest,
    SkillUpdateRequest,
    SkillForkRequest,
    SkillValidateRequest,
    SkillValidateResponse,
    SkillDuplicateCheckRequest,
    SkillDuplicateCheckResponse,
)
from dashboard.api_utils import (
    SKILLS_DIRS,
    AGENTS_DIR,
    PROJECT_ROOT,
    parse_skill_md,
    build_skills_list,
    save_skill_md,
    get_active_epics_using_skill,
)
import dashboard.global_state as global_state
from dashboard.auth import get_current_user

router = APIRouter(tags=["skills"])
logger = logging.getLogger(__name__)

_sync_lock = asyncio.Lock()
_sync_in_progress = False
_sync_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="skills-sync")


def _normalize_skill_name(name: str) -> str:
    return name.strip().casefold()


def _find_skill_on_disk(name: str) -> Optional[Dict[str, Any]]:
    """Resolve a skill by frontmatter name instead of assuming folder == skill name."""
    wanted_name = _normalize_skill_name(name)
    folder_name = name.strip().lower().replace(" ", "-")

    for sdir in SKILLS_DIRS:
        if not sdir.exists():
            continue

        # Fast path for conventional folder naming.
        candidate = sdir / folder_name
        if candidate.is_dir() and (candidate / "SKILL.md").exists():
            skill_data = parse_skill_md(candidate)
            if (
                skill_data
                and _normalize_skill_name(skill_data.get("name", "")) == wanted_name
            ):
                return skill_data

        # Fallback for skills whose display name differs from the folder name.
        for skill_md in sdir.rglob("SKILL.md"):
            path = skill_md.parent
            rel_parts = (
                path.relative_to(sdir).parts
                if path.is_relative_to(sdir)
                else path.parts
            )
            if any(
                p in ("references", ".versions") for p in rel_parts
            ):  # skip reference/archive copies
                continue
            skill_data = parse_skill_md(path)
            if (
                skill_data
                and _normalize_skill_name(skill_data.get("name", "")) == wanted_name
            ):
                return skill_data

    return None


def _index_skill_from_disk(store: Any, skill_data: Dict[str, Any]) -> None:
    """Refresh the zvec entry from parsed on-disk skill data."""
    store.index_skill(
        name=skill_data["name"],
        description=skill_data["description"],
        tags=skill_data["tags"],
        path=skill_data["path"],
        relative_path=skill_data.get("relative_path", ""),
        trust_level=skill_data["trust_level"],
        source=skill_data["source"],
        content=skill_data["content"],
        version=skill_data.get("version", "0.1.0"),
        category=skill_data.get("category"),
        applicable_roles=skill_data.get("applicable_roles", []),
        params=skill_data.get("params", []),
        changelog=skill_data.get("changelog", []),
        author=skill_data.get("author"),
        forked_from=skill_data.get("forked_from"),
        is_draft=skill_data.get("is_draft", False),
        enabled=skill_data.get("enabled", True),
    )


def _matches_text_query(skill: Skill, query: str) -> bool:
    """Fallback lexical match for skills that are missing from zvec."""
    query_l = query.strip().casefold()
    if not query_l:
        return True

    haystack = " ".join(
        filter(
            None,
            [
                skill.name,
                skill.description,
                " ".join(skill.tags),
                " ".join(skill.applicable_roles),
                skill.content,
            ],
        )
    ).casefold()

    if query_l in haystack:
        return True

    terms = [term for term in re.split(r"\s+", query_l) if term]
    return bool(terms) and all(term in haystack for term in terms)


@router.get("/api/skills", response_model=List[Skill])
async def list_skills(
    role: Optional[str] = None,
    tags: List[str] = Query([]),
    include_disabled: bool = Query(False),
    user: dict = Depends(get_current_user),
):
    """List all available skills with optional filtering."""
    skills = build_skills_list(
        role=role, tags=tags, include_drafts=True, include_disabled=include_disabled
    )
    current_username = user.get("username", "unknown")
    filtered = [s for s in skills if not s.is_draft or s.author == current_username]
    if role:
        filtered = [
            s for s in filtered if not s.applicable_roles or role in s.applicable_roles
        ]
    return filtered


@router.get("/api/skills/search", response_model=List[Skill])
async def search_skills_endpoint(
    q: str = Query(..., description="Semantic search query"),
    role: Optional[str] = None,
    tags: List[str] = Query([]),
    limit: int = Query(50, ge=1, le=100, description="Max results to return"),
    include_disabled: bool = Query(False),
    user: dict = Depends(get_current_user),
):
    """Semantic search for skills with role-based post-filtering."""
    store = global_state.store
    ranked_names: List[str] = []
    skills_by_name: Dict[str, Skill] = {}

    if store:
        results = store.search_skills(q, limit=limit)
        for res in results:
            skill = Skill(**res)
            skills_by_name[skill.name] = skill
            ranked_names.append(skill.name)

    # Backfill from disk so skills with invalid zvec doc IDs (for example names with
    # spaces) still appear in search and carry the current enabled state.
    disk_skills = build_skills_list(
        role=role,
        tags=tags,
        limit=1000,
        include_drafts=True,
        include_disabled=True,
    )
    for disk_skill in disk_skills:
        if not _matches_text_query(disk_skill, q):
            continue
        if disk_skill.name in skills_by_name:
            merged = skills_by_name[disk_skill.name].dict()
            merged.update(disk_skill.dict())
            skills_by_name[disk_skill.name] = Skill(**merged)
        else:
            skills_by_name[disk_skill.name] = disk_skill
            ranked_names.append(disk_skill.name)

    skills = []
    for skill_name in ranked_names:
        skill = skills_by_name[skill_name]
        if not include_disabled and not getattr(skill, "enabled", True):
            continue
        skills.append(skill)

    current_username = user.get("username", "unknown")
    filtered = [s for s in skills if not s.is_draft or s.author == current_username]
    if role:
        filtered = [
            s for s in filtered if not s.applicable_roles or role in s.applicable_roles
        ]
    return filtered


@router.get("/api/skills/tags", response_model=List[str])
async def list_skill_tags(user: dict = Depends(get_current_user)):
    """List all unique tags across all available skills."""
    skills = build_skills_list()
    tags = set()
    for s in skills:
        for t in s.tags:
            tags.add(t)
    return sorted(list(tags))


@router.get("/api/skills/roles", response_model=List[str])
async def list_skill_roles(user: dict = Depends(get_current_user)):
    """List all available roles from the registry."""
    from dashboard.api_utils import build_roles_list

    roles = build_roles_list({})  # Empty config to get all registry roles
    return [r["name"] for r in roles]


# ─── ClawHub Marketplace (search must be registered before {name} wildcard) ──

_CLAWHUB_CONVEX_BASE = "https://wry-manatee-359.convex.cloud/api"

# Global skills directory — all ClawHub installs go here
_GLOBAL_SKILLS_DIR = Path.home() / ".ostwin" / ".agents" / "skills"
# clawhub CLI writes its lock to <workdir>/.clawhub/lock.json
_CLAWHUB_WORKDIR = Path.home() / ".ostwin" / ".agents"
_GLOBAL_CLAWHUB_LOCK = _CLAWHUB_WORKDIR / ".clawhub" / "lock.json"

# Strict pattern: only allow alphanumeric, hyphens, underscores, dots, and @scopes
_SAFE_SKILL_NAME = re.compile(r"^(@[a-zA-Z0-9_-]+/)?[a-zA-Z0-9._-]+$")

def _build_clawhub_install_command(skill_name: str) -> List[str]:
    """Build the Bun-based ClawHub install command.

    Prefer an already-installed clawhub CLI (typically installed with
    `bun add -g clawhub`). If it is not on PATH, use Bun's package executor as
    the only fallback; npm/npx/pnpm are intentionally not used here.
    """
    clawhub = shutil.which("clawhub")
    base_cmd = [clawhub] if clawhub else ["bun", "x", "clawhub"]
    return [
        *base_cmd,
        "install",
        skill_name,
        "--workdir",
        str(_CLAWHUB_WORKDIR),
        "--dir",
        "skills",
        "--no-input",
    ]


# Global install lock — prevents concurrent installs from racing
_install_lock = asyncio.Lock()


class ClawhubInstallRequest(BaseModel):
    skill_name: str = Field(..., min_length=1, max_length=128)

    @field_validator("skill_name")
    @classmethod
    def validate_skill_name(cls, v: str) -> str:
        # Normalize: lowercase, spaces to hyphens
        v = v.strip().lower().replace(" ", "-")
        if not _SAFE_SKILL_NAME.match(v):
            raise ValueError(
                "Invalid skill name. Only alphanumeric characters, hyphens, underscores, dots, and @scoped names are allowed."
            )
        return v


class SkillMigrationConflictStrategy(str, Enum):
    skip = "skip"
    overwrite = "overwrite"
    fail = "fail"


class SkillMigrationApplyRequest(BaseModel):
    delete_source: bool = True
    conflict_strategy: SkillMigrationConflictStrategy = SkillMigrationConflictStrategy.skip
    dry_run: bool = False


_MIGRATION_SOURCE_ROOTS: Optional[List[Path]] = None


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _prune_empty_skill_parents(skill_dir: Path, source_root: Path) -> None:
    current = _resolved(skill_dir).parent
    source_root = _resolved(source_root)

    while current != source_root and _path_is_relative_to(current, source_root):
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _migration_target_root() -> Path:
    return _resolved(_GLOBAL_SKILLS_DIR)


def _migration_source_roots() -> List[Path]:
    if _MIGRATION_SOURCE_ROOTS is not None:
        candidates = _MIGRATION_SOURCE_ROOTS
    else:
        candidates = [
            PROJECT_ROOT / ".agents" / "skills",
            AGENTS_DIR / "skills",
            PROJECT_ROOT / ".deepagents" / "skills",
            Path.home() / ".agents" / "skills",
            Path.home() / ".deepagents" / "agent" / "skills",
        ]

    target = _migration_target_root()
    roots: List[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        root = _resolved(candidate)
        if root == target:
            continue
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        roots.append(root)
    return roots


def _skill_migration_plan() -> Dict[str, Any]:
    target_root = _migration_target_root()
    sources = []
    items = []
    total_skills = 0
    conflict_count = 0
    planned_targets: set[str] = set()

    for source_root in _migration_source_roots():
        source_summary = {
            "source_path": str(source_root),
            "exists": source_root.exists(),
            "skill_count": 0,
        }
        if source_root.exists():
            for skill_md in source_root.rglob("SKILL.md"):
                skill_dir = _resolved(skill_md.parent)
                if not _path_is_relative_to(skill_dir, source_root):
                    continue
                relative_path = skill_dir.relative_to(source_root)
                if any(part in ("references", ".versions") for part in relative_path.parts):
                    continue

                skill_data = parse_skill_md(skill_dir)
                if not skill_data:
                    continue

                target_path = target_root / relative_path
                target_key = str(_resolved(target_path))
                conflict = target_path.exists() or target_key in planned_targets
                if conflict:
                    conflict_count += 1
                planned_targets.add(target_key)
                source_summary["skill_count"] += 1
                total_skills += 1
                items.append(
                    {
                        "name": skill_data.get("name") or skill_dir.name,
                        "source_root": str(source_root),
                        "source_path": str(skill_dir),
                        "target_path": str(target_path),
                        "relative_path": str(relative_path),
                        "conflict": conflict,
                    }
                )
        sources.append(source_summary)

    if total_skills == 0:
        message = "No project-local or legacy skills were found to migrate."
        recommended_action = "none"
    elif conflict_count:
        message = f"Found {total_skills} skill(s) to migrate, including {conflict_count} target conflict(s)."
        recommended_action = "preview_conflicts"
    else:
        message = f"Found {total_skills} skill(s) that can be migrated to the global Ostwin skill store."
        recommended_action = "migrate"

    return {
        "target_path": str(target_root),
        "source_summaries": sources,
        "total_skills": total_skills,
        "conflicts": conflict_count,
        "items": items,
        "recommended_action": recommended_action,
        "message": message,
    }


def _map_clawhub_result(entry: dict) -> dict:
    """Normalise a ClawHub API result into a stable shape for the frontend."""
    # search:searchSkills nests under "skill" + "owner"; listPublicPageV4 uses the same shape
    skill = entry.get("skill") or entry
    owner = entry.get("owner") or {}
    stats = skill.get("stats") or {}
    version_obj = entry.get("latestVersion") or {}
    return {
        "name": skill.get("displayName") or skill.get("slug", ""),
        "slug": skill.get("slug", ""),
        "description": skill.get("summary") or "",
        "author": entry.get("ownerHandle") or owner.get("handle"),
        "tags": [],
        "category": None,
        "downloads": int(stats.get("downloads") or 0),
        "installs": int(stats.get("installsAllTime") or 0),
        "version": version_obj.get("version"),
        "score": entry.get("score"),
    }


@router.get("/api/skills/clawhub-search")
async def clawhub_search(
    q: str = Query("", description="Search query for ClawHub skills"),
    limit: int = Query(25, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """Search the ClawHub marketplace.

    Uses the vector-search action (search:searchSkills) when a query is
    provided, and falls back to the paginated browse endpoint
    (skills:listPublicPageV4) when the query is empty.
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            q_stripped = q.strip()
            if q_stripped:
                # Vector search — returns ranked results
                resp = await client.post(
                    f"{_CLAWHUB_CONVEX_BASE}/action",
                    json={
                        "path": "search:searchSkills",
                        "args": {
                            "query": q_stripped,
                            "highlightedOnly": False,
                            "nonSuspiciousOnly": True,
                            "limit": limit,
                        },
                    },
                )
            else:
                # Browse — paginated list sorted by downloads
                resp = await client.post(
                    f"{_CLAWHUB_CONVEX_BASE}/query",
                    json={
                        "path": "skills:listPublicPageV4",
                        "args": {
                            "numItems": limit,
                            "sort": "downloads",
                            "dir": "desc",
                            "highlightedOnly": False,
                            "nonSuspiciousOnly": True,
                        },
                    },
                )
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != "success":
            raise HTTPException(
                status_code=502, detail="Unexpected response from ClawHub"
            )

        value = data["value"]

        # search:searchSkills returns a list; listPublicPageV4 returns {page, hasMore, ...}
        if isinstance(value, dict):
            entries = value.get("page", [])
        elif isinstance(value, list):
            entries = value
        else:
            entries = []

        return [_map_clawhub_result(e) for e in entries]

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"ClawHub returned {exc.response.status_code}",
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach ClawHub: {exc}",
        )


@router.get("/api/skills/clawhub-installed")
async def clawhub_installed(user: dict = Depends(get_current_user)):
    """Return ClawHub skill slugs that are actually installed on disk.

    Reads the global lock file at ~/.ostwin/.agents/skills/.clawhub-lock.json
    and verifies the skill folder exists in ~/.ostwin/.agents/skills/.
    """
    installed: Dict[str, Any] = {}

    # 1. Read the global lock file (clawhub writes to <workdir>/.clawhub/lock.json)
    lock_candidates: Dict[str, dict] = {}
    if _GLOBAL_CLAWHUB_LOCK.exists():
        try:
            data = json.loads(_GLOBAL_CLAWHUB_LOCK.read_text())
            # clawhub lock schema: { "version": 1, "skills": { slug: { version, installedAt } } }
            for slug, info in (data.get("skills") or {}).items():
                lock_candidates[slug] = info
        except Exception:
            pass

    # 2. Verify each lock entry actually exists on disk
    for slug, info in lock_candidates.items():
        skill_dir = _GLOBAL_SKILLS_DIR / slug
        if skill_dir.is_dir():
            installed[slug] = {
                "slug": slug,
                "version": info.get("version"),
                "installedAt": info.get("installedAt"),
            }

    # 3. Also pick up any skill in global/ that has origin.json
    #    (in case lock file is missing/stale)
    if _GLOBAL_SKILLS_DIR.exists():
        for child in _GLOBAL_SKILLS_DIR.iterdir():
            if not child.is_dir() or child.name in installed:
                continue
            origin = child / "origin.json"
            if origin.exists():
                try:
                    origin_data = json.loads(origin.read_text())
                    installed[child.name] = {
                        "slug": child.name,
                        "version": origin_data.get("installedVersion")
                        or origin_data.get("version"),
                        "installedAt": origin_data.get("installedAt"),
                    }
                except Exception:
                    installed[child.name] = {"slug": child.name}

    return list(installed.values())


@router.get("/api/skills/migration/status")
async def skill_migration_status(user: dict = Depends(get_current_user)):
    """Report project-local and legacy skills that can move to the global store."""
    return _skill_migration_plan()


@router.post("/api/skills/migration/preview")
async def skill_migration_preview(user: dict = Depends(get_current_user)):
    """Preview migrating local skill folders into ~/.ostwin/.agents/skills."""
    return _skill_migration_plan()


@router.post("/api/skills/migration/apply")
async def skill_migration_apply(
    req: SkillMigrationApplyRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Copy migratable skill folders into the canonical Ostwin global skill store."""
    confirm = (request.headers.get("x-confirm-migrate") or "").lower()
    if confirm != "true":
        raise HTTPException(
            status_code=403,
            detail="Migration requires confirmation. Set header X-Confirm-Migrate: true.",
        )

    plan = _skill_migration_plan()
    if req.conflict_strategy == SkillMigrationConflictStrategy.fail and plan["conflicts"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Migration conflicts detected.",
                "conflicts": [item for item in plan["items"] if item["conflict"]],
            },
        )

    target_root = _migration_target_root()
    result: Dict[str, Any] = {
        "target_path": str(target_root),
        "dry_run": req.dry_run,
        "copied": [],
        "skipped": [],
        "overwritten": [],
        "deleted": [],
        "errors": [],
        "sync_result": None,
    }

    if not req.dry_run:
        target_root.mkdir(parents=True, exist_ok=True)

    for item in plan["items"]:
        source_path = _resolved(Path(item["source_path"]))
        target_path = _resolved(Path(item["target_path"]))

        if not _path_is_relative_to(target_path, target_root):
            result["errors"].append(
                {"item": item, "error": "Target path is outside the migration target root."}
            )
            continue

        conflict = target_path.exists()
        if conflict and req.conflict_strategy == SkillMigrationConflictStrategy.fail:
            result["errors"].append(
                {
                    "item": item,
                    "error": "Target path already exists; conflict_strategy=fail prevents overwrite.",
                }
            )
            continue

        if conflict and req.conflict_strategy == SkillMigrationConflictStrategy.skip:
            result["skipped"].append(item)
            continue

        try:
            if req.dry_run:
                if conflict and req.conflict_strategy == SkillMigrationConflictStrategy.overwrite:
                    result["overwritten"].append(item)
                else:
                    result["copied"].append(item)
                continue

            if conflict:
                if not _path_is_relative_to(target_path, target_root):
                    raise ValueError("Refusing to overwrite outside target root")
                shutil.rmtree(target_path)
                result["overwritten"].append(item)
            else:
                result["copied"].append(item)

            shutil.copytree(source_path, target_path)
            copied_skill = parse_skill_md(target_path)
            if not (target_path / "SKILL.md").exists() or not copied_skill:
                raise ValueError("Copied skill failed SKILL.md verification")

            if req.delete_source:
                shutil.rmtree(source_path)
                source_root = _resolved(Path(item.get("source_root", source_path)))
                if source_path != source_root:
                    _prune_empty_skill_parents(source_path, source_root)
                result["deleted"].append(item)
        except Exception as exc:
            result["errors"].append({"item": item, "error": str(exc)})

    if not req.dry_run and global_state.store:
        try:
            result["sync_result"] = global_state.store.sync_skills(SKILLS_DIRS)
        except Exception as exc:
            result["sync_result"] = {"error": str(exc)}

    return result


@router.patch("/api/skills/{name}/toggle", response_model=Skill)
async def toggle_skill(name: str, user: dict = Depends(get_current_user)):
    """Toggle the enabled/disabled state of a skill."""
    skill = await get_skill(name, user)
    new_enabled = not getattr(skill, "enabled", True)

    disk_skill_data = _find_skill_on_disk(skill.name)
    skill_path = (
        Path(skill.path)
        if skill.path and (Path(skill.path) / "SKILL.md").exists()
        else None
    )
    if not skill_path and disk_skill_data:
        skill_path = Path(disk_skill_data["path"])

    if not skill_path:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found on disk")

    skill_dict = disk_skill_data or skill.dict()
    skill_dict["enabled"] = new_enabled
    save_skill_md(skill_dict, path=skill_path)

    updated_data = parse_skill_md(skill_path)
    if not updated_data:
        raise HTTPException(
            status_code=500, detail=f"Failed to reload updated skill '{name}' from disk"
        )

    store = global_state.store
    if store:
        _index_skill_from_disk(store, updated_data)

    updated_skill = Skill(**updated_data)
    updated_skill.active_epics_count = get_active_epics_using_skill(updated_skill.name)
    return updated_skill


@router.get("/api/skills/{name}", response_model=Skill)
async def get_skill(name: str, user: dict = Depends(get_current_user)):
    """Fetch details for a specific skill."""
    store = global_state.store
    store_skill_data = None

    if store:
        store_skill_data = store.get_skill(name)

    disk_skill_data = _find_skill_on_disk(name)
    if store_skill_data and disk_skill_data:
        skill_data = {**store_skill_data, **disk_skill_data}
    else:
        skill_data = disk_skill_data or store_skill_data

    if not skill_data:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")

    skill = Skill(**skill_data)
    skill.active_epics_count = get_active_epics_using_skill(skill.name)
    return skill


@router.get("/api/skills/{name}/versions/{version}")
async def get_skill_version(
    name: str, version: str, user: dict = Depends(get_current_user)
):
    """Fetch raw instruction template for a historical version of a skill."""
    current_data = _find_skill_on_disk(name)
    if current_data:
        path = Path(current_data["path"])
        if current_data.get("version") == version:
            return {"content": current_data.get("content", "")}

        version_filename = f"v{version}.md"
        version_file = path / ".versions" / version_filename
        if version_file.exists():
            historical_data = parse_skill_md(
                path, filename=f".versions/{version_filename}"
            )
            if historical_data:
                return {"content": historical_data.get("content", "")}

    raise HTTPException(
        status_code=404, detail=f"Version {version} of skill '{name}' not found"
    )


@router.post("/api/skills/install")
async def install_skill(
    req: SkillInstallRequest, user: dict = Depends(get_current_user)
):
    """Install a new skill from a local filesystem path."""
    path = Path(req.path)
    if not path.exists() or not path.is_dir():
        raise HTTPException(
            status_code=400, detail="Path does not exist or is not a directory"
        )

    skill_md = path / "SKILL.md"
    if not skill_md.exists():
        raise HTTPException(
            status_code=400, detail="Directory must contain a valid SKILL.md file"
        )

    data = parse_skill_md(path)
    if not data:
        raise HTTPException(status_code=400, detail="Failed to parse SKILL.md")

    store = global_state.store
    if store:
        store.index_skill(
            name=data["name"],
            description=data["description"],
            tags=data["tags"],
            path=data["path"],
            relative_path=data.get("relative_path", ""),
            trust_level=data["trust_level"],
            source=data["source"],
            content=data["content"],
        )

    return {"status": "installed", "skill": data["name"]}


@router.get("/api/skills/sync/status")
async def sync_status_endpoint(user: dict = Depends(get_current_user)):
    """Check if a skills sync is currently in progress."""
    return {"sync_in_progress": _sync_in_progress}


@router.post("/api/skills/sync", response_model=SkillSyncResponse)
async def sync_skills_endpoint(user: dict = Depends(get_current_user)):
    """Synchronize the vector database with on-disk skills directories."""
    global _sync_in_progress

    store = global_state.store
    if not store:
        raise HTTPException(status_code=503, detail="Vector store not available")

    if _sync_in_progress:
        return SkillSyncResponse(synced_count=0, added=[], updated=[], removed=[])

    async with _sync_lock:
        if _sync_in_progress:
            return SkillSyncResponse(synced_count=0, added=[], updated=[], removed=[])
        _sync_in_progress = True

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _sync_executor, store.sync_skills, SKILLS_DIRS
        )
        return SkillSyncResponse(**result)
    finally:
        _sync_in_progress = False


@router.post("/api/skills", response_model=Skill)
async def create_skill(req: SkillCreateRequest, user: dict = Depends(get_current_user)):
    """Create a new custom skill."""
    # Check for name uniqueness
    existing = build_skills_list()
    if any(s.name.lower() == req.name.lower() for s in existing):
        raise HTTPException(
            status_code=400, detail=f"Skill with name '{req.name}' already exists"
        )

    timestamp = datetime.now(timezone.utc).timestamp()
    skill_data = {
        "name": req.name,
        "description": req.description,
        "category": req.category,
        "applicable_roles": req.applicable_roles,
        "tags": req.tags,
        "content": req.content,
        "is_draft": req.is_draft,
        "author": user.get("username", "unknown"),
        "version": "1.0.0" if not req.is_draft else "0.1.0",
        "changelog": [
            {
                "version": "1.0.0" if not req.is_draft else "0.1.0",
                "date": timestamp,
                "changes": "Initial creation",
            }
        ],
    }

    path = save_skill_md(skill_data)
    indexed_data = parse_skill_md(path)

    store = global_state.store
    if store:
        idx = {
            k: v
            for k, v in indexed_data.items()
            if k not in ("updated_at", "score", "active_epics_count")
        }
        store.index_skill(**idx)

    return Skill(**indexed_data)


@router.put("/api/skills/{name}", response_model=Skill)
async def update_skill(
    name: str, req: SkillUpdateRequest, user: dict = Depends(get_current_user)
):
    """Update an existing skill."""
    # Fetch existing skill
    skill_data = await get_skill(name, user)
    if not skill_data:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")

    skill_dict = skill_data.dict()

    # Apply updates
    if req.description is not None:
        skill_dict["description"] = req.description
    if req.category is not None:
        skill_dict["category"] = req.category
    if req.applicable_roles is not None:
        skill_dict["applicable_roles"] = req.applicable_roles
    if req.tags is not None:
        skill_dict["tags"] = req.tags
    if req.content is not None:
        skill_dict["content"] = req.content
    if req.is_draft is not None:
        skill_dict["is_draft"] = req.is_draft

    # Version bump logic
    current_version = skill_dict.get("version", "1.0.0")
    major, minor, patch = map(int, current_version.split("."))
    if req.major_bump:
        new_version = f"{major + 1}.0.0"
    else:
        new_version = f"{major}.{minor + 1}.0"

    skill_dict["version"] = new_version

    # Add changelog entry
    changelog = skill_dict.get("changelog", [])
    timestamp = datetime.now(timezone.utc).timestamp()
    changelog.insert(
        0,
        {
            "version": new_version,
            "date": timestamp,
            "changes": req.change_description or "Manual update",
        },
    )
    skill_dict["changelog"] = changelog

    # Save back to disk
    path = Path(skill_dict["path"])
    save_skill_md(skill_dict, path=path)

    # Update index
    store = global_state.store
    if store:
        indexed_data = parse_skill_md(path)
        idx = {
            k: v
            for k, v in indexed_data.items()
            if k not in ("updated_at", "score", "active_epics_count")
        }
        store.index_skill(**idx)
        return Skill(**indexed_data)

    return Skill(**skill_dict)


@router.post("/api/skills/{name}/fork", response_model=Skill)
async def fork_skill(
    name: str, req: SkillForkRequest, user: dict = Depends(get_current_user)
):
    """Fork an existing skill."""
    original = await get_skill(name, user)
    if not original:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")

    # Check for name uniqueness
    existing = build_skills_list()
    if any(s.name.lower() == req.name.lower() for s in existing):
        raise HTTPException(
            status_code=400, detail=f"Skill with name '{req.name}' already exists"
        )

    fork_data = original.dict()
    fork_data["name"] = req.name
    fork_data["version"] = "1.0.0"
    fork_data["author"] = user.get("username", "unknown")
    fork_data["forked_from"] = name
    timestamp = datetime.now(timezone.utc).timestamp()
    fork_data["changelog"] = [
        {"version": "1.0.0", "date": timestamp, "changes": f"Forked from {name}"}
    ]
    fork_data.pop("path", None)
    fork_data.pop("relative_path", None)

    path = save_skill_md(fork_data)
    indexed_data = parse_skill_md(path)

    store = global_state.store
    if store:
        idx = {
            k: v
            for k, v in indexed_data.items()
            if k not in ("updated_at", "score", "active_epics_count")
        }
        store.index_skill(**idx)

    return Skill(**indexed_data)


@router.delete("/api/skills/{name}", status_code=204)
async def delete_skill(
    name: str, force: bool = False, user: dict = Depends(get_current_user)
):
    """Delete a skill from disk and vector store."""
    active_count = get_active_epics_using_skill(name)
    if active_count > 0 and not force:
        raise HTTPException(
            status_code=409,
            detail=f"Skill '{name}' is used by {active_count} active epic(s). Use force=true to delete anyway.",
        )

    disk_skill_data = _find_skill_on_disk(name)
    skill_path = Path(disk_skill_data["path"]) if disk_skill_data else None

    if not skill_path:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found on disk")

    shutil.rmtree(skill_path)

    store = global_state.store
    if store:
        store.delete_skill(name)

    return


@router.post("/api/skills/validate", response_model=SkillValidateResponse)
async def validate_skill_template(
    req: SkillValidateRequest, user: dict = Depends(get_current_user)
):
    """Validate skill instruction template and return markers for editor."""
    content = req.content
    errors = []
    warnings = []
    markers = []

    # Known variables
    KNOWN_VARS = {
        "task_description",
        "working_dir",
        "definition_of_done",
        "acceptance_criteria",
        "previous_feedback",
    }

    # Simple line/col calculation helper
    def get_pos(offset):
        lines = content[:offset].split("\n")
        return len(lines), len(lines[-1]) + 1

    # Check for malformed brackets
    if content.count("{{") != content.count("}}"):
        errors.append("Malformed template variables: mismatched brackets '{{' and '}}'")
        # Heuristic markers for mismatched brackets
        for m in re.finditer(r"\{\{[^\}]*$", content, re.MULTILINE):
            line, col = get_pos(m.start())
            markers.append(
                {
                    "message": "Unclosed bracket '{{'",
                    "severity": 8,  # Error
                    "startLineNumber": line,
                    "startColumn": col,
                    "endLineNumber": line,
                    "endColumn": col + 2,
                }
            )

    # Check for unknown variables
    for m in re.finditer(r"\{\{([^}]+)\}\}", content):
        var = m.group(1).strip()
        if var not in KNOWN_VARS:
            line, col = get_pos(m.start())
            msg = f"Unknown template variable: '{{{{{var}}}}}'"
            warnings.append(msg)
            markers.append(
                {
                    "message": msg,
                    "severity": 4,  # Warning
                    "startLineNumber": line,
                    "startColumn": col,
                    "endLineNumber": line,
                    "endColumn": col + len(m.group(0)),
                }
            )

    # Check length
    if len(content) < 50:
        errors.append("Instruction template is too short (minimum 50 characters)")

    return SkillValidateResponse(
        valid=len(errors) == 0, errors=errors, warnings=warnings, markers=markers
    )


@router.post("/api/skills/check-duplicate", response_model=SkillDuplicateCheckResponse)
async def check_duplicate_skill(
    req: SkillDuplicateCheckRequest, user: dict = Depends(get_current_user)
):
    """Check for similar existing skills."""
    name = req.name.lower()
    existing_skills = build_skills_list()

    similar = []
    for s in existing_skills:
        if name in s.name.lower() or s.name.lower() in name:
            similar.append(s.name)
        # Simple Levenshtein substitute: check for high overlap or common words
        elif len(set(name.split()) & set(s.name.lower().split())) >= 2:
            similar.append(s.name)

    return SkillDuplicateCheckResponse(
        is_duplicate=any(s.name.lower() == name for s in existing_skills),
        similar_skills=similar[:5],
    )


async def _verify_clawhub_skill_exists(slug: str) -> bool:
    """Check that a skill actually exists on ClawHub before installing."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_CLAWHUB_CONVEX_BASE}/query",
                json={"path": "skills:getBySlug", "args": {"slug": slug}},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("status") == "success" and data.get("value") is not None
    except Exception:
        return False


@router.post("/api/skills/clawhub-install")
async def clawhub_install(
    req: ClawhubInstallRequest,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Install a skill from ClawHub using the clawhub CLI.

    Protections:
    - Requires X-Confirm-Install: true header (admin intent gate)
    - skill_name is validated against a strict allowlist pattern
    - Skill existence is verified on ClawHub before install
    - Only one install runs at a time (global lock)
    - Subprocess runs async (non-blocking)
    - Atomic directory swap with backup/rollback on failure
    """
    # ── Admin intent gate ────────────────────────────────────────────────
    confirm = (request.headers.get("x-confirm-install") or "").lower()
    if confirm != "true":
        raise HTTPException(
            status_code=403,
            detail="Install requires confirmation. Set header X-Confirm-Install: true.",
        )

    skill_name = req.skill_name
    username = user.get("username", "unknown")
    logger.info("clawhub-install requested by=%s skill=%s", username, skill_name)

    # ── Verify skill exists on ClawHub before running anything ──────────
    if not await _verify_clawhub_skill_exists(skill_name):
        raise HTTPException(
            status_code=404,
            detail=f"Skill '{skill_name}' not found on ClawHub. Verify the slug is correct.",
        )

    # ── Concurrency gate ─────────────────────────────────────────────────
    if _install_lock.locked():
        raise HTTPException(
            status_code=409,
            detail="Another skill install is already in progress. Please wait and retry.",
        )

    async with _install_lock:
        try:
            # Ensure target directories exist
            _CLAWHUB_WORKDIR.mkdir(parents=True, exist_ok=True)
            _GLOBAL_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

            # Use --workdir and --dir so clawhub installs into
            # ~/.ostwin/.agents/skills/<slug> regardless of its own global defaults.
            proc = await asyncio.create_subprocess_exec(
                *_build_clawhub_install_command(skill_name),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                raise HTTPException(status_code=504, detail="clawhub install timed out")

            if proc.returncode != 0:
                detail = (stderr or stdout or b"").decode(errors="replace")
                logger.error(
                    "clawhub-install failed by=%s skill=%s: %s",
                    username,
                    skill_name,
                    detail,
                )
                raise HTTPException(
                    status_code=500,
                    detail="clawhub install failed. Check server logs for details.",
                )

            # Skill is now in ~/.ostwin/.agents/skills/<skill_name>
            dest = _GLOBAL_SKILLS_DIR / skill_name

            # ── Index into zvec so the skill is immediately searchable ────────
            if dest.exists() and (dest / "SKILL.md").exists():
                skill_data = parse_skill_md(dest)
                if skill_data:
                    store = global_state.store
                    if store:
                        _index_skill_from_disk(store, skill_data)
                        logger.info(
                            "clawhub-install indexed skill=%s into zvec", skill_name
                        )

            logger.info(
                "clawhub-install success by=%s skill=%s dest=%s",
                username,
                skill_name,
                dest,
            )
            return {
                "status": "installed",
                "skill": skill_name,
                "output": (stdout or b"").decode(errors="replace"),
            }
        except HTTPException:
            raise
        except FileNotFoundError:
            raise HTTPException(
                status_code=500,
                detail="clawhub CLI/Bun not found. Install Bun, then run: bun add -g clawhub",
            )
