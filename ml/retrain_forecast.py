#!/usr/bin/env python3
"""
Retrain water-level forecasting models on demand using live data from PostgreSQL.

Queries the last N days of sensor readings, retrains per-site Prophet models,
and regenerates the 24-hour forecast JSON artifacts consumed by the backend API.

Usage:
    DATABASE_URL=postgresql://user:pass@host:5432/db python retrain_forecast.py
    DATABASE_URL=... python retrain_forecast.py --days 180
    DATABASE_URL=... python retrain_forecast.py --dry-run
    DATABASE_URL=... python retrain_forecast.py --site-ids 1 2

Environment:
    DATABASE_URL   PostgreSQL connection string (required)
    ML_MODEL_DIR   Override default output directory
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

from forecasting.pipeline import DEFAULT_THRESHOLDS, ForecastBundle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = Path(
    os.environ.get("ML_MODEL_DIR", str(Path(__file__).parent / "models"))
)

_QUERY = text("""
SELECT
    s.id            AS site_id,
    s.name          AS site_name,
    r.timestamp,
    r.water_level_m,
    EXISTS (
        SELECT 1 FROM alerts a
        WHERE a.site_id = s.id
          AND r.timestamp BETWEEN a.triggered_at
                              AND COALESCE(a.resolved_at, NOW())
    )::boolean AS is_anomaly
FROM sensor_readings r
JOIN sites s ON s.id = r.site_id
WHERE r.timestamp >= :since
  AND r.water_level_m IS NOT NULL
ORDER BY s.id, r.timestamp
""")


def fetch_from_db(
    db_url: str,
    days: int,
    site_ids: list[int] | None = None,
) -> pd.DataFrame:
    since  = datetime.now(timezone.utc) - timedelta(days=days)
    engine = create_engine(db_url)

    query = _QUERY
    if site_ids:
        # Append an optional site filter without rewriting the whole query
        from sqlalchemy import text as t
        site_filter = ", ".join(str(s) for s in site_ids)
        query = t(str(_QUERY.text) + f" AND s.id IN ({site_filter})")

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"since": since})

    logger.info(
        "Fetched %d rows from DB  (last %d days, since %s)",
        len(df), days, since.date(),
    )
    return df


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Retrain groundwater forecasting models from PostgreSQL"
    )
    p.add_argument(
        "--days",
        type=int,
        default=90,
        help="Number of historical days to pull (default: 90)",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_MODEL_DIR,
        help="Directory to write model PKLs and forecast JSONs",
    )
    p.add_argument(
        "--site-ids",
        type=int,
        nargs="*",
        default=None,
        help="Limit retraining to specific site IDs (default: all sites)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and report data stats but do not train or save models",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL environment variable is not set.")
        sys.exit(1)

    df = fetch_from_db(db_url, args.days, site_ids=args.site_ids)

    if df.empty:
        logger.error("No data returned from DB — nothing to train on.")
        sys.exit(1)

    for sid, g in df.groupby("site_id"):
        n_anom = int(g["is_anomaly"].sum()) if "is_anomaly" in g.columns else 0
        logger.info(
            "  Site %d  %-30s  rows=%d  labeled_anomalies=%d  (%.1f%%)",
            sid,
            f"({g['site_name'].iloc[0]})",
            len(g),
            n_anom,
            100 * n_anom / len(g),
        )

    if args.dry_run:
        logger.info("Dry-run — no models trained or saved.")
        return

    logger.info("─── Training forecast models ─────────────────────")
    bundle = ForecastBundle.train(df)

    logger.info("─── Saving models + forecast artifacts ───────────")
    bundle.save(args.output_dir)
    logger.info("Retrain complete  →  %s", args.output_dir)


if __name__ == "__main__":
    main()
