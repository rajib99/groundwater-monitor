"""
AI site health summary service.

Assembles the last 6 hours of sensor readings, any active anomaly alerts,
and the 24-hour forecast for a site, then calls Claude claude-sonnet-4-6 to
produce a concise plain-English health summary for a groundwater monitoring
engineer.

Summaries are cached in Redis for 15 minutes to avoid redundant API calls.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.alert import Alert
from app.models.sensor_reading import SensorReading
from app.models.site import Site

logger = logging.getLogger(__name__)

_SUMMARY_TTL_SECONDS = 15 * 60   # 15 minutes
_READINGS_WINDOW_H   = 6
_MODEL               = "llama-3.3-70b-versatile"

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a senior groundwater monitoring engineer with deep expertise in \
construction dewatering systems across the UAE. You are reviewing real-time \
telemetry and model outputs for active excavation and tunnel sites.

Your role is to write concise, actionable site health summaries for site \
supervisors who may not have an engineering background. Each summary must:
- Be 3 to 5 sentences in plain English.
- Start with an overall status verdict (e.g. "All systems normal", \
"Early warning signs detected", "Immediate attention required").
- Explain what the data shows in plain language — translate numbers into \
meaning (e.g. "risen 0.4 m" rather than "water_level_m = -8.3").
- If anomalies are present, describe what they suggest about equipment or \
groundwater conditions.
- If the 24-hour forecast shows breach risk, state the estimated time and \
recommended action window.
- Close with a clear recommendation: monitor, inspect within N hours, or \
escalate immediately.

Do NOT include bullet points, headers, markdown, or JSON. Plain prose only.\
"""

# ── Data assembly ─────────────────────────────────────────────────────────────

async def _fetch_readings(
    site_id: int,
    db: AsyncSession,
    window_hours: int = _READINGS_WINDOW_H,
) -> list[dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    rows = (
        await db.execute(
            select(SensorReading)
            .where(
                SensorReading.site_id == site_id,
                SensorReading.timestamp >= since,
            )
            .order_by(SensorReading.timestamp)
        )
    ).scalars().all()

    return [
        {
            "timestamp":          r.timestamp.isoformat(),
            "water_level_m":      round(r.water_level_m, 3),
            "flow_rate_lpm":      round(r.flow_rate_lpm, 1)      if r.flow_rate_lpm      is not None else None,
            "pump_pressure_bar":  round(r.pump_pressure_bar, 2)  if r.pump_pressure_bar  is not None else None,
            "turbidity_ntu":      round(r.turbidity_ntu, 1)      if r.turbidity_ntu      is not None else None,
            "conductivity_us_cm": round(r.conductivity_us_cm, 0) if r.conductivity_us_cm is not None else None,
            "temperature_c":      round(r.temperature_c, 1)      if r.temperature_c      is not None else None,
        }
        for r in rows
    ]


async def _fetch_active_alerts(
    site_id: int,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(Alert)
            .where(
                Alert.site_id == site_id,
                Alert.resolved_at.is_(None),
            )
            .order_by(desc(Alert.triggered_at))
            .limit(10)
        )
    ).scalars().all()

    return [
        {
            "type":         a.alert_type,
            "severity":     a.severity,
            "message":      a.message,
            "triggered_at": a.triggered_at.isoformat(),
        }
        for a in rows
    ]


def _load_forecast(site_id: int) -> dict[str, Any] | None:
    path = Path(settings.forecast_model_dir) / f"forecast_{site_id}_24h.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        # Trim the per-hour forecast to the first 12 points so the prompt
        # stays compact; breach metadata is what matters most.
        data = dict(data)
        data["forecast"] = data["forecast"][:12]
        return data
    except Exception:
        logger.warning("Could not read forecast artifact for site %d", site_id)
        return None


def _summarise_readings(readings: list[dict]) -> dict[str, Any]:
    """Derive trend statistics from raw readings to keep the prompt compact."""
    if not readings:
        return {"count": 0}

    wl      = [r["water_level_m"] for r in readings]
    fl      = [r["flow_rate_lpm"]  for r in readings if r["flow_rate_lpm"]  is not None]
    pr      = [r["pump_pressure_bar"] for r in readings if r["pump_pressure_bar"] is not None]
    tu      = [r["turbidity_ntu"]  for r in readings if r["turbidity_ntu"]  is not None]
    co      = [r["conductivity_us_cm"] for r in readings if r["conductivity_us_cm"] is not None]

    def _stats(vals: list[float]) -> dict:
        if not vals:
            return {}
        return {
            "min":   round(min(vals), 3),
            "max":   round(max(vals), 3),
            "mean":  round(sum(vals) / len(vals), 3),
            "delta": round(vals[-1] - vals[0], 3),   # change over the window
            "latest": round(vals[-1], 3),
        }

    return {
        "window_hours":     _READINGS_WINDOW_H,
        "count":            len(readings),
        "first_timestamp":  readings[0]["timestamp"],
        "last_timestamp":   readings[-1]["timestamp"],
        "water_level_m":    _stats(wl),
        "flow_rate_lpm":    _stats(fl),
        "pump_pressure_bar": _stats(pr),
        "turbidity_ntu":    _stats(tu),
        "conductivity_us_cm": _stats(co),
    }


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_user_prompt(
    site: Site,
    reading_stats: dict[str, Any],
    active_alerts: list[dict[str, Any]],
    forecast: dict[str, Any] | None,
) -> str:
    parts: list[str] = [
        f"SITE: {site.name}",
        f"LOCATION: {site.location or 'unknown'}",
        f"CURRENT TIME (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
        "",
        "=== SENSOR READINGS (last 6 hours) ===",
        json.dumps(reading_stats, indent=2),
    ]

    if active_alerts:
        parts += [
            "",
            "=== ACTIVE (UNRESOLVED) ALERTS ===",
            json.dumps(active_alerts, indent=2),
        ]
    else:
        parts += ["", "=== ACTIVE ALERTS: none ==="]

    if forecast:
        breach = {
            "threshold_m":           forecast.get("threshold_m"),
            "breach_risk":           forecast.get("breach_risk"),
            "breach_confidence":     forecast.get("breach_confidence"),
            "estimated_breach_time": forecast.get("estimated_breach_time"),
        }
        parts += [
            "",
            "=== 24-HOUR FORECAST (next 12 hourly points shown) ===",
            f"Breach metadata: {json.dumps(breach)}",
            json.dumps(forecast.get("forecast", []), indent=2),
        ]
    else:
        parts += ["", "=== FORECAST: not available ==="]

    parts += [
        "",
        "Write the site health summary now.",
    ]

    return "\n".join(parts)


# ── Groq call ─────────────────────────────────────────────────────────────────

async def _call_groq(user_prompt: str) -> str:
    import groq as groq_lib
    client = groq_lib.AsyncGroq(api_key=settings.groq_api_key)
    response = await client.chat.completions.create(
        model=_MODEL,
        max_tokens=400,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
    )
    return response.choices[0].message.content.strip()


# ── Redis cache ───────────────────────────────────────────────────────────────

def _cache_key(site_id: int) -> str:
    return f"ai_summary:{site_id}"


async def _get_cached(site_id: int) -> str | None:
    import redis.asyncio as aioredis
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        async with r:
            return await r.get(_cache_key(site_id))
    except Exception as exc:
        logger.warning("Redis read failed (site %d): %s", site_id, exc)
        return None


async def _set_cached(site_id: int, summary: str) -> None:
    import redis.asyncio as aioredis
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        async with r:
            await r.set(_cache_key(site_id), summary, ex=_SUMMARY_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Redis write failed (site %d): %s", site_id, exc)


# ── Public entry point ────────────────────────────────────────────────────────

async def get_ai_summary(
    site: Site,
    db: AsyncSession,
    force_refresh: bool = False,
) -> str:
    """
    Return a plain-English site health summary, served from Redis cache when
    available.  Falls back gracefully if Redis is unavailable.

    Args:
        site:          ORM Site object (must be loaded).
        db:            Async SQLAlchemy session.
        force_refresh: Bypass cache and call Claude unconditionally.
    """
    if not force_refresh:
        cached = await _get_cached(site.id)
        if cached:
            logger.debug("AI summary cache hit for site %d", site.id)
            return cached

    readings    = await _fetch_readings(site.id, db)
    alerts      = await _fetch_active_alerts(site.id, db)
    forecast    = _load_forecast(site.id)
    stats       = _summarise_readings(readings)
    user_prompt = _build_user_prompt(site, stats, alerts, forecast)

    logger.info(
        "Calling Groq for site %d (%s): %d readings, %d alerts, forecast=%s",
        site.id, site.name, stats.get("count", 0), len(alerts), forecast is not None,
    )

    summary = await _call_groq(user_prompt)

    await _set_cached(site.id, summary)
    return summary


# ── Report executive summary (no cache, longer prose) ────────────────────────

_REPORT_SYSTEM = """\
You are a senior groundwater engineer writing the executive summary section of \
a formal technical report for a UAE construction site. Write a single paragraph \
of 4–6 sentences (100–140 words) in professional report language.

Cover: overall site condition over the reporting period, notable sensor trends \
(reference specific numbers), anomaly count and any critical events, pump health \
trajectory, and a clear operational recommendation.

Do NOT use bullet points, headings, or markdown. Plain prose only. Past tense \
where describing the reporting period; present tense for recommendations.\
"""


async def get_report_summary(
    *,
    site_name: str,
    site_location: str | None,
    readings_df: pd.DataFrame,
    alerts: list[dict],
    health_scores: list[dict],
    date_range_start: datetime,
    date_range_end: datetime,
) -> str:
    """Generate a formal executive summary for the PDF report.

    Unlike ``get_ai_summary`` this is not cached — each report gets a fresh
    summary tailored to its exact date range and statistics.
    """
    if not settings.groq_api_key:
        return (
            "AI executive summary is unavailable because GROQ_API_KEY is "
            "not configured on this server."
        )

    fmt = lambda d: d.strftime("%d %b %Y %H:%M UTC")
    parts: list[str] = [
        f"SITE: {site_name}",
        f"LOCATION: {site_location or 'Not specified'}",
        f"REPORT PERIOD: {fmt(date_range_start)} — {fmt(date_range_end)}",
        "",
        "=== SENSOR STATISTICS (period-wide) ===",
    ]

    _sensor_cols = [
        ("water_level_m",      "Water level",    "m"),
        ("flow_rate_lpm",      "Flow rate",      "L/min"),
        ("pump_pressure_bar",  "Pump pressure",  "bar"),
        ("turbidity_ntu",      "Turbidity",      "NTU"),
        ("conductivity_us_cm", "Conductivity",   "µS/cm"),
        ("temperature_c",      "Temperature",    "°C"),
    ]
    if not readings_df.empty:
        for col, label, unit in _sensor_cols:
            if col in readings_df.columns and readings_df[col].notna().any():
                ser = readings_df[col].dropna()
                parts.append(
                    f"{label}: mean={ser.mean():.3f} {unit}, "
                    f"min={ser.min():.3f}, max={ser.max():.3f}, "
                    f"readings={len(ser)}"
                )
    else:
        parts.append("No sensor readings available for this period.")

    active = [a for a in alerts if not a.get("resolved_at")]
    critical = [a for a in alerts if a.get("severity") == "critical"]
    parts += [
        "",
        "=== ALERT SUMMARY ===",
        f"Total alerts: {len(alerts)}, active (unresolved): {len(active)}, critical: {len(critical)}",
    ]
    for a in sorted(alerts, key=lambda x: x.get("severity", ""))[:5]:
        parts.append(f"  [{a['severity'].upper()}] {a.get('alert_type', '')} — {a.get('message', '')}")

    health_vals = [h["score"] for h in health_scores if h.get("score") is not None]
    if health_vals:
        parts += [
            "",
            "=== PUMP HEALTH ===",
            f"mean={np.mean(health_vals):.1f}, min={min(health_vals):.1f}, "
            f"max={max(health_vals):.1f}, latest={health_vals[-1]:.1f}",
        ]

    parts += ["", "Write the executive summary paragraph now."]

    try:
        import groq as groq_lib
        client = groq_lib.AsyncGroq(api_key=settings.groq_api_key)
        response = await client.chat.completions.create(
            model=_MODEL,
            max_tokens=400,
            messages=[
                {"role": "system", "content": _REPORT_SYSTEM},
                {"role": "user",   "content": "\n".join(parts)},
            ],
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("Groq report summary failed: %s", exc)
        return (
            "The AI-generated executive summary could not be produced at this "
            "time. Please review the data tables and chart in this report."
        )
