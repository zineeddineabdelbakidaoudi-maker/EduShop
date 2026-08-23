from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Dict, List
import json

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.admin_connections: List[WebSocket] = []
        self.seller_connections: Dict[int, List[WebSocket]] = {}

    async def connect_admin(self, ws: WebSocket):
        await ws.accept()
        self.admin_connections.append(ws)

    async def connect_seller(self, ws: WebSocket, seller_id: int):
        await ws.accept()
        self.seller_connections.setdefault(seller_id, []).append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.admin_connections:
            self.admin_connections.remove(ws)
        for sid, conns in self.seller_connections.items():
            if ws in conns:
                conns.remove(ws)

    async def broadcast_admin(self, event: str, data: dict):
        msg = json.dumps({"event": event, "data": data})
        dead = []
        for ws in self.admin_connections:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.admin_connections.remove(ws)

    async def broadcast_seller(self, seller_id: int, event: str, data: dict):
        msg = json.dumps({"event": event, "data": data})
        conns = self.seller_connections.get(seller_id, [])
        dead = []
        for ws in conns:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            conns.remove(ws)

    async def broadcast_all(self, event: str, data: dict):
        await self.broadcast_admin(event, data)
        for sid in list(self.seller_connections.keys()):
            await self.broadcast_seller(sid, event, data)

manager = ConnectionManager()

@router.websocket("/ws/{user_id}")
async def websocket_endpoint(ws: WebSocket, user_id: int, role: str = Query("seller")):
    if role == "admin":
        await manager.connect_admin(ws)
    else:
        await manager.connect_seller(ws, user_id)
    try:
        while True:
            await ws.receive_text()  # keep alive, we only push from server
    except WebSocketDisconnect:
        manager.disconnect(ws)
