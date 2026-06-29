#!/usr/bin/env bash
# first-deploy.sh — run once on the VPS to bootstrap the production stack.
#
# Usage:
#   1. Copy repo to /opt/groundwater-monitor on the VPS
#   2. Copy .env.example to .env and fill in all required values
#   3. chmod +x scripts/first-deploy.sh && ./scripts/first-deploy.sh
#
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="docker compose -f $DEPLOY_DIR/docker-compose.prod.yml"

echo "==> Working directory: $DEPLOY_DIR"
cd "$DEPLOY_DIR"

# ── Validate .env ─────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example and fill in all values."
  exit 1
fi

# Source .env to read DOMAIN and CERTBOT_EMAIL
set -a; source .env; set +a

: "${DOMAIN:?DOMAIN must be set in .env}"
: "${CERTBOT_EMAIL:?CERTBOT_EMAIL must be set in .env}"

# ── Prerequisite: Docker + Compose ───────────────────────────────────────────
command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker not installed."; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: docker compose plugin not found."; exit 1; }

# ── Create the external 'web' network if used by other services ───────────────
# (Not required for prod compose which uses gwm_net internally)

# ── Pull all images ───────────────────────────────────────────────────────────
echo "==> Pulling images"
$COMPOSE pull --quiet

# ── Start Nginx + Postgres + Redis first (no SSL yet) ─────────────────────────
echo "==> Starting infrastructure services"
$COMPOSE up -d postgres redis

echo "==> Waiting for Postgres to be healthy..."
until docker inspect --format='{{.State.Health.Status}}' gwm-postgres 2>/dev/null | grep -q healthy; do
  sleep 3
done

# ── Run database migrations ───────────────────────────────────────────────────
echo "==> Running database migrations"
$COMPOSE run --rm migrate

# ── Start Nginx in HTTP-only mode for certbot ACME challenge ──────────────────
echo "==> Starting Nginx (HTTP-only for certificate issuance)"
$COMPOSE up -d nginx

echo "==> Waiting for Nginx to start..."
sleep 5

# ── Obtain TLS certificate ────────────────────────────────────────────────────
echo "==> Requesting TLS certificate for $DOMAIN"
$COMPOSE run --rm certbot certonly \
  --webroot \
  --webroot-path /var/www/certbot \
  --email "$CERTBOT_EMAIL" \
  --agree-tos \
  --no-eff-email \
  -d "$DOMAIN"

# ── Reload Nginx to pick up the new certificate ───────────────────────────────
echo "==> Reloading Nginx with TLS enabled"
docker exec gwm-nginx nginx -s reload

# ── Start remaining services ──────────────────────────────────────────────────
echo "==> Starting all services"
$COMPOSE up -d --wait --wait-timeout 120

# ── Final health check ────────────────────────────────────────────────────────
echo ""
echo "==> Service status:"
$COMPOSE ps

echo ""
echo "==> Health:"
docker inspect --format='  {{.Name}}: {{.State.Health.Status}}' \
  gwm-backend gwm-frontend gwm-nginx gwm-postgres gwm-redis 2>/dev/null || true

echo ""
echo "==> First deploy complete. Site should be live at https://${DOMAIN}"
echo ""
echo "    Next steps:"
echo "    • Set up the GitHub Actions secrets (see DEPLOY.md)"
echo "    • Run ML training when you have enough data:"
echo "      docker compose -f docker-compose.prod.yml --profile ml-train run --rm ml-train"
