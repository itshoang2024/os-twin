import json
import asyncio
from typing import List
from dashboard.ws_router import manager

class Broadcaster:
    def __init__(self):
        self.sse_clients: List[asyncio.Queue] = []

    async def subscribe_sse(self) -> asyncio.Queue:
        queue = asyncio.Queue()
        self.sse_clients.append(queue)
        return queue

    def unsubscribe_sse(self, queue: asyncio.Queue):
        if queue in self.sse_clients:
            self.sse_clients.remove(queue)

    async def broadcast(self, event_type: str, data: dict):
        event_dict = {**data, "event": event_type}
        json_event = json.dumps(event_dict)
        
        # SSE format
        sse_event = f"data: {json_event}\n\n"
        for queue in list(self.sse_clients):
            await queue.put(sse_event)
            
        # WebSocket format
        await manager.broadcast(event_dict)

    async def broadcast_orchestration_event(self, event: dict):
        """Broadcast the normalized dashboard-to-bot orchestration envelope.

        Legacy dashboard messages still use ``broadcast()`` and keep their
        historical ``{"event": ...}`` shape. Bot consumers should use this
        normalized envelope so they never infer event semantics from mixed
        ``{"event": ..., ...data}`` payloads.
        """
        event_dict = {"type": "orchestration.event", "data": event}
        json_event = json.dumps(event_dict)

        sse_event = f"data: {json_event}\n\n"
        for queue in list(self.sse_clients):
            await queue.put(sse_event)

        await manager.broadcast(event_dict)

broadcaster = Broadcaster()

# These will be initialized by api.py on startup
store = None
planning_store = None
tunnel_url: str | None = None

# Bot process manager — initialized in tasks.py startup_all()
bot_manager = None
