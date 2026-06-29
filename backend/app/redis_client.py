"""
Module-level Redis connection pool shared across all request handlers.

Import ``get_redis()`` wherever a Redis client is needed.  The pool is
lazily created on first use and reused for the lifetime of the process.
"""
from __future__ import annotations

import redis.asyncio as aioredis

from app.config import settings

_pool: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _pool
