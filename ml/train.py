#!/usr/bin/env python3
"""
Train the Isolation Forest anomaly detector from CSV files.

Usage:
    python train.py                                 # uses ml/data/all_readings.csv
    python train.py --data path/to/readings.csv
    python train.py --data dir/                     # loads *.csv from directory
    python train.py --no-eval                       # skip evaluation step

Output:
    ml/models/anomaly_detector.pkl

The CSV must contain columns:
    site_id, site_name, water_level_m, flow_rate_lpm, pump_pressure_bar,
    turbidity_ntu, conductivity_us_cm, is_anomaly
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

# Allow running from the ml/ directory without installing the package
sys.path.insert(0, str(Path(__file__).parent))

from anomaly_detection.pipeline import FEATURES, AnomalyDetectorBundle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_DATA = Path(__file__).parent / "data" / "all_readings.csv"
DEFAULT_MODEL = Path(__file__).parent / "models" / "anomaly_detector.pkl"

REQUIRED_COLS = {"site_name", "is_anomaly"} | set(FEATURES)


# ── Data loading ──────────────────────────────────────────────────────────────

def load_data(source: Path) -> pd.DataFrame:
    if source.is_dir():
        parts = [pd.read_csv(f) for f in sorted(source.glob("*.csv"))
                 if f.name != "all_readings.csv"]
        if not parts:
            raise FileNotFoundError(f"No CSV files found in {source}")
        df = pd.concat(parts, ignore_index=True)
        logger.info("Loaded %d rows from %d files in %s", len(df), len(parts), source)
    else:
        df = pd.read_csv(source)
        logger.info("Loaded %d rows from %s", len(df), source)

    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}")

    # Synthetic CSVs use boolean strings; normalise
    df["is_anomaly"] = df["is_anomaly"].astype(str).str.strip().str.lower().isin(
        {"true", "1", "yes"}
    )

    # Synthesise integer site_ids from site_name if not present or not numeric
    if "site_id" not in df.columns or df["site_id"].dtype == object:
        mapping = {n: i + 1 for i, n in enumerate(sorted(df["site_name"].unique()))}
        df["site_id"] = df["site_name"].map(mapping)
        logger.info("Assigned site_ids: %s", mapping)

    df["site_id"] = df["site_id"].astype(int)
    return df


# ── Training ──────────────────────────────────────────────────────────────────

def train(df: pd.DataFrame) -> AnomalyDetectorBundle:
    logger.info("─── Training ────────────────────────────────────")
    for site_id, site_df in df.groupby("site_id"):
        site_name = site_df["site_name"].iloc[0]
        n_total = len(site_df)
        n_normal = int((~site_df["is_anomaly"]).sum())
        n_anom = n_total - n_normal
        logger.info(
            "  Site %d %-30s  total=%d  normal=%d  anomaly=%d (%.1f%%)",
            site_id, f"({site_name})", n_total, n_normal, n_anom, 100 * n_anom / n_total,
        )

    bundle = AnomalyDetectorBundle.train(df)
    logger.info("Bundle trained (version=%s)", bundle.bundle_version)
    return bundle


# ── Evaluation ────────────────────────────────────────────────────────────────

def evaluate(bundle: AnomalyDetectorBundle, df: pd.DataFrame) -> None:
    logger.info("─── Evaluation ──────────────────────────────────")
    report = bundle.evaluate_all(df)

    for site_name, metrics in report.items():
        if site_name == "aggregate":
            continue
        logger.info(
            "  %-34s  P=%.3f  R=%.3f  F1=%.3f  AUC=%.3f  (TP=%d FN=%d FP=%d)",
            site_name,
            metrics["precision"], metrics["recall"],
            metrics["f1"],        metrics["roc_auc"],
            metrics["tp"],        metrics["fn"],        metrics["fp"],
        )

    agg = report["aggregate"]
    logger.info(
        "  %-34s  P=%.3f  R=%.3f  F1=%.3f  (n=%d, anomalies=%d)",
        "AGGREGATE",
        agg["precision"], agg["recall"], agg["f1"],
        agg["total_samples"], agg["total_anomalies"],
    )

    # Severity distribution on true anomalies
    logger.info("─── Severity distribution (true anomalies) ──────")
    anom_df = df[df["is_anomaly"]]
    counts: dict[str, int] = {"low": 0, "medium": 0, "critical": 0, "normal": 0}
    for site_id, site_df in anom_df.groupby("site_id"):
        model = bundle.site_models.get(int(site_id), bundle.fallback)
        for _, row in site_df.iterrows():
            result = model.predict(row[FEATURES].to_dict())
            counts[result["severity"]] += 1

    total = sum(counts.values())
    for sev, n in counts.items():
        pct = 100 * n / total if total else 0
        logger.info("    %-10s %5d  (%5.1f%%)", sev, n, pct)


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train groundwater anomaly detector")
    p.add_argument("--data",    type=Path, default=DEFAULT_DATA,
                   help="CSV file or directory of CSV files")
    p.add_argument("--output",  type=Path, default=DEFAULT_MODEL,
                   help="Output model path (.pkl)")
    p.add_argument("--no-eval", action="store_true",
                   help="Skip evaluation after training")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not args.data.exists():
        logger.error("Data not found: %s", args.data)
        logger.error("Run ml/generate_sample_data.py first to create training data.")
        sys.exit(1)

    df = load_data(args.data)
    bundle = train(df)

    if not args.no_eval:
        evaluate(bundle, df)

    bundle.save(args.output)
    logger.info("─────────────────────────────────────────────────")
    logger.info("Model saved → %s", args.output)
    logger.info(
        "Sites: %s",
        ", ".join(f"{sid}={m.site_name}" for sid, m in bundle.site_models.items()),
    )


if __name__ == "__main__":
    main()
