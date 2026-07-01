ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS builder
WORKDIR /build
RUN pip install --no-cache-dir uv
COPY requirements.txt .
RUN uv venv /venv && \
    uv pip install --python /venv/bin/python --no-cache -r requirements.txt

FROM python:${PYTHON_VERSION}-slim AS runtime

RUN groupadd --system --gid 1001 mluser && \
    useradd  --system --uid 1001 --gid 1001 --no-create-home mluser

WORKDIR /app
COPY --from=builder /venv /venv
COPY --chown=mluser:mluser scripts/          ./scripts/
COPY --chown=mluser:mluser anomaly_detection/ ./anomaly_detection/
COPY --chown=mluser:mluser forecasting/      ./forecasting/
COPY --chown=mluser:mluser train.py          ./train.py
COPY --chown=mluser:mluser retrain.py        ./retrain.py
COPY --chown=mluser:mluser train_forecast.py ./train_forecast.py
COPY --chown=mluser:mluser retrain_forecast.py ./retrain_forecast.py

RUN mkdir -p /app/models && chown mluser:mluser /app/models

USER mluser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/venv/bin:$PATH" \
    ML_MODEL_PATH=/app/models/anomaly_detector.pkl

# Default: retrain anomaly detector from DB. Override CMD to run other scripts.
CMD ["python", "retrain.py", "--output", "/app/models/anomaly_detector.pkl"]
