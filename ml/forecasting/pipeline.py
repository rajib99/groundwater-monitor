"""
Prophet-based water-level forecasting pipeline for groundwater sites.

Architecture
────────────
One Prophet model is trained *per site* on that site's normal (non-anomalous)
hourly water-level readings only — semi-supervised so the model learns the
baseline signal rather than anomaly-distorted behaviour.

Seasonalities:
  - Daily (Fourier order 10)  — strong dewatering pump cycle
  - Tidal M2 (12.42 h)        — coastal sites only (Dubai Marina, Yas Island)
  - UAE work-hour regressor   — captures Sun–Thu 06:00-20:00 dewatering effect

Breach risk
───────────
A "breach" occurs when water level rises above a configurable threshold (m).
  breach_risk = True  if yhat itself exceeds threshold, OR
                      if yhat_upper exceeds threshold for ≥20 % of the horizon
  breach_confidence   = fraction of forecast hours where yhat_upper > threshold
  estimated_breach_time = first forecast hour where yhat_upper > threshold
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

# Suppress Prophet / Stan noise
logging.getLogger("prophet").setLevel(logging.WARNING)
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

FORECAST_HORIZON_H = 24

# Sites that sit in tidal zones (add M2 tidal seasonality)
COASTAL_SITES: frozenset[str] = frozenset(
    ["Dubai Marina Excavation", "Yas Island Construction"]
)

# Default breach threshold per site (m).  Water level is negative; a reading
# is dangerous when it RISES above (becomes less negative than) this value.
DEFAULT_THRESHOLDS: dict[str, float] = {
    "Dubai Marina Excavation": -7.5,
    "Abu Dhabi Tunnel":        -12.0,
    "Yas Island Construction": -4.0,
    "_global":                 -6.0,
}


# ── UAE work-hour helper ──────────────────────────────────────────────────────

def _uae_work_hour(ds: pd.Series) -> np.ndarray:
    """
    Returns 1.0 during UAE working hours, 0.0 otherwise.

    UAE timezone: UTC+4 (Gulf Standard Time, no DST).
    Working week : Sunday–Thursday.
    Working hours: 06:00–20:00 local (02:00–16:00 UTC).
    """
    uae_hour = (ds.dt.hour + 4) % 24
    # If UTC hour ≥ 20, the calendar date in UAE has already rolled forward
    uae_dow = (ds.dt.dayofweek + (ds.dt.hour >= 20).astype(int)) % 7
    is_workday = ~np.isin(uae_dow, [4, 5])   # Fri=4, Sat=5
    is_work_hr = (uae_hour >= 6) & (uae_hour < 20)
    return (is_workday & is_work_hr).astype(float).values


# ── Per-site model ────────────────────────────────────────────────────────────

@dataclass
class SiteForecastModel:
    site_id:    int
    site_name:  str
    threshold_m: float
    is_coastal: bool
    n_train:    int
    trained_at: str        # ISO-8601
    latest_ds:  str        # ISO-8601 timestamp of last training point
    prophet:    object     # prophet.Prophet (typed as object to avoid hard import)


# ── Bundle ────────────────────────────────────────────────────────────────────

class ForecastBundle:
    """
    Container for all per-site Prophet models.

    Usage:
        bundle = ForecastBundle.train(df)
        bundle.save("models/")   # writes forecast_{id}.pkl + forecast_{id}_24h.json

        bundle = ForecastBundle.load("models/")
        artifact = bundle.forecast(site_id=1)
    """

    def __init__(self) -> None:
        self.site_models:    dict[int, SiteForecastModel] = {}
        self.name_to_id:     dict[str, int] = {}
        self.bundle_version: str = ""

    # ── Training ──────────────────────────────────────────────────────────────

    @classmethod
    def train(
        cls,
        df: pd.DataFrame,
        thresholds: dict[str, float] | None = None,
        site_id_col: str = "site_id",
        site_name_col: str = "site_name",
    ) -> "ForecastBundle":
        """
        Train per-site Prophet models.

        df must contain: site_id, site_name, timestamp, water_level_m.
        Optionally: is_anomaly (bool) — anomalous hours are excluded from training.
        """
        bundle = cls()
        bundle.bundle_version = datetime.now(timezone.utc).isoformat()
        thresholds = thresholds or {}

        for site_id, site_df in df.groupby(site_id_col):
            site_name  = site_df[site_name_col].iloc[0]
            threshold  = thresholds.get(
                site_name,
                DEFAULT_THRESHOLDS.get(site_name, DEFAULT_THRESHOLDS["_global"]),
            )
            is_coastal = site_name in COASTAL_SITES

            df_hourly = _prepare_site_data(site_df)
            logger.info(
                "Training forecast for site %d (%s): %d hourly points, threshold=%.2f m",
                site_id, site_name, len(df_hourly), threshold,
            )

            model = _train_one_site(
                int(site_id), site_name, df_hourly, threshold, is_coastal
            )
            bundle.site_models[int(site_id)] = model
            bundle.name_to_id[site_name] = int(site_id)

        return bundle

    # ── Forecasting ───────────────────────────────────────────────────────────

    def forecast(self, site_id: int, horizon_h: int = FORECAST_HORIZON_H) -> dict:
        """
        Generate a forecast artifact dict for the given site.

        The artifact is JSON-serialisable and matches the ForecastResponse
        schema used by the backend API.
        """
        site_model = self.site_models.get(site_id)
        if site_model is None:
            if not self.site_models:
                raise ValueError("ForecastBundle has no loaded models")
            site_model = next(iter(self.site_models.values()))
            logger.warning(
                "Site %d not in bundle; falling back to %s", site_id, site_model.site_name
            )

        future = site_model.prophet.make_future_dataframe(
            periods=horizon_h, freq="h", include_history=False
        )
        future["is_uae_work_hour"] = _uae_work_hour(future["ds"])

        raw = site_model.prophet.predict(future)
        fc  = raw[["ds", "yhat", "yhat_lower", "yhat_upper"]].copy()

        breach_risk, breach_time, breach_conf = _breach_analysis(fc, site_model.threshold_m)

        return {
            "site_id":                site_model.site_id,
            "site_name":              site_model.site_name,
            "generated_at":           datetime.now(timezone.utc).isoformat(),
            "model_trained_at":       site_model.trained_at,
            "training_rows":          site_model.n_train,
            "forecast_horizon_hours": horizon_h,
            "threshold_m":            site_model.threshold_m,
            "breach_risk":            breach_risk,
            "estimated_breach_time":  breach_time,
            "breach_confidence":      breach_conf,
            "forecast": [
                {
                    "ds":         row.ds.isoformat(),
                    "yhat":       round(float(row.yhat), 4),
                    "yhat_lower": round(float(row.yhat_lower), 4),
                    "yhat_upper": round(float(row.yhat_upper), 4),
                }
                for row in fc.itertuples()
            ],
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, model_dir: str | Path) -> None:
        """
        For each site, saves:
          forecast_{site_id}.pkl       — Prophet model (for future retraining)
          forecast_{site_id}_24h.json  — Latest 24h forecast artifact (for backend)
        """
        model_dir = Path(model_dir)
        model_dir.mkdir(parents=True, exist_ok=True)

        for site_id, site_model in self.site_models.items():
            pkl_path = model_dir / f"forecast_{site_id}.pkl"
            joblib.dump(
                {
                    "site_id":    site_model.site_id,
                    "site_name":  site_model.site_name,
                    "threshold_m": site_model.threshold_m,
                    "is_coastal": site_model.is_coastal,
                    "n_train":    site_model.n_train,
                    "trained_at": site_model.trained_at,
                    "latest_ds":  site_model.latest_ds,
                    "prophet":    site_model.prophet,
                },
                pkl_path,
                compress=3,
            )
            logger.info("Saved Prophet model → %s", pkl_path)

            artifact  = self.forecast(site_id)
            json_path = model_dir / f"forecast_{site_id}_24h.json"
            json_path.write_text(json.dumps(artifact, indent=2))
            logger.info(
                "Saved forecast artifact → %s  (breach_risk=%s, confidence=%.0f%%)",
                json_path,
                artifact["breach_risk"],
                artifact["breach_confidence"] * 100,
            )

    @classmethod
    def load(
        cls,
        model_dir: str | Path,
        site_ids: list[int] | None = None,
    ) -> "ForecastBundle":
        """Load Prophet models from PKL files (needed for retraining, not for backend reads)."""
        model_dir = Path(model_dir)
        bundle    = cls()

        if site_ids:
            pkl_paths = [model_dir / f"forecast_{sid}.pkl" for sid in site_ids]
        else:
            pkl_paths = sorted(model_dir.glob("forecast_[0-9]*.pkl"))

        for pkl_path in pkl_paths:
            if not pkl_path.exists():
                logger.warning("Forecast PKL not found: %s", pkl_path)
                continue
            d = joblib.load(pkl_path)
            site_model = SiteForecastModel(**d)
            bundle.site_models[site_model.site_id] = site_model
            bundle.name_to_id[site_model.site_name] = site_model.site_id
            logger.info(
                "Loaded forecast model for site %d (%s) trained at %s",
                site_model.site_id, site_model.site_name, site_model.trained_at,
            )

        return bundle


# ── Internal helpers ──────────────────────────────────────────────────────────

def _prepare_site_data(site_df: pd.DataFrame) -> pd.DataFrame:
    """
    Resample 15-min readings to hourly, exclude anomalous hours.

    Returns a clean DataFrame with columns [ds, y] ready for Prophet.
    ds is UTC timezone-naive (Prophet requirement).
    """
    df = site_df.copy()

    # Parse timestamps if they came in as strings (CSV path)
    ts = pd.to_datetime(df["timestamp"], utc=True)
    ts = ts.dt.tz_localize(None)  # strip tz → UTC-naive for Prophet + resample

    df = df.sort_values("timestamp")
    df.index = ts.sort_values()

    # Identify anomalous hourly buckets (exclude any hour with ≥1 anomalous reading)
    has_labels = "is_anomaly" in df.columns
    if has_labels:
        # .any() not available on DatetimeIndexResampler in pandas 2.x; use max() instead
        anom_hourly = df["is_anomaly"].astype(int).resample("h").max().astype(bool)

    wl_hourly = df["water_level_m"].resample("h").median()

    result = (
        pd.DataFrame({"ds": wl_hourly.index, "y": wl_hourly.values})
        .dropna()
        .reset_index(drop=True)
    )

    if has_labels:
        mask = anom_hourly.reindex(result["ds"]).fillna(False).values
        result = result[~mask].reset_index(drop=True)

    return result


def _train_one_site(
    site_id: int,
    site_name: str,
    df_hourly: pd.DataFrame,
    threshold_m: float,
    is_coastal: bool,
) -> SiteForecastModel:
    """Fit a Prophet model on clean hourly water-level data."""
    from prophet import Prophet  # lazy import keeps the module importable without prophet

    m = Prophet(
        growth="linear",
        changepoint_prior_scale=0.05,
        seasonality_prior_scale=10.0,
        seasonality_mode="additive",
        yearly_seasonality=False,      # only 90 days of data
        weekly_seasonality=False,      # replaced by UAE work-hour regressor
        daily_seasonality=True,        # strong pump-cycle signal
        interval_width=0.90,
        n_changepoints=25,
    )

    if is_coastal:
        # M2 tidal period: 12.42 h = 12.42/24 days
        m.add_seasonality(name="tidal_m2", period=12.42 / 24, fourier_order=3)

    m.add_regressor("is_uae_work_hour", mode="additive")

    df_fit = df_hourly.copy()
    df_fit["is_uae_work_hour"] = _uae_work_hour(df_fit["ds"])
    m.fit(df_fit)

    return SiteForecastModel(
        site_id=site_id,
        site_name=site_name,
        threshold_m=threshold_m,
        is_coastal=is_coastal,
        n_train=len(df_hourly),
        trained_at=datetime.now(timezone.utc).isoformat(),
        latest_ds=df_hourly["ds"].max().isoformat(),
        prophet=m,
    )


def _breach_analysis(
    fc: pd.DataFrame,
    threshold_m: float,
) -> tuple[bool, str | None, float]:
    """
    Analyse a forecast DataFrame for breach risk.

    Returns:
        breach_risk            — True if central forecast or persistent upper CI breaches
        estimated_breach_time  — ISO timestamp of first upper-CI breach (or None)
        breach_confidence      — fraction of horizon hours where upper CI > threshold
    """
    upper_breach = fc["yhat_upper"] > threshold_m
    yhat_breach  = fc["yhat"] > threshold_m

    breach_confidence = round(float(upper_breach.mean()), 3)

    if not upper_breach.any():
        return False, None, 0.0

    # Persistent upper-CI exceedance (≥20 % of hours) counts as breach risk even
    # if the central forecast stays below threshold.
    breach_risk = bool(yhat_breach.any() or breach_confidence >= 0.20)

    first_breach_time = fc.loc[upper_breach, "ds"].iloc[0].isoformat()

    return breach_risk, first_breach_time, breach_confidence
