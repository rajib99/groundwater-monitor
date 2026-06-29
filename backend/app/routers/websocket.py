import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.ws import manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


@router.websocket("/ws/live-feed")
async def live_feed(
    websocket: WebSocket,
    site_id: int | None = Query(
        None,
        description="Subscribe to a single site; omit to receive all sites",
    ),
) -> None:
    """
    Real-time sensor data stream.

    On connect the server sends a `connected` handshake.
    Thereafter every POST /api/ingest triggers a `reading` broadcast to
    subscribed clients.  Clients may send the text `ping` to receive a `pong`.

    Message shape:
      { "event": "connected"|"reading"|"pong",
        "site_id": int|null, "site_name": str|null,
        "data": ReadingResponse|null,
        "server_time": ISO-8601 }
    """
    await manager.connect(websocket, site_id)

    await websocket.send_json(
        {
            "event": "connected",
            "site_id": site_id,
            "message": (
                f"Subscribed to site {site_id}" if site_id else "Subscribed to all sites"
            ),
            "server_time": datetime.now(timezone.utc).isoformat(),
        }
    )

    try:
        while True:
            text = await websocket.receive_text()
            if text.strip().lower() == "ping":
                await websocket.send_json(
                    {
                        "event": "pong",
                        "server_time": datetime.now(timezone.utc).isoformat(),
                    }
                )
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)
