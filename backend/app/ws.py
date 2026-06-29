"""
WebSocket connection manager — module-level singleton shared across all routers.

Usage:
    from app.ws import manager
    await manager.broadcast(message_dict, site_id)
"""
import asyncio
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        # Maps each WebSocket to an optional site_id filter.
        # None means the client receives broadcasts from all sites.
        self._connections: dict[WebSocket, int | None] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, site_id: int | None = None) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[websocket] = site_id
        logger.info(
            "WS connected  filter=site_id:%s  total_connections=%d",
            site_id,
            len(self._connections),
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.pop(websocket, None)
        logger.info("WS disconnected  remaining=%d", len(self._connections))

    async def broadcast(self, message: dict, site_id: int) -> None:
        """Send `message` to every client subscribed to `site_id` (or all sites)."""
        if not self._connections:
            return

        payload = json.dumps(message, default=str)

        # Snapshot targets under the lock so we don't hold it during I/O.
        async with self._lock:
            targets = [
                ws
                for ws, filter_id in self._connections.items()
                if filter_id is None or filter_id == site_id
            ]

        failed: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(payload)
            except Exception:
                failed.append(ws)

        for ws in failed:
            await self.disconnect(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# Single instance imported everywhere that needs broadcast access.
manager = ConnectionManager()
