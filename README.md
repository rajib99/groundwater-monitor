# Groundwater Monitor

Real-time groundwater level monitoring for construction sites — time-series storage, anomaly detection, 24-hour forecasting, AI-generated summaries, and PDF reporting.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Browser / Client                           │
└───────────────┬─────────────────────────────────────┬───────────────┘
                │ HTTPS / WSS                          │
                ▼                                      ▼
┌──────────────────────────┐               ┌───────────────────────────┐
│      Nginx (port 443)    │               │   Next.js Frontend        │
│  • TLS termination       │──/api, /ws──▶ │   (port 3000 internal)    │
│  • rate limiting         │◀─────────────│   SWR + WebSocket hooks   │
│  • static asset caching  │               └───────────────────────────┘
└─────────────┬────────────┘
              │
              ▼
┌──────────────────────────┐
│   FastAPI Backend         │
│   (port 8000 internal)   │
│                          │
│  /api/sites/*            │
│  /api/ingest             │
│  /api/dashboard/summary  │
│  /api/ml/*               │
│  /ws/live-feed           │
└────┬──────────┬──────────┘
     │          │
     ▼          ▼
┌─────────┐  ┌────────────────┐
│ Redis 7 │  │ TimescaleDB    │
│ • cache │  │ (PostgreSQL 16 │
│ • rate  │  │  + hypertable  │
│   limit │  │  extension)    │
└─────────┘  └────────────────┘

Supporting services:
  Simulator  — injects synthetic readings every 30s (development)
  ML worker  — anomaly detection + Prophet forecasting (on-demand)
  Certbot    — SSL certificate renewal (production)
```

## Quick Start

```bash
git clone https://github.com/your-org/groundwater-monitor.git
cd groundwater-monitor

cp .env.example .env
# Edit .env — at minimum set POSTGRES_PASSWORD and SECRET_KEY:
#   SECRET_KEY=$(openssl rand -hex 32)

docker compose up --build
```

The stack starts in order automatically:

1. **postgres + redis** become healthy
2. **migrate** runs Alembic migrations
3. **seed** inserts 4 default UAE construction sites (no-op if already populated)
4. **backend** starts and passes its health check
5. **frontend** and **simulator** start

| Service | URL |
|---------|-----|
| Dashboard | http://localhost:3000 |
| API | http://localhost:8000 |
| Interactive API docs | http://localhost:8000/docs |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `POSTGRES_DB` | Yes | Database name |
| `POSTGRES_USER` | Yes | PostgreSQL user |
| `POSTGRES_PASSWORD` | Yes | PostgreSQL password |
| `SECRET_KEY` | Yes | App secret (`openssl rand -hex 32`) |
| `ANTHROPIC_API_KEY` | No | Enables AI summaries and report executive paragraphs |
| `API_KEYS` | No | Comma-separated API keys; leave empty to disable auth |
| `DOMAIN` | Prod only | FQDN for Nginx SSL config |
| `REGISTRY` | Prod only | Container registry prefix (e.g. `ghcr.io/your-org`) |
| `IMAGE_TAG` | Prod only | Image tag; CI sets this to the git commit SHA |

## API Reference

All `/api/*` endpoints require `X-API-Key: <key>` when `API_KEYS` is set. WebSocket accepts the key as `?api_key=<key>`.

### Sites

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/sites/` | List all monitoring sites |
| `GET` | `/api/sites/{id}/readings` | Paginated readings (`?start=`, `?end=`, `?page=`, `?page_size=`) |
| `GET` | `/api/sites/{id}/latest` | Most recent sensor reading |
| `GET` | `/api/sites/{id}/alerts` | Alert history (`?limit=`) |
| `GET` | `/api/sites/{id}/health` | Latest pump health score (0–100) |
| `GET` | `/api/sites/{id}/forecast` | 24-hour water level forecast with breach risk |
| `GET` | `/api/sites/{id}/ai-summary` | Claude-generated plain-English site summary |

### Reports

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/sites/{id}/report` | Generate PDF report for a date range |
| `GET` | `/api/sites/{id}/report/{filename}` | Download a generated PDF |

**Report request body:**
```json
{
  "start_date": "2025-06-01",
  "end_date":   "2025-06-30"
}
```

### Dashboard

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/dashboard/summary` | All-sites overview: latest readings, health, active alerts |

### Ingest

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/ingest` | Submit a sensor reading (rate-limited: 10 req/s per site) |

**Ingest request body:**
```json
{
  "site_id":            1,
  "timestamp":          "2025-06-29T12:00:00Z",
  "water_level_m":      3.45,
  "flow_rate_lpm":      12.1,
  "pump_pressure_bar":  2.8,
  "turbidity_ntu":      1.2,
  "conductivity_us_cm": 480.0,
  "temperature_c":      24.5
}
```

### ML

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/ml/detect-anomaly` | Score a single reading for anomalies |
| `GET` | `/api/ml/model-info` | Loaded model metadata |

### WebSocket

```
ws://localhost:8000/ws/live-feed
ws://localhost:8000/ws/live-feed?site_id=1        # single-site subscription
ws://localhost:8000/ws/live-feed?api_key=<key>    # with auth
```

On connect the server sends a `connected` event. Every ingested reading triggers a `reading` broadcast. Send `ping` to receive `pong`.

### Health

```
GET /health   →  200 OK  (unauthenticated)
```
Returns `503` when database or Redis is unreachable.

## Adding a New Site

### Option A — seed script (persistent across rebuilds)

Edit `backend/seed.py` and add a row to the `SITES` list:

```python
SITES = [
    # existing sites …
    {
        "name": "Fujairah Coastal Tunnel",
        "location": "Fujairah, UAE",
        "latitude": 25.1288,
        "longitude": 56.3265,
        "water_level_threshold_m": 4.5,
    },
]
```

Then rerun the seed container (it is idempotent — existing sites are skipped):

```bash
docker compose run --rm seed
```

### Option B — API call

```bash
curl -X POST http://localhost:8000/api/sites/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{
    "name": "Fujairah Coastal Tunnel",
    "location": "Fujairah, UAE",
    "latitude": 25.1288,
    "longitude": 56.3265,
    "water_level_threshold_m": 4.5
  }'
```

## Production Deployment

The repository ships a `docker-compose.prod.yml` that uses pre-built images from a container registry. A GitHub Actions workflow (`.github/workflows/deploy.yml`) builds and pushes all images on every push to `main`, then SSHs into the Hetzner VPS to deploy.

```bash
# First deploy (on the VPS)
cp .env.example .env   # fill in all production values
docker compose -f docker-compose.prod.yml up -d --build

# SSL — obtain a certificate (Nginx must be running first)
docker compose -f docker-compose.prod.yml run --rm certbot \
  certonly --webroot -w /var/www/certbot \
  -d monitor.example.com --email ops@example.com --agree-tos
docker compose -f docker-compose.prod.yml restart nginx
```

Subsequent deploys are handled automatically by the CI/CD pipeline.

## Running the ML Worker

The ML worker (anomaly detection training + Prophet forecasting) runs on demand:

```bash
docker compose run --rm ml
```

Trained models are stored in the `ml_models` Docker volume and loaded by the backend at startup.

## Project Structure

```
groundwater-monitor/
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI app + CORS + health
│   │   ├── config.py           # Pydantic settings
│   │   ├── models/             # SQLAlchemy ORM models
│   │   ├── routers/            # Route handlers
│   │   ├── services/           # AI summary, report generation
│   │   └── dependencies/       # Auth (API key verification)
│   ├── alembic/                # DB migrations
│   └── seed.py                 # Site seeding script
├── frontend/
│   └── src/
│       ├── app/                # Next.js App Router pages
│       ├── components/         # UI components
│       └── lib/                # SWR hooks, WebSocket hook, API types
├── ml/
│   └── scripts/
│       ├── analyze.py          # Anomaly detection (Isolation Forest)
│       └── forecast.py         # Prophet time-series forecasting
├── nginx/
│   ├── nginx.conf              # Rate-limit zones, upstream keepalive
│   └── templates/              # Envsubst Nginx config template
├── docker/
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   ├── Dockerfile.ml
│   └── Dockerfile.simulator
├── .github/workflows/
│   └── deploy.yml              # Build → push → SSH deploy pipeline
├── docker-compose.yml          # Local development stack
├── docker-compose.prod.yml     # Production stack (image-based)
└── .env.example
```
