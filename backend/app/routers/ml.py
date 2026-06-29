"""
POST /api/ml/detect-anomaly
POST /api/ml/model-info
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.schemas import AnomalyDetectResponse, AnomalyDetectRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ml", tags=["ml"])

FEATURES: list[str] = [
    "water_level_m",
    "flow_rate_lpm",
    "pump_pressure_bar",
    "turbidity_ntu",
    "conductivity_us_cm",
]


# ── Artifact loading ──────────────────────────────────────────────────────────
# Loaded lazily on first request; cached for the process lifetime.
# The artifact is a plain dict of sklearn objects — no custom class import needed.

@lru_cache(maxsize=1)
def _load_artifact() -> dict[str, Any]:
    path = Path(settings.ml_model_path)
    if not path.exists():
        raise FileNotFoundError(f"ML model not found at {path}")
    artifact = joblib.load(path)
    logger.info("Loaded anomaly detector bundle (trained %s)", artifact.get("bundle_version"))
    return artifact


def _get_site_dict(artifact: dict, site_id: int | None, site_name: str | None) -> dict[str, Any]:
    """Resolve the per-site model dict, falling back to the global model."""
    name_to_id: dict[str, int] = artifact.get("name_to_id", {})
    site_models: dict[int, dict] = artifact.get("site_models", {})

    resolved_id = (
        site_id
        or (name_to_id.get(site_name) if site_name else None)
    )
    if resolved_id is not None:
        m = site_models.get(int(resolved_id))
        if m:
            return m
    fallback = artifact.get("fallback")
    if fallback is None:
        raise HTTPException(status_code=503, detail="No ML model available")
    return fallback


# ── Scoring helpers (mirror pipeline.py logic without importing it) ───────────

def _if_normalize(raw: float, thresholds: dict) -> float:
    boundary = thresholds["boundary"]
    critical = thresholds["critical"]
    if raw >= boundary:
        return 0.0
    if raw <= critical:
        return 1.0
    return round((boundary - raw) / (boundary - critical), 4)


def _severity(score: float, is_anomaly: bool) -> str:
    if not is_anomaly:
        return "normal"
    if score >= 0.70:
        return "critical"
    if score >= 0.35:
        return "medium"
    return "low"


def _score_reading(site_dict: dict, reading: dict[str, Any]) -> dict[str, Any]:
    import pandas as pd

    scaler    = site_dict["scaler"]
    iso       = site_dict["iso_forest"]
    thresholds = site_dict["thresholds"]
    zscore_thresholds: dict[str, float] = site_dict.get("zscore_thresholds", {
        f: 5.0 for f in FEATURES
    })

    x_df = pd.DataFrame(
        [[reading.get(f, float(scaler.mean_[i])) for i, f in enumerate(FEATURES)]],
        columns=FEATURES,
    )
    x_scaled = scaler.transform(x_df)[0]

    # Isolation Forest
    raw_if     = float(iso.score_samples(x_scaled.reshape(1, -1))[0])
    if_anomaly = bool(iso.predict(x_scaled.reshape(1, -1))[0] == -1)
    if_score   = _if_normalize(raw_if, thresholds)

    # Per-feature Z-score
    abs_z = {f: float(abs(x_scaled[i])) for i, f in enumerate(FEATURES)}
    z_excess = {
        f: max(0.0, (abs_z[f] - zscore_thresholds[f]) / zscore_thresholds[f])
        for f in FEATURES
    }
    z_score_norm = round(min(1.0, max(z_excess.values())), 4)
    z_anomaly    = z_score_norm > 0.0

    is_anomaly    = if_anomaly or z_anomaly
    anomaly_score = round(max(if_score, z_score_norm), 4)

    contributions = {
        f: round(min(1.0, abs_z[f] / zscore_thresholds[f]), 4)
        for f in FEATURES
    }

    return {
        "is_anomaly":            is_anomaly,
        "anomaly_score":         anomaly_score,
        "severity":              _severity(anomaly_score, is_anomaly),
        "contributing_features": contributions,
        "detectors": {
            "isolation_forest": {"triggered": if_anomaly, "score": round(if_score, 4)},
            "zscore":           {"triggered": z_anomaly,  "score": z_score_norm},
        },
        "site_model_used": site_dict["site_name"],
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/detect-anomaly", response_model=AnomalyDetectResponse, summary="Score a sensor reading for anomalies")
async def detect_anomaly(body: AnomalyDetectRequest) -> AnomalyDetectResponse:
    try:
        artifact = _load_artifact()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    site_dict = _get_site_dict(artifact, body.site_id, body.site_name)
    reading   = body.model_dump(exclude={"site_id", "site_name"}, exclude_none=False)

    result = _score_reading(site_dict, reading)
    result["model_version"] = artifact.get("bundle_version", "unknown")
    result["features"]      = artifact.get("features", FEATURES)
    return AnomalyDetectResponse(**result)


@router.get("/model-info", summary="Metadata about the loaded anomaly detection model")
async def model_info() -> dict[str, Any]:
    try:
        artifact = _load_artifact()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    sites = {
        str(sid): {
            "site_name":         m["site_name"],
            "n_train":           m["n_train"],
            "n_anomaly_labeled": m["n_anomaly_labeled"],
            "trained_at":        m["trained_at"],
        }
        for sid, m in artifact.get("site_models", {}).items()
    }
    return {
        "format":         artifact.get("format"),
        "bundle_version": artifact.get("bundle_version"),
        "features":       artifact.get("features"),
        "site_count":     len(sites),
        "sites":          sites,
    }
