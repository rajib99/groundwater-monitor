"""
PDF report generation endpoint.

POST /api/sites/{site_id}/report  — generates a PDF and returns a download URL.
GET  /api/sites/{site_id}/report/{filename}  — streams the PDF.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.alert import Alert
from app.models.pump_health_score import PumpHealthScore
from app.models.sensor_reading import SensorReading
from app.models.site import Site
from app.schemas import ReportRequest, ReportResponse
from app.services.ai_summary import get_report_summary
from app.services.report_generator import generate_pdf

router = APIRouter(prefix="/sites", tags=["reports"])


async def _get_site_or_404(site_id: int, db: AsyncSession) -> Site:
    site = await db.get(Site, site_id)
    if not site:
        raise HTTPException(status_code=404, detail=f"Site {site_id} not found")
    return site


@router.post(
    "/{site_id}/report",
    response_model=ReportResponse,
    summary="Generate a PDF site report for a date range",
    responses={
        422: {"description": "Invalid date range"},
        503: {"description": "Report storage directory not configured"},
    },
)
async def generate_report(
    site_id: int,
    req: ReportRequest,
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    if req.end <= req.start:
        raise HTTPException(status_code=422, detail="'end' must be after 'start'")
    span_days = (req.end - req.start).days
    if span_days > 90:
        raise HTTPException(
            status_code=422,
            detail="Date range cannot exceed 90 days per report",
        )

    site = await _get_site_or_404(site_id, db)

    # ── Fetch readings ─────────────────────────────────────────────────────────
    reading_rows = (
        await db.execute(
            select(SensorReading)
            .where(
                SensorReading.site_id == site_id,
                SensorReading.timestamp >= req.start,
                SensorReading.timestamp <= req.end,
            )
            .order_by(SensorReading.timestamp)
        )
    ).scalars().all()

    readings_df = (
        pd.DataFrame([
            {
                "timestamp":          r.timestamp,
                "water_level_m":      r.water_level_m,
                "flow_rate_lpm":      r.flow_rate_lpm,
                "pump_pressure_bar":  r.pump_pressure_bar,
                "turbidity_ntu":      r.turbidity_ntu,
                "conductivity_us_cm": r.conductivity_us_cm,
                "temperature_c":      r.temperature_c,
            }
            for r in reading_rows
        ])
        if reading_rows
        else pd.DataFrame(columns=[
            "timestamp", "water_level_m", "flow_rate_lpm", "pump_pressure_bar",
            "turbidity_ntu", "conductivity_us_cm", "temperature_c",
        ])
    )

    # ── Fetch alerts ───────────────────────────────────────────────────────────
    alert_rows = (
        await db.execute(
            select(Alert)
            .where(
                Alert.site_id == site_id,
                Alert.triggered_at >= req.start,
                Alert.triggered_at <= req.end,
            )
            .order_by(desc(Alert.triggered_at))
        )
    ).scalars().all()

    alerts = [
        {
            "triggered_at": a.triggered_at,
            "severity":     a.severity,
            "alert_type":   a.alert_type,
            "message":      a.message,
            "resolved_at":  a.resolved_at,
        }
        for a in alert_rows
    ]

    # ── Fetch pump health scores ───────────────────────────────────────────────
    health_rows = (
        await db.execute(
            select(PumpHealthScore)
            .where(
                PumpHealthScore.site_id == site_id,
                PumpHealthScore.timestamp >= req.start,
                PumpHealthScore.timestamp <= req.end,
            )
            .order_by(PumpHealthScore.timestamp)
        )
    ).scalars().all()

    health_scores = [
        {"timestamp": h.timestamp, "score": h.score}
        for h in health_rows
    ]

    # ── Claude executive summary (async — keep outside executor) ───────────────
    executive_summary = await get_report_summary(
        site_name=site.name,
        site_location=site.location,
        readings_df=readings_df,
        alerts=alerts,
        health_scores=health_scores,
        date_range_start=req.start,
        date_range_end=req.end,
    )

    # ── Generate PDF in thread pool (CPU-bound) ────────────────────────────────
    reports_dir = Path(settings.reports_dir)
    slug = req.start.strftime("%Y%m%d") + "_" + req.end.strftime("%Y%m%d")
    uid = uuid.uuid4().hex[:8]
    filename = f"report_site{site_id}_{slug}_{uid}.pdf"
    output_path = reports_dir / filename

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        partial(
            generate_pdf,
            site_name=site.name,
            site_location=site.location,
            date_range_start=req.start,
            date_range_end=req.end,
            readings_df=readings_df,
            alerts=alerts,
            health_scores=health_scores,
            executive_summary=executive_summary,
            output_path=output_path,
        ),
    )

    return ReportResponse(
        site_id=site_id,
        site_name=site.name,
        filename=filename,
        report_url=f"/api/sites/{site_id}/report/{filename}",
        generated_at=datetime.now(timezone.utc),
        date_range_start=req.start,
        date_range_end=req.end,
        reading_count=len(reading_rows),
        alert_count=len(alert_rows),
    )


@router.get(
    "/{site_id}/report/{filename}",
    summary="Download a previously generated PDF report",
    response_class=FileResponse,
)
async def download_report(
    site_id: int,
    filename: str,
) -> FileResponse:
    # Reject any path-traversal attempts
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF downloads are supported")
    # Ensure the file belongs to this site
    if not filename.startswith(f"report_site{site_id}_"):
        raise HTTPException(status_code=404, detail="Report not found")

    path = Path(settings.reports_dir) / filename
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Report file not found — it may have been purged",
        )

    return FileResponse(
        str(path),
        media_type="application/pdf",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
