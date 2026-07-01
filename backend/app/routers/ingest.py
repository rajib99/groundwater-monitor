import logging
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, AsyncSessionLocal
from app.models.pump_health_score import PumpHealthScore
from app.models.sensor_reading import SensorReading
from app.models.site import Site
from app.redis_client import get_redis
from app.schemas import ReadingCreate, ReadingResponse
from app.ws import manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ingest"])

_INGEST_LIMIT = 10   # max requests per second per site_id


async def _check_rate_limit(site_id: int) -> None:
    """Fixed-window counter: max 10 POST /ingest per second per site."""
    window = int(time.time())           # 1-second bucket
    key    = f"rl:ingest:{site_id}:{window}"
    try:
        redis = get_redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 2)  # auto-expire; guards against stuck keys
        if count > _INGEST_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded for site {site_id}: "
                    f"max {_INGEST_LIMIT} readings/second"
                ),
                headers={"Retry-After": "1"},
            )
    except HTTPException:
        raise
    except Exception as exc:
        # Redis unavailable — fail-open so ingestion keeps working
        logger.warning("Rate-limit Redis error for site %d: %s", site_id, exc)


async def _compute_and_store_health(site_id: int, site_name: str, reading: SensorReading) -> None:
    """Compute a pump health score from the ML model and persist it. Fail-open."""
    try:
        from app.routers.ml import _load_artifact, _get_site_dict, _score_reading
        artifact  = _load_artifact()
        site_dict = _get_site_dict(artifact, site_id, site_name)
        result    = _score_reading(site_dict, {
            "water_level_m":      reading.water_level_m,
            "flow_rate_lpm":      reading.flow_rate_lpm,
            "pump_pressure_bar":  reading.pump_pressure_bar,
            "turbidity_ntu":      reading.turbidity_ntu,
            "conductivity_us_cm": reading.conductivity_us_cm,
        })
        score = round((1.0 - result["anomaly_score"]) * 100, 2)
        async with AsyncSessionLocal() as session:
            session.add(PumpHealthScore(
                site_id=site_id,
                timestamp=reading.timestamp,
                score=score,
                contributing_factors=result["contributing_features"],
            ))
            await session.commit()
        logger.debug("Health score %.1f stored for site=%d", score, site_id)
    except Exception as exc:
        logger.debug("Health score skipped for site=%d: %s", site_id, exc)


@router.post(
    "/ingest",
    response_model=ReadingResponse,
    status_code=201,
    summary="Ingest a new sensor reading (live feed / simulator)",
)
async def ingest_reading(
    payload: ReadingCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> SensorReading:
    # ── Rate limit (per-site, fail-open when Redis is unavailable) ─────────
    await _check_rate_limit(payload.site_id)

    # ── Validate site exists ───────────────────────────────────────────────
    site = await db.get(Site, payload.site_id)
    if not site:
        raise HTTPException(status_code=404, detail=f"Site {payload.site_id} not found")

    # ── Persist ────────────────────────────────────────────────────────────
    reading = SensorReading(**payload.model_dump())
    db.add(reading)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A reading already exists for this site at the given timestamp",
        )

    await db.refresh(reading)
    logger.debug("Ingested reading  site=%d  ts=%s", site.id, reading.timestamp)

    # ── Broadcast to WebSocket subscribers (non-blocking) ─────────────────
    if manager.connection_count > 0:
        await manager.broadcast(
            {
                "event":     "reading",
                "site_id":   site.id,
                "site_name": site.name,
                "data": {
                    "site_id":            reading.site_id,
                    "timestamp":          reading.timestamp.isoformat(),
                    "water_level_m":      reading.water_level_m,
                    "flow_rate_lpm":      reading.flow_rate_lpm,
                    "pump_pressure_bar":  reading.pump_pressure_bar,
                    "turbidity_ntu":      reading.turbidity_ntu,
                    "conductivity_us_cm": reading.conductivity_us_cm,
                    "temperature_c":      reading.temperature_c,
                },
            },
            site_id=site.id,
        )

    # ── Compute pump health score in background (fail-open) ───────────────
    background_tasks.add_task(_compute_and_store_health, site.id, site.name, reading)

    return reading
