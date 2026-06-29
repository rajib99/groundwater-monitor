import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import engine
from app.routers import dashboard_router, ingest_router, ml_router, sites_router, ws_router

logger = logging.getLogger(__name__)

_API = "/api"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Groundwater Monitor API starting")
    yield
    await engine.dispose()
    logger.info("Groundwater Monitor API stopped")


app = FastAPI(
    title="Groundwater Monitor API",
    version="2.0.0",
    description=(
        "Real-time groundwater monitoring for UAE construction sites.\n\n"
        "**WebSocket** live feed: `ws://<host>/ws/live-feed?site_id=<id>`"
    ),
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.backend_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global error handler ──────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(sites_router,     prefix=_API)   # /api/sites/...
app.include_router(ingest_router,    prefix=_API)   # /api/ingest
app.include_router(dashboard_router, prefix=_API)   # /api/dashboard/...
app.include_router(ml_router,        prefix=_API)   # /api/ml/...
app.include_router(ws_router)                       # /ws/live-feed  (no /api prefix)

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["health"], summary="Liveness probe")
async def health() -> dict:
    return {"status": "ok", "version": "2.0.0"}
