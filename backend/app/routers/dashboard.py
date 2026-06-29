from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import DashboardSummary, ReadingResponse, SiteSummary

router = APIRouter(tags=["dashboard"])

# Single efficient query: latest reading + latest health score + alert counts per site.
# DISTINCT ON is PostgreSQL-specific and works on TimescaleDB.
_DASHBOARD_SQL = text("""
WITH latest_readings AS (
    SELECT DISTINCT ON (site_id)
        site_id,
        timestamp,
        water_level_m,
        flow_rate_lpm,
        pump_pressure_bar,
        turbidity_ntu,
        conductivity_us_cm,
        temperature_c
    FROM sensor_readings
    ORDER BY site_id, timestamp DESC
),
latest_health AS (
    SELECT DISTINCT ON (site_id)
        site_id,
        score
    FROM pump_health_scores
    ORDER BY site_id, timestamp DESC
),
alert_counts AS (
    SELECT
        site_id,
        COUNT(*) FILTER (WHERE resolved_at IS NULL)                             AS active_count,
        COUNT(*) FILTER (WHERE resolved_at IS NULL AND severity = 'critical')   AS critical_count,
        COUNT(*) FILTER (WHERE resolved_at IS NULL AND severity = 'high')       AS high_count
    FROM alerts
    GROUP BY site_id
)
SELECT
    s.id                            AS site_id,
    s.name                          AS site_name,
    s.location,
    s.latitude,
    s.longitude,
    lr.timestamp                    AS reading_timestamp,
    lr.water_level_m,
    lr.flow_rate_lpm,
    lr.pump_pressure_bar,
    lr.turbidity_ntu,
    lr.conductivity_us_cm,
    lr.temperature_c,
    lh.score                        AS health_score,
    COALESCE(ac.active_count,   0)  AS active_alert_count,
    COALESCE(ac.critical_count, 0)  AS critical_alert_count,
    COALESCE(ac.high_count,     0)  AS high_alert_count
FROM       sites           s
LEFT JOIN  latest_readings lr ON s.id = lr.site_id
LEFT JOIN  latest_health   lh ON s.id = lh.site_id
LEFT JOIN  alert_counts    ac ON s.id = ac.site_id
ORDER BY s.id
""")


def _derive_status(
    health_score: float | None,
    critical_alerts: int,
    high_alerts: int,
) -> str:
    if critical_alerts > 0 or (health_score is not None and health_score < 40):
        return "critical"
    if high_alerts > 0 or (health_score is not None and health_score < 70):
        return "warning"
    return "normal"


@router.get(
    "/dashboard/summary",
    response_model=DashboardSummary,
    summary="All-sites overview: latest readings, health scores, and active alerts",
)
async def dashboard_summary(db: AsyncSession = Depends(get_db)) -> DashboardSummary:
    rows = (await db.execute(_DASHBOARD_SQL)).mappings().all()

    summaries: list[SiteSummary] = []
    for row in rows:
        latest: ReadingResponse | None = None
        if row["reading_timestamp"] is not None:
            latest = ReadingResponse(
                site_id=row["site_id"],
                timestamp=row["reading_timestamp"],
                water_level_m=row["water_level_m"],
                flow_rate_lpm=row["flow_rate_lpm"],
                pump_pressure_bar=row["pump_pressure_bar"],
                turbidity_ntu=row["turbidity_ntu"],
                conductivity_us_cm=row["conductivity_us_cm"],
                temperature_c=row["temperature_c"],
            )

        summaries.append(
            SiteSummary(
                site_id=row["site_id"],
                site_name=row["site_name"],
                location=row["location"],
                latitude=row["latitude"],
                longitude=row["longitude"],
                latest_reading=latest,
                health_score=row["health_score"],
                active_alert_count=int(row["active_alert_count"]),
                status=_derive_status(
                    row["health_score"],
                    int(row["critical_alert_count"]),
                    int(row["high_alert_count"]),
                ),
            )
        )

    statuses = [s.status for s in summaries]
    return DashboardSummary(
        sites=summaries,
        total_sites=len(summaries),
        sites_critical=statuses.count("critical"),
        sites_warning=statuses.count("warning"),
        sites_normal=statuses.count("normal"),
        generated_at=datetime.now(timezone.utc),
    )
