import json
import asyncio
import logging
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dashboard.auth import get_current_user
import dashboard.global_state as global_state

from dashboard.api_utils import PLANS_DIR
from dashboard.routes.plans import create_plan_on_disk
from dashboard.asset_store import persist_images_from_message, list_thread_assets

router = APIRouter(tags=["threads"])
logger = logging.getLogger(__name__)
# Logging for threads route

class ImageData(BaseModel):
    url: str
    name: str = ""
    type: str = "image/jpeg"

class ThreadMessageRequest(BaseModel):
    message: str
    images: Optional[List[ImageData]] = None
    # Template metadata (sent when user submits from the template picker)
    template_id: Optional[str] = None
    template_name: Optional[str] = None
    template_fields: Optional[Dict[str, Any]] = None
    # Explicit title (template name + user context)
    title: Optional[str] = None

class PromoteRequest(BaseModel):
    title: Optional[str] = None
    working_dir: Optional[str] = None

@router.post("/api/plans/threads", status_code=201)
async def create_thread(request: ThreadMessageRequest, user: dict = Depends(get_current_user)):
    if not request.message.strip():
        raise HTTPException(status_code=422, detail="Message cannot be empty")
    
    from dashboard.plan_agent import plan_logger as tlog
    
    store = global_state.planning_store
    if not store:
        raise HTTPException(status_code=500, detail="Planning store not initialized")

    tlog.info("=" * 80)
    tlog.info("POST /api/plans/threads — CREATE_THREAD")
    tlog.info("  title: %s", request.title or "(none → 'New Idea')")
    tlog.info("  template_name: %s", request.template_name or "(none)")
    tlog.info("  message length: %d chars", len(request.message))
    tlog.debug("  message preview: %s", request.message[:300].replace('\n', '\\n'))

    # Store template metadata in the thread for downstream agent context
    template_meta = None
    if request.template_id:
        template_meta = {
            "template_id": request.template_id,
            "template_name": request.template_name,
            "template_fields": request.template_fields,
        }

    initial_title = request.title or "New Idea"
    thread = store.create(title=initial_title, template_meta=template_meta)
    images_data = [img.model_dump() for img in request.images] if request.images else None

    # Persist images to $PROJECT_DIR/assets/threads/<thread_id>/
    if images_data:
        images_data = persist_images_from_message(images_data, thread_id=thread.id)
        tlog.info("  Persisted %d images to assets/threads/%s/", len(images_data), thread.id)

    await store.append_message(thread.id, "user", request.message, images=images_data)

    tlog.info("  → thread_id: %s, title: %s", thread.id, thread.title)
    return {"thread_id": thread.id, "title": thread.title}

@router.get("/api/plans/threads")
async def list_threads(limit: int = Query(20), offset: int = Query(0), user: dict = Depends(get_current_user)):
    store = global_state.planning_store
    if not store:
        raise HTTPException(status_code=500, detail="Planning store not initialized")
        
    threads = store.list_threads(limit=limit, offset=offset)
    total = len(store._read_index())
    return {"threads": threads, "total": total}

@router.get("/api/plans/threads/{thread_id}")
async def get_thread(thread_id: str, user: dict = Depends(get_current_user)):
    store = global_state.planning_store
    if not store:
        raise HTTPException(status_code=500, detail="Planning store not initialized")
        
    thread = store.get(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
        
    messages = store.get_messages(thread_id)
    return {"thread": thread, "messages": messages}

async def auto_generate_title(thread_id: str, first_message: str):
    """Reuse the title OpenCode already generates for the thread's session.

    OpenCode auto-titles every session from its own conversation content, so
    we just read it back instead of spending a second LLM round-trip on a
    title-only prompt.  The dashboard maps each planning thread to one
    OpenCode session under conversation_id ``thread-{thread_id}``; we poll
    that session until the placeholder ``"New session - …"`` title is
    replaced with the real one.
    """
    try:
        from dashboard.master_agent import _session_registry, get_opencode_client

        session_id = _session_registry.get(f"thread-{thread_id}")
        if not session_id:
            logger.warning("Auto-title skipped: no opencode session for thread %s", thread_id)
            return

        client = get_opencode_client()
        title: str | None = None
        for _ in range(15):
            session = await client.get(f"/session/{session_id}", cast_to=object)
            candidate = (session.get("title") if isinstance(session, dict) else getattr(session, "title", "")) or ""
            candidate = candidate.strip()
            if candidate and not candidate.startswith("New session"):
                title = candidate
                break
            await asyncio.sleep(2)

        if not title:
            logger.warning("Auto-title skipped: opencode session %s not titled yet", session_id)
            return

        title = title.strip('"').strip("'")
        store = global_state.planning_store
        if store:
            store.update_title(thread_id, title)
    except Exception as e:
        logger.error("Auto-title generation failed: %s", e)

@router.post("/api/plans/threads/{thread_id}/messages/stream")
async def stream_thread_message(thread_id: str, request: ThreadMessageRequest, user: dict = Depends(get_current_user)):
    from dashboard.plan_agent import plan_logger as tlog
    if not request.message.strip():
        raise HTTPException(status_code=422, detail="Message cannot be empty")

    tlog.info("=" * 80)
    tlog.info("POST /api/plans/threads/%s/messages/stream — STREAM_MESSAGE", thread_id)
    tlog.info("  message length: %d chars", len(request.message))
    tlog.debug("  message preview: %s", request.message[:300].replace('\n', '\\n'))

    # Validate and persist images
    images_data = None
    if request.images:
        if len(request.images) > 10:
            raise HTTPException(status_code=422, detail="Maximum 10 images allowed")
        for img in request.images:
            if not img.url.startswith("data:image/"):
                raise HTTPException(status_code=422, detail="Images must be data URIs (data:image/...)")
            if len(img.url) > 2 * 1024 * 1024:
                raise HTTPException(status_code=422, detail=f"Image '{img.name}' exceeds 2MB limit")
        images_data = [img.model_dump() for img in request.images]
        images_data = persist_images_from_message(images_data, thread_id=thread_id)
        tlog.info("  Persisted %d images to assets/threads/%s/", len(images_data), thread_id)

    store = global_state.planning_store
    if not store:
        raise HTTPException(status_code=500, detail="Planning store not initialized")

    thread = store.get(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Only append user message if the last stored message isn't already this exact text
    # (avoids duplicates when auto-triggering reply for the initial message)
    existing = store.get_messages(thread_id)
    last_msg = existing[-1] if existing else None
    is_dedup = last_msg and last_msg.role == "user" and last_msg.content == request.message
    if not is_dedup:
        await store.append_message(thread_id, "user", request.message, images=images_data)
        tlog.debug("  Appended new user message to store")
    else:
        tlog.debug("  Dedup: user message already in store, skipping append")
        if last_msg and not images_data and last_msg.images:
            images_data = last_msg.images

    # Load history (include images for multimodal replay)
    db_messages = store.get_messages(thread_id)
    chat_history = [{"role": m.role, "content": m.content, "images": m.images} for m in db_messages[:-1]]
    tlog.info("  chat_history: %d prior turns, current msg is turn %d", len(chat_history), len(db_messages))
    tlog.info("  → calling brainstorm_stream()")

    from dashboard.plan_agent import brainstorm_stream
    async def event_generator():
        full_response = ""
        try:
            async for token in brainstorm_stream(
                user_message=request.message,
                chat_history=chat_history,
                images=images_data,
                conversation_id=f"thread-{thread_id}",
            ):
                if "[Error:" in token:
                    yield f'data: {{"error": {json.dumps(token)}}}\n\n'
                else:
                    full_response += token
                    yield f'data: {{"token": {json.dumps(token)}}}\n\n'
            
            # Save assistant response
            if full_response:
                await store.append_message(thread_id, "assistant", full_response)
                tlog.info("  Saved assistant response: %d chars", len(full_response))
                
            yield 'data: {"done": true}\n\n'
            
            # Trigger auto-title if needed
            db_messages_after = store.get_messages(thread_id)
            if thread.title == "New Idea" and len(db_messages_after) <= 2:
                first_msg = next((m.content for m in db_messages_after if m.role == "user"), request.message)
                tlog.info("  Triggering auto-title generation")
                asyncio.create_task(auto_generate_title(thread_id, first_msg))
                
        except Exception as e:
            tlog.error("  STREAM ERROR: %s", e)
            logger.error("Streaming error: %s", e)
            yield f'data: {{"error": {json.dumps(str(e))}}}\n\n'
            yield 'data: {"done": true}\n\n'

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/api/plans/threads/{thread_id}/promote")
async def promote_thread(thread_id: str, request: PromoteRequest, user: dict = Depends(get_current_user)):
    from dashboard.plan_agent import plan_logger as tlog
    store = global_state.planning_store
    if not store:
        raise HTTPException(status_code=500, detail="Planning store not initialized")
        
    thread = store.get(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
        
    if thread.status == "promoted":
        raise HTTPException(status_code=400, detail="Thread is already promoted")

    from dashboard.plan_agent import plan_logger as tlog

    tlog.info("=" * 80)
    tlog.info("POST /api/plans/threads/%s/promote — PROMOTE_TO_PLAN", thread_id)
        
    db_messages = store.get_messages(thread_id)
    chat_history = [{"role": m.role, "content": m.content} for m in db_messages]
    tlog.info("  Conversation: %d messages total", len(db_messages))
    for i, m in enumerate(db_messages):
        tlog.debug("  MSG[%d] %s: %s...", i, m.role, m.content[:120].replace('\n', '\\n'))
    
    try:
        # Include asset context so the plan agent knows about uploaded files
        assets = list_thread_assets(thread_id)
        asset_context = ""
        if assets:
            asset_lines = [f"  - {a['path']} ({a['type']}, {a['size']} bytes)" for a in assets]
            asset_context = f"\n\nUploaded assets for this project:\n" + "\n".join(asset_lines)
            tlog.info("  Assets found: %d files", len(assets))

        user_msg = f"Based on this brainstorming conversation, create a structured plan.{asset_context}"
        from dashboard.plan_agent import refine_plan, plan_logger
        tlog = plan_logger
        tlog.info("  → calling refine_plan() with %d history turns", len(chat_history))
        result = await refine_plan(
            user_message=user_msg, 
            plan_content="", 
            chat_history=chat_history,
            plans_dir=PLANS_DIR,
            conversation_id=f"thread-{thread_id}",
        )
        
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
            
        plan_content = result.get("plan")
        if not plan_content:
            plan_content = result.get("full_response", "Failed to generate plan content.")
            
        title = request.title or thread.title
        result = create_plan_on_disk(
            title=title,
            content=plan_content,
            working_dir=request.working_dir,
            thread_id=thread_id
        )
        plan_id = result["plan_id"]
        store.set_promoted(thread_id, plan_id)
        return result
    except Exception as e:
        logger.error("Promote failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
