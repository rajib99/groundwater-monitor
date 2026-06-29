"""
Isolation Forest anomaly detection pipeline for groundwater sensor readings.

Architecture
────────────
One IsolationForest + StandardScaler is trained *per site* on that site's
normal (is_anomaly=False) data only — semi-supervised so the model learns
exactly what healthy looks like for each site's baseline.

A "global" fallback model is also trained on all normal data across sites
for readings whose site is unknown or new.

Severity thresholds are calibrated from the empirical distribution of known
anomaly scores:
  score ≥ boundary          → normal
  P35 ≤ score < boundary    → low
  P10 ≤ score < P35         → medium
  score < P10               → critical

where score = IsolationForest.score_samples() (lower = more anomalous).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

# ── Feature set ───────────────────────────────────────────────────────────────

FEATURES: list[str] = [
    "water_level_m",
    "flow_rate_lpm",
    "pump_pressure_bar",
    "turbidity_ntu",
    "conductivity_us_cm",
]

# IsolationForest hyper-parameters
_N_ESTIMATORS = 200
_MAX_SAMPLES = "auto"
_CONTAMINATION = 0.02   # expected FPR on clean training data (~2 %)
_RANDOM_STATE = 42


# ── Per-site model ────────────────────────────────────────────────────────────

@dataclass
class SiteModel:
    site_name: str
    scaler: StandardScaler
    iso_forest: IsolationForest
    thresholds: dict[str, float]         # {"boundary", "medium", "critical"}
    zscore_thresholds: dict[str, float]  # per-feature: 1.5 × P99.5 of |z| in normal data
    n_train: int
    n_anomaly_labeled: int
    trained_at: str                       # ISO-8601

    # ── Scoring ───────────────────────────────────────────────────────────────

    def score_samples(self, X_raw: np.ndarray) -> np.ndarray:
        """Return raw IsolationForest scores (lower = more anomalous)."""
        return self.iso_forest.score_samples(self.scaler.transform(X_raw))

    def predict(self, reading: dict[str, Any]) -> dict[str, Any]:
        """
        Hybrid anomaly assessment:
          1. Isolation Forest  — catches correlated multi-feature anomalies.
          2. Per-feature Z-score — catches single-sensor spikes the IF may miss
             (e.g. pure conductivity intrusion, pressure blockage).

        Final score = max(IF normalised score, Z-score normalised score).
        Missing features are imputed with the training-set mean.
        """
        x_df = pd.DataFrame(
            [[reading.get(f, float(self.scaler.mean_[i])) for i, f in enumerate(FEATURES)]],
            columns=FEATURES,
        )
        x_scaled = self.scaler.transform(x_df)[0]

        # ── Isolation Forest signal ───────────────────────────────────────────
        raw_if = float(self.iso_forest.score_samples(x_scaled.reshape(1, -1))[0])
        if_anomaly   = bool(self.iso_forest.predict(x_scaled.reshape(1, -1))[0] == -1)
        if_score     = self._if_normalize(raw_if)

        # ── Per-feature Z-score signal ────────────────────────────────────────
        abs_z = {f: float(abs(x_scaled[i])) for i, f in enumerate(FEATURES)}
        # Normalise each feature's z against its calibrated threshold
        z_excess = {
            f: max(0.0, (abs_z[f] - self.zscore_thresholds[f]) / self.zscore_thresholds[f])
            for f in FEATURES
        }
        z_score_norm = round(min(1.0, max(z_excess.values())), 4)
        z_anomaly    = z_score_norm > 0.0

        # ── Combine ───────────────────────────────────────────────────────────
        is_anomaly    = if_anomaly or z_anomaly
        anomaly_score = round(max(if_score, z_score_norm), 4)
        severity      = self._severity(anomaly_score, is_anomaly)

        # Contributions: each feature's z-score relative to its threshold
        contributions = {
            f: round(min(1.0, abs_z[f] / self.zscore_thresholds[f]), 4)
            for f in FEATURES
        }

        return {
            "is_anomaly": is_anomaly,
            "anomaly_score": anomaly_score,
            "severity": severity,
            "contributing_features": contributions,
            "detectors": {
                "isolation_forest": {"triggered": if_anomaly, "score": round(if_score, 4)},
                "zscore":           {"triggered": z_anomaly,  "score": z_score_norm},
            },
            "site_model_used": self.site_name,
        }

    def _if_normalize(self, raw: float) -> float:
        """Map raw IF score → [0, 1]  (0 = normal, 1 = maximally anomalous)."""
        boundary = self.thresholds["boundary"]
        critical = self.thresholds["critical"]
        if raw >= boundary:
            return 0.0
        if raw <= critical:
            return 1.0
        return round((boundary - raw) / (boundary - critical), 4)

    def _severity(self, score: float, is_anomaly: bool) -> str:
        if not is_anomaly:
            return "normal"
        if score >= 0.70:
            return "critical"
        if score >= 0.35:
            return "medium"
        return "low"

    def _contributions(self, x_scaled_row: np.ndarray) -> dict[str, float]:
        abs_z = np.abs(x_scaled_row)
        denom = float(abs_z.max()) if abs_z.max() > 0 else 1.0
        return {f: round(float(abs_z[i]) / denom, 4) for i, f in enumerate(FEATURES)}

    # ── Evaluation ────────────────────────────────────────────────────────────

    def evaluate(self, df_test: pd.DataFrame) -> dict[str, Any]:
        """Compute precision/recall/F1/AUC on a labelled test DataFrame."""
        X = df_test[FEATURES].fillna(pd.Series(self.scaler.mean_, index=FEATURES)).values
        y_true = df_test["is_anomaly"].astype(int).values
        scores = self.iso_forest.score_samples(self.scaler.transform(X))
        y_pred = (scores < self.thresholds["boundary"]).astype(int)

        tp = int(((y_pred == 1) & (y_true == 1)).sum())
        fn = int(((y_pred == 0) & (y_true == 1)).sum())
        fp = int(((y_pred == 1) & (y_true == 0)).sum())

        auc = float(roc_auc_score(y_true, -scores)) if len(np.unique(y_true)) > 1 else float("nan")

        return {
            "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
            "recall":    round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
            "f1":        round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
            "roc_auc":   round(auc, 4),
            "tp": tp, "fn": fn, "fp": fp,
        }


# ── Bundle (all sites + fallback) ─────────────────────────────────────────────

class AnomalyDetectorBundle:
    """
    Container for all per-site models and a global fallback.

    Usage:
        bundle = AnomalyDetectorBundle.train(df)
        bundle.save("models/anomaly_detector.pkl")

        bundle = AnomalyDetectorBundle.load("models/anomaly_detector.pkl")
        result = bundle.score(site_id=1, reading={...})
    """

    def __init__(self) -> None:
        self.site_models:  dict[int, SiteModel] = {}     # site_id → SiteModel
        self.name_to_id:   dict[str, int] = {}
        self.fallback:     SiteModel | None = None
        self.features:     list[str] = FEATURES
        self.bundle_version: str = ""

    # ── Training ──────────────────────────────────────────────────────────────

    @classmethod
    def train(
        cls,
        df: pd.DataFrame,
        site_id_col: str = "site_id",
        site_name_col: str = "site_name",
    ) -> "AnomalyDetectorBundle":
        """
        Train per-site models from a DataFrame that must contain:
          - FEATURES columns
          - `is_anomaly` (bool)
          - `site_id` (int)
          - `site_name` (str)
        """
        bundle = cls()
        bundle.bundle_version = datetime.now(timezone.utc).isoformat()

        # ── Per-site models ──────────────────────────────────────────────────
        for site_id, site_df in df.groupby(site_id_col):
            site_name = site_df[site_name_col].iloc[0]
            model = _train_one_site(int(site_id), site_name, site_df)
            bundle.site_models[int(site_id)] = model
            bundle.name_to_id[site_name] = int(site_id)
            logger.info("Trained model for site %d (%s)", site_id, site_name)

        # ── Global fallback (all sites combined) ─────────────────────────────
        bundle.fallback = _train_one_site(0, "global", df)
        logger.info("Trained global fallback model")

        return bundle

    # ── Inference ─────────────────────────────────────────────────────────────

    def score(
        self,
        reading: dict[str, Any],
        site_id: int | None = None,
        site_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Score a single reading.  Site resolution order:
          1. site_id kwarg
          2. site_name kwarg
          3. reading["site_id"]
          4. global fallback
        """
        resolved_id = (
            site_id
            or (self.name_to_id.get(site_name) if site_name else None)
            or reading.get("site_id")
        )
        model = self.site_models.get(int(resolved_id), self.fallback) if resolved_id else self.fallback

        result = model.predict(reading)
        result["model_version"] = self.bundle_version
        result["features"] = self.features
        return result

    # ── Evaluation ────────────────────────────────────────────────────────────

    def evaluate_all(self, df: pd.DataFrame) -> dict[str, Any]:
        """Return per-site + aggregate evaluation metrics."""
        report: dict[str, Any] = {}
        all_preds, all_true = [], []

        for site_id, site_df in df.groupby("site_id"):
            model = self.site_models.get(int(site_id), self.fallback)
            metrics = model.evaluate(site_df)
            report[model.site_name] = metrics

            X = site_df[FEATURES].fillna(
                pd.Series(model.scaler.mean_, index=FEATURES)
            ).values
            scores = model.iso_forest.score_samples(model.scaler.transform(X))
            all_preds.extend((scores < model.thresholds["boundary"]).astype(int).tolist())
            all_true.extend(site_df["is_anomaly"].astype(int).tolist())

        y_pred = np.array(all_preds)
        y_true = np.array(all_true)
        report["aggregate"] = {
            "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
            "recall":    round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
            "f1":        round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
            "total_samples": int(len(y_true)),
            "total_anomalies": int(y_true.sum()),
        }
        return report

    # ── Persistence ───────────────────────────────────────────────────────────
    #
    # We serialize to a plain dict whose values are sklearn objects (always
    # importable wherever sklearn is installed) rather than pickling the custom
    # dataclasses. This means the backend can load the artifact with only
    # scikit-learn + joblib — no dependency on this `anomaly_detection` module.

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._to_artifact(), p, compress=3)
        logger.info("Saved artifact to %s", p)

    def _to_artifact(self) -> dict:
        def _site_dict(m: SiteModel) -> dict:
            return {
                "site_name":         m.site_name,
                "scaler":            m.scaler,
                "iso_forest":        m.iso_forest,
                "thresholds":        m.thresholds,
                "zscore_thresholds": m.zscore_thresholds,
                "n_train":           m.n_train,
                "n_anomaly_labeled": m.n_anomaly_labeled,
                "trained_at":        m.trained_at,
            }

        return {
            "format":         "groundwater_anomaly_v1",
            "bundle_version": self.bundle_version,
            "features":       self.features,
            "name_to_id":     self.name_to_id,
            "site_models":    {sid: _site_dict(m) for sid, m in self.site_models.items()},
            "fallback":       _site_dict(self.fallback) if self.fallback else None,
        }

    @classmethod
    def load(cls, path: str | Path) -> "AnomalyDetectorBundle":
        artifact = joblib.load(path)
        bundle = cls()
        bundle.bundle_version = artifact["bundle_version"]
        bundle.features       = artifact["features"]
        bundle.name_to_id     = artifact["name_to_id"]
        for sid, d in artifact["site_models"].items():
            bundle.site_models[int(sid)] = SiteModel(**d)
        if artifact.get("fallback"):
            bundle.fallback = SiteModel(**artifact["fallback"])
        logger.info("Loaded bundle from %s (trained %s)", path, bundle.bundle_version)
        return bundle


# ── Internal training helper ──────────────────────────────────────────────────

def _train_one_site(site_id: int, site_name: str, df: pd.DataFrame) -> SiteModel:
    """Fit scaler + IsolationForest on normal data; calibrate thresholds."""
    has_labels = "is_anomaly" in df.columns
    normal_mask = ~df["is_anomaly"].astype(bool) if has_labels else np.ones(len(df), bool)

    X_all = df[FEATURES].copy()
    X_normal = X_all[normal_mask]

    # Impute any NaN with column median (computed on normal data)
    medians = X_normal.median()
    X_all = X_all.fillna(medians)
    X_normal_filled = X_all[normal_mask]

    # Scaler fitted on normal data only
    scaler = StandardScaler()
    scaler.fit(X_normal_filled)

    X_all_scaled = scaler.transform(X_all)
    X_normal_scaled = X_all_scaled[normal_mask]

    # IsolationForest trained on normal data only (semi-supervised)
    iso = IsolationForest(
        n_estimators=_N_ESTIMATORS,
        max_samples=_MAX_SAMPLES,
        contamination=_CONTAMINATION,
        random_state=_RANDOM_STATE,
        n_jobs=-1,
    )
    iso.fit(X_normal_scaled)

    # Calibrate severity thresholds from the known anomaly score distribution
    thresholds = _calibrate(iso, X_all_scaled, df.get("is_anomaly") if has_labels else None)

    n_anom = int(df["is_anomaly"].sum()) if has_labels else 0

    # Per-feature Z-score thresholds: 1.5 × P99.5 of |z| on normal training data,
    # floored at 5.0 so a single rogue reading never sets an absurdly tight threshold.
    per_feature_max_z = np.percentile(np.abs(X_normal_scaled), 99.5, axis=0)
    zscore_thresholds = {
        f: float(max(per_feature_max_z[i] * 1.5, 5.0))
        for i, f in enumerate(FEATURES)
    }

    return SiteModel(
        site_name=site_name,
        scaler=scaler,
        iso_forest=iso,
        thresholds=thresholds,
        zscore_thresholds=zscore_thresholds,
        n_train=int(normal_mask.sum()),
        n_anomaly_labeled=n_anom,
        trained_at=datetime.now(timezone.utc).isoformat(),
    )


def _calibrate(
    iso: IsolationForest,
    X_all_scaled: np.ndarray,
    labels: pd.Series | None,
) -> dict[str, float]:
    """
    Return thresholds dict with keys: boundary, medium, critical.

    boundary  ≈ IsolationForest decision boundary (model.offset_)
    medium    = 35th percentile of anomaly scores (65% of anomalies score above → "low")
    critical  = 10th percentile of anomaly scores (10% of anomalies score below → "critical")
    """
    boundary = float(iso.offset_)

    if labels is not None and labels.astype(bool).any():
        anom_scores = iso.score_samples(X_all_scaled[labels.astype(bool).values])
        medium   = float(np.percentile(anom_scores, 35))
        critical = float(np.percentile(anom_scores, 10))
    else:
        # Fallback without labels: fixed offsets below the boundary
        all_scores = iso.score_samples(X_all_scaled)
        medium   = boundary - 0.04
        critical = float(np.percentile(all_scores, 2))

    # Guard: ensure critical ≤ medium ≤ boundary
    medium   = min(medium,   boundary)
    critical = min(critical, medium)

    return {"boundary": boundary, "medium": medium, "critical": critical}
