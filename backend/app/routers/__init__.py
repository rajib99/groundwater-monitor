from app.routers.dashboard import router as dashboard_router
from app.routers.ingest import router as ingest_router
from app.routers.ml import router as ml_router
from app.routers.sites import router as sites_router
from app.routers.websocket import router as ws_router

__all__ = ["sites_router", "ingest_router", "dashboard_router", "ws_router", "ml_router"]
