#!/usr/bin/env python3
"""
Retrain the anomaly detector on demand using live data from PostgreSQL.

Queries sensor_readings joined to sites, pulls data from the last N days
(default: 90), then calls the same training pipeline used by train.py.

Usage:
    DATABASE_URL=postgresql://user:pass@localhost:5432/db python retrain.py
    DATABASE_URL=... python retrain.py --days 180 --output models/anomaly_detector.pkl
    DATABASE_URL=... python retrain.py --dry-run      # fetch & report, no save

Environment:
    DATABASE_URL   PostgreSQL connection string (required)
    ML_MODEL_PATH  Override default output path
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).parent))

from anomaly_detection.pipeline import FEATURES, AnomalyDetectorBundle
from train import evaluate, train

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_MODEL = Path(
    os.environ.get("ML_MODEL_PATH",
                   str(Path(__file__).parent / "models" / "anomaly_detector.pkl"))
)

# ── Database query ────────────────────────────────────────────────────────────

_QUERY = text("""
SELECT
    s.id            AS site_id,
    s.name          AS site_name,
    r.timestamp,
    r.water_level_m,
    r.flow_rate_lpm,
    r.pump_pressure_bar,
    r.turbidity_ntu,
    r.conductivity_us_cm,
    r.temperature_c,
    -- Join to alerts to produce a pseudo-label:
    -- a reading is "anomalous" if an unresolved alert was active at its timestamp.
    EXISTS (
        SELECT 1 FROM alerts a
        WHERE a.site_id = s.id
          AND r.timestamp BETWEEN a.triggered_at
                              AND COALESCE(a.resolved_at, NOW())
    )::boolean AS is_anomaly
FROM sensor_readings r
JOIN sites s ON s.id = r.site_id
WHERE r.timestamp >= :since
ORDER BY s.id, r.timestamp
""")


def fetch_from_db(db_url: str, days: int) -> pd.DataFrame:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    engine = create_engine(db_url)
    with engine.connect() as conn:
        df = pd.read_sql(_QUERY, conn, params={"since": since})
    logger.info(
        "Fetched %d rows from DB (last %d days,  since %s)",
        len(df), days, since.date(),
    )
    return df


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Retrain anomaly detector from PostgreSQL")
    p.add_argument("--days",    type=int,  default=90,
                   help="Number of historical days to pull (default: 90)")
    p.add_argument("--output",  type=Path, default=DEFAULT_MODEL,
                   help="Output path for the trained model")
    p.add_argument("--no-eval", action="store_true",
                   help="Skip evaluation step")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch data and report stats but do not save model")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL environment variable is not set.")
        sys.exit(1)

    df = fetch_from_db(db_url, args.days)

    if df.empty:
        logger.error("No data returned from DB — nothing to train on.")
        sys.exit(1)

    # Summarise what we pulled
    for sid, g in df.groupby("site_id"):
        n_anom = int(g["is_anomaly"].sum())
        logger.info(
            "  Site %d %-30s  rows=%d  labeled_anomalies=%d (%.1f%%)",
            sid, f"({g['site_name'].iloc[0]})",
            len(g), n_anom, 100 * n_anom / len(g),
        )

    if args.dry_run:
        logger.info("Dry-run — model NOT saved.")
        return

    bundle = train(df)

    if not args.no_eval:
        evaluate(bundle, df)

    bundle.save(args.output)
    logger.info("Retrain complete → %s", args.output)


if __name__ == "__main__":
    main()
