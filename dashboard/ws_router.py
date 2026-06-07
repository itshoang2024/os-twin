import json
import logging
import time
from typing import Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self._last_states: dict[str, Any] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            if conn in self.active_connections:
                self.active_connections.remove(conn)

    async def broadcast_epic_progress(self, plan_id: str, epic_ref: str, status: str, progress: int):
        await self.broadcast({
            "type": "epic_progress",
            "plan_id": plan_id,
            "epic_ref": epic_ref,
            "status": status,
            "progress": progress
        })

    async def broadcast_connection_health(self, service: str, status: str, latency: float = 0.0):
        await self.broadcast({
            "type": "connection_health",
            "service": service,
            "status": status,
            "latency": latency
        })

    @property
    def client_count(self):
        return len(self.active_connections)

manager = ConnectionManager()

async def handle_client_message(websocket: WebSocket, msg: dict):
    msg_type = msg.get("type")
    
    if msg_type == "ping":
        await websocket.send_json({"type": "pong", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    elif msg_type == "orchestration.event.ingest":
        from dashboard import global_state
        from dashboard.orchestration_events import ingest_live_orchestration_event

        event = msg.get("data") or msg.get("event")
        if not isinstance(event, dict):
            logger.warning("Rejected orchestration event ingest without object event data")
            await websocket.send_json({"type": "orchestration.event.ack", "accepted": False, "reason": "missing event data"})
            return
        payload = event.get("payload", {}) if isinstance(event.get("payload", {}), dict) else {}
        logger.info(
            "Received live orchestration event ingest event_type=%s event_id=%s plan_id=%s run_id=%s room_id=%s epic_ref=%s",
            event.get("event_type"),
            event.get("event_id"),
            event.get("plan_id"),
            event.get("run_id"),
            event.get("room_id") or payload.get("room_id"),
            event.get("epic_ref") or payload.get("epic_ref"),
        )
        result = await ingest_live_orchestration_event(
            event,
            global_state.broadcaster,
            store=global_state.store,
        )
        logger.info("Live orchestration event ingest ack event_id=%s result=%s", event.get("event_id"), result)
        await websocket.send_json({"type": "orchestration.event.ack", **result})

def create_ws_router() -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            await websocket.send_json({
                "event": "connected",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            })

            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                    await handle_client_message(websocket, msg)
                except json.JSONDecodeError:
                    pass

        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("WebSocket error")
        finally:
            manager.disconnect(websocket)

    return router
