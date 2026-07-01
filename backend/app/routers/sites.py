import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.alert import Alert
from app.models.pump_health_score import PumpHealthScore
from app.models.sensor_reading import SensorReading
from app.models.site import Site
from app.schemas import (
    AISummaryResponse,
    AlertResponse,
    ForecastResponse,
    HealthResponse,
    PaginatedReadings,
    ReadingResponse,
    SiteResponse,
)

from app.services.ai_summary import _SUMMARY_TTL_SECONDS, _get_cached, get_ai_summary

router = APIRouter(prefix="/sites", tags=["sites"])


async def _get_site_or_404(site_id: int, db: AsyncSession) -> Site:
    site = await db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail=f"Site {site_id} not found")
    return site


@router.get(
    "",
    response_model=list[SiteResponse],
    summary="List all monitoring sites",
)
async def list_sites(db: AsyncSession = Depends(get_db)) -> list[Site]:
    result = await db.execute(select(Site).order_by(Site.id))
    return result.scalars().all()


@router.get(
    "/{site_id}/readings",
    response_model=PaginatedReadings,
    summary="Paginated sensor readings with optional date-range filter",
)
async def get_readings(
    site_id: int,
    start: datetime | None = Query(None, description="ISO 8601 range start (inclusive)"),
    end: datetime | None = Query(None, description="ISO 8601 range end (inclusive)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> PaginatedReadings:
    await _get_site_or_404(site_id, db)

    filters = [SensorReading.site_id == site_id]
    if start:
        filters.append(SensorReading.timestamp >= start)
    if end:
        filters.append(SensorReading.timestamp <= end)

    total: int = (
        await db.execute(
            select(func.count()).select_from(SensorReading).where(*filters)
        )
    ).scalar_one()

    offset = (page - 1) * page_size
    rows = (
        await db.execute(
            select(SensorReading)
            .where(*filters)
            .order_by(desc(SensorReading.timestamp))
            .limit(page_size)
            .offset(offset)
        )
    ).scalars().all()

    return PaginatedReadings(
        data=rows,
        total=total,
        page=page,
        page_size=page_size,
        has_next=(offset + len(rows)) < total,
    )


@router.get(
    "/{site_id}/latest",
    response_model=ReadingResponse,
    summary="Most recent sensor reading for a site",
)
async def get_latest_reading(
    site_id: int,
    db: AsyncSession = Depends(get_db),
) -> SensorReading:
    await _get_site_or_404(site_id, db)
    row = (
        await db.execute(
            select(SensorReading)
            .where(SensorReading.site_id == site_id)
            .order_by(desc(SensorReading.timestamp))
            .limit(1)
        )
    ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="No readings available for this site")
    return row


@router.get(
    "/{site_id}/alerts",
    response_model=list[AlertResponse],
    summary="Alert history for a site",
)
async def get_alerts(
    site_id: int,
    resolved: bool | None = Query(
        None,
        description="true = resolved only, false = unresolved only, omit = all",
    ),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[Alert]:
    await _get_site_or_404(site_id, db)

    stmt = (
        select(Alert)
        .where(Alert.site_id == site_id)
        .order_by(desc(Alert.triggered_at))
        .limit(limit)
    )
    if resolved is True:
        stmt = stmt.where(Alert.resolved_at.is_not(None))
    elif resolved is False:
        stmt = stmt.where(Alert.resolved_at.is_(None))

    return (await db.execute(stmt)).scalars().all()


@router.get(
    "/{site_id}/health",
    response_model=HealthResponse,
    summary="Latest pump health score for a site",
)
async def get_health_score(
    site_id: int,
    db: AsyncSession = Depends(get_db),
) -> PumpHealthScore:
    await _get_site_or_404(site_id, db)
    row = (
        await db.execute(
            select(PumpHealthScore)
            .where(PumpHealthScore.site_id == site_id)
            .order_by(desc(PumpHealthScore.timestamp))
            .limit(1)
        )
    ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="No health scores available for this site")
    return row


@router.get(
    "/{site_id}/forecast",
    response_model=ForecastResponse,
    summary="24-hour water level forecast with breach risk assessment",
    responses={
        503: {"description": "Forecast artifact not yet available — run train_forecast.py first"},
    },
)
async def get_forecast(
    site_id: int,
    db: AsyncSession = Depends(get_db),
) -> ForecastResponse:
    await _get_site_or_404(site_id, db)

    json_path = Path(settings.forecast_model_dir) / f"forecast_{site_id}_24h.json"
    if not json_path.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                f"Forecast not yet available for site {site_id}. "
                "Run ml/train_forecast.py (or ml/retrain_forecast.py) to generate it."
            ),
        )

    artifact = json.loads(json_path.read_text())
    return ForecastResponse(**artifact)


@router.get(
    "/{site_id}/ai-summary",
    response_model=AISummaryResponse,
    summary="Claude-generated plain-English site health summary",
    responses={
        503: {"description": "Anthropic API key not configured"},
    },
)
async def get_ai_summary_endpoint(
    site_id: int,
    refresh: bool = Query(False, description="Bypass the 15-minute cache and force a fresh summary"),
    db: AsyncSession = Depends(get_db),
) -> AISummaryResponse:
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not configured on this server.",
        )

    site = await _get_site_or_404(site_id, db)

    # Check cache first so we can set the `cached` flag accurately
    was_cached = not refresh and bool(await _get_cached(site_id))

    summary = await get_ai_summary(site, db, force_refresh=refresh)

    return AISummaryResponse(
        site_id=site.id,
        site_name=site.name,
        summary=summary,
        generated_at=datetime.now(timezone.utc),
        cached=was_cached,
        cache_ttl_s=_SUMMARY_TTL_SECONDS,
    )
