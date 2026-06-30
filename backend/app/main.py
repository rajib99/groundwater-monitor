import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import engine, get_db
from app.dependencies import verify_api_key
from app.redis_client import get_redis
from app.routers import (
    dashboard_router,
    ingest_router,
    ml_router,
    reports_router,
    sites_router,
    ws_router,
)

logger = logging.getLogger(__name__)

_API        = "/api"
_START_TIME = time.monotonic()
_VERSION    = "2.0.0"

_auth = [Depends(verify_api_key)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Groundwater Monitor API v%s starting", _VERSION)
    yield
    await engine.dispose()
    logger.info("Groundwater Monitor API stopped")


app = FastAPI(
    title="Groundwater Monitor API",
    version=_VERSION,
    redirect_slashes=False,
    description=(
        "Real-time groundwater monitoring for UAE construction sites.\n\n"
        "All `/api/*` endpoints require the `X-API-Key` header when "
        "`API_KEYS` is configured.\n\n"
        "**WebSocket** live feed: `ws://<host>/ws/live-feed?site_id=<id>`  \n"
        "WebSocket clients may pass the key as `?api_key=<key>` instead."
    ),
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-API-Key"],
)

# ── Global error handler ──────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ── Routers (auth applied to all /api/* routes) ───────────────────────────────
app.include_router(sites_router,     prefix=_API, dependencies=_auth)
app.include_router(ingest_router,    prefix=_API, dependencies=_auth)
app.include_router(dashboard_router, prefix=_API, dependencies=_auth)
app.include_router(ml_router,        prefix=_API, dependencies=_auth)
app.include_router(reports_router,   prefix=_API, dependencies=_auth)
app.include_router(ws_router)   # auth handled inside the WS handler


# ── Health check (unauthenticated — used by Docker, Nginx, uptime monitors) ──
@app.get(
    "/health",
    tags=["health"],
    summary="Liveness + dependency health probe",
    response_description="200 = healthy, 503 = one or more checks failed",
)
async def health(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    checks: dict[str, str] = {}

    # Database
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.warning("Health check: DB error: %s", exc)
        checks["database"] = "error"

    # Redis
    try:
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:
        logger.warning("Health check: Redis error: %s", exc)
        checks["redis"] = "error"

    healthy    = all(v == "ok" for v in checks.values())
    status_code = 200 if healthy else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status":   "ok" if healthy else "degraded",
            "version":  _VERSION,
            "uptime_s": round(time.monotonic() - _START_TIME, 1),
            "checks":   checks,
        },
    )
