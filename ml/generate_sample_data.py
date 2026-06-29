#!/usr/bin/env python3
"""
Generate 90 days of realistic groundwater sensor readings for three UAE construction sites.

Signal model per sensor:
  water_level  = baseline + seasonal_trend + tidal(M2+K1+spring-neap) + diurnal
                 + workday_dewatering + noise  [+anomaly deltas]
  conductivity = baseline + tidal_modulation + noise  [+anomaly deltas]
  flow_rate    = baseline + f(water_level_deviation) + noise
  pressure     = baseline + f(flow) + f(depth) + noise
  turbidity    = baseline + f(flow_excess) + noise  [+anomaly deltas]
  temperature  = baseline + seasonal + diurnal(damped) + noise

Anomaly types injected (5-8 per site):
  pump_failure        – WL rises, flow/pressure collapse
  saltwater_intrusion – conductivity spike (coastal sites)
  storm_event         – WL + turbidity + flow spike, conductivity dilutes
  gradual_drift       – slow multi-day WL rise (sheet-pile micro-breach)
  pump_blockage       – pressure spike, flow drop
  heat_anomaly        – temperature spike (equipment heat)
  turbidity_spike     – turbidity spike (dredging / excavation activity)
  cond_drift          – slow conductivity creep
  combined_event      – WL + conductivity + turbidity simultaneous

Outputs:
  ml/data/<slug>.csv          per-site CSV with anomaly labels
  ml/data/all_readings.csv    combined dataset

Set DATABASE_URL to also seed PostgreSQL and create alert records:
  DATABASE_URL=postgresql://user:pass@localhost:5432/groundwater \\
      python generate_sample_data.py
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

# ─── Constants ────────────────────────────────────────────────────────────────

DAYS = 90
INTERVAL_MIN = 15
SAMPLES = DAYS * 24 * (60 // INTERVAL_MIN)   # 8 640 per site
RNG_SEED = 42

END_DATE = datetime(2026, 6, 29, 23, 45, tzinfo=timezone.utc)
START_DATE = END_DATE - timedelta(days=DAYS)

OUTPUT_DIR = Path(__file__).parent / "data"
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ─── Site profiles ────────────────────────────────────────────────────────────

SITES = [
    {
        "name": "Dubai Marina Excavation",
        "location": "Dubai Marina, Dubai, UAE",
        "latitude": 25.0772,
        "longitude": 55.1386,
        # Water level (m, negative = below ground datum)
        "wl_baseline": -9.50,
        "wl_trend": +0.0020,          # m/day — seasonal water-table rise
        "wl_noise_sd": 0.040,
        "wl_daily_amp": 0.080,        # 24 h diurnal variation
        "wl_tidal_amp": 0.220,        # M2 tidal amplitude
        "wl_tidal_phase": 2.30,       # radians
        "wl_workday_effect": -0.15,   # active dewatering depresses level Sun–Thu
        # Conductivity (µS/cm)
        "cond_baseline": 5_500.0,
        "cond_noise_sd": 180.0,
        "cond_tidal_factor": 280.0,   # rises at high tide (saltwater head)
        # Temperature (°C, groundwater)
        "temp_baseline": 30.2,
        "temp_seasonal_amp": 3.5,
        "temp_noise_sd": 0.25,
        # Flow rate (L/min)
        "flow_baseline": 128.0,
        "flow_noise_sd": 18.0,
        "flow_wl_coeff": -12.0,       # L/min per metre WL rise above baseline
        # Pump pressure (bar)
        "pressure_baseline": 3.85,
        "pressure_noise_sd": 0.28,
        # Turbidity (NTU)
        "turbidity_baseline": 8.5,
        "turbidity_noise_sd": 2.8,
        "turbidity_flow_factor": 0.06,  # NTU per L/min excess flow
        # Anomalies: (day_offset, type, params)
        "anomalies": [
            (7.4,  "pump_failure",        {"wl_delta": +2.6,  "rise_h": 2.5, "hold_h": 1.5, "fall_h": 5.0}),
            (21.8, "saltwater_intrusion", {"cond_delta": +8500, "rise_h": 4,  "hold_h": 12,  "fall_h": 20}),
            (34.6, "storm_event",         {"wl_delta": +1.9,  "turb_factor": 7.5, "flow_factor": 2.8, "rise_h": 3, "hold_h": 8, "fall_h": 14}),
            (50.2, "gradual_drift",       {"wl_delta": +0.85, "duration_days": 4.5}),
            (67.9, "saltwater_intrusion", {"cond_delta": +12800, "rise_h": 6, "hold_h": 24, "fall_h": 36}),
            (82.1, "pump_blockage",       {"pressure_factor": 1.85, "flow_factor": 0.45, "rise_h": 1.0, "hold_h": 5.0, "fall_h": 2.0}),
        ],
    },
    {
        "name": "Abu Dhabi Tunnel",
        "location": "Mussafah, Abu Dhabi, UAE",
        "latitude": 24.3537,
        "longitude": 54.5093,
        "wl_baseline": -14.20,
        "wl_trend": +0.0008,
        "wl_noise_sd": 0.030,
        "wl_daily_amp": 0.045,
        "wl_tidal_amp": 0.0,          # inland — no tidal influence
        "wl_tidal_phase": 0.0,
        "wl_workday_effect": -0.10,
        "cond_baseline": 850.0,
        "cond_noise_sd": 45.0,
        "cond_tidal_factor": 0.0,
        "temp_baseline": 27.8,
        "temp_seasonal_amp": 2.2,
        "temp_noise_sd": 0.18,
        "flow_baseline": 65.0,
        "flow_noise_sd": 11.0,
        "flow_wl_coeff": -8.0,
        "pressure_baseline": 5.20,
        "pressure_noise_sd": 0.35,
        "turbidity_baseline": 4.2,
        "turbidity_noise_sd": 1.4,
        "turbidity_flow_factor": 0.04,
        "anomalies": [
            (11.5, "gradual_drift",  {"wl_delta": +1.55, "duration_days": 6.0}),
            (30.8, "pump_blockage",  {"pressure_factor": 1.90, "flow_factor": 0.38, "rise_h": 0.8, "hold_h": 3.5, "fall_h": 1.5}),
            (46.3, "heat_anomaly",   {"temp_delta": +9.5,  "rise_h": 4.0, "hold_h": 8.0, "fall_h": 12.0}),
            (62.0, "storm_event",    {"wl_delta": +2.8,  "turb_factor": 9.0, "flow_factor": 3.2, "rise_h": 2, "hold_h": 6, "fall_h": 18}),
            (77.7, "cond_drift",     {"cond_factor": 3.2, "duration_days": 5.0}),
        ],
    },
    {
        "name": "Yas Island Construction",
        "location": "Yas Island, Abu Dhabi, UAE",
        "latitude": 24.4672,
        "longitude": 54.6077,
        "wl_baseline": -5.80,
        "wl_trend": +0.0030,
        "wl_noise_sd": 0.060,
        "wl_daily_amp": 0.120,
        "wl_tidal_amp": 0.460,
        "wl_tidal_phase": 0.85,
        "wl_workday_effect": -0.18,
        "cond_baseline": 12_500.0,
        "cond_noise_sd": 380.0,
        "cond_tidal_factor": 820.0,
        "temp_baseline": 32.0,
        "temp_seasonal_amp": 4.2,
        "temp_noise_sd": 0.45,
        "flow_baseline": 168.0,
        "flow_noise_sd": 28.0,
        "flow_wl_coeff": -18.0,
        "pressure_baseline": 2.80,
        "pressure_noise_sd": 0.28,
        "turbidity_baseline": 15.5,
        "turbidity_noise_sd": 5.0,
        "turbidity_flow_factor": 0.09,
        "anomalies": [
            (5.2,  "storm_event",         {"wl_delta": +1.6,   "turb_factor": 12.0, "flow_factor": 3.5, "rise_h": 2, "hold_h": 16, "fall_h": 20}),
            (19.0, "saltwater_intrusion", {"cond_delta": +22000, "rise_h": 5, "hold_h": 36, "fall_h": 48}),
            (33.5, "pump_failure",        {"wl_delta": +1.9,   "rise_h": 3.0, "hold_h": 2.0, "fall_h": 4.5}),
            (47.8, "turbidity_spike",     {"turb_delta": +480,  "flow_factor": 1.8,  "rise_h": 1, "hold_h": 5, "fall_h": 8}),
            (57.5, "cond_drift",          {"cond_factor": 2.4,  "duration_days": 8.0}),
            (70.3, "combined_event",      {"wl_delta": +2.1,   "cond_delta": +18000, "turb_factor": 14, "flow_factor": 3.8, "rise_h": 3, "hold_h": 18, "fall_h": 24}),
            (84.6, "pump_blockage",       {"pressure_factor": 2.10, "flow_factor": 0.35, "rise_h": 1.5, "hold_h": 8.0, "fall_h": 3.0}),
        ],
    },
]

SEVERITY_MAP = {
    "pump_failure": "critical",
    "saltwater_intrusion": "high",
    "storm_event": "high",
    "gradual_drift": "medium",
    "pump_blockage": "high",
    "heat_anomaly": "medium",
    "turbidity_spike": "medium",
    "cond_drift": "low",
    "combined_event": "critical",
}

# ─── Signal primitives ────────────────────────────────────────────────────────

def _smooth_pulse(t_h: np.ndarray, onset_h: float, rise_h: float,
                  hold_h: float, fall_h: float) -> np.ndarray:
    """
    Normalised [0 → 1] pulse with sigmoid rise, flat plateau, sigmoid fall.
    Used for acute anomaly events.
    """
    peak_start = onset_h + rise_h
    peak_end   = peak_start + hold_h
    offset     = peak_end + fall_h

    y = np.zeros(len(t_h))

    rise_mask = (t_h >= onset_h) & (t_h < peak_start)
    if rise_mask.any():
        t_norm = (t_h[rise_mask] - onset_h) / rise_h
        y[rise_mask] = 1 / (1 + np.exp(-10 * (t_norm - 0.5)))

    y[(t_h >= peak_start) & (t_h <= peak_end)] = 1.0

    fall_mask = (t_h > peak_end) & (t_h <= offset)
    if fall_mask.any():
        t_norm = (t_h[fall_mask] - peak_end) / fall_h
        y[fall_mask] = 1 - 1 / (1 + np.exp(-10 * (t_norm - 0.5)))

    return y


def _sigmoid_drift(t_h: np.ndarray, onset_h: float, duration_h: float) -> np.ndarray:
    """
    Slow logistic ramp 0 → 1 over duration_h, never fully decaying.
    Used for gradual breach / formation-change anomalies.
    """
    midpoint = onset_h + duration_h / 2
    k = 8.0 / duration_h
    result = np.zeros(len(t_h))
    mask = t_h >= onset_h
    result[mask] = 1 / (1 + np.exp(-k * (t_h[mask] - midpoint)))
    return result


def _tidal(t_h: np.ndarray, amp: float, phase: float) -> np.ndarray:
    """
    Arabian Gulf mixed tidal signal: M2 + S2 (spring-neap modulation) + K1 diurnal.
    Spring-neap envelope cycles every 14.8 days.
    """
    if amp == 0:
        return np.zeros(len(t_h))
    spring_neap = 0.70 + 0.30 * np.cos(2 * np.pi * t_h / (14.8 * 24))
    m2 = spring_neap * amp       * np.sin(2 * np.pi * t_h / 12.42 + phase)
    s2 = spring_neap * 0.35 * amp * np.sin(2 * np.pi * t_h / 12.00 + phase + 1.2)
    k1 = spring_neap * 0.20 * amp * np.sin(2 * np.pi * t_h / 23.93 + phase + 0.5)
    return m2 + s2 + k1


def _seasonal(t_h: np.ndarray, amp: float) -> np.ndarray:
    """
    UAE seasonal air-temp variation: peak in early August (day ~220).
    Groundwater lags air by ~30-45 days and is significantly damped.
    Start of dataset = April 1 (day 91 of year).
    """
    start_day_of_year = 91
    day = start_day_of_year + t_h / 24
    peak_day = 220
    return amp * np.cos(2 * np.pi * (day - peak_day) / 365)


def _workday(timestamps: pd.DatetimeIndex, effect: float) -> np.ndarray:
    """
    UAE workweek is Sunday–Thursday.  Active dewatering during working hours
    (06:00–20:00) depresses the water table by `effect` metres.
    """
    dow = timestamps.dayofweek   # 0=Mon … 6=Sun
    is_work = ~np.isin(dow, [4, 5])          # Fri=4, Sat=5 are weekend
    is_hours = (timestamps.hour >= 6) & (timestamps.hour < 20)
    return np.where(is_work & is_hours, effect, 0.0)

# ─── Per-site data generation ─────────────────────────────────────────────────

def _generate_site(cfg: dict, rng: np.random.Generator) -> pd.DataFrame:
    timestamps = pd.date_range(START_DATE, periods=SAMPLES,
                               freq=f"{INTERVAL_MIN}min", tz="UTC")
    t_h = np.arange(SAMPLES, dtype=float) * (INTERVAL_MIN / 60.0)  # hours from start

    # ── Base signals ─────────────────────────────────────────────────────────

    # Water level
    trend   = cfg["wl_baseline"] + cfg["wl_trend"] * (t_h / 24)
    tidal   = _tidal(t_h, cfg["wl_tidal_amp"], cfg["wl_tidal_phase"])
    diurnal = cfg["wl_daily_amp"] * np.sin(2 * np.pi * (t_h % 24 - 6) / 24)
    workday = _workday(timestamps, cfg["wl_workday_effect"])
    wl      = trend + tidal + diurnal + workday + rng.normal(0, cfg["wl_noise_sd"], SAMPLES)

    # Temperature — seasonal (air-driven with ~40-day lag at depth) + small diurnal
    seasonal = _seasonal(t_h, cfg["temp_seasonal_amp"])
    temp_diurnal = 0.4 * np.sin(2 * np.pi * (t_h % 24 - 4) / 24)
    temp = (cfg["temp_baseline"] + seasonal + temp_diurnal
            + rng.normal(0, cfg["temp_noise_sd"], SAMPLES))

    # Conductivity — tidal modulation on coastal sites
    cond_tidal = cfg["cond_tidal_factor"] * _tidal(t_h, 1.0, cfg["wl_tidal_phase"])
    cond = (cfg["cond_baseline"] + cond_tidal
            + rng.normal(0, cfg["cond_noise_sd"], SAMPLES))

    # Flow rate — inversely correlated with water level (more inflow → more pumping)
    wl_dev  = wl - cfg["wl_baseline"]          # deviation from design baseline
    flow    = (cfg["flow_baseline"]
               + cfg["flow_wl_coeff"] * wl_dev
               + rng.normal(0, cfg["flow_noise_sd"], SAMPLES))

    # Pump pressure — driven by flow demand and static head (depth below datum)
    depth   = np.abs(wl)                        # positive depth below datum
    pressure = (cfg["pressure_baseline"]
                + 0.008 * (flow - cfg["flow_baseline"])
                + 0.005 * (depth - np.abs(cfg["wl_baseline"]))
                + rng.normal(0, cfg["pressure_noise_sd"], SAMPLES))

    # Turbidity — spikes when flow exceeds baseline (disturbs formation)
    flow_excess = np.maximum(0, flow - cfg["flow_baseline"])
    turbidity = (cfg["turbidity_baseline"]
                 + cfg["turbidity_flow_factor"] * flow_excess
                 + rng.normal(0, cfg["turbidity_noise_sd"], SAMPLES))

    # ── Anomaly injection ────────────────────────────────────────────────────

    anomaly_label = np.full(SAMPLES, "", dtype=object)
    anomaly_flag  = np.zeros(SAMPLES, dtype=bool)

    for day_offset, atype, p in cfg["anomalies"]:
        onset_h = day_offset * 24

        if atype == "pump_failure":
            pulse = _smooth_pulse(t_h, onset_h, p["rise_h"], p["hold_h"], p["fall_h"])
            wl       += p["wl_delta"] * pulse
            flow     -= cfg["flow_baseline"] * 0.92 * pulse   # pump off → flow collapses
            pressure -= cfg["pressure_baseline"] * 0.88 * pulse

        elif atype == "saltwater_intrusion":
            pulse = _smooth_pulse(t_h, onset_h, p["rise_h"], p["hold_h"], p["fall_h"])
            cond += p["cond_delta"] * pulse
            wl   += 0.35 * pulse                              # saline head raises WL slightly

        elif atype == "storm_event":
            pulse = _smooth_pulse(t_h, onset_h, p["rise_h"], p["hold_h"], p["fall_h"])
            wl        += p["wl_delta"] * pulse
            turbidity += cfg["turbidity_baseline"] * (p["turb_factor"] - 1) * pulse
            flow      += cfg["flow_baseline"] * (p["flow_factor"] - 1) * pulse
            cond      -= cfg["cond_noise_sd"] * 1.5 * pulse   # rain dilutes conductivity

        elif atype == "gradual_drift":
            drift = _sigmoid_drift(t_h, onset_h, p["duration_days"] * 24)
            wl   += p["wl_delta"] * drift
            flow += cfg["flow_wl_coeff"] * (-p["wl_delta"] * drift)  # more inflow

        elif atype == "pump_blockage":
            pulse     = _smooth_pulse(t_h, onset_h, p["rise_h"], p["hold_h"], p["fall_h"])
            pressure *= (1 + (p["pressure_factor"] - 1) * pulse)
            flow     *= (1 - (1 - p["flow_factor"]) * pulse)

        elif atype == "heat_anomaly":
            pulse = _smooth_pulse(t_h, onset_h, p["rise_h"], p["hold_h"], p["fall_h"])
            temp += p["temp_delta"] * pulse

        elif atype == "turbidity_spike":
            pulse      = _smooth_pulse(t_h, onset_h, p["rise_h"], p["hold_h"], p["fall_h"])
            turbidity += p["turb_delta"] * pulse
            flow      += cfg["flow_baseline"] * (p["flow_factor"] - 1) * pulse

        elif atype == "cond_drift":
            drift = _sigmoid_drift(t_h, onset_h, p["duration_days"] * 24)
            cond *= (1 + (p["cond_factor"] - 1) * drift)

        elif atype == "combined_event":
            pulse      = _smooth_pulse(t_h, onset_h, p["rise_h"], p["hold_h"], p["fall_h"])
            wl        += p["wl_delta"] * pulse
            cond      += p["cond_delta"] * pulse
            turbidity += cfg["turbidity_baseline"] * (p["turb_factor"] - 1) * pulse
            flow      += cfg["flow_baseline"] * (p["flow_factor"] - 1) * pulse

        # Label samples where anomaly amplitude > 10 % of its peak.
        # For slow drifts, only the active ramp-up zone (0.10–0.90) is labelled;
        # once a drift stabilises at a new level it becomes the site's new normal.
        if atype in ("gradual_drift", "cond_drift"):
            duration_h = p.get("duration_days", 5) * 24
            sig = _sigmoid_drift(t_h, onset_h, duration_h)
            active = (sig > 0.10) & (sig < 0.90)
        else:
            active = _smooth_pulse(t_h, onset_h,
                                   p["rise_h"], p["hold_h"], p["fall_h"]) > 0.10
        anomaly_flag[active] = True
        anomaly_label[active] = atype

    # ── Physical bounds ───────────────────────────────────────────────────────

    flow      = np.maximum(flow, 0.0)
    pressure  = np.maximum(pressure, 0.2)
    turbidity = np.maximum(turbidity, 0.1)
    cond      = np.maximum(cond, 50.0)
    temp      = np.clip(temp, 18.0, 48.0)

    # ── Assemble DataFrame ────────────────────────────────────────────────────

    return pd.DataFrame({
        "site_name":         cfg["name"],
        "timestamp":         timestamps,
        "water_level_m":     np.round(wl, 4),
        "flow_rate_lpm":     np.round(flow, 2),
        "pump_pressure_bar": np.round(pressure, 3),
        "turbidity_ntu":     np.round(turbidity, 2),
        "conductivity_us_cm": np.round(cond, 1),
        "temperature_c":     np.round(temp, 2),
        "is_anomaly":        anomaly_flag,
        "anomaly_type":      anomaly_label,
    })


def generate_all() -> list[pd.DataFrame]:
    rng = np.random.default_rng(RNG_SEED)
    return [_generate_site(cfg, rng) for cfg in SITES]


# ─── CSV output ───────────────────────────────────────────────────────────────

def write_csv(dfs: list[pd.DataFrame]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for df in dfs:
        slug = df["site_name"].iloc[0].lower().replace(" ", "_")
        path = OUTPUT_DIR / f"{slug}.csv"
        df.to_csv(path, index=False)
        n_anomaly = df["is_anomaly"].sum()
        pct = 100 * n_anomaly / len(df)
        print(f"  {path.name}: {len(df):,} rows  |  {n_anomaly:,} anomalous ({pct:.1f} %)")

    combined = pd.concat(dfs, ignore_index=True)
    combined_path = OUTPUT_DIR / "all_readings.csv"
    combined.to_csv(combined_path, index=False)
    print(f"  all_readings.csv: {len(combined):,} rows total")


# ─── PostgreSQL seeding ───────────────────────────────────────────────────────

def _psycopg2_url(url: str) -> str:
    """Strip SQLAlchemy dialect prefix so psycopg2 can use it directly."""
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    return url


def seed_database(dfs: list[pd.DataFrame]) -> None:
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        print("psycopg2 not available — skipping database seed.")
        return

    conn = psycopg2.connect(_psycopg2_url(DATABASE_URL))
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # ── Upsert sites ──────────────────────────────────────────────────────
        site_ids: dict[str, int] = {}
        for cfg in SITES:
            cur.execute(
                """
                INSERT INTO sites (name, location, latitude, longitude)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE
                    SET location  = EXCLUDED.location,
                        latitude  = EXCLUDED.latitude,
                        longitude = EXCLUDED.longitude
                RETURNING id
                """,
                (cfg["name"], cfg["location"], cfg["latitude"], cfg["longitude"]),
            )
            site_ids[cfg["name"]] = cur.fetchone()[0]
        conn.commit()
        print(f"  Upserted {len(site_ids)} sites → ids {list(site_ids.values())}")

        # ── Sensor readings (batched, 1 000 rows at a time) ───────────────────
        BATCH = 1_000
        for df in dfs:
            site_id = site_ids[df["site_name"].iloc[0]]

            # Clear existing sample data for this site so re-runs are idempotent
            cur.execute(
                "DELETE FROM sensor_readings WHERE site_id = %s "
                "  AND timestamp >= %s AND timestamp <= %s",
                (site_id,
                 df["timestamp"].iloc[0].to_pydatetime(),
                 df["timestamp"].iloc[-1].to_pydatetime()),
            )

            rows = [
                (
                    site_id,
                    row.timestamp.to_pydatetime(),
                    row.water_level_m,
                    row.flow_rate_lpm,
                    row.pump_pressure_bar,
                    row.turbidity_ntu,
                    row.conductivity_us_cm,
                    row.temperature_c,
                )
                for row in df.itertuples(index=False)
            ]

            for i in range(0, len(rows), BATCH):
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO sensor_readings
                        (site_id, timestamp, water_level_m, flow_rate_lpm,
                         pump_pressure_bar, turbidity_ntu, conductivity_us_cm, temperature_c)
                    VALUES %s
                    ON CONFLICT (site_id, timestamp) DO NOTHING
                    """,
                    rows[i : i + BATCH],
                )
            conn.commit()
            print(f"  Inserted {len(rows):,} readings for '{df['site_name'].iloc[0]}'")

        # ── Alerts from anomaly events ─────────────────────────────────────────
        cur.execute("DELETE FROM alerts WHERE site_id = ANY(%s)",
                    (list(site_ids.values()),))

        alert_rows = []
        for cfg in SITES:
            site_id = site_ids[cfg["name"]]
            for day_offset, atype, p in cfg["anomalies"]:
                triggered_at = START_DATE + timedelta(days=day_offset)

                # Compute resolved_at based on event duration
                if atype in ("gradual_drift", "cond_drift"):
                    duration_h = p.get("duration_days", 5) * 24
                else:
                    duration_h = p.get("rise_h", 2) + p.get("hold_h", 4) + p.get("fall_h", 6)
                resolved_at = triggered_at + timedelta(hours=duration_h)

                alert_rows.append((
                    site_id,
                    atype,
                    SEVERITY_MAP.get(atype, "medium"),
                    _alert_message(cfg["name"], atype, p),
                    triggered_at,
                    resolved_at,
                ))

        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO alerts
                (site_id, alert_type, severity, message, triggered_at, resolved_at)
            VALUES %s
            """,
            alert_rows,
        )
        conn.commit()
        print(f"  Inserted {len(alert_rows)} alert records")

    except Exception as exc:
        conn.rollback()
        print(f"  Database error: {exc}", file=sys.stderr)
        raise
    finally:
        cur.close()
        conn.close()


def _alert_message(site_name: str, atype: str, params: dict) -> str:
    msgs = {
        "pump_failure":        f"Dewatering pump failure detected at {site_name}. "
                               f"Water level rose {params.get('wl_delta', 0):.1f} m above baseline.",
        "saltwater_intrusion": f"Saltwater intrusion event at {site_name}. "
                               f"Conductivity spiked +{params.get('cond_delta', 0):,.0f} µS/cm.",
        "storm_event":         f"Storm-induced inflow at {site_name}. "
                               f"Water level +{params.get('wl_delta', 0):.1f} m, "
                               f"turbidity ×{params.get('turb_factor', 1):.1f}.",
        "gradual_drift":       f"Gradual water-level drift at {site_name} — possible micro-breach. "
                               f"+{params.get('wl_delta', 0):.2f} m over "
                               f"{params.get('duration_days', 0):.1f} days.",
        "pump_blockage":       f"Pump blockage at {site_name}. "
                               f"Pressure ×{params.get('pressure_factor', 1):.1f}, "
                               f"flow rate {int(params.get('flow_factor', 1)*100)} % of normal.",
        "heat_anomaly":        f"Abnormal temperature rise at {site_name}. "
                               f"+{params.get('temp_delta', 0):.1f} °C above baseline "
                               f"(possible equipment overheating).",
        "turbidity_spike":     f"Turbidity spike at {site_name} (+{params.get('turb_delta', 0):.0f} NTU). "
                               f"Likely nearby excavation or dredging activity.",
        "cond_drift":          f"Slow conductivity increase at {site_name} "
                               f"(×{params.get('cond_factor', 1):.1f} over "
                               f"{params.get('duration_days', 0):.1f} days). Possible formation change.",
        "combined_event":      f"Combined storm + saltwater event at {site_name}. "
                               f"Water level +{params.get('wl_delta', 0):.1f} m, "
                               f"conductivity +{params.get('cond_delta', 0):,.0f} µS/cm.",
    }
    return msgs.get(atype, f"Anomaly ({atype}) detected at {site_name}.")


# ─── Summary stats ────────────────────────────────────────────────────────────

def print_summary(dfs: list[pd.DataFrame]) -> None:
    print("\n─── Anomaly breakdown ────────────────────────────────────────────")
    for df in dfs:
        site = df["site_name"].iloc[0]
        types = df[df["is_anomaly"]]["anomaly_type"].value_counts()
        print(f"\n  {site}")
        for atype, count in types.items():
            duration_h = count * INTERVAL_MIN / 60
            print(f"    {atype:<28} {count:>5} samples  (~{duration_h:.1f} h)")

    print("\n─── Sensor ranges (all sites, normal data only) ──────────────────")
    normal = pd.concat(dfs)[lambda d: ~d["is_anomaly"]]
    cols = ["water_level_m", "flow_rate_lpm", "pump_pressure_bar",
            "turbidity_ntu", "conductivity_us_cm", "temperature_c"]
    print(normal[cols].agg(["min", "mean", "max"]).round(2).to_string())


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Generating {DAYS}-day dataset  "
          f"({SAMPLES:,} samples/site × {len(SITES)} sites = "
          f"{SAMPLES * len(SITES):,} total rows)")
    print(f"Period: {START_DATE.date()} → {END_DATE.date()}\n")

    dfs = generate_all()

    print("Writing CSV files…")
    write_csv(dfs)

    if DATABASE_URL:
        print("\nSeeding PostgreSQL…")
        seed_database(dfs)
    else:
        print("\nDATABASE_URL not set — skipping database seed.")
        print("  Set it to also insert into PostgreSQL:")
        print("  DATABASE_URL=postgresql://user:pass@host:5432/db python generate_sample_data.py")

    print_summary(dfs)
    print(f"\nDone.  CSV files written to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
