#!/usr/bin/env python3
"""
Train per-site Prophet water-level forecasting models from CSV files.

Usage:
    python train_forecast.py                               # default data + output paths
    python train_forecast.py --data path/to/readings.csv
    python train_forecast.py --output-dir models/
    python train_forecast.py --thresholds '{"Dubai Marina Excavation": -7.0}'

Output per site:
    ml/models/forecast_{site_id}.pkl        — trained Prophet model (for retraining)
    ml/models/forecast_{site_id}_24h.json   — 24-hour forecast artifact (for API)

The CSV must contain columns:
    site_id (or site_name to synthesise one), site_name,
    timestamp, water_level_m
Optionally: is_anomaly (bool) — anomalous hours are excluded from training.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from forecasting.pipeline import DEFAULT_THRESHOLDS, ForecastBundle
from train import load_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_DATA      = Path(__file__).parent / "data" / "all_readings.csv"
DEFAULT_MODEL_DIR = Path(__file__).parent / "models"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train groundwater water-level forecasting models")
    p.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA,
        help="CSV file or directory of CSV files (default: ml/data/all_readings.csv)",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_MODEL_DIR,
        help="Directory to write model PKLs and forecast JSONs (default: ml/models/)",
    )
    p.add_argument(
        "--thresholds",
        type=str,
        default="",
        help=(
            'JSON object of {site_name: threshold_m} overrides.  '
            'Example: \'{"Dubai Marina Excavation": -7.0}\''
        ),
    )
    p.add_argument(
        "--horizon",
        type=int,
        default=24,
        help="Forecast horizon in hours (default: 24)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not args.data.exists():
        logger.error("Data not found: %s", args.data)
        logger.error("Run ml/generate_sample_data.py first to create training data.")
        sys.exit(1)

    df = load_data(args.data)

    thresholds: dict[str, float] = {}
    if args.thresholds.strip():
        thresholds = json.loads(args.thresholds)
        logger.info("Using custom thresholds: %s", thresholds)

    logger.info("─── Training forecast models ─────────────────────")
    bundle = ForecastBundle.train(df, thresholds=thresholds)

    logger.info("─── Generating forecasts + saving artifacts ──────")
    bundle.save(args.output_dir)

    logger.info("─── Summary ──────────────────────────────────────")
    for site_id, m in bundle.site_models.items():
        default_thr = DEFAULT_THRESHOLDS.get(m.site_name, DEFAULT_THRESHOLDS["_global"])
        effective   = thresholds.get(m.site_name, default_thr)
        logger.info(
            "  Site %d  %-30s  training_rows=%d  threshold=%.2f m  coastal=%s",
            site_id, m.site_name, m.n_train, effective, m.is_coastal,
        )
    logger.info(
        "Models → %s",
        ", ".join(f"forecast_{sid}.pkl" for sid in bundle.site_models),
    )
    logger.info(
        "Forecasts → %s",
        ", ".join(f"forecast_{sid}_24h.json" for sid in bundle.site_models),
    )


if __name__ == "__main__":
    main()
