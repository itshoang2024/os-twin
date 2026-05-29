import os
import json
import hashlib
import asyncio
import re
import logging
import zipfile
from email.parser import BytesParser
from email.policy import default
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
import subprocess
_re_mod = re
from fastapi import APIRouter, HTTPException, Query, Depends, BackgroundTasks, Request
from fastapi.responses import StreamingResponse

from dashboard.models import CreatePlanRequest, SavePlanRequest, RefineRequest, UpdatePlanRoleConfigRequest, RunRequest
from dashboard.api_utils import (
    AGENTS_DIR, PROJECT_ROOT, PLANS_DIR, GLOBAL_PLANS_DIR,
    get_plan_roles_config, build_roles_list,
    resolve_runtime_plan_warrooms_dir,
    process_notification
)
import dashboard.global_state as global_state
from dashboard.auth import get_current_user

router = APIRouter(tags=["plans"])
logger = logging.getLogger(__name__)


def _resolve_plans_dir_for_write() -> Path:
    """Resolve where new plans should be written.

    Always writes to global store (~/.ostwin/.agents/plans) so plans are
    accessible across all projects and from the bot.
    """
    return GLOBAL_PLANS_DIR


def _find_plan_file(plan_id: str) -> Optional[Path]:
    """Find a plan file, checking local store first, then global."""
    local = PLANS_DIR / f"{plan_id}.md"
    if local.exists():
        return local
    if GLOBAL_PLANS_DIR != PLANS_DIR:
        global_path = GLOBAL_PLANS_DIR / f"{plan_id}.md"
        if global_path.exists():
            return global_path
    return None


def _find_plan_meta(plan_id: str) -> Optional[Path]:
    """Find a plan meta file, checking local store first, then global."""
    local = PLANS_DIR / f"{plan_id}.meta.json"
    if local.exists():
        return local
    if GLOBAL_PLANS_DIR != PLANS_DIR:
        global_path = GLOBAL_PLANS_DIR / f"{plan_id}.meta.json"
        if global_path.exists():
            return global_path
    return None


def _find_plan_assets_dir(plan_id: str) -> Optional[Path]:
    """Find a plan assets directory, checking local store first, then global."""
    local = PLANS_DIR / "assets" / plan_id
    if local.exists():
        return local
    if GLOBAL_PLANS_DIR != PLANS_DIR:
        global_path = GLOBAL_PLANS_DIR / "assets" / plan_id
        if global_path.exists():
            return global_path
    return None


def _plan_file_path(plan_id: str) -> Path:
    """Get the path to a plan file (for reading or writing).

    For reading: returns the first existing path (local then global).
    For writing: returns the appropriate store based on where the plan exists.
    """
    existing = _find_plan_file(plan_id)
    if existing:
        return existing
    # New plan: write to the resolved write location
    return _resolve_plans_dir_for_write() / f"{plan_id}.md"


def _plan_meta_path(plan_id: str) -> Path:
    """Get the path to a plan meta file (for reading or writing)."""
    existing = _find_plan_meta(plan_id)
    if existing:
        return existing
    # Check if plan file exists to determine location
    plan_file = _find_plan_file(plan_id)
    if plan_file:
        return plan_file.parent / f"{plan_id}.meta.json"
    return _resolve_plans_dir_for_write() / f"{plan_id}.meta.json"


def _plan_assets_dir(plan_id: str) -> Path:
    """Get the path to a plan assets directory (for reading or writing)."""
    existing = _find_plan_assets_dir(plan_id)
    if existing:
        return existing
    # Check if plan file exists to determine location
    plan_file = _find_plan_file(plan_id)
    if plan_file:
        return plan_file.parent / "assets" / plan_id
    return _resolve_plans_dir_for_write() / "assets" / plan_id


def _validate_id(identifier: str, name: str = "ID") -> None:
    """Check that identifier is alphanumeric/dashes only (no path traversal)."""
    if ".." in identifier or "/" in identifier or "\\" in identifier:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {name}: '{identifier}'. Path traversal is not allowed.",
        )
    if not re.match(r"^[a-zA-Z0-9._-]+$", identifier):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {name}: '{identifier}'. Must be alphanumeric with dashes/dots/underscores.",
        )


def _require_plan_file(plan_id: str) -> Path:
    _validate_id(plan_id, "plan_id")
    plan_file = _plan_file_path(plan_id)
    if not plan_file.exists():
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
    return plan_file


def _extract_plan_title(content: str, default: str) -> str:
    title_match = re.search(r"^# (?:Plan|PLAN):\s*(.+)", content, re.MULTILINE)
    return title_match.group(1).strip() if title_match else default


def _normalize_plan_header(content: str, title: str) -> str:
    """Ensure plan content starts with '# Plan: {title}' header.

    This normalizes various header formats:
    - ': Title' → '# Plan: Title'
    - '# PLAN: Title' → '# Plan: Title'
    - No header → Prepends '# Plan: {title}'
    - Existing '# Plan: ...' → Preserved

    Args:
        content: The plan markdown content
        title: The expected title (used if header is missing)

    Returns:
        Content with normalized '# Plan:' header
    """
    if not content or not content.strip():
        return f"# Plan: {title}\n"

    # Check for existing # Plan: or # PLAN: header
    header_match = _re_mod.search(r"^# (Plan|PLAN):\s*(.+)", content, _re_mod.MULTILINE)

    if header_match:
        existing_title = header_match.group(2).strip()
        # Normalize # PLAN: to # Plan:
        if header_match.group(1) == "PLAN":
            content = _re_mod.sub(r"^# PLAN:", "# Plan:", content, count=1, flags=_re_mod.MULTILINE)
        return content

    # Check for colon-only prefix (': Title')
    colon_match = _re_mod.match(r"^:\s*(.+?)(\n|$)", content)
    if colon_match:
        extracted_title = colon_match.group(1).strip()
        # Replace ': Title' with '# Plan: Title'
        content = _re_mod.sub(r"^:\s*.+?(\n|$)", f"# Plan: {extracted_title}\\1", content, count=1)
        return content

    # No header found - prepend one
    return f"# Plan: {title}\n\n{content}"


def _read_plan_meta(plan_id: str) -> Dict[str, Any]:
    meta_file = _plan_meta_path(plan_id)
    if not meta_file.exists():
        return {}
    try:
        return json.loads(meta_file.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write_plan_meta(plan_id: str, meta: Dict[str, Any]) -> None:
    _plan_meta_path(plan_id).write_text(json.dumps(meta, indent=2) + "\n")


def _ensure_plan_meta(plan_id: str) -> Dict[str, Any]:
    meta = _read_plan_meta(plan_id)
    if meta:
        meta.setdefault("assets", [])
        meta.setdefault("epic_assets", {})
        return meta

    plan_file = _require_plan_file(plan_id)
    content = plan_file.read_text()
    meta = {
        "plan_id": plan_id,
        "title": _extract_plan_title(content, plan_id),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "draft",
        "assets": [],
        "epic_assets": {},
    }
    _write_plan_meta(plan_id, meta)
    return meta


def _safe_asset_filename(original_name: str) -> str:
    original = Path(original_name or "attachment.bin").name
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", Path(original).stem).strip("-._") or "asset"
    suffix = Path(original).suffix[:20]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    fingerprint = hashlib.sha256(f"{original}:{timestamp}".encode()).hexdigest()[:8]
    return f"{timestamp}-{stem[:40]}-{fingerprint}{suffix}"


def _normalize_plan_assets(
    plan_id: str, meta: Dict[str, Any]
) -> List[Dict[str, Any]]:
    assets_dir = _plan_assets_dir(plan_id)
    normalized: List[Dict[str, Any]] = []
    changed = False

    meta.setdefault("epic_assets", {})

    for raw_asset in meta.get("assets", []):
        filename = raw_asset.get("filename")
        if not filename:
            changed = True
            continue

        asset_path = assets_dir / filename
        if not asset_path.exists():
            changed = True
            continue

        asset = dict(raw_asset)
        asset.setdefault("original_name", filename)
        asset.setdefault("mime_type", "application/octet-stream")
        asset.setdefault(
            "uploaded_at",
            raw_asset.get("created_at") or datetime.now(timezone.utc).isoformat()
        )
        asset.setdefault("size_bytes", asset_path.stat().st_size)

        # EPIC-001: Extended metadata
        asset.setdefault("bound_epics", [])
        asset.setdefault("asset_type", "unspecified")
        asset.setdefault("tags", [])
        asset.setdefault("description", "")

        # EPIC-001: Sync epic_assets index from bound_epics (handles legacy migration)
        for epic_ref in asset["bound_epics"]:
            ea = meta.setdefault("epic_assets", {})
            if epic_ref not in ea:
                ea[epic_ref] = []
            if filename not in ea[epic_ref]:
                ea[epic_ref].append(filename)
                changed = True

        if asset != raw_asset:
            changed = True
        normalized.append(asset)

    if changed:
        meta["assets"] = normalized
        _write_plan_meta(plan_id, meta)

    return normalized


def _get_valid_epic_refs(plan_id: str) -> set:
    """Parse the plan markdown and return the set of valid EPIC-NNN refs.

    Matches all supported header formats:
      ### EPIC-001 — Title
      ## Epic: EPIC-001 — Title
      ## Task: EPIC-001 — Title
    """
    plan_file = _plan_file_path(plan_id)
    if not plan_file.exists():
        return set()
    content = plan_file.read_text()
    # Broad pattern: any ##/### heading that contains EPIC-NNN
    return set(_re_mod.findall(r"^#{2,3}\s+(?:(?:Epic|Task):\s*)?(EPIC-\d+)", content, _re_mod.MULTILINE))


def _validate_epic_ref(plan_id: str, epic_ref: str) -> None:
    """Raise 404 if epic_ref does not exist in the plan."""
    valid = _get_valid_epic_refs(plan_id)
    if epic_ref not in valid:
        raise HTTPException(
            status_code=404,
            detail=f"Epic {epic_ref} not found in plan {plan_id}. Valid epics: {sorted(valid)}",
        )


def _replace_existing_assets(
    plan_id: str, existing: List[Dict[str, Any]], new_assets: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Remove superseded assets from the existing list when re-uploading.

    If a new asset has the same original_name as an existing one, the old record
    and its stored file are removed. Returns the cleaned existing list.
    """
    new_names = {a["original_name"] for a in new_assets if a.get("original_name")}
    if not new_names:
        return existing

    assets_dir = _plan_assets_dir(plan_id)
    cleaned = []
    meta = _ensure_plan_meta(plan_id)
    epic_assets = meta.get("epic_assets", {})

    for asset in existing:
        if asset.get("original_name") in new_names:
            # Remove old stored file
            old_path = assets_dir / asset["filename"]
            if old_path.exists():
                try:
                    old_path.unlink()
                except OSError:
                    pass
            # Remove from epic_assets index
            for epic_ref, flist in list(epic_assets.items()):
                if asset["filename"] in flist:
                    flist.remove(asset["filename"])
                    if not flist:
                        del epic_assets[epic_ref]
        else:
            cleaned.append(asset)

    return cleaned


def _inject_assets_to_working_directory(plan_id: str, working_dir: Path) -> None:
    """Inject plan assets into the working directory for agent access.

    Creates a .assets/ directory in the working directory and copies/symlinks
    all assets from the plan's asset directory. This ensures agents have
    direct access to assets during execution.

    Args:
        plan_id: The plan ID
        working_dir: The working directory path
    """
    import shutil

    # Get plan assets
    meta = _ensure_plan_meta(plan_id)
    assets = _normalize_plan_assets(plan_id, meta)

    if not assets:
        logger.info(f"No assets to inject for plan {plan_id}")
        return

    # Create .assets directory in working directory
    assets_target_dir = working_dir / ".assets"
    assets_target_dir.mkdir(parents=True, exist_ok=True)

    # Get source assets directory
    assets_source_dir = _plan_assets_dir(plan_id)

    # Copy/symlink assets
    LARGE_FILE_THRESHOLD = 10 * 1024 * 1024  # 10MB
    injected_count = 0

    for asset in assets:
        stored_name = asset.get("filename")
        original_name = asset.get("original_name", stored_name)

        if not stored_name:
            continue

        source_file = assets_source_dir / stored_name
        if not source_file.exists():
            logger.warning(f"Asset file not found: {source_file}")
            continue

        # Use original name for better readability
        target_file = assets_target_dir / original_name

        # Check file size for symlink vs copy decision
        file_size = source_file.stat().st_size

        try:
            if file_size > LARGE_FILE_THRESHOLD:
                # Symlink large files to save disk space
                if target_file.exists() or target_file.is_symlink():
                    target_file.unlink()
                target_file.symlink_to(source_file.resolve())
                logger.info(f"Symlinked large asset ({file_size} bytes): {original_name}")
            else:
                # Copy small files
                if target_file.exists():
                    target_file.unlink()
                shutil.copy2(source_file, target_file)

            injected_count += 1
        except Exception as e:
            logger.warning(f"Failed to inject asset {original_name}: {e}")

    # Create asset manifest file
    manifest_file = assets_target_dir / "ASSETS.md"
    manifest_lines = [
        "# Plan Assets\n",
        f"This directory contains {injected_count} asset(s) for plan `{plan_id}`.\n",
        "\n## Available Files\n\n",
    ]

    for asset in assets:
        original_name = asset.get("original_name", asset.get("filename", "unknown"))
        atype = asset.get("asset_type", "unspecified")
        desc = asset.get("description", "")
        size = asset.get("size_bytes", 0)

        line = f"- **{original_name}** ({atype}, {size} bytes)"
        if desc:
            line += f" — {desc}"
        manifest_lines.append(line + "\n")

    manifest_file.write_text("".join(manifest_lines))

    logger.info(f"Injected {injected_count} assets into {assets_target_dir} for plan {plan_id}")


def _extract_files_from_zip(
    zip_data: bytes,
    original_zip_name: str,
    epic_ref: Optional[str] = None,
    asset_type: str = "unspecified",
    tags: List[str] = None,
) -> List[Dict[str, Any]]:
    """Extract all files from a ZIP archive and return asset records.

    Args:
        zip_data: Raw bytes of the ZIP file
        original_zip_name: Original filename of the ZIP (for logging)
        epic_ref: Epic to bind all extracted files to
        asset_type: Asset type for all extracted files
        tags: Tags for all extracted files

    Returns:
        List of asset dictionaries with filename, original_name, mime_type, data, etc.
    """
    import io
    from mimetypes import guess_type

    if tags is None:
        tags = []

    extracted = []

    try:
        with zipfile.ZipFile(io.BytesIO(zip_data), 'r') as zf:
            for zip_info in zf.infolist():
                # Skip directories
                if zip_info.is_dir():
                    continue

                # Skip hidden files and macOS metadata
                filename = zip_info.filename
                if filename.startswith('.') or filename.startswith('__MACOSX'):
                    continue

                # Extract filename from path (handle nested directories)
                original_name = Path(filename).name
                if not original_name:
                    continue

                try:
                    file_data = zf.read(zip_info)

                    # Skip empty files
                    if len(file_data) == 0:
                        continue

                    # Guess MIME type
                    mime_type, _ = guess_type(original_name)
                    if not mime_type:
                        mime_type = "application/octet-stream"

                    # Guess asset type if unspecified
                    inferred_type = asset_type
                    if asset_type == "unspecified":
                        name_lower = original_name.lower()
                        if mime_type.startswith("image/"):
                            inferred_type = "design-mockup"
                        elif any(ext in name_lower for ext in [".pdf", ".doc", ".docx", ".txt", ".md"]):
                            inferred_type = "reference-doc"
                        elif any(ext in name_lower for ext in [".yaml", ".yml", ".json", ".xml"]):
                            if "api" in name_lower or "spec" in name_lower:
                                inferred_type = "api-spec"
                            else:
                                inferred_type = "config"
                        elif any(ext in name_lower for ext in [".csv", ".sql", ".db"]):
                            inferred_type = "test-data"

                    extracted.append({
                        "original_name": original_name,
                        "data": file_data,
                        "mime_type": mime_type,
                        "size_bytes": len(file_data),
                        "asset_type": inferred_type,
                        "tags": tags,
                        "bound_epics": [epic_ref] if epic_ref else [],
                    })

                except Exception as e:
                    logger.warning(f"Failed to extract {filename} from {original_zip_name}: {e}")
                    continue

        logger.info(f"Extracted {len(extracted)} files from ZIP: {original_zip_name}")

    except zipfile.BadZipFile as e:
        logger.error(f"Invalid ZIP file {original_zip_name}: {e}")
    except Exception as e:
        logger.error(f"Failed to process ZIP {original_zip_name}: {e}")

    return extracted


def _merge_markdown_asset_edits_into_meta(plan_id: str, markdown_content: str) -> None:
    """Parse #### Assets sections from markdown and merge binding changes into meta.json.

    If an asset's filename appears under a different epic in the markdown than in meta,
    update meta to match. This allows user/AI edits to asset sections to be persisted.
    """
    parsed = _parse_epic_assets_from_markdown(markdown_content)
    if not parsed:
        return

    meta = _ensure_plan_meta(plan_id)
    _normalize_plan_assets(plan_id, meta)
    assets_by_filename: Dict[str, Dict[str, Any]] = {
        a["filename"]: a for a in meta.get("assets", [])
    }
    assets_by_original: Dict[str, Dict[str, Any]] = {
        a.get("original_name", a["filename"]): a for a in meta.get("assets", [])
    }

    # Build new binding map from markdown
    md_bindings: Dict[str, set] = {}  # filename -> set of epic_refs from markdown
    for epic_ref, entries in parsed.items():
        for entry in entries:
            # Entry format: "original_name (type, mime) — description"
            # Or portable: ".assets/original_name (type, mime) — description"
            # Extract original_name (first token before " (")
            raw_name = entry.split(" (")[0].strip() if " (" in entry else entry.strip()
            # Strip portable prefix if present
            original_name = raw_name[len(".assets/"):] if raw_name.startswith(".assets/") else raw_name

            asset = assets_by_original.get(original_name) or assets_by_filename.get(original_name)
            if asset:
                fn = asset["filename"]
                if fn not in md_bindings:
                    md_bindings[fn] = set()
                md_bindings[fn].add(epic_ref)

    if not md_bindings:
        return

    # Apply binding changes
    epic_assets = meta.setdefault("epic_assets", {})
    changed = False
    for filename, md_epics in md_bindings.items():
        asset = assets_by_filename.get(filename)
        if not asset:
            continue
        current_epics = set(asset.get("bound_epics", []))
        # Add new bindings from markdown
        for epic_ref in md_epics - current_epics:
            bound = asset.setdefault("bound_epics", [])
            bound.append(epic_ref)
            ea = epic_assets.setdefault(epic_ref, [])
            if filename not in ea:
                ea.append(filename)
            changed = True

    if changed:
        _write_plan_meta(plan_id, meta)


def _sync_asset_sections(plan_id: str) -> None:
    """Regenerate both plan-level and per-epic asset sections in plan markdown."""
    meta = _ensure_plan_meta(plan_id)
    assets = _normalize_plan_assets(plan_id, meta)
    assets_dir = _plan_assets_dir(plan_id)
    # Plan-level ## Assets shows only unbound assets
    plan_level = [a for a in assets if not a.get("bound_epics")]
    _update_plan_assets_section(plan_id, plan_level, assets_dir)
    # Per-epic #### Assets shows bound assets
    _update_epic_asset_sections(plan_id, assets, assets_dir)


def bind_asset_to_epic(
    plan_id: str, filename: str, epic_ref: str
) -> Dict[str, Any]:
    _validate_epic_ref(plan_id, epic_ref)
    meta = _ensure_plan_meta(plan_id)
    epic_assets = meta.setdefault("epic_assets", {})
    if epic_ref not in epic_assets:
        epic_assets[epic_ref] = []

    if filename not in epic_assets[epic_ref]:
        epic_assets[epic_ref].append(filename)

    # Also update asset metadata
    for asset in meta.get("assets", []):
        if asset.get("filename") == filename:
            bound = asset.setdefault("bound_epics", [])
            if epic_ref not in bound:
                bound.append(epic_ref)
            break

    _write_plan_meta(plan_id, meta)
    _sync_asset_sections(plan_id)
    return meta


def unbind_asset_from_epic(
    plan_id: str, filename: str, epic_ref: str
) -> Dict[str, Any]:
    meta = _ensure_plan_meta(plan_id)
    epic_assets = meta.get("epic_assets", {})
    if epic_ref in epic_assets and filename in epic_assets[epic_ref]:
        epic_assets[epic_ref].remove(filename)
        if not epic_assets[epic_ref]:
            del epic_assets[epic_ref]

    # Also update asset metadata
    for asset in meta.get("assets", []):
        if asset.get("filename") == filename:
            bound = asset.get("bound_epics", [])
            if epic_ref in bound:
                bound.remove(epic_ref)
            break

    _write_plan_meta(plan_id, meta)
    _sync_asset_sections(plan_id)
    return meta


def list_epic_assets(plan_id: str, epic_ref: str, *, validate: bool = True) -> List[Dict[str, Any]]:
    if validate:
        _validate_epic_ref(plan_id, epic_ref)
    meta = _ensure_plan_meta(plan_id)
    _normalize_plan_assets(plan_id, meta)

    all_assets = meta.get("assets", [])
    epic_filenames = meta.get("epic_assets", {}).get(epic_ref, [])

    bound = [a for a in all_assets if a["filename"] in epic_filenames]
    # Assets not bound to ANY epic are plan-level (available to all)
    plan_level = [a for a in all_assets if not a.get("bound_epics")]

    # Return unique list
    seen = set()
    result = []
    for a in bound + plan_level:
        if a["filename"] not in seen:
            result.append(a)
            seen.add(a["filename"])
    return result


def get_asset_or_404(plan_id: str, filename: str) -> Dict[str, Any]:
    """Find an asset by filename in the plan's meta, or raise 404."""
    _validate_id(filename, "filename")
    meta = _ensure_plan_meta(plan_id)
    _normalize_plan_assets(plan_id, meta)
    for asset in meta.get("assets", []):
        if asset.get("filename") == filename:
            return asset
    raise HTTPException(status_code=404, detail=f"Asset {filename} not found in plan {plan_id}")


def update_asset_metadata(
    plan_id: str,
    filename: str,
    asset_type: Optional[str] = None,
    tags: Optional[List[str]] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Update an asset's metadata (type, tags, description). Returns updated asset."""
    meta = _ensure_plan_meta(plan_id)
    _normalize_plan_assets(plan_id, meta)

    target = None
    for asset in meta.get("assets", []):
        if asset.get("filename") == filename:
            target = asset
            break

    if target is None:
        raise HTTPException(status_code=404, detail=f"Asset {filename} not found in plan {plan_id}")

    if asset_type is not None:
        target["asset_type"] = asset_type
    if tags is not None:
        target["tags"] = tags
    if description is not None:
        target["description"] = description

    _write_plan_meta(plan_id, meta)
    return target


def _serialize_plan_asset(
    plan_id: str, asset: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        **asset,
        "plan_id": plan_id,
        "path": str(_plan_assets_dir(plan_id) / asset["filename"]),
    }


def _update_plan_assets_section(plan_id: str, all_assets: list, assets_dir: Path) -> None:
    """Insert or replace an ## Assets section in the plan markdown.

    This gives agents executing the plan a manifest of available files
    with absolute paths so they can load/copy/reference them directly.
    """
    plan_file = PLANS_DIR / f"{plan_id}.md"
    if not plan_file.exists():
        return

    content = plan_file.read_text()

    # Build the new section
    lines = [
        "## Assets",
        "",
        "The following files have been uploaded for this plan.",
        "Use the absolute `path` to read, copy, or reference each asset in your work.",
        "",
    ]
    for asset in all_assets:
        original = asset.get("original_name", asset["filename"])
        mime = asset.get("mime_type", "unknown")
        # Use portable relative path
        portable_path = f".assets/{original}"
        lines.append(f"- **{original}** (`{mime}`)")
        lines.append(f"  - path: `{portable_path}`")

    assets_block = "\n".join(lines) + "\n"

    # Replace existing ## Assets … block, or insert before the first ## section.
    # Use ^## to avoid matching #### Assets sub-sections.
    assets_pattern = r"^## Assets\n(?:.*\n)*?(?=\n## |\Z)"
    if _re_mod.search(assets_pattern, content, _re_mod.MULTILINE):
        content = _re_mod.sub(assets_pattern, assets_block, content, count=1, flags=_re_mod.MULTILINE)
    else:
        first_section = _re_mod.search(r"\n## ", content)
        if first_section:
            pos = first_section.start()
            content = content[:pos] + "\n" + assets_block + "\n" + content[pos:]
        else:
            content = content.rstrip() + "\n\n" + assets_block

    plan_file.write_text(content)


def _update_epic_asset_sections(plan_id: str, all_assets: list, assets_dir: Path) -> None:
    """Insert or replace #### Assets sub-sections within each epic block in the plan markdown.

    Assets bound to a specific epic are listed under that epic's #### Assets heading.
    Placed after #### Tasks and before depends_on:.
    """
    plan_file = PLANS_DIR / f"{plan_id}.md"
    if not plan_file.exists():
        return

    content = plan_file.read_text()

    # Group assets by epic
    by_epic: Dict[str, List[Dict[str, Any]]] = {}
    for asset in all_assets:
        for epic in asset.get("bound_epics", []):
            if epic not in by_epic:
                by_epic[epic] = []
            by_epic[epic].append(asset)

    # Bug 2 Fix: Find all epic sections using #{2,3} to match both ## and ### headers
    epic_pattern = _re_mod.compile(r"(#{2,3} (EPIC-\d+)[^\n]*\n)")
    matches = list(epic_pattern.finditer(content))

    if not matches:
        return

    # Process epics in reverse order to preserve positions
    for i in range(len(matches) - 1, -1, -1):
        match = matches[i]
        epic_ref = match.group(2)
        epic_start = match.start()

        # Find the end of this epic section (next ## or ### or end of file)
        # Bug 2 Fix: Use #{2,3} to match both heading levels
        if i + 1 < len(matches):
            epic_end = matches[i + 1].start()
        else:
            epic_end = len(content)

        epic_block = content[epic_start:epic_end]

        # Remove existing #### Assets section (migration) and > Assets: line.
        epic_block = _re_mod.sub(
            r"\n?#### Assets\n(?:(?!####|depends_on:|\n---|\n#{2,3} ).*\n)*",
            "\n",
            epic_block,
        )
        epic_block = _re_mod.sub(
            r"\n?> Assets: .*\n?",
            "\n",
            epic_block,
        )

        # Build new > Assets: line if this epic has assets
        epic_assets = by_epic.get(epic_ref, [])
        if epic_assets:
            asset_entries = []
            for asset in epic_assets:
                original = asset.get("original_name", asset["filename"])
                atype = asset.get("asset_type", "unspecified")
                mime = asset.get("mime_type", "unknown")
                desc = asset.get("description", "")

                # Format: .assets/spec.yaml (api-spec, text/yaml) — API spec
                entry = f".assets/{original} ({atype}, {mime})"
                if desc:
                    entry += f" — {desc}"
                asset_entries.append(entry)

            asset_line = "> Assets: " + "; ".join(asset_entries) + "\n"

            # Insert after Skills: if present, or before depends_on:/---
            skills_match = _re_mod.search(r"\nSkills: .*\n", epic_block)
            if skills_match:
                insert_pos = skills_match.end()
                epic_block = epic_block[:insert_pos] + asset_line + epic_block[insert_pos:]
            else:
                depends_match = _re_mod.search(r"\ndepends_on:", epic_block)
                separator_match = _re_mod.search(r"\n---", epic_block)
                insert_pos = None
                if depends_match:
                    insert_pos = depends_match.start()
                elif separator_match:
                    insert_pos = separator_match.start()

                if insert_pos is not None:
                    epic_block = epic_block[:insert_pos] + "\n" + asset_line + epic_block[insert_pos:]
                else:
                    epic_block = epic_block.rstrip() + "\n\n" + asset_line

        content = content[:epic_start] + epic_block + content[epic_end:]

    plan_file.write_text(content)


def _parse_epic_assets_from_markdown(content: str) -> Dict[str, List[str]]:
    """Parse #### Assets sections from plan markdown and return {epic_ref: [asset_entries]}.

    Each entry is the raw text line describing an asset (e.g., "spec.yaml (api-spec, text/yaml)").
    """
    result: Dict[str, List[str]] = {}

    # Bug 2 Fix: Find all epic sections using #{2,3} to match both ## and ### headers
    epic_pattern = _re_mod.compile(r"#{2,3} (EPIC-\d+)[^\n]*\n")
    matches = list(epic_pattern.finditer(content))

    for i, match in enumerate(matches):
        epic_ref = match.group(1)
        epic_start = match.end()

        if i + 1 < len(matches):
            epic_end = matches[i + 1].start()
        else:
            epic_end = len(content)

        epic_block = content[epic_start:epic_end]

        # Check for new format: > Assets: ...
        new_match = _re_mod.search(r"^> Assets: (.*)$", epic_block, _re_mod.MULTILINE)
        if new_match:
            # Semicolon-separated entries
            entries = [e.strip() for e in new_match.group(1).split(";") if e.strip()]
            if entries:
                result[epic_ref] = entries
        else:
            # Fallback to legacy format
            # Bug 2 Fix: Use #{2,3} in lookahead to match both heading levels
            assets_match = _re_mod.search(r"#### Assets\n((?:.*\n)*?)(?=####|\ndepends_on:|\n---|\n#{2,3} |\Z)", epic_block)
            if assets_match:
                asset_text = assets_match.group(1)
                entries = []
                for line in asset_text.strip().split("\n"):
                    line = line.strip()
                    if line.startswith("- "):
                        entries.append(line[2:])
                if entries:
                    result[epic_ref] = entries

    return result


def _parse_multipart_files(content_type: str, body: bytes) -> List[Dict[str, Any]]:
    if "multipart/form-data" not in content_type.lower():
        raise HTTPException(status_code=400, detail="Content-Type must be multipart/form-data")

    parser = BytesParser(policy=default)
    message = parser.parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    )
    if not message.is_multipart():
        raise HTTPException(status_code=400, detail="Invalid multipart payload")

    files: List[Dict[str, Any]] = []
    fields: Dict[str, str] = {}
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        field_name = part.get_param("name", header="content-disposition")

        if field_name == "files":
            filename = part.get_filename()
            if not filename:
                continue
            files.append({
                "filename": Path(filename).name,
                "content_type": part.get_content_type() or "application/octet-stream",
                "data": part.get_payload(decode=True) or b"",
            })
        elif field_name in ("epic_ref", "asset_type", "tags"):
            payload = part.get_payload(decode=True)
            if payload:
                fields[field_name] = payload.decode("utf-8", errors="replace")

    return files, fields

def _merge_plan_meta(plan: dict, plans_dir: Path) -> None:
    """Merge {plan_id}.meta.json fields into a plan dict (in-place).

    Adds working_dir, warrooms_dir, launched_at, and a nested 'meta' object
    so the frontend has the full project context from plan creation.
    """
    meta_file = plans_dir / f"{plan['plan_id']}.meta.json"
    if not meta_file.exists():
        return
    try:
        meta = json.loads(meta_file.read_text())
        for key in ("working_dir", "warrooms_dir", "launched_at", "status", "thread_id"):
            if key in meta and meta[key]:
                plan[key] = meta[key]
        plan["meta"] = meta
    except (json.JSONDecodeError, OSError):
        pass


@router.get("/api/plans/{plan_id}/assets")
async def list_plan_assets(plan_id: str, user: dict = Depends(get_current_user)):
    _require_plan_file(plan_id)
    meta = _ensure_plan_meta(plan_id)
    assets = [_serialize_plan_asset(plan_id, asset) for asset in _normalize_plan_assets(plan_id, meta)]
    return {"plan_id": plan_id, "assets": assets, "count": len(assets)}


@router.post("/api/plans/{plan_id}/assets")
async def upload_plan_assets(
    plan_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    _require_plan_file(plan_id)
    content_type = request.headers.get("content-type", "")
    files, fields = _parse_multipart_files(content_type, await request.body())
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    epic_ref = fields.get("epic_ref", "").strip() or None
    asset_type = fields.get("asset_type", "").strip() or "unspecified"
    tags_str = fields.get("tags", "").strip()
    tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []

    # FIX-1: Validate epic_ref before proceeding
    if epic_ref:
        _validate_epic_ref(plan_id, epic_ref)

    meta = _ensure_plan_meta(plan_id)
    existing_assets = _normalize_plan_assets(plan_id, meta)
    assets_dir = _plan_assets_dir(plan_id)
    assets_dir.mkdir(parents=True, exist_ok=True)

    saved_assets: List[Dict[str, Any]] = []
    extracted_count = 0

    for upload in files:
        original_name = upload["filename"]
        upload_data = upload["data"]
        content_type = upload["content_type"]

        # Check if file is a ZIP archive
        is_zip = (
            content_type in ["application/zip", "application/x-zip-compressed", "application/x-zip"] or
            original_name.lower().endswith('.zip')
        )

        if is_zip:
            # Extract all files from ZIP
            extracted_files = _extract_files_from_zip(
                zip_data=upload_data,
                original_zip_name=original_name,
                epic_ref=epic_ref,
                asset_type=asset_type,
                tags=tags,
            )

            # Save extracted files
            for extracted in extracted_files:
                stored_name = _safe_asset_filename(extracted["original_name"])
                asset_path = assets_dir / stored_name

                with asset_path.open("wb") as handle:
                    handle.write(extracted["data"])

                saved_assets.append({
                    "filename": stored_name,
                    "original_name": extracted["original_name"],
                    "mime_type": extracted["mime_type"],
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    "size_bytes": extracted["size_bytes"],
                    "bound_epics": extracted["bound_epics"],
                    "asset_type": extracted["asset_type"],
                    "tags": extracted["tags"],
                    "description": "",
                })
                extracted_count += 1
        else:
            # Normal file upload
            stored_name = _safe_asset_filename(original_name)
            asset_path = assets_dir / stored_name

            with asset_path.open("wb") as handle:
                handle.write(upload_data)

            saved_assets.append({
                "filename": stored_name,
                "original_name": original_name,
                "mime_type": content_type,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "size_bytes": len(upload_data),
                "bound_epics": [epic_ref] if epic_ref else [],
                "asset_type": asset_type,
                "tags": tags,
                "description": "",
            })

    if extracted_count > 0:
        logger.info(f"Extracted {extracted_count} files from ZIP archives for plan {plan_id}")

    # R2-FIX-4: Replace existing assets with same original_name
    existing_assets = _replace_existing_assets(plan_id, existing_assets, saved_assets)

    all_assets = existing_assets + saved_assets
    meta["assets"] = all_assets

    # Update epic_assets index if binding was requested
    if epic_ref:
        ea = meta.setdefault("epic_assets", {})
        if epic_ref not in ea:
            ea[epic_ref] = []
        for sa in saved_assets:
            if sa["filename"] not in ea[epic_ref]:
                ea[epic_ref].append(sa["filename"])

    _write_plan_meta(plan_id, meta)

    # FIX-2: Sync both plan-level and per-epic asset sections in markdown
    _sync_asset_sections(plan_id)

    return {
        "plan_id": plan_id,
        "assets": [_serialize_plan_asset(plan_id, asset) for asset in saved_assets],
        "count": len(saved_assets),
    }


# ── EPIC-002: Asset Management API Endpoints ─────────────────────


@router.post("/api/plans/{plan_id}/assets/{filename}/bind")
async def api_bind_asset(plan_id: str, filename: str, request: Request, user: dict = Depends(get_current_user)):
    """Bind an existing asset to an epic."""
    _require_plan_file(plan_id)
    get_asset_or_404(plan_id, filename)

    body = await request.json()
    epic_ref = body.get("epic_ref")
    if not epic_ref:
        raise HTTPException(status_code=400, detail="epic_ref is required")

    bind_asset_to_epic(plan_id, filename, epic_ref)
    asset = get_asset_or_404(plan_id, filename)
    return {"status": "bound", "asset": _serialize_plan_asset(plan_id, asset)}


@router.delete("/api/plans/{plan_id}/assets/{filename}/bind/{epic_ref}")
async def api_unbind_asset(plan_id: str, filename: str, epic_ref: str, user: dict = Depends(get_current_user)):
    """Unbind an asset from an epic."""
    _require_plan_file(plan_id)
    get_asset_or_404(plan_id, filename)

    unbind_asset_from_epic(plan_id, filename, epic_ref)
    asset = get_asset_or_404(plan_id, filename)
    return {"status": "unbound", "asset": _serialize_plan_asset(plan_id, asset)}


@router.get("/api/plans/{plan_id}/epics/{epic_ref}/assets")
async def api_list_epic_assets(plan_id: str, epic_ref: str, user: dict = Depends(get_current_user)):
    """List assets for a specific epic (plan-level + epic-bound)."""
    _require_plan_file(plan_id)
    assets = list_epic_assets(plan_id, epic_ref)
    serialized = []
    for asset in assets:
        s = _serialize_plan_asset(plan_id, asset)
        s["binding"] = "epic" if epic_ref in asset.get("bound_epics", []) else "plan"
        serialized.append(s)
    return {"plan_id": plan_id, "epic_ref": epic_ref, "assets": serialized, "count": len(serialized)}


@router.patch("/api/plans/{plan_id}/assets/{filename}")
async def api_update_asset_metadata(plan_id: str, filename: str, request: Request, user: dict = Depends(get_current_user)):
    """Update asset metadata (type, tags, description)."""
    _require_plan_file(plan_id)
    _validate_id(filename, "filename")
    body = await request.json()

    updated = update_asset_metadata(
        plan_id,
        filename,
        asset_type=body.get("asset_type"),
        tags=body.get("tags"),
        description=body.get("description"),
    )
    return {"status": "updated", "asset": _serialize_plan_asset(plan_id, updated)}


@router.get("/api/plans/{plan_id}/assets/{filename}/download")
async def download_asset(plan_id: str, filename: str, user: dict = Depends(get_current_user)):
    """Download an asset file."""
    _require_plan_file(plan_id)
    _validate_id(filename, "filename")
    asset_path = _plan_assets_dir(plan_id) / filename
    if not asset_path.exists():
        raise HTTPException(status_code=404, detail=f"Asset file {filename} not found")

    meta = _ensure_plan_meta(plan_id)
    _normalize_plan_assets(plan_id, meta)
    asset = next((a for a in meta.get("assets", []) if a.get("filename") == filename), None)
    mime = asset.get("mime_type", "application/octet-stream") if asset else "application/octet-stream"
    original = asset.get("original_name", filename) if asset else filename

    def iter_file():
        with open(asset_path, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(
        iter_file(),
        media_type=mime,
        headers={"Content-Disposition": f'inline; filename="{original}"'},
    )


@router.post("/api/plans/{plan_id}/generate-from-assets")
async def generate_plan_from_assets(
    plan_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Generate a plan based on uploaded assets using AI.

    Takes the assets already uploaded to this plan and generates a structured plan
    using the PLAN.template.md. The generated plan replaces the current plan content.
    The AI analyzes the actual file contents, not just metadata.
    """
    from dashboard.plan_agent import PlanAgent

    _require_plan_file(plan_id)
    meta = _ensure_plan_meta(plan_id)
    assets = _normalize_plan_assets(plan_id, meta)
    assets_dir = _plan_assets_dir(plan_id)

    if not assets:
        raise HTTPException(status_code=400, detail="No assets found in this plan")

    # Build asset context for AI - including actual file contents
    asset_sections = []

    # Read text-based files (limit to reasonable size)
    MAX_FILE_SIZE = 50000  # 50KB per file
    TEXT_MIME_PREFIXES = ['text/', 'application/json', 'application/xml', 'application/yaml']
    TEXT_EXTENSIONS = ['.txt', '.md', '.yaml', '.yml', '.json', '.xml', '.csv', '.log', '.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css', '.sql', '.sh', '.env', '.cfg', '.ini', '.toml']

    for asset in assets:
        name = asset.get("original_name", asset.get("filename", "unknown"))
        stored_name = asset.get("filename", name)
        atype = asset.get("asset_type", "unspecified")
        desc = asset.get("description", "")
        size = asset.get("size_bytes", 0)
        mime = asset.get("mime_type", "unknown")
        epics = asset.get("bound_epics", [])

        asset_path = assets_dir / stored_name

        # Build asset section
        section = f"\n### Asset: {name}\n"
        section += f"- **Type:** {atype}\n"
        section += f"- **MIME:** {mime}\n"
        section += f"- **Size:** {size} bytes\n"
        if desc:
            section += f"- **Description:** {desc}\n"
        if epics:
            section += f"- **Bound to:** {', '.join(epics)}\n"

        # Try to read file contents if it's text-based
        is_text = (
            any(mime.startswith(prefix) for prefix in TEXT_MIME_PREFIXES) or
            any(name.lower().endswith(ext) for ext in TEXT_EXTENSIONS)
        )

        if asset_path.exists() and size > 0 and size <= MAX_FILE_SIZE and is_text:
            try:
                content = asset_path.read_text(encoding='utf-8', errors='ignore')
                if content.strip():
                    section += f"\n**Content:**\n```\n{content}\n```\n"
            except Exception as e:
                logger.warning(f"Could not read asset {name}: {e}")
        elif asset_path.exists() and is_text and size > MAX_FILE_SIZE:
            section += f"\n**Note:** File is too large ({size} bytes) to include fully. First 5000 characters:\n```\n"
            try:
                with open(asset_path, 'r', encoding='utf-8', errors='ignore') as f:
                    section += f.read(5000) + "...\n```\n"
            except Exception:
                section += "```\n"
        elif mime.startswith('image/'):
            section += f"\n**Note:** This is an image/design mockup. The agent should reference this visual design when building the UI.\n"
        elif mime.startswith('video/'):
            section += f"\n**Note:** This is a video file. Consider adding a content creation or media epic.\n"
        elif mime.startswith('audio/'):
            section += f"\n**Note:** This is an audio file. Consider adding a content creation or media epic.\n"

        asset_sections.append(section)

    asset_context = "\n".join(asset_sections)

    # Build prompt for AI
    prompt = f"""Create a detailed, actionable plan based on the following uploaded assets.

Analyze the actual file contents provided below and create specific, concrete epics and tasks.

{asset_context}

## Instructions:

1. **Read the file contents carefully** - Don't just use the filenames. Extract specific requirements, designs, or specifications from the actual content.

2. **Create specific, actionable epics:**
   - For API specs (YAML/JSON): Create backend epics with specific endpoints
   - For design mockups: Create frontend epics matching the visual design
   - For test data: Create QA/testing epics with specific test scenarios
   - For reference docs: Create documentation or research epics
   - For config files: Create infrastructure/setup epics

3. **Be specific:** Instead of generic tasks like "Implement API", use "Implement POST /users endpoint as specified in api-spec.yaml line 45"

4. **Reference the assets:** Each task should reference which asset it relates to (e.g., "Based on design-mockup.png, implement the hero section")

5. **Extract details:** If a YAML spec defines 5 endpoints, create tasks for each endpoint. If a mockup shows 3 components, create tasks for each.

Create a detailed, concrete plan that directly uses the information in these files."""

    # Use PlanAgent to generate the plan
    try:
        agent = PlanAgent(plans_dir=PLANS_DIR, agents_dir=AGENTS_DIR)

        # Stream the generation
        result_text = ""
        async for chunk in agent.stream_refinement(
            plan_id=plan_id,
            user_message=prompt,
            working_dir=None,
        ):
            if chunk.get("type") == "token":
                result_text += chunk.get("content", "")

        # Parse the result
        from dashboard.plan_agent import parse_structured_response
        parsed = parse_structured_response(result_text)

        if not parsed.get("plan"):
            raise HTTPException(status_code=500, detail="AI failed to generate a valid plan")

        # Save the generated plan
        plan_file = PLANS_DIR / f"{plan_id}.md"
        plan_file.write_text(parsed["plan"])

        # Update meta
        title_match = re.search(r"^# (?:Plan|PLAN):\s*(.+)", parsed["plan"], re.MULTILINE)
        title = title_match.group(1).strip() if title_match else plan_id
        meta["title"] = title
        meta["status"] = "draft"
        _write_plan_meta(plan_id, meta)

        # Sync asset sections
        _sync_asset_sections(plan_id)

        return {
            "status": "generated",
            "plan_id": plan_id,
            "plan": parsed["plan"],
            "explanation": parsed.get("explanation", ""),
        }

    except Exception as e:
        logger.error(f"Failed to generate plan from assets: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate plan: {str(e)}")


@router.get("/api/plans")
async def list_plans(
    q: Optional[str] = Query(None, description="Semantic search query to filter plans"),
    order_by: str = Query("created_desc", description="Sort order: created_desc, created_asc, title, time_id"),
    user: dict = Depends(get_current_user),
):
    """List all stored plans (disk is source of truth, zvec enriches).

    When `q` is provided, performs a semantic vector search via zvec to find
    matching plans. Results are ranked by relevance. When `q` is absent,
    returns all plans as before.
    """
    store = global_state.store
    plans_dir = PLANS_DIR

    if not plans_dir.exists():
        return {"plans": [], "count": 0}

    # ── Semantic search gate ─────────────────────────────────────────────
    # When a query is provided, use zvec to find matching plan_ids first.
    search_plan_ids: Optional[set] = None      # None  = no filter (return all)
    search_ranked_ids: Optional[list] = None   # ordered list for relevance sort
    if q and q.strip():
        q_clean = q.strip()
        if store:
            try:
                search_results = store.search_plans(q_clean, limit=50)
                search_plan_ids = {r["plan_id"] for r in search_results}
                search_ranked_ids = [r["plan_id"] for r in search_results]
            except Exception as e:
                logger.warning("zvec plan search failed, falling back to all: %s", e)
                # Fall through — search_plan_ids stays None → returns all plans

        # If zvec is unavailable or returned nothing, there are no matches
        if search_plan_ids is not None and len(search_plan_ids) == 0:
            return {"plans": [], "count": 0}

    # Build a lookup of zvec-indexed plans for enrichment
    zvec_plans: Dict[str, dict] = {}
    if store:
        try:
            for p in store.get_all_plans():
                zvec_plans[p["plan_id"]] = p
        except Exception as e:
            logger.warning("Failed to load plans from zvec: %s", e)

    plans = []
    for f in sorted(plans_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        # Skip template and .refined.md variants
        if f.stem == "PLAN.template":
            continue
        if f.name.endswith(".refined.md"):
            continue
        content = f.read_text()
        if not content.strip():
            continue

        plan_id = f.stem

        # Skip plans not in search results when a query is active
        if search_plan_ids is not None and plan_id not in search_plan_ids:
            continue

        # Start from zvec data if available, otherwise parse from disk
        if plan_id in zvec_plans:
            p = zvec_plans[plan_id].copy()
            # Ensure disk-derived fields are present
            if "filename" not in p or not p["filename"]:
                p["filename"] = f.name
            if "content" not in p or not p["content"]:
                p["content"] = content
        else:
            title_match = re.search(r"^# (?:Plan|PLAN):\s*(.+)", content, re.MULTILINE)
            title = title_match.group(1).strip() if title_match else plan_id

            epics_found = re.findall(r"^#{2,3} (?:(?:Epic|Task):\s*\S+|EPIC-\d+|TASK-\d+)", content, re.MULTILINE)
            epic_count = len(epics_found)

            status_match = re.search(r"^>\s*Status:\s*(\w+)", content, re.MULTILINE)
            status = status_match.group(1).lower() if status_match else "stored"

            from dashboard.zvec_store import uuid7
            p = {
                "plan_id": plan_id,
                "time_id": uuid7(),
                "title": title,
                "content": content,
                "status": status,
                "epic_count": epic_count,
                "created_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
                "filename": f.name,
            }

            # Best-effort: backfill zvec index for this missing plan
            if store:
                try:
                    store.index_plan(
                        plan_id=plan_id, title=p["title"], content=content,
                        epic_count=p.get("epic_count", 0), filename=f.name,
                        status=p["status"], created_at=p["created_at"],
                        file_mtime=f.stat().st_mtime,
                    )
                    logger.info("Backfilled zvec index for plan %s", plan_id)
                except Exception as e:
                    logger.warning("Failed to backfill plan %s into zvec: %s", plan_id, e)

        # Merge meta.json for working_dir etc.
        _merge_plan_meta(p, plans_dir)

        # Derive lifecycle from runner PID + progress.json heartbeat. This is
        # the single source of truth for "is this plan running?" — the
        # zvec-derived status was a fallback heuristic that only ever produced
        # "completed".
        from dashboard.plan_lifecycle import derive_lifecycle
        lifecycle = derive_lifecycle(plan_id)
        p["lifecycle"] = lifecycle
        p["status"] = lifecycle["state"]

        # Enrich from progress.json if available
        warrooms_dir = p.get("warrooms_dir")
        if not warrooms_dir:
            runtime_warrooms_dir = resolve_runtime_plan_warrooms_dir(plan_id)
            if runtime_warrooms_dir:
                warrooms_dir = str(runtime_warrooms_dir)
                p["warrooms_dir"] = warrooms_dir

        if warrooms_dir:
            # Role distribution from DAG.json
            dag_file = Path(warrooms_dir) / "DAG.json"
            role_dist = {}
            if dag_file.exists():
                try:
                    dag_data = json.loads(dag_file.read_text())
                    for node_data in dag_data.get("nodes", {}).values():
                        role = node_data.get("role")
                        if role:
                            role_dist[role] = role_dist.get(role, 0) + 1
                except (json.JSONDecodeError, OSError):
                    pass
            p["role_distribution"] = role_dist

            prog_file = Path(warrooms_dir) / "progress.json"
            if prog_file.exists():
                try:
                    prog = json.loads(prog_file.read_text())
                    p["epic_count"] = prog.get("total", p.get("epic_count", 0))
                    p["completed_epics"] = prog.get("passed", 0)
                    p["active_epics"] = prog.get("active", 0)
                    p["pct_complete"] = prog.get("pct_complete", 0)
                    p["escalations"] = sum(
                        1 for r in prog.get("rooms", [])
                        if r.get("status") == "manager-triage"
                    )
                    cp_str = prog.get("critical_path", "")
                    if "/" in str(cp_str):
                        parts = str(cp_str).split("/")
                        p["critical_path"] = {"completed": int(parts[0]), "total": int(parts[1])}
                except (json.JSONDecodeError, OSError, ValueError):
                    pass

        # When no progress.json exists yet, leave the counters at zero rather
        # than inventing fake values. Slash commands should render "0%" for
        # a draft plan, not random motion.
        p.setdefault("pct_complete", 0)
        p.setdefault("active_epics", 0)
        p.setdefault("completed_epics", 0)

        plans.append(p)

    # ── Sorting ──────────────────────────────────────────────────────────
    # When searching, default to relevance order (zvec ranking) unless
    # the caller explicitly requests a different sort.
    if search_ranked_ids is not None and order_by == "created_desc":
        # Preserve zvec relevance ranking
        rank_lookup = {pid: i for i, pid in enumerate(search_ranked_ids)}
        plans.sort(key=lambda x: rank_lookup.get(x.get("plan_id", ""), 999))
    elif order_by == "created_desc":
        plans.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    elif order_by == "created_asc":
        plans.sort(key=lambda x: x.get("created_at", ""))
    elif order_by == "title":
        plans.sort(key=lambda x: x.get("title", "").lower())
    elif order_by == "time_id":
        plans.sort(key=lambda x: x.get("time_id", ""), reverse=True)

    return {"plans": plans, "count": len(plans)}

def _get_stats_history() -> List[Dict]:
    history_file = AGENTS_DIR / "stats_history.json"
    if history_file.exists():
        try:
            return json.loads(history_file.read_text())
        except:
            return []
    return []

def _save_stats_snapshot(current_stats: Dict):
    history = _get_stats_history()
    now = datetime.now(timezone.utc)
    now_str = now.isoformat()

    # One snapshot per day is enough for the trends/sparkline requested
    today_str = now_str[:10]
    if history and history[-1]["timestamp"][:10] == today_str:
        history[-1].update(current_stats)
        history[-1]["timestamp"] = now_str
    else:
        history.append({"timestamp": now_str, **current_stats})

    # Keep last 14 days
    if len(history) > 14:
        history = history[-14:]

    (AGENTS_DIR / "stats_history.json").write_text(json.dumps(history, indent=2) + "\n")

@router.get("/api/stats")
async def get_stats(user: dict = Depends(get_current_user)):
    """Aggregate stats across all plans.

    Per-plan status is derived from :mod:`dashboard.plan_lifecycle` (runner
    PID liveness + progress.json heartbeat) so a crashed plan flips from
    ``running`` to ``stopped`` automatically. Epic counters are still summed
    from each plan's progress.json — that file is truth for room outcomes.
    """
    from datetime import timedelta
    from dashboard.plan_lifecycle import derive_lifecycle
    plans_dir = PLANS_DIR
    total_plans = 0
    plan_status_counts = {
        "draft": 0, "running": 0, "stopped": 0, "completed": 0, "failed": 0,
    }
    active_epics = 0
    total_epics = 0
    passed_epics = 0
    escalations = 0

    seen_progress_files = set()

    if plans_dir.exists():
        for f in sorted(plans_dir.glob("*.md")):
            if f.stem == "PLAN.template" or f.name.endswith(".refined.md"):
                continue
            total_plans += 1

            plan_id = f.stem
            lifecycle = derive_lifecycle(plan_id)
            state = lifecycle["state"]
            plan_status_counts[state] = plan_status_counts.get(state, 0) + 1

            meta_file = plans_dir / f"{plan_id}.meta.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text())
                    warrooms_dir = meta.get("warrooms_dir")
                    if warrooms_dir:
                        prog_file = Path(warrooms_dir) / "progress.json"
                        if prog_file.exists():
                            seen_progress_files.add(str(prog_file))
                except (json.JSONDecodeError, OSError):
                    pass

    # Aggregate from unique progress files to avoid double-counting
    for pf_path in seen_progress_files:
        try:
            prog = json.loads(Path(pf_path).read_text())
            active_epics += prog.get("active", 0)
            total_epics += prog.get("total", 0)
            passed_epics += prog.get("passed", 0)
            for room in prog.get("rooms", []):
                if room.get("status") == "manager-triage":
                    escalations += 1
        except (json.JSONDecodeError, OSError):
            pass

    # Weighted average completion rate
    completion_rate = (passed_epics / total_epics * 100) if total_epics > 0 else 0

    current_stats = {
        "total_plans": total_plans,
        "active_epics": active_epics,
        "completion_rate": round(completion_rate, 1),
        "escalations_pending": escalations,
        "plan_status_counts": plan_status_counts
    }

    # Load history
    history = _get_stats_history()

    # Calculate trends
    def get_trend(key, days_ago):
        target_date = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()[:10]
        # Find the value closest to target_date
        past_val = current_stats[key]
        if history:
            for h in reversed(history):
                if h["timestamp"][:10] <= target_date:
                    past_val = h[key]
                    break

        delta = current_stats[key] - past_val
        direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
        return {"direction": direction, "delta": abs(round(delta, 1))}

    # Active Epics Sparkline (7 points from last 14 days)
    sparkline_points = []
    # history currently has 14 mock points + 1 current snapshot
    full_history = history + [{"timestamp": datetime.now(timezone.utc).isoformat(), **current_stats}]

    # Take up to 7 samples from history
    if len(full_history) >= 7:
        # Sample evenly across history
        step = len(full_history) / 7
        for i in range(7):
            idx = int(i * step)
            sparkline_points.append(full_history[idx]["active_epics"])
    else:
        # Pad with current value if not enough history
        for h in full_history:
            sparkline_points.append(h["active_epics"])
        while len(sparkline_points) < 7:
            sparkline_points.insert(0, sparkline_points[0] if sparkline_points else 0)

    # If no history, we need to save one now so it starts accumulating
    if not history:
        _save_stats_snapshot(current_stats)

    return {
        "total_plans": {
            "value": total_plans,
            "trend": get_trend("total_plans", 7),
            "distribution": plan_status_counts,
        },
        "active_epics": {
            "value": active_epics,
            "trend": get_trend("active_epics", 1),
            "sparkline": sparkline_points
        },
        "completion_rate": {
            "value": round(completion_rate, 1),
            "trend": get_trend("completion_rate", 7)
        },
        "escalations_pending": {
            "value": escalations,
            "trend": get_trend("escalations_pending", 1)
        }
    }




@router.post("/api/plans/{plan_id}/reload")
async def reload_plan_from_disk(plan_id: str, user: dict = Depends(get_current_user)):
    """Re-read .md file from disk and update zvec index."""
    plans_dir = PLANS_DIR
    plan_file = plans_dir / f"{plan_id}.md"
    if not plan_file.exists():
        raise HTTPException(status_code=404, detail="Plan file not found")

    content = plan_file.read_text()
    mtime = plan_file.stat().st_mtime

    # Re-parse metadata
    title_match = re.search(r"^# (?:Plan|PLAN):\s*(.+)", content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else plan_id
    epics_found = re.findall(r"^#{2,3} (?:(?:Epic|Task):\s*\S+|EPIC-\d+|TASK-\d+)", content, re.MULTILINE)
    epic_count = len(epics_found)

    # Get created_at from meta.json if available
    meta_file = plans_dir / f"{plan_id}.meta.json"
    created_at = ""
    status = "stored"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            created_at = meta.get("created_at", "")
            status = meta.get("status", "stored")
        except Exception: pass

    store = global_state.store
    if store:
        try:
            store.index_plan(
                plan_id=plan_id,
                title=title,
                content=content,
                epic_count=epic_count,
                filename=f"{plan_id}.md",
                status=status,
                created_at=created_at,
                file_mtime=mtime
            )
        except Exception as e:
            logger.error(f"Failed to update zvec in reload_plan: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return {"status": "reloaded", "plan_id": plan_id}

@router.get("/api/plans/{plan_id}/sync-status")
async def get_plan_sync_status(plan_id: str, user: dict = Depends(get_current_user)):
    """Check if the physical .md file is in sync with zvec index."""
    plans_dir = PLANS_DIR
    plan_file = plans_dir / f"{plan_id}.md"
    if not plan_file.exists():
        raise HTTPException(status_code=404, detail="Plan file not found")

    disk_mtime = plan_file.stat().st_mtime

    store = global_state.store
    zvec_mtime = 0.0
    if store:
        p = store.get_plan(plan_id)
        if p:
            zvec_mtime = p.get("file_mtime", 0.0)

    # Simple float comparison for mtime
    in_sync = abs(disk_mtime - zvec_mtime) < 0.001

    return {
        "in_sync": in_sync,
        "disk_mtime": disk_mtime,
        "zvec_mtime": zvec_mtime
    }

def create_plan_on_disk(title: str, content: Optional[str], working_dir: Optional[str] = None, thread_id: Optional[str] = None) -> dict:
    """Helper to write plan.md, meta.json, and roles.json to disk and index in zvec store."""
    raw = f"{title}:{datetime.now(timezone.utc).isoformat()}"
    plan_id = hashlib.sha256(raw.encode()).hexdigest()[:12]
    plans_dir = _resolve_plans_dir_for_write()
    plans_dir.mkdir(exist_ok=True)
    plan_file = plans_dir / f"{plan_id}.md"

    # Auto-create project subfolder under ~/.ostwin/projects/ if no dir specified
    if not working_dir or working_dir == '.':
        slug = _re_mod.sub(r'[^a-zA-Z0-9]+', '-', title.lower()).strip('-')[:40]
        if not slug:
            slug = plan_id
        project_dir = Path.home() / ".ostwin" / "projects" / slug
        project_dir.mkdir(parents=True, exist_ok=True)
        working_dir = str(project_dir)

    if content:
        # Bug 1 Fix: Normalize the header to ensure '# Plan: {title}' prefix
        content = _normalize_plan_header(content, title)
        plan_file.write_text(content)
    else:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        short_title = _re_mod.sub(r'[^a-zA-Z0-9]+', ' ', title).strip().title()[:60]
        plan_file.write_text(f"# Plan: {short_title}\n\n> Created: {now}\n> Status: draft\n\n## Config\n\nworking_dir: {working_dir}\n\n---\n\n## Goal\n\n{title}\n\n## Epics\n\n> AI worker is drafting the plan structure. This placeholder will be replaced.\n\ndepends_on: []\n")

    # Bug 3 Fix: Initialize assets and epic_assets in meta.json
    meta_file = plans_dir / f"{plan_id}.meta.json"
    meta = {
        "plan_id": plan_id,
        "title": title,
        "working_dir": working_dir,
        "warrooms_dir": str(Path(working_dir) / ".war-rooms"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "draft",
        "assets": [],
        "epic_assets": {}
    }
    # Migrate thread assets to plan assets if thread_id is provided
    if thread_id:
        meta["thread_id"] = thread_id
        try:
            from dashboard.asset_store import ASSETS_DIR
            thread_assets_dir = ASSETS_DIR / "threads" / thread_id
            if thread_assets_dir.exists() and thread_assets_dir.is_dir():
                import shutil
                assets_target_dir = _plan_assets_dir(plan_id)
                assets_target_dir.mkdir(parents=True, exist_ok=True)

                migrated_assets = []
                for asset_file in sorted(thread_assets_dir.iterdir()):
                    if asset_file.is_file():
                        stored_name = _safe_asset_filename(asset_file.name)
                        target_path = assets_target_dir / stored_name
                        shutil.copy2(str(asset_file), str(target_path))

                        ext = asset_file.suffix.lower()
                        mime_map = {".jpg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}

                        migrated_assets.append({
                            "filename": stored_name,
                            "original_name": asset_file.name,
                            "mime_type": mime_map.get(ext, "application/octet-stream"),
                            "uploaded_at": datetime.now(timezone.utc).isoformat(),
                            "size_bytes": asset_file.stat().st_size,
                            "bound_epics": [],
                            "asset_type": "unspecified",
                            "tags": [],
                            "description": "Migrated from brainstorming session"
                        })
                if migrated_assets:
                    meta["assets"] = migrated_assets
                    logger.info(f"Migrated {len(migrated_assets)} assets from thread {thread_id} to plan {plan_id}")
        except Exception as e:
            logger.warning(f"Failed to migrate thread assets: {e}")

    meta_file.write_text(json.dumps(meta, indent=2) + "\n")

    if meta.get("assets"):
        try:
            _sync_asset_sections(plan_id)
        except Exception as e:
            logger.warning(f"Failed to sync asset sections to markdown for plan {plan_id}: {e}")


    plan_roles_file = plans_dir / f"{plan_id}.roles.json"
    if not plan_roles_file.exists():
        global_config_file = AGENTS_DIR / "config.json"
        seed_config = json.loads(global_config_file.read_text()) if global_config_file.exists() else {}
        from dashboard.routes.roles import load_roles
        for role in load_roles():
            if role.name not in seed_config:
                seed_config[role.name] = {}
            rc = seed_config[role.name]
            rc.setdefault("default_model", role.version)
            rc.setdefault("timeout_seconds", role.timeout_seconds)
            if role.skill_refs:
                rc.setdefault("skill_refs", role.skill_refs)
        plan_roles_file.write_text(json.dumps(seed_config, indent=2) + "\n")

    store = global_state.store
    if store:
        try:
            store.index_plan(
                plan_id=plan_id, title=title, content=plan_file.read_text(),
                epic_count=0, filename=f"{plan_id}.md", status="draft",
                created_at=meta["created_at"], file_mtime=plan_file.stat().st_mtime
            )
        except Exception as e:
            logger.warning("Failed to index new plan %s in zvec: %s", plan_id, e)

    return {
        "plan_id": plan_id,
        "url": f"/plans/{plan_id}",
        "title": title,
        "working_dir": working_dir,
        "filename": f"{plan_id}.md"
    }

@router.get("/api/plans/{plan_id}")
async def get_plan(plan_id: str, user: dict = Depends(get_current_user)):
    """Get a specific plan with its epics and meta.json details."""
    store = global_state.store
    plan = None
    epics = []

    if store:
        plan = store.get_plan(plan_id)
        epics = store.get_epics_for_plan(plan_id)

    if not plan:
        plans_dir = PLANS_DIR
        plan_file = plans_dir / f"{plan_id}.md"
        if not plan_file.exists():
            raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
        content = plan_file.read_text()
        title_match = re.search(r"^# (?:Plan|PLAN):\s*(.+)", content, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else plan_id
        epic_count = len(re.findall(r"^#{2,3} (?:(?:Epic|Task):\s*\S+|EPIC-\d+|TASK-\d+)", content, re.MULTILINE))
        from dashboard.zvec_store import uuid7
        plan = {
            "plan_id": plan_id, "time_id": uuid7(), "title": title, "content": content, "status": "stored",
            "epic_count": epic_count,
            "created_at": datetime.fromtimestamp(plan_file.stat().st_mtime, tz=timezone.utc).isoformat(),
            "filename": plan_file.name,
        }

    # --- Merge meta.json for full project context ---
    _merge_plan_meta(plan, PLANS_DIR)

    # Derive lifecycle (running / stopped / completed / failed / draft) from
    # the runner PID + heartbeat instead of trusting meta.json.status, which
    # is only written on launch and never updated on exit.
    from dashboard.plan_lifecycle import derive_lifecycle
    lifecycle = derive_lifecycle(plan_id)
    plan["lifecycle"] = lifecycle
    plan["status"] = lifecycle["state"]

    return {"plan": plan, "epics": epics}

@router.post("/api/plans/create")
async def create_plan(request: CreatePlanRequest):
    """Create a new plan."""
    return create_plan_on_disk(
        title=request.title,
        content=request.content,
        working_dir=request.working_dir or request.path
    )

@router.post("/api/plans/{plan_id}/save")
async def save_plan(plan_id: str, request: SavePlanRequest, user: dict = Depends(get_current_user)):
    plans_dir = PLANS_DIR
    plan_file = plans_dir / f"{plan_id}.md"
    if not plan_file.exists():
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")

    # Bug 1 Fix: Normalize header before saving
    normalized_content = _normalize_plan_header(request.content, plan_id)

    store = global_state.store
    old_content = plan_file.read_text()
    if old_content.strip() and old_content.strip() != normalized_content.strip():
        if store:
            try:
                old_title_match = re.search(r"^# (?:Plan|PLAN):\s*(.+)", old_content, re.MULTILINE)
                old_title = old_title_match.group(1).strip() if old_title_match else plan_id
                old_epics = len(re.findall(r"^#{2,3} (?:(?:Epic|Task):\s*\S+|EPIC-\d+|TASK-\d+)", old_content, re.MULTILINE))
                store.save_plan_version(
                    plan_id=plan_id, content=old_content, title=old_title,
                    epic_count=old_epics, change_source=request.change_source,
                )
            except Exception as e:
                logger.warning("Failed to snapshot plan version for %s: %s", plan_id, e)

    plan_file.write_text(normalized_content)
    new_mtime = plan_file.stat().st_mtime

    # Update meta if title changed (best effort)
    title_match = re.search(r"^# (?:Plan|PLAN):\s*(.+)", normalized_content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else plan_id

    meta = {"plan_id": plan_id, "title": title, "status": "draft", "created_at": datetime.now(timezone.utc).isoformat()}
    meta_file = plans_dir / f"{plan_id}.meta.json"
    if meta_file.exists():
        try:
            stored_meta = json.loads(meta_file.read_text())
            meta.update(stored_meta) # keep existing fields
            meta["title"] = title    # update title from content
            meta_file.write_text(json.dumps(meta, indent=2) + "\n")
        except Exception: pass

    # Update zvec if available
    if store:
        try:
            # Re-parse epic count
            epics_found = re.findall(r"^#{2,3} (?:(?:Epic|Task):\s*\S+|EPIC-\d+|TASK-\d+)", normalized_content, re.MULTILINE)
            epic_count = len(epics_found)

            store.index_plan(
                plan_id=plan_id,
                title=title,
                content=normalized_content,
                epic_count=epic_count,
                filename=f"{plan_id}.md",
                status=meta.get("status", "draft"),
                created_at=meta.get("created_at", datetime.now(timezone.utc).isoformat()),
                file_mtime=new_mtime
            )
        except Exception as e:
            logger.error(f"Failed to update zvec in save_plan: {e}")

    # R2-FIX-1: Parse asset sections from the saved markdown and merge edits into meta,
    # then regenerate the sections so meta.json and PLAN.md stay in sync.
    try:
        _merge_markdown_asset_edits_into_meta(plan_id, normalized_content)
        _sync_asset_sections(plan_id)
    except Exception:
        pass  # Best-effort: don't fail save if asset section sync fails

    return {"status": "saved", "plan_id": plan_id}


@router.delete("/api/plans/{plan_id}")
async def delete_plan(plan_id: str, user: dict = Depends(get_current_user)):
    """Delete a plan and all its artifacts from global store and working directory."""
    import shutil

    # Validate plan_id format to prevent path traversal
    if not re.fullmatch(r"[0-9a-f]{12}", plan_id):
        raise HTTPException(status_code=400, detail="Invalid plan ID format")

    plan_file = _find_plan_file(plan_id)
    if not plan_file:
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")

    cleaned: list[str] = []

    # --- Read meta.json for working_dir before we delete it ---
    working_dir = None
    meta_file = _find_plan_meta(plan_id)
    if meta_file and meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            working_dir = meta.get("working_dir")
        except (json.JSONDecodeError, OSError):
            pass

    # --- 1. Remove from global store (~/.ostwin/.agents/plans/) ---
    plans_dir = plan_file.parent
    for suffix in (".md", ".meta.json", ".roles.json"):
        f = plans_dir / f"{plan_id}{suffix}"
        if f.exists():
            f.unlink()
            cleaned.append(str(f))

    assets_dir = plans_dir / "assets" / plan_id
    if assets_dir.exists() and assets_dir.is_dir():
        shutil.rmtree(assets_dir)
        cleaned.append(str(assets_dir))

    # --- 2. Remove working dir artifacts ---
    if working_dir:
        wd = Path(working_dir)
        if wd.exists() and wd.is_dir():
            agents_dir = wd / ".agents"
            if agents_dir.exists() and agents_dir.is_dir():
                shutil.rmtree(agents_dir)
                cleaned.append(str(agents_dir))

            warrooms_dir = wd / ".war-rooms"
            if warrooms_dir.exists() and warrooms_dir.is_dir():
                shutil.rmtree(warrooms_dir)
                cleaned.append(str(warrooms_dir))

    # --- 3. Remove from zvec index ---
    store = global_state.store
    if store:
        try:
            store.delete_plan(plan_id)
        except Exception as e:
            logger.warning("Failed to remove plan %s from zvec index: %s", plan_id, e)

    logger.info("Deleted plan %s — cleaned: %s", plan_id, cleaned)
    return {"status": "deleted", "plan_id": plan_id, "cleaned_paths": cleaned}


def _resolve_plan_file(plan_id: str) -> Optional[Path]:
    """Find the plan .md file — checks project-local dir then ~/.ostwin."""
    local = PLANS_DIR / f"{plan_id}.md"
    if local.exists():
        return local
    global_path = Path.home() / ".ostwin" / ".agents" / "plans" / f"{plan_id}.md"
    if global_path.exists():
        return global_path
    return None


@router.get("/api/plans/{plan_id}/roles")
async def get_plan_roles(plan_id: str, user: dict = Depends(get_current_user)):
    """Get effective roles by parsing Roles: directives from the plan markdown.

    Single file read + JSON config lookup.  No war-room scanning, no vector
    DB queries, no SKILL.md YAML parsing.
    """
    plan_file = _resolve_plan_file(plan_id)
    if not plan_file:
        raise HTTPException(status_code=404, detail=f"Plan file not found: {plan_id}")

    effective_names = _parse_roles_from_markdown(plan_file.read_text())

    # Build lightweight role objects from plan config + role registry
    # (avoids the expensive build_roles_list → SKILL.md YAML scan)
    plan_config = get_plan_roles_config(plan_id)

    # Quick role lookup from the on-disk role.json files (no skill scanning)
    role_registry: Dict[str, dict] = {}
    for roles_root in [AGENTS_DIR / "roles", Path.home() / ".ostwin" / ".agents" / "roles"]:
        if not roles_root.exists():
            continue
        for role_dir in roles_root.iterdir():
            if not role_dir.is_dir():
                continue
            rj = role_dir / "role.json"
            if rj.exists():
                try:
                    data = json.loads(rj.read_text())
                    role_registry[data.get("name", role_dir.name)] = data
                except (json.JSONDecodeError, OSError):
                    pass

    def _build_role(name: str) -> dict:
        reg = role_registry.get(name, {})
        cfg = plan_config.get(name, {})
        return {
            "name": name,
            "description": reg.get("description", cfg.get("description", "")),
            "default_model": cfg.get("default_model", reg.get("default_model", "")),
            "timeout_seconds": cfg.get("timeout_seconds", reg.get("timeout_seconds", 600)),
            "temperature": cfg.get("temperature", 0.7),
            "skill_refs": cfg.get("skill_refs", reg.get("skill_refs", [])),
            "disabled_skills": cfg.get("disabled_skills", []),
        }

    if effective_names:
        role_defaults = [_build_role(n) for n in effective_names]
    else:
        # No Roles: directives — return all configured roles
        all_names = list(dict.fromkeys(
            list(plan_config.keys()) + list(role_registry.keys())
        ))
        role_defaults = [_build_role(n) for n in all_names]

    return {
        "role_defaults": role_defaults,
        "effective_roles": effective_names,
    }

@router.get("/api/plans/{plan_id}/config")
async def get_plan_config(plan_id: str, user: dict = Depends(get_current_user)):
    """Get the role configuration for a plan."""
    return get_plan_roles_config(plan_id)

@router.post("/api/plans/{plan_id}/config")
async def update_plan_config(plan_id: str, config: Dict[str, Any], user: dict = Depends(get_current_user)):
    """Update the role configuration for a plan."""
    plans_dir = PLANS_DIR
    config_file = plans_dir / f"{plan_id}.roles.json"
    config_file.write_text(json.dumps(config, indent=2) + "\n")
    return {"status": "updated", "plan_id": plan_id}

@router.post("/api/plans/{plan_id}/skills")
async def attach_skill(plan_id: str, skill: Dict[str, str], user: dict = Depends(get_current_user)):
    """Attach a skill to a plan."""
    config = get_plan_roles_config(plan_id)
    if "attached_skills" not in config:
        config["attached_skills"] = []

    skill_name = skill.get("name")
    if not skill_name:
        raise HTTPException(status_code=400, detail="Skill name is required")

    if skill_name not in config["attached_skills"]:
        config["attached_skills"].append(skill_name)

    plans_dir = PLANS_DIR
    config_file = plans_dir / f"{plan_id}.roles.json"
    config_file.write_text(json.dumps(config, indent=2) + "\n")
    return {"status": "attached", "plan_id": plan_id, "skill": skill_name}

@router.delete("/api/plans/{plan_id}/skills/{skill_name}")
async def detach_skill(plan_id: str, skill_name: str, user: dict = Depends(get_current_user)):
    """Detach a skill from a plan."""
    config = get_plan_roles_config(plan_id)
    if "attached_skills" in config and skill_name in config["attached_skills"]:
        config["attached_skills"].remove(skill_name)

    plans_dir = PLANS_DIR
    config_file = plans_dir / f"{plan_id}.roles.json"
    config_file.write_text(json.dumps(config, indent=2) + "\n")
    return {"status": "detached", "plan_id": plan_id, "skill": skill_name}

@router.post("/api/run")
async def run_plan(request: RunRequest, user: dict = Depends(get_current_user)):
    """Launch OS Twin with the provided plan content.

    plan_id is required. The endpoint is idempotent:
    - .md file is only written when the content actually changed.
    - .meta.json is upserted (preserves created_at and custom fields).
    - .roles.json is only seeded from global config when it does not exist yet,
      so user customisations are never overwritten.
    """
    plan = request.plan.strip()
    if not plan:
        raise HTTPException(status_code=422, detail="Plan content is empty")

    # Quick pre-flight: must contain a goal (# Plan: title) or at least one EPIC/Task.
    # Plans without EPICs are allowed — Start-Plan.ps1 will auto-generate them from the goal.
    has_epics = bool(_re_mod.search(r"^#{2,3} (?:EPIC-|Task:|Epic:)", plan, _re_mod.MULTILINE))
    has_goal = bool(_re_mod.search(r"^#\s+(?:Plan|PLAN):\s*.+", plan, _re_mod.MULTILINE))
    if not has_epics and not has_goal:
        raise HTTPException(status_code=400, detail="Plan must contain a '# Plan: Title' goal or at least one '## EPIC-XXX - Title' section.")

    ostwin_bin = AGENTS_DIR / "bin" / "ostwin"
    if not ostwin_bin.exists():
        raise HTTPException(status_code=500, detail="OS Twin binary not found")

    plans_dir = PLANS_DIR
    plans_dir.mkdir(exist_ok=True)

    plan_id = request.plan_id
    plan_path = plans_dir / f"{plan_id}.md"
    plan_filename = plan_path.name

    # --- .md: only write when content actually changed ---
    existing_content = plan_path.read_text() if plan_path.exists() else None
    store = global_state.store
    if existing_content != plan:
        # Snapshot old content before overwriting
        if existing_content and existing_content.strip() and store:
            try:
                old_title_match = _re_mod.search(r"^# (?:Plan|PLAN):\s*(.+)", existing_content, _re_mod.MULTILINE)
                old_title = old_title_match.group(1).strip() if old_title_match else plan_id
                old_epics = len(_re_mod.findall(r"^#{2,3} (?:(?:Epic|Task):\s*\S+|EPIC-\d+|TASK-\d+)", existing_content, _re_mod.MULTILINE))
                store.save_plan_version(
                    plan_id=plan_id, content=existing_content, title=old_title,
                    epic_count=old_epics, change_source="expansion",
                )
            except Exception as e:
                logger.warning("Failed to snapshot plan version before launch %s: %s", plan_id, e)
        plan_path.write_text(plan)
        logger.info(f"run_plan: wrote updated plan content for {plan_id}")
    else:
        logger.debug(f"run_plan: plan content unchanged for {plan_id}, skipping write")

    # Extract title
    title_match = _re_mod.search(r"^# (?:Plan|PLAN):\s*(.+)", plan, _re_mod.MULTILINE)
    title = title_match.group(1).strip() if title_match else plan_id

    # Extract working_dir from plan content (## Config section)
    working_dir = None
    wd_match = _re_mod.search(r"working_dir:\s*(.+)", plan)
    if wd_match:
        working_dir = wd_match.group(1).strip()
    if not working_dir or working_dir == '.':
        slug = _re_mod.sub(r'[^a-zA-Z0-9]+', '-', title.lower()).strip('-')[:40] if title else plan_id
        if not slug:
            slug = plan_id
        working_dir = str(Path.home() / ".ostwin" / "projects" / slug)

    wd_path = Path(working_dir)
    if not wd_path.is_absolute():
        wd_path = Path.home() / ".ostwin" / "projects" / working_dir
    # Create the directory if it doesn't exist
    wd_path.mkdir(parents=True, exist_ok=True)
    working_dir = str(wd_path)

    # --- .meta.json: upsert — merge into existing, preserve created_at ---
    meta_path = plans_dir / f"{plan_id}.meta.json"
    existing_meta = {}
    if meta_path.exists():
        try:
            existing_meta = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    meta = {
        **existing_meta,                           # keep previous fields
        "plan_id": plan_id,
        "title": title,
        "working_dir": working_dir,
        "warrooms_dir": str(Path(working_dir) / ".war-rooms") if Path(working_dir).is_absolute() else str(PROJECT_ROOT / working_dir / ".war-rooms"),
        "status": "launched",
    }
    # Preserve original created_at; only set if missing
    if "created_at" not in meta:
        meta["created_at"] = datetime.now(timezone.utc).isoformat()
    meta["launched_at"] = datetime.now(timezone.utc).isoformat()

    meta_path.write_text(json.dumps(meta, indent=2))

    # --- .roles.json: seed from engine config + dashboard roles when file does NOT exist ---
    role_config_path = plans_dir / f"{plan_id}.roles.json"
    if not role_config_path.exists():
        global_config_file = AGENTS_DIR / "config.json"
        seed_config = {}
        if global_config_file.exists():
            try:
                seed_config = json.loads(global_config_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        # Merge dashboard roles (which have skill_refs) into the plan config
        from dashboard.routes.roles import load_roles
        for role in load_roles():
            if role.name not in seed_config:
                seed_config[role.name] = {}
            rc = seed_config[role.name]
            rc.setdefault("default_model", role.version)
            rc.setdefault("timeout_seconds", role.timeout_seconds)
            if role.skill_refs:
                rc.setdefault("skill_refs", role.skill_refs)
        role_config_path.write_text(json.dumps(seed_config, indent=2))
        logger.info(f"run_plan: seeded roles.json for {plan_id} from engine config + dashboard roles")
    else:
        logger.debug(f"run_plan: roles.json already exists for {plan_id}, preserving user customisations")

    # Sync with zvec store if available
    store = global_state.store
    if store:
        try:
            from dashboard.zvec_store import OSTwinStore
            # Parse epics
            epics = OSTwinStore._parse_plan_epics(plan, plan_id)
            now = datetime.now(timezone.utc).isoformat()
            store.index_plan(
                plan_id=plan_id, title=title, content=plan,
                epic_count=len(epics), filename=plan_filename,
                status="launched", created_at=now,
            )
            for epic in epics:
                store.index_epic(
                    epic_ref=epic["task_ref"], plan_id=plan_id,
                    title=epic["title"], body=epic["body"],
                    room_id=epic["room_id"],
                    working_dir=epic.get("working_dir", "."),
                    status="pending",
                )
        except Exception as e:
            logger.error(f"zvec: plan indexing failed ({e})")

    # Ensure target project is initialized with ostwin
    wd_path = Path(working_dir) if Path(working_dir).is_absolute() else PROJECT_ROOT / working_dir
    if not (wd_path / ".agents").exists():
        logger.info(f"run_plan: target dir {wd_path} not initialized, running ostwin init...")
        if ostwin_bin.exists():
            init_result = subprocess.run(
                [str(ostwin_bin), "init"],
                cwd=str(wd_path),
                capture_output=True, text=True, timeout=120,
            )
            if init_result.returncode != 0:
                logger.error(f"ostwin init failed in {wd_path}: {init_result.stderr}")
                raise HTTPException(status_code=500, detail=f"ostwin init failed in {wd_path}: {init_result.stderr[:200]}")
            logger.info(f"run_plan: ostwin init completed in {wd_path}")
        else:
            logger.warning(f"ostwin binary not found at {ostwin_bin}, skipping init")

    # Inject assets into working directory
    try:
        _inject_assets_to_working_directory(plan_id, wd_path)
    except Exception as e:
        logger.warning(f"Failed to inject assets for plan {plan_id}: {e}")

    # --- Sync plan files into the project's local .agents/plans/ ---
    # opencode's file sandbox blocks reads outside the project directory.
    # Agents need the plan file within their CWD tree, so copy from the
    # global store (PLANS_DIR) into {working_dir}/.agents/plans/.
    local_plans_dir = wd_path / ".agents" / "plans"
    local_plans_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    for suffix in (".md", ".meta.json", ".roles.json"):
        src = plans_dir / f"{plan_id}{suffix}"
        dst = local_plans_dir / f"{plan_id}{suffix}"
        if src.exists() and str(src.resolve()) != str(dst.resolve()):
            shutil.copy2(str(src), str(dst))
            logger.info(f"run_plan: synced {src.name} -> {local_plans_dir}")

    # Bug 4 Fix: Sync assets directory from PLANS_DIR/assets/{plan_id}/ to local .agents/plans/assets/{plan_id}/
    global_assets_dir = plans_dir / "assets" / plan_id
    local_assets_dir = local_plans_dir / "assets" / plan_id
    if global_assets_dir.exists() and global_assets_dir.is_dir():
        local_assets_dir.mkdir(parents=True, exist_ok=True)
        for asset_file in global_assets_dir.iterdir():
            if asset_file.is_file():
                dst_file = local_assets_dir / asset_file.name
                if not dst_file.exists() or str(dst_file.resolve()) != str(asset_file.resolve()):
                    shutil.copy2(str(asset_file), str(dst_file))
        logger.info(f"run_plan: synced assets -> {local_assets_dir}")

    # Use the local copy for ostwin run so the path is within the sandbox
    local_plan_path = local_plans_dir / f"{plan_id}.md"
    launch_plan_path = local_plan_path if local_plan_path.exists() else plan_path

    # Log file for debugging ostwin run
    log_file = wd_path / ".agents" / "logs" / f"launch-{plan_id}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(log_file, 'w')

    # Spawn OS Twin in background (capture output to log file)
    # Run from working_dir - ostwin will auto-detect project context
    proc = subprocess.Popen(
        [str(ostwin_bin), "run", str(launch_plan_path), "--non-interactive"],
        cwd=str(wd_path),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    logger.info(f"run_plan: launched ostwin run for {plan_id}, pid={proc.pid}, logs: {log_file}")

    # Record the runner PID so /api/plans, /api/stats, and the slash commands
    # can derive a truthful lifecycle (running/stopped/completed/failed) on
    # each request instead of guessing from stale meta.json status.
    from dashboard.plan_lifecycle import record_launch, register_runner
    try:
        record_launch(plan_id, proc.pid)
        # Keep the Popen handle so derive_lifecycle can poll() it and reap
        # zombies — otherwise a crashed runner stays "alive" until the
        # dashboard restarts.
        register_runner(proc.pid, proc)
    except Exception as e:
        logger.warning("run_plan: failed to record launch lifecycle for %s: %s", plan_id, e)

    return {"status": "launched", "plan_file": plan_filename, "plan_id": plan_id, "runner_pid": proc.pid}

@router.post("/api/plans/{plan_id}/status")
async def update_plan_status(plan_id: str, request: dict):
    plans_dir = PLANS_DIR
    meta_file = plans_dir / f"{plan_id}.meta.json"
    if not meta_file.exists():
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
    meta = json.loads(meta_file.read_text())
    meta["status"] = request.get("status", meta["status"])
    meta_file.write_text(json.dumps(meta, indent=2) + "\n")

    # Update zvec if available
    store = global_state.store
    if store:
        try:
            store.index_plan(
                plan_id=plan_id, title=meta.get("title", ""),
                content="", # placeholder
                status=meta["status"],
                filename=f"{plan_id}.md",
                created_at=meta.get("created_at", "")
            )
        except Exception: pass
    return {"status": "updated", "plan_id": plan_id, "new_status": meta["status"]}

# --- Plan Versioning ---

@router.get("/api/plans/{plan_id}/versions")
async def list_plan_versions(plan_id: str, user: dict = Depends(get_current_user)):
    """List all versions for a plan (content excluded for performance)."""
    store = global_state.store
    if not store or not hasattr(store, 'get_plan_versions'):
        return {"plan_id": plan_id, "versions": [], "count": 0}
    try:
        versions = store.get_plan_versions(plan_id)
    except Exception:
        return {"plan_id": plan_id, "versions": [], "count": 0}
    return {"plan_id": plan_id, "versions": versions, "count": len(versions)}

@router.get("/api/plans/{plan_id}/versions/{version}")
async def get_plan_version(plan_id: str, version: int, user: dict = Depends(get_current_user)):
    """Fetch a specific plan version with full content."""
    store = global_state.store
    if not store or not hasattr(store, 'get_plan_version'):
        raise HTTPException(status_code=503, detail="Version store not available")
    try:
        v = store.get_plan_version(plan_id, version)
    except Exception:
        raise HTTPException(status_code=503, detail="Version store error")
    if not v:
        raise HTTPException(status_code=404, detail=f"Version {version} not found for plan {plan_id}")
    return {"plan_id": plan_id, "version": v}

@router.post("/api/plans/{plan_id}/versions/{version}/restore")
async def restore_plan_version(plan_id: str, version: int, user: dict = Depends(get_current_user)):
    """Restore a previous version as the current plan content."""
    store = global_state.store
    if not store:
        raise HTTPException(status_code=503, detail="Version store not available")

    # Fetch the version to restore
    v = store.get_plan_version(plan_id, version)
    if not v:
        raise HTTPException(status_code=404, detail=f"Version {version} not found for plan {plan_id}")

    plans_dir = PLANS_DIR
    plan_file = plans_dir / f"{plan_id}.md"
    if not plan_file.exists():
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")

    # Snapshot current content before restoring
    current_content = plan_file.read_text()
    if current_content.strip():
        try:
            cur_title_match = re.search(r"^# (?:Plan|PLAN):\s*(.+)", current_content, re.MULTILINE)
            cur_title = cur_title_match.group(1).strip() if cur_title_match else plan_id
            cur_epics = len(re.findall(r"^#{2,3} (?:(?:Epic|Task):\s*\S+|EPIC-\d+|TASK-\d+)", current_content, re.MULTILINE))
            store.save_plan_version(
                plan_id=plan_id, content=current_content, title=cur_title,
                epic_count=cur_epics, change_source="before_restore",
            )
        except Exception as e:
            logger.warning("Failed to snapshot before restore %s: %s", plan_id, e)

    # Restore
    restored_content = v["content"]
    plan_file.write_text(restored_content)

    # Update zvec plan index
    try:
        title_match = re.search(r"^# (?:Plan|PLAN):\s*(.+)", restored_content, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else plan_id
        epics_found = re.findall(r"^#{2,3} (?:(?:Epic|Task):\s*\S+|EPIC-\d+|TASK-\d+)", restored_content, re.MULTILINE)
        store.index_plan(
            plan_id=plan_id, title=title, content=restored_content,
            epic_count=len(epics_found), filename=f"{plan_id}.md",
        )
    except Exception as e:
        logger.warning("Failed to update zvec after restore %s: %s", plan_id, e)

    return {"status": "restored", "plan_id": plan_id, "restored_version": version}

@router.get("/api/plans/{plan_id}/changes")
async def list_plan_changes(plan_id: str, user: dict = Depends(get_current_user)):
    """Unified timeline of plan versions and git-based asset changes."""
    store = global_state.store
    plans_dir = PLANS_DIR
    plan_file = plans_dir / f"{plan_id}.md"

    if not plan_file.exists():
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")

    # 1. Get working_dir from plan meta
    working_dir = None
    meta_file = plans_dir / f"{plan_id}.meta.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            working_dir = meta.get("working_dir")
        except Exception:
            pass

    if not working_dir:
        # Try resolving via api_utils
        from dashboard.api_utils import resolve_plan_warrooms_dir
        warrooms_dir = resolve_plan_warrooms_dir(plan_id)
        if warrooms_dir:
            working_dir = str(warrooms_dir.parent)

    changes = []

    # 2. Get git log and status if available
    if working_dir and Path(working_dir).exists():
        try:
            # Check if we are in a git repo
            proc_check = await asyncio.create_subprocess_exec(
                "git", "rev-parse", "--is-inside-work-tree",
                cwd=working_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc_check.communicate()

            if proc_check.returncode == 0:
                # 2.1. Get uncommitted changes (git status)
                proc_status = await asyncio.create_subprocess_exec(
                    "git", "status", "--porcelain",
                    cwd=working_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout_status, _ = await proc_status.communicate()
                if stdout_status:
                    status_lines = stdout_status.decode().splitlines()
                    uncommitted_files = []
                    for line in status_lines:
                        if len(line) > 3:
                            uncommitted_files.append(line[3:].strip())

                    if uncommitted_files:
                        changes.append({
                            "id": "uncommitted",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "author": "Current Session",
                            "message": "Uncommitted local changes",
                            "files": uncommitted_files,
                            "type": "asset_change",
                            "source": "git",
                            "is_uncommitted": True
                        })

                # 2.2. Get last 50 commits with file changes
                cmd = ["git", "log", "-n", "50", "--pretty=format:%H|%cI|%an|%s", "--name-only"]
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=working_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode == 0:
                    lines = stdout.decode().splitlines()
                    current_commit = None
                    for line in lines:
                        if "|" in line:
                            parts = line.split("|", 3)
                            if len(parts) == 4:
                                current_commit = {
                                    "id": parts[0],
                                    "timestamp": parts[1],
                                    "author": parts[2],
                                    "message": parts[3],
                                    "files": [],
                                    "type": "asset_change",
                                    "source": "git"
                                }
                                changes.append(current_commit)
                        elif line.strip() and current_commit:
                            current_commit["files"].append(line.strip())
        except Exception as e:
            logger.warning(f"Failed to read git log for {plan_id}: {e}")

    # 3. Add plan versions from zvec if available
    if store:
        if hasattr(store, 'get_plan_versions'):
            try:
                versions = store.get_plan_versions(plan_id)
                for v in versions:
                    changes.append({
                        "id": v["id"],
                        "version": v["version"],
                        "timestamp": v["created_at"],
                        "title": v["title"],
                        "change_source": v["change_source"],
                        "type": "plan_version",
                        "source": "zvec"
                    })
            except Exception: pass

        if hasattr(store, 'get_changes_for_plan'):
            try:
                asset_changes = store.get_changes_for_plan(plan_id)
                for ac in asset_changes:
                    changes.append({
                        "id": ac["id"],
                        "timestamp": ac["timestamp"],
                        "change_type": ac["change_type"],
                        "file_path": ac["file_path"],
                        "diff_summary": ac["diff_summary"],
                        "source": ac["source"],
                        "type": "asset_change"
                    })
            except Exception: pass

    # 4. Sort all changes by timestamp desc
    changes.sort(key=lambda x: x["timestamp"], reverse=True)

    return {"plan_id": plan_id, "changes": changes, "count": len(changes)}

@router.get("/api/plans/{plan_id}/changes/{change_id}/diff")
async def get_change_diff(plan_id: str, change_id: str, file_path: str = Query(None), user: dict = Depends(get_current_user)):
    """Fetch the diff for a specific change entry."""
    store = global_state.store
    plans_dir = PLANS_DIR

    # Case 1: Plan version (zvec)
    if change_id.startswith(f"{plan_id}-v"):
        if not store or not hasattr(store, 'get_plan_version'):
            raise HTTPException(status_code=503, detail="Version store not available")

        try:
            # We want to compare v with v-1
            m = re.match(rf"{plan_id}-v(\d+)", change_id)
            if not m:
                raise HTTPException(status_code=400, detail="Invalid change ID")
            v_num = int(m.group(1))

            v_curr = store.get_plan_version(plan_id, v_num)
            if not v_curr:
                raise HTTPException(status_code=404, detail="Version not found")

            # Get previous content
            v_prev_content = ""
            if v_num > 1:
                v_prev = store.get_plan_version(plan_id, v_num - 1)
                if v_prev:
                    v_prev_content = v_prev["content"]
            else:
                # v1 should be compared with nothing or the very first state if known
                pass

            import difflib
            diff = difflib.unified_diff(
                v_prev_content.splitlines(keepends=True),
                v_curr["content"].splitlines(keepends=True),
                fromfile=f"v{v_num-1}", tofile=f"v{v_num}"
            )
            return {"diff": "".join(diff), "type": "plan_version", "id": change_id}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # Case 1.5: Asset change from zvec
    if store and hasattr(store, 'get_change_event'):
        ce = store.get_change_event(change_id)
        if ce:
            return {
                "diff": ce.get("diff_summary", "No diff available."),
                "type": "asset_change",
                "id": change_id,
                "source": ce.get("source"),
                "file_path": ce.get("file_path")
            }

    # Case 2: Git commit (asset change)
    # 2.1. Find working_dir
    working_dir = None
    meta_file = plans_dir / f"{plan_id}.meta.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            working_dir = meta.get("working_dir")
        except Exception:
            pass
    if not working_dir:
        from dashboard.api_utils import resolve_plan_warrooms_dir
        warrooms_dir = resolve_plan_warrooms_dir(plan_id)
        if warrooms_dir:
            working_dir = str(warrooms_dir.parent)

    if working_dir and Path(working_dir).exists():
        try:
            if change_id == "uncommitted":
                # git diff for unstaged and staged changes
                cmd = ["git", "diff", "HEAD", "--no-color"]
                if file_path:
                    cmd = ["git", "diff", "HEAD", "--no-color", "--", file_path]
            else:
                # git show change_id
                cmd = ["git", "show", change_id, "--no-color"]
                if file_path:
                    cmd = ["git", "show", change_id, "--no-color", "--", file_path]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=working_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                diff_out = stdout.decode()
                if not diff_out and change_id == "uncommitted":
                    diff_out = "No diff available for uncommitted changes (might be untracked files)."
                return {"diff": diff_out, "type": "asset_change", "id": change_id}
            else:
                raise HTTPException(status_code=500, detail=stderr.decode())
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    raise HTTPException(status_code=404, detail="Change entry not found")

@router.get("/api/goals")
async def get_all_goals():
    """Aggregate goals from all plans."""
    plans_dir = PLANS_DIR
    if not plans_dir.exists():
        return {"goals": []}

    all_goals = []
    for f in plans_dir.glob("*.md"):
        if f.stem == "PLAN.template":
            continue
        content = f.read_text()
        # Simple heuristic for goals
        goal_section = re.search(r"## Goal\n\n(.*?)\n\n##", content, re.DOTALL)
        if goal_section:
            all_goals.append({
                "plan_id": f.stem,
                "goal": goal_section.group(1).strip()
            })
    return {"goals": all_goals}

def _persist_plan_images_from_data_uris(plan_id: str, images: list) -> None:
    """Persist data URI images from a refine request as plan assets."""
    if not images or not plan_id:
        return

    try:
        meta = _ensure_plan_meta(plan_id)
        existing_assets = _normalize_plan_assets(plan_id, meta)
        assets_dir = _plan_assets_dir(plan_id)
        assets_dir.mkdir(parents=True, exist_ok=True)

        saved_assets = []
        for img in images:
            data_uri = img.get("url", "")
            if not data_uri.startswith("data:"):
                continue

            original_name = img.get("name", "attachment")

            import base64
            import hashlib
            m = re.match(r"data:([^;]+);base64,(.+)", data_uri, re.DOTALL)
            if not m:
                continue

            mime_type = m.group(1)
            raw_bytes = base64.b64decode(m.group(2))

            # Reuse _safe_asset_filename but ensure we have an extension
            ext = ""
            if mime_type == "image/jpeg": ext = ".jpg"
            elif mime_type == "image/png": ext = ".png"
            elif mime_type == "image/gif": ext = ".gif"
            elif mime_type == "image/webp": ext = ".webp"

            if ext and not original_name.lower().endswith(ext):
                original_name += ext

            stored_name = _safe_asset_filename(original_name)
            asset_path = assets_dir / stored_name

            with asset_path.open("wb") as handle:
                handle.write(raw_bytes)

            saved_assets.append({
                "filename": stored_name,
                "original_name": original_name,
                "mime_type": mime_type,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "size_bytes": len(raw_bytes),
                "bound_epics": [],
                "asset_type": "unspecified",
                "tags": [],
                "description": "Uploaded during plan refinement"
            })

        if saved_assets:
            all_assets = existing_assets + saved_assets
            meta["assets"] = all_assets
            _write_plan_meta(plan_id, meta)
            _sync_asset_sections(plan_id)
            logger.info(f"Persisted {len(saved_assets)} images as assets for plan {plan_id}")
    except Exception as e:
        logger.warning(f"Failed to persist refine images for plan {plan_id}: {e}")

@router.post("/api/plans/refine")
async def refine_plan_endpoint(request: RefineRequest):
    try:
        from plan_agent import refine_plan
        plans_dir = PLANS_DIR
        plan_content = request.plan_content
        if request.plan_id and not plan_content:
            p_file = plans_dir / f"{request.plan_id}.md"
            if p_file.exists():
                plan_content = p_file.read_text()
        user_message = request.message
        if request.asset_context:
            asset_lines = []
            for asset in request.asset_context:
                asset_name = asset.get("original_name") or asset.get("filename") or "attachment"
                mime_type = asset.get("mime_type") or "application/octet-stream"
                asset_path = asset.get("path") or asset.get("filename") or "<unknown>"
                asset_lines.append(f"- {asset_name} ({mime_type}) at {asset_path}")
            user_message = (
                f"{request.message}\n\n"
                "Plan assets available for reference:\n"
                f"{chr(10).join(asset_lines)}\n"
                "Use these files as supporting context when refining the plan."
            )
        # Convert images to format expected by plan_agent
        images = None
        if request.images:
            images = [{"url": img.get("url", "")} for img in request.images if img.get("url")]
            logger.info(f"[REFINE] Received {len(images)} image(s) for multimodal processing")
            for i, img in enumerate(images[:3]):  # Log first 3
                url_preview = img["url"][:100] + "..." if len(img["url"]) > 100 else img["url"]
                logger.info(f"[REFINE] Image {i+1}: {url_preview}")

            # Persist these images to the plan's assets!
            if request.plan_id:
                _persist_plan_images_from_data_uris(request.plan_id, [img.model_dump() for img in request.images])
        result = await refine_plan(user_message=user_message, plan_content=plan_content, chat_history=request.chat_history, model=request.model, plans_dir=plans_dir if plans_dir.exists() else None, working_dir=request.working_dir or None, images=images, conversation_id=f"plan-{request.plan_id}" if request.plan_id else None)
        if isinstance(result, dict):
            # Backward compatible: refined_plan is a string. Rich info is also available.
            return {
                "refined_plan": result.get("full_response", ""),
                "explanation": result.get("explanation", ""),
                "actions": result.get("actions", []),
                "plan": result.get("plan", ""),
                "raw_result": result # For debugging/future-proofing
            }
        return {"refined_plan": result}
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"LLM SDK not available: {e}. Install with: pip install openai google-genai")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Plan refinement failed: {str(e)}")

@router.post("/api/plans/refine/stream")
async def refine_plan_stream_endpoint(request: RefineRequest):
    try:
        from plan_agent import refine_plan_stream
        plans_dir = PLANS_DIR
        plan_content = request.plan_content
        if request.plan_id and not plan_content:
            p_file = plans_dir / f"{request.plan_id}.md"
            if p_file.exists():
                plan_content = p_file.read_text()
        # Convert images for multimodal support
        images = None
        if request.images:
            images = [{"url": img.get("url", "")} for img in request.images if img.get("url")]

            # Persist these images to the plan's assets!
            if request.plan_id:
                _persist_plan_images_from_data_uris(request.plan_id, [img.model_dump() for img in request.images])
        async def event_generator():
            try:
                from plan_agent import parse_structured_response
                full_response = ""
                async for chunk in refine_plan_stream(user_message=request.message, plan_content=plan_content, chat_history=request.chat_history, model=request.model, plans_dir=plans_dir if plans_dir.exists() else None, working_dir=request.working_dir or None, images=images, conversation_id=f"plan-{request.plan_id}" if request.plan_id else None):
                    if isinstance(chunk, dict):
                        # If a dictionary is yielded, treat it as a rich event and accumulate if it has a 'token'
                        token = chunk.get("token", "")
                        full_response += token
                        yield f"data: {json.dumps(chunk)}\n\n"
                    else:
                        full_response += chunk
                        yield f"data: {json.dumps({'token': chunk})}\n\n"

                # After streaming is complete, parse the full response and emit as a structured result event
                result = parse_structured_response(full_response)
                yield f"data: {json.dumps({'result': result})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
        return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"LLM SDK not available: {e}. Install with: pip install openai google-genai")


@router.get("/api/plan-refine-prompt")
async def refine_prompt(mode: str = "refine"):
    """Return the plan-architect system prompt used by /api/plans/refine.

    Consumed by the ``ostwin-worker`` OpenCode subagent, which runs in the
    OpenCode runtime (TS/Bun) and therefore cannot call Python's
    ``plan_agent.get_system_prompt`` directly.  Keeping the prompt
    materialization on the dashboard side means the worker always uses the
    same template + roles-registry-rendered prompt the dashboard UI uses,
    even when the roles registry changes at runtime.

    mode: "refine" for the 3-section output format (dashboard refine endpoint)
          "worker" for direct file-writing format (ostwin-worker subagent)
    """
    from dashboard.plan_agent import get_system_prompt
    plans_dir = PLANS_DIR if PLANS_DIR.exists() else None
    agents_dir = plans_dir.parent if plans_dir else None
    prompt = get_system_prompt(plans_dir, agents_dir=agents_dir, working_dir=None, mode=mode)
    return {"system_prompt": prompt}


@router.get("/api/plans/{plan_id}/epics")
async def get_plan_epics(plan_id: str):
    store = global_state.store
    if store:
        epics = store.get_epics_for_plan(plan_id)
        if epics: return {"epics": epics, "count": len(epics)}
    plan_file = _find_plan_file(plan_id)
    if not plan_file:
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
    content = plan_file.read_text()
    from dashboard.zvec_store import OSTwinStore
    epics_raw = OSTwinStore._parse_plan_epics(content, plan_id)
    return {"epics": epics_raw, "count": len(epics_raw)}

@router.get("/api/search/plans")
async def search_plans(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=50)):
    store = global_state.store
    if not store: raise HTTPException(status_code=503, detail="Vector search not available")
    results = store.search_plans(q, limit=limit)
    return {"results": results, "count": len(results)}

@router.get("/api/search/epics")
async def search_epics(q: str = Query(..., min_length=1), plan_id: Optional[str] = Query(None), limit: int = Query(20, ge=1, le=100)):
    store = global_state.store
    if not store: raise HTTPException(status_code=503, detail="Vector search not available")
    results = store.search_epics(q, plan_id=plan_id, limit=limit)
    return {"results": results, "count": len(results)}

# --- Plan-scoped roles & rooms ---

@router.get("/api/plans/{plan_id}/roles/assignments")
async def get_plan_role_assignments(plan_id: str, user: dict = Depends(get_current_user)):
    config = get_plan_roles_config(plan_id)
    roles = build_roles_list(config, include_skills=True)
    warrooms_dir = resolve_runtime_plan_warrooms_dir(plan_id)
    rooms_with_roles = []
    role_summary: Dict[str, int] = {}
    if warrooms_dir and warrooms_dir.exists():
        for room_dir in sorted(warrooms_dir.glob("room-*")):
            if not room_dir.is_dir(): continue
            room_config_file = room_dir / "config.json"
            room_config = {}
            if room_config_file.exists():
                try:
                    room_config = json.loads(room_config_file.read_text())
                    if room_config.get("plan_id") and room_config["plan_id"] != plan_id: continue
                except json.JSONDecodeError: continue
            role_instances = []
            for f in sorted(room_dir.glob("*_*.json")):
                if f.name == "config.json": continue
                try:
                    data = json.loads(f.read_text())
                    if "role" in data and "instance_id" in data:
                        data["filename"] = f.name
                        role_instances.append(data)
                        rn = data["role"]
                        role_summary[rn] = role_summary.get(rn, 0) + 1
                except (json.JSONDecodeError, KeyError): continue
            if role_instances:
                rooms_with_roles.append({"room_id": room_dir.name, "task_ref": room_config.get("task_ref", "UNKNOWN"), "roles": role_instances})
    return {
        "plan_id": plan_id,
        "warrooms_dir": str(warrooms_dir) if warrooms_dir else None,
        "role_defaults": roles,
        "rooms": rooms_with_roles,
        "summary": role_summary,
        "total_assignments": sum(role_summary.values()),
        "attached_skills": config.get("attached_skills", [])
    }

@router.put("/api/plans/{plan_id}/roles/{role_name}/config")
async def update_plan_role_config(plan_id: str, role_name: str, request: UpdatePlanRoleConfigRequest, user: dict = Depends(get_current_user)):
    plans_dir = PLANS_DIR
    plan_roles_file = plans_dir / f"{plan_id}.roles.json"
    if plan_roles_file.exists(): config = json.loads(plan_roles_file.read_text())
    else:
        config_file = AGENTS_DIR / "config.json"
        config = json.loads(config_file.read_text()) if config_file.exists() else {}
    if role_name not in config: config[role_name] = {}
    if request.default_model is not None: config[role_name]["default_model"] = request.default_model
    if request.temperature is not None: config[role_name]["temperature"] = request.temperature
    if request.timeout_seconds is not None: config[role_name]["timeout_seconds"] = request.timeout_seconds
    if request.cli is not None: config[role_name]["cli"] = request.cli
    if request.skill_refs is not None: config[role_name]["skill_refs"] = request.skill_refs
    if request.disabled_skills is not None: config[role_name]["disabled_skills"] = request.disabled_skills
    plan_roles_file.write_text(json.dumps(config, indent=2) + "\n")
    return {"status": "updated", "plan_id": plan_id, "role": role_name, "config": config[role_name]}

@router.get("/api/plans/{plan_id}/rooms")
async def get_plan_rooms(plan_id: str, user: dict = Depends(get_current_user)):
    """Get war-rooms for a specific plan, using the plan's working_dir."""
    from dashboard.api_utils import read_room
    warrooms_dir = resolve_runtime_plan_warrooms_dir(plan_id)
    if not warrooms_dir or not warrooms_dir.exists():
        return {"plan_id": plan_id, "warrooms_dir": str(warrooms_dir) if warrooms_dir else None, "rooms": [], "count": 0}
    rooms = []
    for room_dir in sorted(warrooms_dir.glob("room-*")):
        if not room_dir.is_dir(): continue
        room_config_file = room_dir / "config.json"
        if room_config_file.exists():
            try:
                rc = json.loads(room_config_file.read_text())
                room_plan_id = rc.get("plan_id", "")
                # Only include shared-dir rooms that either explicitly match
                # the plan or are legacy unstamped rooms inside a plan-scoped dir.
                if room_plan_id and room_plan_id != plan_id:
                    continue
            except json.JSONDecodeError: continue
        # Use enhanced read_room with metadata for rich data
        room_data = read_room(room_dir, include_metadata=True)
        rooms.append(room_data)
    return {"plan_id": plan_id, "warrooms_dir": str(warrooms_dir), "rooms": rooms, "count": len(rooms)}


@router.get("/api/plans/{plan_id}/progress")
async def get_plan_progress(plan_id: str, user: dict = Depends(get_current_user)):
    """Get the progress.json content for a specific plan."""
    warrooms_dir = resolve_runtime_plan_warrooms_dir(plan_id)
    if not warrooms_dir:
        return {
            "total": 0, "passed": 0, "failed": 0, "blocked": 0, "active": 0, "pending": 0,
            "pct_complete": 0, "rooms": []
        }
    prog_file = warrooms_dir / "progress.json"
    if not prog_file.exists():
        return {
            "total": 0, "passed": 0, "failed": 0, "blocked": 0, "active": 0, "pending": 0,
            "pct_complete": 0, "rooms": []
        }
    try:
        data = json.loads(prog_file.read_text())
        cp_str = data.get("critical_path", "")
        if isinstance(cp_str, str) and "/" in cp_str:
            parts = cp_str.split("/")
            data["critical_path"] = {"completed": int(parts[0]), "total": int(parts[1])}
        return data
    except (json.JSONDecodeError, OSError):
        raise HTTPException(status_code=500, detail="Failed to read progress.json")


@router.post("/api/plans/{plan_id}/epics/{epic_ref}/state")
async def update_epic_state(plan_id: str, epic_ref: str, body: dict, user: dict = Depends(get_current_user)):
    """Change the status of an EPIC's war-room on disk.

    Writes the new status to ``room-xxx/status`` and recalculates
    ``progress.json`` by scanning every room in the plan's warrooms dir.

    Accepted body: ``{ "status": "passed" | "developing" | "pending" | ... }``
    """
    from dashboard.api_utils import resolve_plan_warrooms_dir

    new_status = body.get("status") or body.get("lifecycle_state")
    if not new_status:
        raise HTTPException(status_code=422, detail="Missing 'status' in request body")

    ALLOWED_STATUSES = {"passed", "developing", "pending", "blocked", "failed-final", "signoff"}
    if new_status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status '{new_status}'. Allowed: {sorted(ALLOWED_STATUSES)}")

    warrooms_dir = resolve_plan_warrooms_dir(plan_id)
    if not warrooms_dir.exists():
        raise HTTPException(status_code=404, detail=f"War-rooms directory not found for plan {plan_id}")

    # Find the room directory that matches this epic_ref via task-ref files
    target_room_dir = None
    for room_dir in sorted(warrooms_dir.glob("room-*")):
        if not room_dir.is_dir():
            continue
        tr_file = room_dir / "task-ref"
        if tr_file.exists() and tr_file.read_text().strip() == epic_ref:
            target_room_dir = room_dir
            break

    if not target_room_dir:
        raise HTTPException(status_code=404, detail=f"No war-room found for epic_ref '{epic_ref}' in plan {plan_id}")

    # Write new status to the room's status file
    status_file = target_room_dir / "status"
    status_file.write_text(new_status + "\n")

    # Recalculate progress.json by scanning all rooms
    _recalculate_progress(warrooms_dir)

    return {
        "status": "updated",
        "plan_id": plan_id,
        "epic_ref": epic_ref,
        "room_id": target_room_dir.name,
        "new_status": new_status,
    }


def _recalculate_progress(warrooms_dir: Path):
    """Rebuild progress.json by scanning all room-* directories.

    Mirrors the logic from ``.agents/plan/Update-Progress.ps1``.
    """
    from datetime import datetime, timezone

    total = passed = failed = blocked = active = pending = 0
    rooms = []

    for room_dir in sorted(warrooms_dir.glob("room-*")):
        if not room_dir.is_dir():
            continue
        total += 1

        status_file = room_dir / "status"
        status = status_file.read_text().strip() if status_file.exists() else "pending"

        tr_file = room_dir / "task-ref"
        task_ref = tr_file.read_text().strip() if tr_file.exists() else "?"

        if status == "passed":
            passed += 1
        elif status == "failed-final":
            failed += 1
        elif status == "blocked":
            blocked += 1
        elif status == "pending":
            pending += 1
        else:
            active += 1

        rooms.append({"room_id": room_dir.name, "task_ref": task_ref, "status": status})

    pct_complete = round((passed / total) * 100, 1) if total > 0 else 0

    # Critical path progress from DAG.json
    critical_path_str = ""
    dag_file = warrooms_dir / "DAG.json"
    if dag_file.exists():
        try:
            dag = json.loads(dag_file.read_text())
            cp = dag.get("critical_path", [])
            if cp:
                cp_passed = 0
                for cp_ref in cp:
                    cp_node = dag.get("nodes", {}).get(cp_ref, {})
                    cp_room_id = cp_node.get("room_id")
                    if cp_room_id:
                        cp_status_file = warrooms_dir / cp_room_id / "status"
                        if cp_status_file.exists() and cp_status_file.read_text().strip() == "passed":
                            cp_passed += 1
                critical_path_str = f"{cp_passed}/{len(cp)}"
        except (json.JSONDecodeError, OSError):
            pass

    progress_data = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": total,
        "passed": passed,
        "failed": failed,
        "blocked": blocked,
        "active": active,
        "pending": pending,
        "pct_complete": pct_complete,
        "critical_path": critical_path_str,
        "rooms": rooms,
    }

    prog_file = warrooms_dir / "progress.json"
    prog_file.write_text(json.dumps(progress_data, indent=2) + "\n")


@router.get("/api/plans/{plan_id}/dag")
async def get_plan_dag(plan_id: str, user: dict = Depends(get_current_user)):
    """Return the DAG.json for a plan, read from its warrooms_dir.

    The DAG.json is produced by the OS-Twin planner and contains the full
    directed-acyclic-graph of war-room / EPIC dependencies including nodes,
    critical_path, waves, topological_order, and metadata like max_depth.
    """
    warrooms_dir = resolve_runtime_plan_warrooms_dir(plan_id)
    dag_file = warrooms_dir / "DAG.json" if warrooms_dir else None

    if dag_file and dag_file.exists():
        try:
            return json.loads(dag_file.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read DAG.json: {exc}")

    # Fallback: build a temp DAG from the markdown
    from dashboard.zvec_store import OSTwinStore
    from dashboard.api_utils import generate_fallback_dag
    plan_file = _find_plan_file(plan_id)
    if not plan_file or not plan_file.exists():
        return {
            "nodes": {}, "edges": [], "critical_path": [],
            "waves": {}, "topological_order": [], "max_depth": 0,
            "total_nodes": 0, "generated_at": datetime.now(timezone.utc).isoformat(),
            "critical_path_length": 0,
            "error": "DAG.json not found and Plan markdown not found"
        }

    content = plan_file.read_text()
    epics = OSTwinStore._parse_plan_epics(content, plan_id)
    return generate_fallback_dag(epics)


@router.get("/api/plans/{plan_id}/epics/{task_ref}")
async def get_plan_epic(
    plan_id: str,
    task_ref: str,
    include_metadata: bool = Query(False),
    include_messages: bool = Query(False),
    user: dict = Depends(get_current_user)
):
    """Get full details for a specific EPIC within a plan."""
    from dashboard.api_utils import read_room
    warrooms_dir = resolve_runtime_plan_warrooms_dir(plan_id)
    if not warrooms_dir or not warrooms_dir.exists():
        raise HTTPException(status_code=404, detail=f"No war-rooms for plan {plan_id}")

    for room_dir in warrooms_dir.glob("room-*"):
        if not room_dir.is_dir():
            continue
        tr_file = room_dir / "task-ref"
        current_ref = tr_file.read_text().strip() if tr_file.exists() else None

        # Fallback to config.json if task-ref file missing
        if not current_ref:
            room_config_file = room_dir / "config.json"
            if room_config_file.exists():
                try:
                    rc = json.loads(room_config_file.read_text())
                    current_ref = rc.get("task_ref")
                except json.JSONDecodeError:
                    pass

        if current_ref == task_ref:
            room_data = read_room(room_dir, include_metadata=include_metadata, include_messages=include_messages)

            # Enrich with plan title
            plan_file = PLANS_DIR / f"{plan_id}.md"
            if plan_file.exists():
                content = plan_file.read_text()
                title_match = re.search(r"^# (?:Plan|PLAN):\s*(.+)", content, re.MULTILINE)
                if title_match:
                    room_data["plan_title"] = title_match.group(1).strip()

            # Enrich with DAG info (dependents)
            dag_file = warrooms_dir / "DAG.json"
            if dag_file.exists():
                try:
                    dag = json.loads(dag_file.read_text())
                    node_info = dag.get("nodes", {}).get(task_ref, {})
                    if "dependents" in node_info:
                        # Add to config so frontend can find it easily
                        if "config" not in room_data:
                            room_data["config"] = {}
                        room_data["config"]["dependents"] = node_info["dependents"]
                        # Also add to top level
                        room_data["dependents"] = node_info["dependents"]
                except (json.JSONDecodeError, OSError):
                    pass

            return room_data

    raise HTTPException(status_code=404, detail=f"EPIC {task_ref} not found in plan {plan_id}")

@router.get("/api/plans/{plan_id}/rooms/{room_id}/roles")
async def get_plan_room_roles(plan_id: str, room_id: str, user: dict = Depends(get_current_user)):
    warrooms_dir = resolve_runtime_plan_warrooms_dir(plan_id)
    if not warrooms_dir:
        raise HTTPException(status_code=404, detail="Room not found")
    room_dir = warrooms_dir / room_id
    if not room_dir.exists(): raise HTTPException(status_code=404, detail="Room not found")
    role_instances = []
    for f in sorted(room_dir.glob("*_*.json")):
        if f.name == "config.json": continue
        try:
            data = json.loads(f.read_text())
            if "role" in data and "instance_id" in data:
                data["filename"] = f.name
                role_instances.append(data)
        except (json.JSONDecodeError, KeyError): continue
    return {"plan_id": plan_id, "room_id": room_id, "roles": role_instances, "count": len(role_instances)}

@router.get("/api/plans/{plan_id}/rooms/{room_id}/channel")
async def get_plan_room_channel(plan_id: str, room_id: str, user: dict = Depends(get_current_user)):
    """Get channel messages for a plan-scoped war-room."""
    from dashboard.api_utils import read_channel
    warrooms_dir = resolve_runtime_plan_warrooms_dir(plan_id)
    if not warrooms_dir:
        raise HTTPException(status_code=404, detail=f"Room {room_id} not found in plan {plan_id}")
    room_dir = warrooms_dir / room_id
    if not room_dir.exists():
        raise HTTPException(status_code=404, detail=f"Room {room_id} not found in plan {plan_id}")
    return {"messages": read_channel(room_dir), "plan_id": plan_id, "room_id": room_id}

@router.get("/api/plans/{plan_id}/rooms/{room_id}/state")
async def get_plan_room_state(plan_id: str, room_id: str, user: dict = Depends(get_current_user)):
    """Get full room state with metadata for a plan-scoped war-room."""
    from dashboard.api_utils import read_room
    warrooms_dir = resolve_runtime_plan_warrooms_dir(plan_id)
    if not warrooms_dir:
        raise HTTPException(status_code=404, detail=f"Room {room_id} not found in plan {plan_id}")
    room_dir = warrooms_dir / room_id
    if not room_dir.exists():
        raise HTTPException(status_code=404, detail=f"Room {room_id} not found in plan {plan_id}")
    room_data = read_room(room_dir, include_metadata=True)
    return {"plan_id": plan_id, **room_data}

@router.post("/api/plans/{plan_id}/rooms/{room_id}/action")
async def plan_room_action(
    plan_id: str,
    room_id: str,
    background_tasks: BackgroundTasks,
    action: str = Query(...),
    user: dict = Depends(get_current_user),
):
    """Perform an action on a plan-scoped war-room (stop, pause, resume, start)."""
    warrooms_dir = resolve_runtime_plan_warrooms_dir(plan_id)
    if not warrooms_dir:
        raise HTTPException(status_code=404, detail=f"Room {room_id} not found in plan {plan_id}")
    room_dir = warrooms_dir / room_id
    if not room_dir.exists():
        raise HTTPException(status_code=404, detail=f"Room {room_id} not found in plan {plan_id}")

    status_file = room_dir / "status"
    if action == "stop":
        status_file.write_text("failed-final")
    elif action == "pause":
        status_file.write_text("paused")
    elif action in ("resume", "start"):
        status_file.write_text("pending")
    else:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")

    background_tasks.add_task(
        process_notification, "room_action",
        {"room_id": room_id, "action": action, "plan_id": plan_id},
    )
    return {"status": "ok", "action": action, "room_id": room_id, "plan_id": plan_id}


def _resolve_room_dir(plan_id: str, task_ref: str) -> Optional[Path]:
    """Internal helper to find the room directory for a given task/epic reference."""
    warrooms_dir = resolve_runtime_plan_warrooms_dir(plan_id)
    if not warrooms_dir or not warrooms_dir.exists():
        return None

    for room_dir in warrooms_dir.glob("room-*"):
        if not room_dir.is_dir():
            continue
        # 1. task-ref file
        tr_file = room_dir / "task-ref"
        if tr_file.exists():
            if tr_file.read_text().strip() == task_ref:
                return room_dir
        # 2. config.json
        cfg_file = room_dir / "config.json"
        if cfg_file.exists():
            try:
                if json.loads(cfg_file.read_text()).get("task_ref") == task_ref:
                    return room_dir
            except (json.JSONDecodeError, OSError): pass
    return None

@router.get("/api/plans/{plan_id}/epics/{task_ref}/tasks")
async def get_epic_tasks(plan_id: str, task_ref: str, user: dict = Depends(get_current_user)):
    """Parse TASKS.md from the war-room and return structured task list."""
    room_dir = _resolve_room_dir(plan_id, task_ref)
    if not room_dir:
        return {"tasks": [], "raw": ""}
    tasks_file = room_dir / "TASKS.md"
    if not tasks_file.exists():
        return {"tasks": [], "raw": ""}
    raw = tasks_file.read_text()
    tasks = []
    current_task = None
    for line in raw.splitlines():
        line_stripped = line.strip()
        # Match: - [x] TASK-001 — Description  or  - [ ] TASK-002 — Description
        if line_stripped.startswith("- ["):
            completed = line_stripped.startswith("- [x]") or line_stripped.startswith("- [X]")
            rest = line_stripped[6:].strip()  # after "- [x] " or "- [ ] "
            parts = rest.split(" — ", 1) if " — " in rest else rest.split(" - ", 1)
            task_id = parts[0].strip() if len(parts) > 1 else rest
            description = parts[1].strip() if len(parts) > 1 else ""
            current_task = {"task_id": task_id, "description": description, "completed": completed, "acceptance_criteria": []}
            tasks.append(current_task)
        elif line_stripped.startswith("- AC:") and current_task:
            current_task["acceptance_criteria"].append(line_stripped[5:].strip())
    return {"tasks": tasks, "count": len(tasks), "raw": raw}

@router.get("/api/plans/{plan_id}/epics/{task_ref}/lifecycle")
async def get_epic_lifecycle(plan_id: str, task_ref: str, user: dict = Depends(get_current_user)):
    room_dir = _resolve_room_dir(plan_id, task_ref)
    if not room_dir: return {"states": {}, "transitions": [], "error": "Room not found"}
    lc_file = room_dir / "lifecycle.json"
    if not lc_file.exists(): return {"states": {}, "transitions": [], "error": "lifecycle.json not found"}
    try: return json.loads(lc_file.read_text())
    except (json.JSONDecodeError, OSError): return {"states": {}, "transitions": [], "error": "JSON error"}

@router.get("/api/plans/{plan_id}/epics/{task_ref}/audit")
async def get_epic_audit(plan_id: str, task_ref: str, user: dict = Depends(get_current_user)):
    room_dir = _resolve_room_dir(plan_id, task_ref)
    if not room_dir: return []
    audit_file = room_dir / "audit.log"
    if not audit_file.exists(): return []
    try:
        lines = audit_file.read_text().splitlines()
        # Parse lines like: [2026-03-24T03:46:16Z] Transitioning: state1 -> state2
        results = []
        for line in lines:
            if "Transitioning:" in line:
                m = re.search(r"\[(.*?)\] Transitioning: (.*?) -> (.*)", line)
                if m:
                    results.append({"timestamp": m.group(1), "from_state": m.group(2), "to_state": m.group(3)})
        return results
    except OSError: return []

@router.get("/api/plans/{plan_id}/epics/{task_ref}/brief")
async def get_epic_brief(plan_id: str, task_ref: str, user: dict = Depends(get_current_user)):
    room_dir = _resolve_room_dir(plan_id, task_ref)
    if not room_dir: return {"content": "", "working_dir": "", "created_at": None}
    brief_file = room_dir / "brief.md"
    config_file = room_dir / "config.json"
    content = brief_file.read_text() if brief_file.exists() else "# No brief provided"
    working_dir = ""
    if config_file.exists():
        try:
            cfg = json.loads(config_file.read_text())
            if "working_dir" in cfg and cfg["working_dir"]:
                working_dir = cfg["working_dir"]
        except: pass
    return {"content": content, "working_dir": working_dir, "created_at": None}

@router.get("/api/plans/{plan_id}/epics/{task_ref}/artifacts")
async def get_epic_artifacts(plan_id: str, task_ref: str, user: dict = Depends(get_current_user)):
    room_dir = _resolve_room_dir(plan_id, task_ref)
    if not room_dir: return []
    art_dir = room_dir / "artifacts"
    if not art_dir.exists(): return []
    files = []
    for f in art_dir.iterdir():
        if f.is_file():
            files.append({"name": f.name, "size": f.stat().st_size, "type": f.suffix.lstrip(".")})
    return sorted(files, key=lambda x: x["name"])

@router.get("/api/plans/{plan_id}/epics/{task_ref}/agents")
async def get_epic_agents(plan_id: str, task_ref: str, user: dict = Depends(get_current_user)):
    room_dir = _resolve_room_dir(plan_id, task_ref)
    if not room_dir: return []
    agents = []
    # Any role-named file like architect_001.json
    for f in room_dir.glob("*_*.json"):
        if f.name == "config.json": continue
        try:
            data = json.loads(f.read_text())
            if "role" in data: agents.append(data)
        except: pass
    return agents

@router.get("/api/plans/{plan_id}/epics/{task_ref}/config")
async def get_epic_config(plan_id: str, task_ref: str, user: dict = Depends(get_current_user)):
    room_dir = _resolve_room_dir(plan_id, task_ref)
    if not room_dir: return {"error": "Room not found"}
    cfg_file = room_dir / "config.json"
    if not cfg_file.exists(): return {"error": "config.json missing"}
    try: return json.loads(cfg_file.read_text())
    except: return {"error": "JSON parse error"}

def _parse_roles_from_markdown(text: str) -> list[str]:
    """Extract role names from 'Roles: @a, @b, c' lines in markdown content.

    Supports multiple formats aligned with the canonical PlanParser.psm1:
      - Plain:    Roles: engineer, qa
      - @-prefix: Roles: @engineer, @qa
      - Mixed:    Roles: @engineer, qa, @designer
      - Spaced:   Roles: @engineer @qa @designer
      - Heading:  ### Roles: @engineer, @qa
      - Bold:     **Roles**: @designer
      - Italic:   *Role*: @architect
      - Singular: Role: engineer
      - Suffixed: @engineer:fe, @qa
    """
    roles: list[str] = []
    # Match optional markdown heading prefix (### ), optional bold/italic wrapping
    pattern = r"(?m)^(?:#{1,6}\s+)?(?:\*{1,2})?Roles?(?:\*{1,2})?:\s*(.+)$"
    for m in re.finditer(pattern, text):
        line = m.group(1)
        line = re.sub(r"\(.*$", "", line)  # strip trailing comments
        # Split by comma or whitespace (supports both "a, b" and "@a @b")
        for part in re.split(r"[,\s]+", line):
            name = part.strip().lstrip("@")  # strip @ prefix
            if name and re.match(r"[a-zA-Z0-9]", name) and not re.match(r"^<.*>$", name) and name != "...":
                roles.append(name)
    return list(dict.fromkeys(roles))  # dedupe, preserve order


@router.get("/api/plans/{plan_id}/epics/{task_ref}/roles")
async def get_epic_roles(plan_id: str, task_ref: str, user: dict = Depends(get_current_user)):
    """Get roles list for a specific Epic, including overrides from war-room config.

    Returns markdown_roles (from Roles: directive in brief.md) alongside
    candidate_roles (manually assigned). When candidate_roles is empty the
    frontend should fall back to markdown_roles.
    """
    room_dir = _resolve_room_dir(plan_id, task_ref)
    if not room_dir: raise HTTPException(status_code=404, detail="Epic room not found")

    plan_config = get_plan_roles_config(plan_id)
    room_config_file = room_dir / "config.json"
    room_overrides = {}
    candidate_roles = []
    if room_config_file.exists():
        try:
            rc = json.loads(room_config_file.read_text())
            room_overrides = rc.get("roles", {})
            candidate_roles = rc.get("assignment", {}).get("candidate_roles", [])
        except json.JSONDecodeError: pass

    # Parse Roles: directive from brief.md
    markdown_roles: list[str] = []
    brief_file = room_dir / "brief.md"
    if brief_file.exists():
        try:
            markdown_roles = _parse_roles_from_markdown(brief_file.read_text())
        except Exception:
            pass
    # Fallback: try epic body from store if brief didn't have roles
    if not markdown_roles:
        try:
            store = global_state.store
            if store:
                epics = store.get_epics_for_plan(plan_id)
                epic = next((e for e in epics if e.get("epic_ref") == task_ref), None)
                if epic and epic.get("body"):
                    markdown_roles = _parse_roles_from_markdown(epic["body"])
        except Exception:
            pass

    merged_config = plan_config.copy()
    for role_name, role_overrides in room_overrides.items():
        if role_name not in merged_config:
             merged_config[role_name] = {}
        merged_config[role_name].update(role_overrides)

    roles = build_roles_list(merged_config, include_skills=True)
    return {
        "roles": roles,
        "plan_config": plan_config,
        "room_overrides": room_overrides,
        "candidate_roles": candidate_roles,
        "markdown_roles": markdown_roles,
    }

from pydantic import BaseModel
class UpdateEpicAssignmentRequest(BaseModel):
    candidate_roles: List[str]

@router.put("/api/plans/{plan_id}/epics/{task_ref}/roles/assignment")
async def update_epic_role_assignment(
    plan_id: str,
    task_ref: str,
    request: UpdateEpicAssignmentRequest,
    user: dict = Depends(get_current_user)
):
    """Update role assignment (candidate_roles) for a specific Epic."""
    room_dir = _resolve_room_dir(plan_id, task_ref)
    if not room_dir: raise HTTPException(status_code=404, detail="Epic room not found")

    room_config_file = room_dir / "config.json"
    if not room_config_file.exists():
         raise HTTPException(status_code=404, detail="config.json missing")

    try:
        rc = json.loads(room_config_file.read_text())
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid config.json")

    if "assignment" not in rc: rc["assignment"] = {}
    rc["assignment"]["candidate_roles"] = request.candidate_roles

    room_config_file.write_text(json.dumps(rc, indent=2) + "\n")
    return {"status": "updated", "task_ref": task_ref, "candidate_roles": rc["assignment"]["candidate_roles"]}

@router.put("/api/plans/{plan_id}/epics/{task_ref}/roles/{role_name}/config")
async def update_epic_role_config(
    plan_id: str,
    task_ref: str,
    role_name: str,
    request: UpdatePlanRoleConfigRequest,
    user: dict = Depends(get_current_user)
):
    """Update role configuration for a specific Epic (saved in war-room config.json)."""
    room_dir = _resolve_room_dir(plan_id, task_ref)
    if not room_dir: raise HTTPException(status_code=404, detail="Epic room not found")

    room_config_file = room_dir / "config.json"
    if not room_config_file.exists():
         raise HTTPException(status_code=404, detail="config.json missing")

    try:
        rc = json.loads(room_config_file.read_text())
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid config.json")

    if "roles" not in rc: rc["roles"] = {}
    if role_name not in rc["roles"]: rc["roles"][role_name] = {}

    if request.default_model is not None: rc["roles"][role_name]["default_model"] = request.default_model
    if request.temperature is not None: rc["roles"][role_name]["temperature"] = request.temperature
    if request.timeout_seconds is not None: rc["roles"][role_name]["timeout_seconds"] = request.timeout_seconds
    if request.cli is not None: rc["roles"][role_name]["cli"] = request.cli
    if request.skill_refs is not None: rc["roles"][role_name]["skill_refs"] = request.skill_refs
    if request.disabled_skills is not None: rc["roles"][role_name]["disabled_skills"] = request.disabled_skills

    room_config_file.write_text(json.dumps(rc, indent=2) + "\n")
    return {"status": "updated", "task_ref": task_ref, "role": role_name, "config": rc["roles"][role_name]}

@router.get("/api/plans/{plan_id}/epics/{task_ref}/roles/{role_name}/preview")
async def preview_epic_role_prompt(
    plan_id: str,
    task_ref: str,
    role_name: str,
    user: dict = Depends(get_current_user)
):
    """Generate and return the final system prompt preview for a role in an Epic."""
    from dashboard.epic_manager import EpicSkillsManager
    try:
        prompt = EpicSkillsManager.generate_system_prompt(plan_id, task_ref, role_name)
        return {"role": role_name, "prompt": prompt}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate prompt: {e}")
