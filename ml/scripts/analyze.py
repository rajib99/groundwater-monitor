"""
Anomaly detection for groundwater sensor readings.
Flags readings that deviate significantly from the rolling mean.
"""
import os

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ["DATABASE_URL"]
SENSOR_ID = int(os.getenv("SENSOR_ID", "1"))
WINDOW_DAYS = int(os.getenv("WINDOW_DAYS", "7"))
Z_THRESHOLD = float(os.getenv("Z_THRESHOLD", "2.5"))


def load_readings(engine, sensor_id: int, days: int) -> pd.DataFrame:
    query = text("""
        SELECT timestamp, water_level_m, temperature_c, ph
        FROM sensor_readings
        WHERE sensor_id = :sensor_id
          AND timestamp >= NOW() - INTERVAL ':days days'
        ORDER BY timestamp ASC
    """)
    return pd.read_sql(query, engine, params={"sensor_id": sensor_id, "days": days})


def detect_anomalies(df: pd.DataFrame, column: str = "water_level_m") -> pd.DataFrame:
    rolling = df[column].rolling(window=24, min_periods=1)
    df["rolling_mean"] = rolling.mean()
    df["rolling_std"] = rolling.std().fillna(1)
    df["z_score"] = (df[column] - df["rolling_mean"]) / df["rolling_std"]
    df["is_anomaly"] = df["z_score"].abs() > Z_THRESHOLD
    return df


def main():
    engine = create_engine(DATABASE_URL)
    df = load_readings(engine, SENSOR_ID, WINDOW_DAYS)

    if df.empty:
        print(f"No readings found for sensor {SENSOR_ID}")
        return

    df = detect_anomalies(df)
    anomalies = df[df["is_anomaly"]]
    print(f"Analysed {len(df)} readings — {len(anomalies)} anomalies detected")
    if not anomalies.empty:
        print(anomalies[["timestamp", "water_level_m", "z_score"]].to_string(index=False))


if __name__ == "__main__":
    main()
