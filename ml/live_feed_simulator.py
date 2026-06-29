#!/usr/bin/env python3
"""
Live feed simulator for the Groundwater Monitor system.

Reads the last known state per site from PostgreSQL, then continuously
generates physics-consistent sensor readings every SIMULATOR_INTERVAL_S
seconds and POSTs them to POST /api/ingest.

Signal model
────────────
Readings are generated from the same deterministic signal model used in
generate_sample_data.py, anchored to DATASET_ORIGIN so tidal phases,
seasonal curves, and diurnal pump cycles are coherent with historical data.
A continuity correction blends the last DB value to the formula baseline
over ~4 hours so there's no visible discontinuity on (re)start.

Anomaly injection
─────────────────
Each tick carries a ANOMALY_PROB (default 5 %) chance of triggering a
realistic anomaly event.  While an anomaly is active it evolves through a
rise → hold → fall lifecycle using the same smooth-pulse / sigmoid-drift
primitives from generate_sample_data.py.  Parallel anomalies are blocked
(a new one only starts once the current one finishes).

Environment variables
─────────────────────
    DATABASE_URL           PostgreSQL DSN  (required)
    API_URL                Backend base URL (default: http://localhost:8000)
    SIMULATOR_INTERVAL_S   Seconds between readings per site (default: 30)
    ANOMALY_PROB           Per-tick injection probability  (default: 0.05)
    LOG_LEVEL              DEBUG | INFO | WARNING           (default: INFO)
"""
from __future__ import annotations

import json
import logging
import math
import os
import random
import signal
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg2
import psycopg2.extras

# ── Configuration ─────────────────────────────────────────────────────────────

DATABASE_URL     = os.environ.get("DATABASE_URL", "")
API_URL          = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
INTERVAL_S       = int(os.environ.get("SIMULATOR_INTERVAL_S", "30"))
ANOMALY_PROB     = float(os.environ.get("ANOMALY_PROB", "0.05"))
LOG_LEVEL        = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("simulator")

# Time origin used when generating the 90-day historical dataset.
# All signal functions compute t_h relative to this anchor so phases are
# coherent with the data already in the database.
DATASET_ORIGIN = datetime(2026, 4, 1, 23, 45, tzinfo=timezone.utc)

# Exponential-decay time constant for the continuity correction (hours).
# After 4 × TAU the correction is < 2 % of its initial value.
CONTINUITY_DECAY_TAU_H = 4.0

# ── Site profiles (mirrors generate_sample_data.py SITES) ────────────────────

SITES: list[dict] = [
    {
        "name": "Dubai Marina Excavation",
        "wl_baseline": -9.50,  "wl_trend": +0.0020,
        "wl_noise_sd": 0.040,  "wl_daily_amp": 0.080,
        "wl_tidal_amp": 0.220, "wl_tidal_phase": 2.30,
        "wl_workday_effect": -0.15,
        "cond_baseline": 5_500.0, "cond_noise_sd": 180.0, "cond_tidal_factor": 280.0,
        "temp_baseline": 30.2, "temp_seasonal_amp": 3.5, "temp_noise_sd": 0.25,
        "flow_baseline": 128.0, "flow_noise_sd": 18.0, "flow_wl_coeff": -12.0,
        "pressure_baseline": 3.85, "pressure_noise_sd": 0.28,
        "turbidity_baseline": 8.5, "turbidity_noise_sd": 2.8, "turbidity_flow_factor": 0.06,
        "is_coastal": True,
    },
    {
        "name": "Abu Dhabi Tunnel",
        "wl_baseline": -14.20, "wl_trend": +0.0008,
        "wl_noise_sd": 0.030,  "wl_daily_amp": 0.045,
        "wl_tidal_amp": 0.0,   "wl_tidal_phase": 0.0,
        "wl_workday_effect": -0.10,
        "cond_baseline": 850.0, "cond_noise_sd": 45.0, "cond_tidal_factor": 0.0,
        "temp_baseline": 27.8, "temp_seasonal_amp": 2.2, "temp_noise_sd": 0.18,
        "flow_baseline": 65.0, "flow_noise_sd": 11.0, "flow_wl_coeff": -8.0,
        "pressure_baseline": 5.20, "pressure_noise_sd": 0.35,
        "turbidity_baseline": 4.2, "turbidity_noise_sd": 1.4, "turbidity_flow_factor": 0.04,
        "is_coastal": False,
    },
    {
        "name": "Yas Island Construction",
        "wl_baseline": -5.80,  "wl_trend": +0.0030,
        "wl_noise_sd": 0.060,  "wl_daily_amp": 0.120,
        "wl_tidal_amp": 0.460, "wl_tidal_phase": 0.85,
        "wl_workday_effect": -0.18,
        "cond_baseline": 12_500.0, "cond_noise_sd": 380.0, "cond_tidal_factor": 820.0,
        "temp_baseline": 32.0, "temp_seasonal_amp": 4.2, "temp_noise_sd": 0.45,
        "flow_baseline": 168.0, "flow_noise_sd": 28.0, "flow_wl_coeff": -18.0,
        "pressure_baseline": 2.80, "pressure_noise_sd": 0.28,
        "turbidity_baseline": 15.5, "turbidity_noise_sd": 5.0, "turbidity_flow_factor": 0.09,
        "is_coastal": True,
    },
]

# Map site name → profile for fast lookup
_SITE_CFG: dict[str, dict] = {s["name"]: s for s in SITES}

# ── Anomaly catalogue ─────────────────────────────────────────────────────────
# Each entry: (type_name, weight, param_sampler_fn)
# Weights within each site class are normalised at selection time.

def _p_saltwater(cfg: dict) -> dict:
    return {
        "cond_delta":  random.uniform(4_000, 14_000),
        "rise_h":      random.uniform(3, 7),
        "hold_h":      random.uniform(8, 24),
        "fall_h":      random.uniform(16, 36),
    }

def _p_pump_failure(cfg: dict) -> dict:
    return {
        "wl_delta":  random.uniform(1.2, 2.8),
        "rise_h":    random.uniform(1.5, 3.5),
        "hold_h":    random.uniform(1.0, 3.0),
        "fall_h":    random.uniform(3.0, 8.0),
    }

def _p_storm(cfg: dict) -> dict:
    return {
        "wl_delta":      random.uniform(0.8, 2.5),
        "turb_factor":   random.uniform(4.0, 10.0),
        "flow_factor":   random.uniform(1.8, 3.5),
        "rise_h":        random.uniform(2, 4),
        "hold_h":        random.uniform(4, 12),
        "fall_h":        random.uniform(8, 20),
    }

def _p_pump_blockage(cfg: dict) -> dict:
    return {
        "pressure_factor": random.uniform(1.5, 2.2),
        "flow_factor":     random.uniform(0.30, 0.55),
        "rise_h":          random.uniform(0.5, 1.5),
        "hold_h":          random.uniform(2.0, 6.0),
        "fall_h":          random.uniform(1.0, 3.0),
    }

def _p_heat_anomaly(cfg: dict) -> dict:
    return {
        "temp_delta": random.uniform(5.0, 12.0),
        "rise_h":     random.uniform(3.0, 6.0),
        "hold_h":     random.uniform(4.0, 10.0),
        "fall_h":     random.uniform(8.0, 16.0),
    }

def _p_turbidity_spike(cfg: dict) -> dict:
    return {
        "turb_delta":  random.uniform(80, 400),
        "flow_factor": random.uniform(1.4, 2.2),
        "rise_h":      random.uniform(0.5, 1.5),
        "hold_h":      random.uniform(3.0, 7.0),
        "fall_h":      random.uniform(4.0, 10.0),
    }

def _p_gradual_drift(cfg: dict) -> dict:
    return {
        "wl_delta":       random.uniform(0.5, 1.8),
        "duration_days":  random.uniform(3.0, 7.0),
    }

def _p_cond_drift(cfg: dict) -> dict:
    return {
        "cond_factor":    random.uniform(1.8, 3.5),
        "duration_days":  random.uniform(3.0, 8.0),
    }

def _p_combined(cfg: dict) -> dict:
    return {
        "wl_delta":    random.uniform(1.0, 2.2),
        "cond_delta":  random.uniform(8_000, 18_000),
        "turb_factor": random.uniform(6.0, 14.0),
        "flow_factor": random.uniform(2.0, 4.0),
        "rise_h":      random.uniform(2.0, 4.0),
        "hold_h":      random.uniform(8.0, 20.0),
        "fall_h":      random.uniform(12.0, 28.0),
    }

# (type_name, relative_weight, param_fn) per site class
_ANOMALY_MENU: dict[str, list[tuple]] = {
    "coastal": [
        ("saltwater_intrusion", 0.30, _p_saltwater),
        ("pump_failure",        0.15, _p_pump_failure),
        ("storm_event",         0.20, _p_storm),
        ("pump_blockage",       0.15, _p_pump_blockage),
        ("turbidity_spike",     0.10, _p_turbidity_spike),
        ("combined_event",      0.10, _p_combined),
    ],
    "inland": [
        ("pump_failure",   0.22, _p_pump_failure),
        ("pump_blockage",  0.25, _p_pump_blockage),
        ("heat_anomaly",   0.18, _p_heat_anomaly),
        ("storm_event",    0.20, _p_storm),
        ("gradual_drift",  0.08, _p_gradual_drift),
        ("cond_drift",     0.07, _p_cond_drift),
    ],
}


# ── Physics helpers ───────────────────────────────────────────────────────────

def _t_h(ts: datetime) -> float:
    """Hours elapsed since DATASET_ORIGIN."""
    return (ts - DATASET_ORIGIN).total_seconds() / 3600.0


def _tidal(t: float, amp: float, phase: float) -> float:
    if amp == 0:
        return 0.0
    spring_neap = 0.70 + 0.30 * math.cos(2 * math.pi * t / (14.8 * 24))
    m2 = spring_neap * amp        * math.sin(2 * math.pi * t / 12.42 + phase)
    s2 = spring_neap * 0.35 * amp * math.sin(2 * math.pi * t / 12.00 + phase + 1.2)
    k1 = spring_neap * 0.20 * amp * math.sin(2 * math.pi * t / 23.93 + phase + 0.5)
    return m2 + s2 + k1


def _seasonal(t: float, amp: float) -> float:
    day = 91 + t / 24    # dataset starts ~April 1 (day 91)
    return amp * math.cos(2 * math.pi * (day - 220) / 365)


def _workday_effect(ts_utc: datetime, effect: float) -> float:
    """UAE workday: Sunday–Thursday, 06:00–20:00 local (UTC+4)."""
    uae_hour = (ts_utc.hour + 4) % 24
    uae_dow  = (ts_utc.weekday() + (1 if ts_utc.hour >= 20 else 0)) % 7
    is_work  = uae_dow not in (4, 5)          # Fri=4, Sat=5
    is_hours = 6 <= uae_hour < 20
    return effect if (is_work and is_hours) else 0.0


def _base_signals(cfg: dict, ts_utc: datetime, rng: random.Random) -> dict[str, float]:
    """Deterministic + noise base signal at a given timestamp."""
    t = _t_h(ts_utc)

    wl_trend   = cfg["wl_baseline"] + cfg["wl_trend"] * (t / 24)
    wl_tidal   = _tidal(t, cfg["wl_tidal_amp"], cfg["wl_tidal_phase"])
    wl_diurnal = cfg["wl_daily_amp"] * math.sin(2 * math.pi * ((t % 24) - 6) / 24)
    wl_work    = _workday_effect(ts_utc, cfg["wl_workday_effect"])
    wl         = wl_trend + wl_tidal + wl_diurnal + wl_work + rng.gauss(0, cfg["wl_noise_sd"])

    seasonal   = _seasonal(t, cfg["temp_seasonal_amp"])
    temp_diur  = 0.4 * math.sin(2 * math.pi * ((t % 24) - 4) / 24)
    temp       = cfg["temp_baseline"] + seasonal + temp_diur + rng.gauss(0, cfg["temp_noise_sd"])

    cond_tidal = cfg["cond_tidal_factor"] * _tidal(t, 1.0, cfg["wl_tidal_phase"])
    cond       = cfg["cond_baseline"] + cond_tidal + rng.gauss(0, cfg["cond_noise_sd"])

    wl_dev     = wl - cfg["wl_baseline"]
    flow       = cfg["flow_baseline"] + cfg["flow_wl_coeff"] * wl_dev + rng.gauss(0, cfg["flow_noise_sd"])

    depth      = abs(wl)
    pressure   = (cfg["pressure_baseline"]
                  + 0.008 * (flow - cfg["flow_baseline"])
                  + 0.005 * (depth - abs(cfg["wl_baseline"]))
                  + rng.gauss(0, cfg["pressure_noise_sd"]))

    flow_excess = max(0.0, flow - cfg["flow_baseline"])
    turbidity   = (cfg["turbidity_baseline"]
                   + cfg["turbidity_flow_factor"] * flow_excess
                   + rng.gauss(0, cfg["turbidity_noise_sd"]))

    return {
        "water_level_m":      wl,
        "flow_rate_lpm":      max(0.0, flow),
        "pump_pressure_bar":  max(0.2, pressure),
        "turbidity_ntu":      max(0.1, turbidity),
        "conductivity_us_cm": max(50.0, cond),
        "temperature_c":      min(48.0, max(18.0, temp)),
    }


# ── Anomaly pulse helpers ─────────────────────────────────────────────────────

def _pulse(elapsed_h: float, rise_h: float, hold_h: float, fall_h: float) -> float:
    """Smooth-pulse amplitude at elapsed_h hours after onset. Returns 0–1."""
    peak_start = rise_h
    peak_end   = rise_h + hold_h
    total      = rise_h + hold_h + fall_h
    if elapsed_h < 0:
        return 0.0
    if elapsed_h < peak_start:
        t_norm = elapsed_h / rise_h
        return 1.0 / (1.0 + math.exp(-10.0 * (t_norm - 0.5)))
    if elapsed_h <= peak_end:
        return 1.0
    if elapsed_h <= total:
        t_norm = (elapsed_h - peak_end) / fall_h
        return 1.0 - 1.0 / (1.0 + math.exp(-10.0 * (t_norm - 0.5)))
    return 0.0


def _drift(elapsed_h: float, duration_h: float) -> float:
    """Sigmoid ramp 0→1 over duration_h. Returns 0–1."""
    if elapsed_h < 0:
        return 0.0
    k = 8.0 / duration_h
    return 1.0 / (1.0 + math.exp(-k * (elapsed_h - duration_h / 2.0)))


def _anomaly_duration_h(atype: str, params: dict) -> float:
    """Total expected lifetime of an anomaly event (hours)."""
    if atype in ("gradual_drift", "cond_drift"):
        return params["duration_days"] * 24 * 2.0   # 2× so drift fully establishes
    return params["rise_h"] + params["hold_h"] + params["fall_h"] + 2.0  # +2 h buffer


def _apply_anomaly_delta(
    signals: dict[str, float],
    cfg: dict,
    atype: str,
    params: dict,
    amplitude: float,
) -> None:
    """Modify `signals` in-place by the anomaly effect scaled by amplitude."""
    if amplitude <= 0.0:
        return

    if atype == "pump_failure":
        signals["water_level_m"]     += params["wl_delta"] * amplitude
        signals["flow_rate_lpm"]     -= cfg["flow_baseline"] * 0.92 * amplitude
        signals["pump_pressure_bar"] -= cfg["pressure_baseline"] * 0.88 * amplitude

    elif atype == "saltwater_intrusion":
        signals["conductivity_us_cm"] += params["cond_delta"] * amplitude
        signals["water_level_m"]      += 0.35 * amplitude

    elif atype == "storm_event":
        signals["water_level_m"]   += params["wl_delta"] * amplitude
        signals["turbidity_ntu"]   += cfg["turbidity_baseline"] * (params["turb_factor"] - 1) * amplitude
        signals["flow_rate_lpm"]   += cfg["flow_baseline"] * (params["flow_factor"] - 1) * amplitude
        signals["conductivity_us_cm"] -= cfg["cond_noise_sd"] * 1.5 * amplitude

    elif atype == "pump_blockage":
        signals["pump_pressure_bar"] *= (1 + (params["pressure_factor"] - 1) * amplitude)
        signals["flow_rate_lpm"]     *= (1 - (1 - params["flow_factor"]) * amplitude)

    elif atype == "heat_anomaly":
        signals["temperature_c"] += params["temp_delta"] * amplitude

    elif atype == "turbidity_spike":
        signals["turbidity_ntu"]  += params["turb_delta"] * amplitude
        signals["flow_rate_lpm"]  += cfg["flow_baseline"] * (params["flow_factor"] - 1) * amplitude

    elif atype == "gradual_drift":
        signals["water_level_m"] += params["wl_delta"] * amplitude
        signals["flow_rate_lpm"] += cfg["flow_wl_coeff"] * (-params["wl_delta"] * amplitude)

    elif atype == "cond_drift":
        signals["conductivity_us_cm"] *= (1 + (params["cond_factor"] - 1) * amplitude)

    elif atype == "combined_event":
        signals["water_level_m"]      += params["wl_delta"] * amplitude
        signals["conductivity_us_cm"] += params["cond_delta"] * amplitude
        signals["turbidity_ntu"]      += cfg["turbidity_baseline"] * (params["turb_factor"] - 1) * amplitude
        signals["flow_rate_lpm"]      += cfg["flow_baseline"] * (params["flow_factor"] - 1) * amplitude

    # Re-apply physical bounds after modification
    signals["flow_rate_lpm"]      = max(0.0, signals["flow_rate_lpm"])
    signals["pump_pressure_bar"]  = max(0.2, signals["pump_pressure_bar"])
    signals["turbidity_ntu"]      = max(0.1, signals["turbidity_ntu"])
    signals["conductivity_us_cm"] = max(50.0, signals["conductivity_us_cm"])
    signals["temperature_c"]      = min(48.0, max(18.0, signals["temperature_c"]))


# ── State dataclasses ─────────────────────────────────────────────────────────

@dataclass
class ActiveAnomaly:
    atype:          str
    params:         dict
    onset_ts:       datetime
    duration_h:     float     # when amplitude has fully decayed

    def amplitude(self, now: datetime) -> float:
        elapsed_h = (now - self.onset_ts).total_seconds() / 3600.0
        if self.atype in ("gradual_drift", "cond_drift"):
            return _drift(elapsed_h, self.params["duration_days"] * 24)
        return _pulse(elapsed_h,
                      self.params["rise_h"],
                      self.params["hold_h"],
                      self.params["fall_h"])

    def is_expired(self, now: datetime) -> bool:
        elapsed_h = (now - self.onset_ts).total_seconds() / 3600.0
        return elapsed_h > self.duration_h


@dataclass
class SiteState:
    site_id:             int
    site_name:           str
    cfg:                 dict
    last_post_ts:        datetime | None       # last successfully posted timestamp
    # Per-signal correction to blend last DB value → formula baseline (decays over time)
    continuity_offsets:  dict[str, float]
    continuity_ref_ts:   datetime             # when the offsets were computed
    active_anomaly:      ActiveAnomaly | None = field(default=None)
    rng:                 random.Random        = field(default_factory=random.Random)

    def continuity_correction(self, signal: str, now: datetime) -> float:
        offset = self.continuity_offsets.get(signal, 0.0)
        if offset == 0.0:
            return 0.0
        elapsed_h = (now - self.continuity_ref_ts).total_seconds() / 3600.0
        return offset * math.exp(-elapsed_h / CONTINUITY_DECAY_TAU_H)


# ── Main simulator ────────────────────────────────────────────────────────────

class LiveFeedSimulator:
    def __init__(
        self,
        db_url:      str,
        api_url:     str,
        interval_s:  int   = 30,
        anomaly_prob: float = 0.05,
    ) -> None:
        self.db_url       = db_url
        self.api_url      = api_url
        self.interval_s   = interval_s
        self.anomaly_prob = anomaly_prob
        self.site_states: list[SiteState] = []
        self._running     = True

        signal.signal(signal.SIGINT,  self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, *_: Any) -> None:
        logger.info("Shutdown signal received — stopping after current tick.")
        self._running = False

    # ── Initialisation ────────────────────────────────────────────────────────

    def _connect_db(self) -> psycopg2.extensions.connection:
        """Connect to PostgreSQL, stripping asyncpg dialect prefix if present."""
        url = self.db_url
        for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://"):
            if url.startswith(prefix):
                url = "postgresql://" + url[len(prefix):]
                break
        return psycopg2.connect(url)

    def _wait_for_backend(self, timeout_s: int = 120) -> None:
        """Block until the backend's /health endpoint responds."""
        health_url = f"{self.api_url}/health"
        deadline   = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(health_url, timeout=5) as resp:
                    if resp.status == 200:
                        logger.info("Backend is up — starting simulation.")
                        return
            except Exception:
                pass
            logger.info("Waiting for backend at %s …", health_url)
            time.sleep(5)
        logger.warning("Backend did not respond within %ds — starting anyway.", timeout_s)

    def _init_states(self) -> None:
        """
        Fetch sites and last readings from the DB.
        Build SiteState with continuity offsets so the live signal blends
        smoothly from the last known value to the formula baseline.
        """
        now = datetime.now(timezone.utc)

        conn = self._connect_db()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT id, name FROM sites ORDER BY id")
                db_sites = cur.fetchall()

                cur.execute("""
                    SELECT DISTINCT ON (site_id)
                        site_id, timestamp,
                        water_level_m, flow_rate_lpm, pump_pressure_bar,
                        turbidity_ntu, conductivity_us_cm, temperature_c
                    FROM sensor_readings
                    ORDER BY site_id, timestamp DESC
                """)
                last_readings = {row["site_id"]: dict(row) for row in cur.fetchall()}
        finally:
            conn.close()

        if not db_sites:
            logger.error("No sites found in the database.  Seed with generate_sample_data.py first.")
            sys.exit(1)

        for row in db_sites:
            site_id   = row["id"]
            site_name = row["name"]
            cfg       = _SITE_CFG.get(site_name)

            if cfg is None:
                logger.warning("Site '%s' has no signal profile — skipping.", site_name)
                continue

            last     = last_readings.get(site_id)
            last_ts  = last["timestamp"].replace(tzinfo=timezone.utc) if last else None

            # Compute continuity offsets: difference between last DB value and
            # what the formula gives at that same timestamp (no noise, no anomaly).
            ref_ts = last_ts or now
            formula_at_ref = _base_signals(cfg, ref_ts, random.Random(0))
            # Use a fresh RNG seeded from the site_id for reproducibility per site.
            site_rng = random.Random(site_id * 31337)

            offsets: dict[str, float] = {}
            if last:
                for key in ("water_level_m", "flow_rate_lpm", "pump_pressure_bar",
                            "turbidity_ntu", "conductivity_us_cm", "temperature_c"):
                    db_val  = last.get(key)
                    formula = formula_at_ref.get(key, 0.0)
                    if db_val is not None:
                        offsets[key] = db_val - formula

            self.site_states.append(SiteState(
                site_id=site_id,
                site_name=site_name,
                cfg=cfg,
                last_post_ts=last_ts,
                continuity_offsets=offsets,
                continuity_ref_ts=ref_ts,
                rng=site_rng,
            ))

            logger.info(
                "Initialised site %d (%s) — last reading: %s  wl_offset: %+.3f m",
                site_id, site_name,
                last_ts.isoformat() if last_ts else "none",
                offsets.get("water_level_m", 0.0),
            )

    # ── Per-tick generation ───────────────────────────────────────────────────

    def _maybe_start_anomaly(self, state: SiteState, now: datetime) -> None:
        """Roll for a new anomaly event if none is currently active."""
        if state.active_anomaly is not None:
            return
        if state.rng.random() >= self.anomaly_prob:
            return

        menu_key = "coastal" if state.cfg.get("is_coastal") else "inland"
        menu     = _ANOMALY_MENU[menu_key]
        weights  = [w for _, w, _ in menu]
        total    = sum(weights)
        r        = state.rng.random() * total
        cumul    = 0.0
        chosen   = menu[-1]
        for entry in menu:
            cumul += entry[1]
            if r <= cumul:
                chosen = entry
                break

        atype, _, param_fn = chosen
        params    = param_fn(state.cfg)
        duration  = _anomaly_duration_h(atype, params)

        state.active_anomaly = ActiveAnomaly(
            atype=atype, params=params, onset_ts=now, duration_h=duration,
        )
        logger.warning(
            "⚠  ANOMALY START  site=%s  type=%s  expected_duration=%.1fh",
            state.site_name, atype, duration,
        )

    def _tick(self, state: SiteState, now: datetime) -> dict[str, Any] | None:
        """Generate one reading for a site at `now`. Returns None if duplicate."""
        # Skip if we just posted a reading in the last 20 s (e.g. restart edge case)
        if state.last_post_ts and (now - state.last_post_ts).total_seconds() < 20:
            return None

        self._maybe_start_anomaly(state, now)

        signals = _base_signals(state.cfg, now, state.rng)

        # Apply continuity correction (decays exponentially from startup offsets)
        for key in signals:
            signals[key] += state.continuity_correction(key, now)

        # Apply active anomaly
        anom_tag = ""
        if state.active_anomaly is not None:
            anom     = state.active_anomaly
            amp      = anom.amplitude(now)
            _apply_anomaly_delta(signals, state.cfg, anom.atype, anom.params, amp)
            anom_tag = f"  [{anom.atype} amp={amp:.2f}]"

            if anom.is_expired(now):
                logger.info(
                    "✓  ANOMALY END    site=%s  type=%s",
                    state.site_name, anom.atype,
                )
                state.active_anomaly = None

        logger.info(
            "%-28s  wl=%+.3f  fl=%6.1f  pr=%.2f  tu=%5.1f  co=%7.0f  t=%.1f%s",
            state.site_name,
            signals["water_level_m"],
            signals["flow_rate_lpm"],
            signals["pump_pressure_bar"],
            signals["turbidity_ntu"],
            signals["conductivity_us_cm"],
            signals["temperature_c"],
            anom_tag,
        )

        return {
            "site_id":            state.site_id,
            "timestamp":          now.isoformat(),
            "water_level_m":      round(signals["water_level_m"], 4),
            "flow_rate_lpm":      round(max(0.0, signals["flow_rate_lpm"]), 2),
            "pump_pressure_bar":  round(max(0.0, signals["pump_pressure_bar"]), 3),
            "turbidity_ntu":      round(max(0.0, signals["turbidity_ntu"]), 2),
            "conductivity_us_cm": round(max(0.0, signals["conductivity_us_cm"]), 1),
            "temperature_c":      round(signals["temperature_c"], 2),
        }

    # ── HTTP POST ─────────────────────────────────────────────────────────────

    def _post_reading(self, reading: dict[str, Any]) -> bool:
        """POST a reading to /api/ingest. Returns True on success."""
        url     = f"{self.api_url}/api/ingest"
        payload = json.dumps(reading).encode()
        req     = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 201):
                    return True
                logger.warning("Ingest returned HTTP %d for site %d", resp.status, reading["site_id"])
                return False
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                # Duplicate (site_id, timestamp) — not an error, just skip.
                return True
            logger.warning("HTTP %d posting to %s: %s", exc.code, url, exc.reason)
            return False
        except Exception as exc:
            logger.warning("POST failed for site %d: %s", reading["site_id"], exc)
            return False

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        logger.info("Live feed simulator starting  (interval=%ds, anomaly_prob=%.0f%%)",
                    self.interval_s, self.anomaly_prob * 100)

        self._wait_for_backend()
        self._init_states()

        if not self.site_states:
            logger.error("No active site states — nothing to simulate.")
            sys.exit(1)

        logger.info("Simulating %d sites: %s",
                    len(self.site_states),
                    ", ".join(s.site_name for s in self.site_states))

        ok_count = err_count = 0

        while self._running:
            tick_start = time.monotonic()
            now        = datetime.now(timezone.utc)

            for state in self.site_states:
                reading = self._tick(state, now)
                if reading is None:
                    continue

                if self._post_reading(reading):
                    state.last_post_ts = now
                    ok_count += 1
                else:
                    err_count += 1

            # Status line every ~5 minutes
            total = ok_count + err_count
            if total > 0 and total % (5 * 60 // self.interval_s * len(self.site_states)) == 0:
                success_pct = 100 * ok_count / total
                logger.info(
                    "Stats: %d readings posted (%.1f%% success)", total, success_pct
                )

            elapsed = time.monotonic() - tick_start
            sleep_s = max(0.0, self.interval_s - elapsed)
            time.sleep(sleep_s)

        logger.info("Simulator stopped.  Total posted: %d  Errors: %d", ok_count, err_count)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not DATABASE_URL:
        logger.error("DATABASE_URL environment variable is not set.")
        sys.exit(1)

    simulator = LiveFeedSimulator(
        db_url       = DATABASE_URL,
        api_url      = API_URL,
        interval_s   = INTERVAL_S,
        anomaly_prob = ANOMALY_PROB,
    )
    simulator.run()
