"""
Water level forecasting using Facebook Prophet.
Outputs a 30-day forecast to stdout and optionally saves a CSV.
"""
import os

import pandas as pd
from prophet import Prophet
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ["DATABASE_URL"]
SENSOR_ID = int(os.getenv("SENSOR_ID", "1"))
FORECAST_DAYS = int(os.getenv("ML_FORECAST_HORIZON_DAYS", "30"))
OUTPUT_PATH = os.getenv("FORECAST_OUTPUT", "/app/models/forecast.csv")


def load_readings(engine, sensor_id: int) -> pd.DataFrame:
    query = text("""
        SELECT timestamp AS ds, water_level_m AS y
        FROM sensor_readings
        WHERE sensor_id = :sensor_id
        ORDER BY timestamp ASC
    """)
    return pd.read_sql(query, engine, params={"sensor_id": sensor_id})


def run_forecast(df: pd.DataFrame, periods: int) -> pd.DataFrame:
    model = Prophet(
        changepoint_prior_scale=0.05,
        seasonality_mode="multiplicative",
        yearly_seasonality=True,
        weekly_seasonality=True,
        daily_seasonality=False,
    )
    model.fit(df)
    future = model.make_future_dataframe(periods=periods, freq="D")
    forecast = model.predict(future)
    return forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]].tail(periods)


def main():
    engine = create_engine(DATABASE_URL)
    df = load_readings(engine, SENSOR_ID)

    if len(df) < 30:
        print(f"Not enough data for sensor {SENSOR_ID} (need ≥30 rows, got {len(df)})")
        return

    print(f"Training forecast on {len(df)} readings for sensor {SENSOR_ID}…")
    forecast = run_forecast(df, FORECAST_DAYS)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    forecast.to_csv(OUTPUT_PATH, index=False)
    print(f"Forecast saved to {OUTPUT_PATH}")
    print(forecast.to_string(index=False))


if __name__ == "__main__":
    main()
