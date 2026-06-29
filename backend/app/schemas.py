"""
All Pydantic request/response models for the Groundwater Monitor API.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ── Site ──────────────────────────────────────────────────────────────────────

class SiteResponse(BaseModel):
    id: int
    name: str
    location: str | None
    latitude: float | None
    longitude: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Sensor reading ────────────────────────────────────────────────────────────

class ReadingCreate(BaseModel):
    site_id: int = Field(..., gt=0)
    timestamp: datetime
    water_level_m: float = Field(..., description="Metres below datum (negative = below ground)")
    flow_rate_lpm: float | None = Field(None, ge=0, description="Flow rate in litres/minute")
    pump_pressure_bar: float | None = Field(None, ge=0, description="Pump discharge pressure in bar")
    turbidity_ntu: float | None = Field(None, ge=0, description="Turbidity in NTU")
    conductivity_us_cm: float | None = Field(None, ge=0, description="Electrical conductivity in µS/cm")
    temperature_c: float | None = Field(None, ge=-10, le=60, description="Groundwater temperature °C")

    @field_validator("water_level_m")
    @classmethod
    def must_be_finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("water_level_m must be a finite number")
        return v


class ReadingResponse(BaseModel):
    site_id: int
    timestamp: datetime
    water_level_m: float
    flow_rate_lpm: float | None
    pump_pressure_bar: float | None
    turbidity_ntu: float | None
    conductivity_us_cm: float | None
    temperature_c: float | None

    model_config = {"from_attributes": True}


class PaginatedReadings(BaseModel):
    data: list[ReadingResponse]
    total: int
    page: int
    page_size: int
    has_next: bool


# ── Alert ─────────────────────────────────────────────────────────────────────

class AlertResponse(BaseModel):
    id: int
    site_id: int
    alert_type: str
    severity: Literal["critical", "high", "medium", "low"]
    message: str
    triggered_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


# ── Pump health score ─────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    site_id: int
    timestamp: datetime
    score: float = Field(..., ge=0, le=100, description="Health score 0–100 (100 = perfect)")
    contributing_factors: dict[str, Any] | None

    model_config = {"from_attributes": True}


# ── Dashboard ─────────────────────────────────────────────────────────────────

class SiteSummary(BaseModel):
    site_id: int
    site_name: str
    location: str | None
    latitude: float | None
    longitude: float | None
    latest_reading: ReadingResponse | None
    health_score: float | None
    active_alert_count: int
    status: Literal["normal", "warning", "critical"]


class DashboardSummary(BaseModel):
    sites: list[SiteSummary]
    total_sites: int
    sites_critical: int
    sites_warning: int
    sites_normal: int
    generated_at: datetime


# ── Forecasting ──────────────────────────────────────────────────────────────

class ForecastPoint(BaseModel):
    ds:          datetime
    yhat:        float = Field(..., description="Predicted water level (m)")
    yhat_lower:  float = Field(..., description="90 % CI lower bound (m)")
    yhat_upper:  float = Field(..., description="90 % CI upper bound (m)")


class ForecastResponse(BaseModel):
    site_id:                int
    site_name:              str
    generated_at:           datetime = Field(..., description="When this forecast was produced")
    model_trained_at:       datetime = Field(..., description="When the underlying model was trained")
    training_rows:          int
    forecast_horizon_hours: int
    threshold_m:            float = Field(
        ..., description="Breach threshold (m). Water level rising above this value is dangerous."
    )
    breach_risk:            bool  = Field(
        ..., description="True if the forecast indicates elevated breach risk within the horizon"
    )
    estimated_breach_time:  datetime | None = Field(
        None, description="First forecast hour where the upper CI exceeds the threshold"
    )
    breach_confidence:      float = Field(
        ..., ge=0, le=1,
        description="Fraction of forecast hours where the upper CI exceeds the threshold (0–1)"
    )
    forecast:               list[ForecastPoint]


# ── ML anomaly detection ──────────────────────────────────────────────────────

class AnomalyDetectRequest(BaseModel):
    site_id: int | None = Field(None, gt=0, description="Site ID for per-site model selection")
    site_name: str | None = Field(None, description="Site name (alternative to site_id)")
    water_level_m: float | None = None
    flow_rate_lpm: float | None = Field(None, ge=0)
    pump_pressure_bar: float | None = Field(None, ge=0)
    turbidity_ntu: float | None = Field(None, ge=0)
    conductivity_us_cm: float | None = Field(None, ge=0)


class DetectorDetail(BaseModel):
    triggered: bool
    score: float


class AnomalyDetectResponse(BaseModel):
    is_anomaly: bool
    anomaly_score: float = Field(..., ge=0, le=1, description="0 = normal, 1 = maximally anomalous")
    severity: Literal["normal", "low", "medium", "critical"]
    contributing_features: dict[str, float]
    detectors: dict[str, DetectorDetail]
    site_model_used: str
    model_version: str
    features: list[str]


# ── AI summary ───────────────────────────────────────────────────────────────

class AISummaryResponse(BaseModel):
    site_id:      int
    site_name:    str
    summary:      str  = Field(..., description="Plain-English site health summary from Claude")
    generated_at: datetime
    cached:       bool = Field(..., description="True if served from Redis cache")
    cache_ttl_s:  int  = Field(900, description="Cache TTL in seconds")


# ── WebSocket messages ────────────────────────────────────────────────────────

class LiveReadingMessage(BaseModel):
    event: Literal["connected", "reading", "pong"]
    site_id: int | None = None
    site_name: str | None = None
    data: ReadingResponse | None = None
    message: str | None = None
    server_time: datetime | None = None
