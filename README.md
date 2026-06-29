# Groundwater Monitor

Real-time groundwater level monitoring with time-series storage, anomaly detection, and forecasting.

## Stack

| Layer | Technology |
|-------|-----------|
| Backend API | FastAPI + SQLAlchemy (async) |
| Frontend | Next.js 15 + Tailwind CSS |
| Database | PostgreSQL 16 + TimescaleDB |
| Cache | Redis 7 |
| ML | Prophet (forecasting) + scikit-learn (anomaly detection) |
| Container | Docker + Docker Compose |

## Quick Start

```bash
cp .env.example .env
# Edit .env with your values

docker network create web
docker compose up -d --build
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs

## Project Structure

```
groundwater-monitor/
├── backend/          # FastAPI app
│   └── app/
│       ├── main.py
│       ├── config.py
│       ├── database.py
│       ├── models/   # SQLAlchemy ORM models
│       └── routers/  # API route handlers
├── frontend/         # Next.js app
│   └── src/app/
├── ml/               # Python ML scripts
│   └── scripts/
│       ├── analyze.py    # Anomaly detection
│       └── forecast.py   # Prophet forecasting
├── docker/           # Dockerfiles
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   └── Dockerfile.ml
├── docker-compose.yml
└── .env.example
```

## Running ML Scripts

```bash
# Anomaly detection
docker compose run --rm ml

# Forecasting
docker compose run --rm ml python scripts/forecast.py

# Override sensor
docker compose run --rm -e SENSOR_ID=2 ml
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/v1/sensors` | List sensors |
| POST | `/api/v1/sensors` | Register sensor |
| GET | `/api/v1/sensors/{id}` | Get sensor |
| POST | `/api/v1/readings` | Ingest reading |
| GET | `/api/v1/readings/{sensor_id}` | Query readings |
