"""
API key authentication dependency.

All API routes require the header ``X-API-Key: <key>`` when
``API_KEYS`` is set in the environment.  Auth is disabled when
``API_KEYS`` is empty (default in development).

WebSocket clients that cannot set headers may pass the key as the
``api_key`` query parameter instead.
"""
from __future__ import annotations

from fastapi import HTTPException, Query, Security, WebSocket, status
from fastapi.security import APIKeyHeader

from app.config import settings

_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


def _valid_keys() -> frozenset[str]:
    return frozenset(k.strip() for k in settings.api_keys.split(",") if k.strip())


async def verify_api_key(
    key_from_header: str | None = Security(_header_scheme),
) -> None:
    """FastAPI dependency — raises 401 if key is invalid.

    Auth is a no-op when ``API_KEYS`` env var is empty.
    """
    keys = _valid_keys()
    if not keys:
        return  # auth disabled

    if not key_from_header or key_from_header not in keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "X-API-Key"},
        )


async def verify_ws_api_key(
    websocket: WebSocket,
    api_key: str | None = Query(None, description="API key (use when header is unavailable)"),
) -> None:
    """WebSocket variant — checks query param then falls back to header."""
    keys = _valid_keys()
    if not keys:
        return  # auth disabled

    # Check query param first, then header
    candidate = api_key or websocket.headers.get("x-api-key")
    if not candidate or candidate not in keys:
        await websocket.close(code=4401, reason="Invalid or missing API key")
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
