import asyncio
import os
import json
import logging
from pathlib import Path

from dashboard.api_utils import (
    WARROOMS_DIR,
    AGENTS_DIR,
    PLANS_DIR,
    read_room,
    read_channel,
    process_notification,
)
import dashboard.global_state as global_state
from dashboard.epic_manager import EpicSkillsManager
# Heavy imports moved to background thread to prevent startup blocking

# Telegram command handling is now in the Node.js bot (bot/src/telegram.ts).
# Outbound notifications use notify.py (formerly telegram_bot.py).

logger = logging.getLogger(__name__)


async def poll_war_rooms():
    """Background task to poll war-room state and broadcast changes."""
    last_snapshot: dict[str, dict] = {}

    _cached_warroom_dirs: list[Path] = []
    _cached_warroom_dirs_time: float = 0
    _WARROOM_CACHE_TTL = 10  # seconds

    def _discover_warroom_dirs() -> list[Path]:
        """Discover all war-room directories: global + plan-specific.

        Results are cached for 10 seconds to avoid re-globbing and re-reading
        .meta.json files on every 1-second poll cycle, which can exhaust the
        OS file-descriptor limit (macOS default is often only 256).
        """
        nonlocal _cached_warroom_dirs, _cached_warroom_dirs_time
        import time

        now = time.monotonic()
        if (
            _cached_warroom_dirs
            and (now - _cached_warroom_dirs_time) < _WARROOM_CACHE_TTL
        ):
            return _cached_warroom_dirs

        dirs = set()
        if WARROOMS_DIR.exists():
            dirs.add(WARROOMS_DIR)
        # Scan plans meta for plan-specific war-room dirs
        plans_dir = PLANS_DIR
        if plans_dir.exists():
            for meta_file in plans_dir.glob("*.meta.json"):
                try:
                    meta = json.loads(meta_file.read_text())
                    wd = meta.get("working_dir") or meta.get("warrooms_dir")
                    if wd:
                        warrooms_path = Path(wd)
                        if warrooms_path.name != ".war-rooms":
                            warrooms_path = warrooms_path / ".war-rooms"
                        if warrooms_path.exists():
                            dirs.add(warrooms_path)
                except (json.JSONDecodeError, KeyError):
                    pass

        _cached_warroom_dirs = list(dirs)
        _cached_warroom_dirs_time = now
        return _cached_warroom_dirs

    def _find_plan_id_for_warroom_dir(warroom_dir: Path) -> str | None:
        """Find the plan_id whose warrooms_dir matches."""
        if not PLANS_DIR.exists():
            return None
        resolved = warroom_dir.resolve()
        for meta_file in PLANS_DIR.glob("*.meta.json"):
            try:
                meta = json.loads(meta_file.read_text())
                wd = meta.get("warrooms_dir") or meta.get("working_dir")
                if wd:
                    wd_path = Path(wd)
                    if wd_path.name != ".war-rooms":
                        wd_path = wd_path / ".war-rooms"
                    if wd_path.resolve() == resolved:
                        return meta.get("plan_id", meta_file.stem.replace(".meta", ""))
            except (json.JSONDecodeError, KeyError):
                continue
        return None

    # Initialize snapshot
    for warroom_dir in _discover_warroom_dirs():
        for room_dir in sorted(warroom_dir.glob("room-*")):
            if room_dir.is_dir():
                room = read_room(room_dir)
                last_snapshot[room["room_id"]] = room

    # Release file
    release_file = AGENTS_DIR / "RELEASE.md"
    if release_file.exists():
        last_snapshot["__release__"] = {"mtime": release_file.stat().st_mtime}

    # Plans
    plans_dir = PLANS_DIR
    if plans_dir.exists():
        for plan_file in plans_dir.glob("*.md"):
            last_snapshot[f"__plan_{plan_file.name}__"] = {
                "mtime": plan_file.stat().st_mtime
            }

    while True:
        try:
            current: dict[str, dict] = {}
            for warroom_dir in _discover_warroom_dirs():
                for room_dir in sorted(warroom_dir.glob("room-*")):
                    if room_dir.is_dir():
                        room = read_room(room_dir)
                        current[room["room_id"]] = room

            # Detect changes: new rooms, status changes, new messages
            for room_id, room in current.items():
                prev = last_snapshot.get(room_id)
                if prev is None:
                    # New room
                    await global_state.broadcaster.broadcast(
                        "room_created", {"room": room}
                    )
                    await process_notification("room_created", {"room": room})
                    if global_state.store:
                        global_state.store.upsert_room_metadata(room_id, room)

                    room_parent = None
                    for wd in _discover_warroom_dirs():
                        if (wd / room_id).is_dir():
                            room_parent = wd
                            break

                    if room_parent:
                        plan_id = _find_plan_id_for_warroom_dir(room_parent)
                        if plan_id:
                            try:
                                EpicSkillsManager.sync_room_skills(
                                    room_parent / room_id, plan_id
                                )
                            except Exception as e:
                                logger.warning(
                                    "Failed to sync skills for room %s: %s", room_id, e
                                )
                            # EPIC-004: Inject assets into war room
                            epic_ref = room.get("task_ref", "")
                            if epic_ref:
                                try:
                                    EpicSkillsManager.inject_room_assets(
                                        room_parent / room_id, plan_id, epic_ref
                                    )
                                except Exception as e:
                                    logger.warning(
                                        "Failed to inject assets for room %s: %s",
                                        room_id,
                                        e,
                                    )

                    if room_parent and room["message_count"] > 0:
                        messages = read_channel(room_parent / room_id)
                        event_data = {"room": room, "new_messages": messages}
                        await global_state.broadcaster.broadcast(
                            "room_updated", event_data
                        )
                        await process_notification("room_updated", event_data)
                        if global_state.store:
                            global_state.store.index_messages_batch(room_id, messages)
                elif (
                    prev["status"] != room["status"]
                    or prev["message_count"] != room["message_count"]
                ):
                    # Changed room — find correct dir and include latest channel messages
                    room_parent = None
                    for wd in _discover_warroom_dirs():
                        if (wd / room_id).is_dir():
                            room_parent = wd
                            break
                    if room_parent:
                        messages = read_channel(room_parent / room_id)
                    else:
                        messages = read_channel(WARROOMS_DIR / room_id)
                    new_messages = messages[prev["message_count"] :]
                    event_data = {"room": room, "new_messages": new_messages}
                    await global_state.broadcaster.broadcast("room_updated", event_data)
                    await process_notification("room_updated", event_data)

                    # Index new messages and update metadata in zvec
                    if global_state.store:
                        global_state.store.index_messages_batch(room_id, new_messages)
                        global_state.store.upsert_room_metadata(room_id, room)
                        # Sync epic status if room status changed
                        if prev["status"] != room["status"]:
                            epic_ref = room.get("task_ref", "")
                            if epic_ref:
                                # Find plan_id from plans dir (latest launched)
                                try:
                                    p_dir = PLANS_DIR
                                    if p_dir.exists():
                                        latest = max(
                                            p_dir.glob("agent-os-plan-*.md"),
                                            key=lambda p: p.stat().st_mtime,
                                            default=None,
                                        )
                                        if latest:
                                            global_state.store.update_epic_status(
                                                latest.stem, epic_ref, room["status"]
                                            )
                                except Exception:
                                    pass

            # Detect removed rooms
            for room_id in last_snapshot:
                if (
                    room_id != "__release__"
                    and not room_id.startswith("__plan_")
                    and room_id not in current
                ):
                    await global_state.broadcaster.broadcast(
                        "room_removed", {"room_id": room_id}
                    )

            # Check release
            if release_file.exists():
                curr_mtime = release_file.stat().st_mtime
                if curr_mtime != last_snapshot.get("__release__", {}).get("mtime", 0):
                    await global_state.broadcaster.broadcast(
                        "release", {"content": release_file.read_text()}
                    )
                    current["__release__"] = {"mtime": curr_mtime}

            # Check plans
            plans_changed = False
            if plans_dir.exists():
                for plan_file in plans_dir.glob("*.md"):
                    if plan_file.stem == "PLAN.template":
                        continue
                    plan_key = f"__plan_{plan_file.name}__"
                    curr_mtime = plan_file.stat().st_mtime
                    if curr_mtime != last_snapshot.get(plan_key, {}).get("mtime", 0):
                        plans_changed = True
                    current[plan_key] = {"mtime": curr_mtime}

            # Check for deleted plans
            for key in last_snapshot:
                if key.startswith("__plan_") and key not in current:
                    plans_changed = True

            if plans_changed:
                await global_state.broadcaster.broadcast("plans_updated", {})

            last_snapshot = current
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - intentional catch-all for polling resilience
            logger.error("poll_war_rooms error: %s", e, exc_info=True)
            await asyncio.sleep(2)


async def startup_all():
    """Initialize state."""
    asyncio.create_task(poll_war_rooms())

    # ── Push Deployment Notification to Lark ──────────────────────────
    # Only trigger at runtime on Cloud Run (excludes Docker build phase)
    if os.environ.get("K_SERVICE"):
        async def _notify_lark_delayed():
            try:
                # Small delay to ensure networking is fully up and stable
                await asyncio.sleep(5)
                
                from dashboard.notify import send_lark_message
                env_path = Path.home() / ".ostwin" / ".env"
                if env_path.exists():
                    from dotenv import load_dotenv
                    load_dotenv(env_path)

                api_key = os.environ.get("OSTWIN_API_KEY")
                if api_key:
                    app_url = os.environ.get("BASE_URL")
                    msg_lines = [
                        f"🔑 **OSTWIN_API_KEY**: {api_key}",
                        f"📦 **Revision**: {os.environ.get('K_REVISION', 'unknown')}",
                    ]
                    if app_url:
                        msg_lines.append(f"🌐 **Dashboard**: {app_url}")
                    else:
                        msg_lines.append("🌐 **Service**: Cloud Run (URL not set)")

                    msg = "\n".join(msg_lines)
                    await send_lark_message(msg, title="🚀 OS-Twin Deployed Successfully")
            except Exception as e:
                logger.error(f"Lark notification background task failed: {e}")

        asyncio.create_task(_notify_lark_delayed())



    # ── Hot-reload ~/.ostwin/.env on file changes ─────────────────────

    try:
        from dashboard.env_watcher import watch_env_file

        asyncio.create_task(watch_env_file())
    except Exception as e:
        logger.error("env_watcher failed to start: %s", e)

    # Models catalog and heavy syncs move to the background thread

    # Telegram polling removed — handled by the Node.js bot (bot/src/telegram.ts)
    # Planning thread store (initialized early/sync to avoid race conditions with first requests)
    try:
        from dashboard.planning_thread_store import PlanningThreadStore

        global_state.planning_store = PlanningThreadStore()
        logger.info("Planning thread store initialized (Sync)")
    except Exception as e:
        logger.error(f"Planning store init failed: {e}")

    try:
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        # Initialize store in the background thread to prevent slow imports
        # from blocking the main loop.

        # Force re-index if requested via CLI flag
        if os.environ.get("OSTWIN_REINDEX") == "true":
            logger.info("Forcing full re-index as requested")
            import shutil

            if global_state.store.zvec_dir.exists():
                shutil.rmtree(global_state.store.zvec_dir)
                global_state.store.zvec_dir.mkdir(parents=True, exist_ok=True)

        global_state.store.ensure_collections()

        def _background_sync():
            from dashboard.routes import skills as skills_routes

            skills_routes._sync_in_progress = True
            try:
                # ── Grace Period ──
                # Give the browser 5 seconds to load HTML/JS/CSS before we
                # start hogging the CPU with Torch and YAML parsing.
                import time

                time.sleep(5)

                # Lazy import of heavy vector store
                from dashboard.zvec_store import OSTwinStore

                global_state.store = OSTwinStore(WARROOMS_DIR, agents_dir=AGENTS_DIR)

                # ── Load model catalog from models.dev ────────────────────────────
                try:
                    from dashboard.lib.settings.models_dev_loader import (
                        load_models_on_startup,
                    )

                    load_models_on_startup()
                except Exception as e:
                    logger.error("Models catalog load failed: %s", e)

                # ── Generate OpenCode custom tools ──────────────────────────
                try:
                    from dashboard.opencode_tools import generate_all

                    port = os.environ.get("DASHBOARD_PORT", "3366")
                    generate_all(dashboard_port=port)
                    logger.info("OpenCode custom tools generated (port=%s)", port)
                except Exception as e:
                    logger.warning("OpenCode tool generation failed: %s", e)
                
                # Initialization (slow — loads 600MB model)
                global_state.store.ensure_collections()

                # Syncing
                global_state.store.sync_from_disk()
                from dashboard.api_utils import SKILLS_DIRS

                global_state.store.sync_skills(SKILLS_DIRS)
                logger.info("Skills synced from disk")
                global_state.store.sync_roles(AGENTS_DIR / "roles")
                logger.info("Roles synced from disk")
                from dashboard.routes.roles import sync_roles_from_disk

                result = sync_roles_from_disk()
                if result["synced"]:
                    logger.info(
                        "Roles bridged from disk role.json: %s", result["synced"]
                    )
                logger.info("Background zvec sync complete")
            except Exception as e:
                logger.error("Background zvec sync failed: %s", e)
            finally:
                skills_routes._sync_in_progress = False

        import threading

        sync_thread = threading.Thread(
            target=_background_sync, daemon=True, name="zvec-sync"
        )
        sync_thread.start()
        logger.info("zvec sync started in background thread")
    except Exception as e:
        logger.error(f"zvec init failed: {e}")
        global_state.store = None

    # Initialize bot manager but don't auto-start — use POST /api/bot/start instead
    try:
        from dashboard.bot_manager import BotProcessManager, BOT_DIR

        if BOT_DIR.exists():
            global_state.bot_manager = BotProcessManager()
            logger.info("Bot manager initialized — start via POST /api/bot/start")
        else:
            logger.info("Bot directory not found — bot manager disabled")
    except Exception as e:
        logger.error("Bot manager init failed: %s", e)

    # Auto-start ngrok tunnel if NGROK_AUTHTOKEN is set
    auth_token = os.environ.get("NGROK_AUTHTOKEN")
    if auth_token:
        try:
            from dashboard.tunnel import start_tunnel

            port = int(os.environ.get("DASHBOARD_PORT", "3366"))
            domain = os.environ.get("NGROK_DOMAIN")
            url = await start_tunnel(port, auth_token, domain)
            global_state.tunnel_url = url
            logger.info("ngrok tunnel active: %s", url)
            # Notify Telegram chats
            try:
                from dashboard.notify import send_message

                await send_message(f"📡 Dashboard is live at: {url}")
            except Exception:
                pass
        except Exception as e:
            logger.error("ngrok tunnel failed: %s", e)
