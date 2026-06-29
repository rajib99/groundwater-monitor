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
COPY --chown=mluser:mluser scripts/ ./scripts/

RUN mkdir -p /app/models && chown mluser:mluser /app/models

USER mluser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/venv/bin:$PATH"

# Default: run anomaly detection. Override with docker compose run ml python scripts/forecast.py
CMD ["/venv/bin/python", "scripts/analyze.py"]
