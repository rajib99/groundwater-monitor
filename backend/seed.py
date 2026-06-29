#!/usr/bin/env python3
"""
Database seed script — inserts the default UAE construction sites on first run.

Usage (run after `alembic upgrade head`):
    python seed.py

The script is idempotent: it checks row count before inserting and exits
without changes when the table is already populated.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logging.basicConfig(level=logging.INFO, format="[seed] %(message)s")
log = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    sys.exit("ERROR: DATABASE_URL environment variable is not set")

# ── Site definitions ──────────────────────────────────────────────────────────
# Keep in sync with ml/live_feed_simulator.py SITES profiles so the simulator
# can immediately start posting readings for every seeded site.
SITES: list[dict] = [
    {
        "name":      "Dubai Marina Excavation",
        "location":  "Dubai Marina, Dubai, UAE",
        "latitude":  25.0797,
        "longitude": 55.1405,
    },
    {
        "name":      "Abu Dhabi Tunnel",
        "location":  "Downtown Abu Dhabi, UAE",
        "latitude":  24.4539,
        "longitude": 54.3773,
    },
    {
        "name":      "Yas Island Construction",
        "location":  "Yas Island, Abu Dhabi, UAE",
        "latitude":  24.4672,
        "longitude": 54.6031,
    },
    {
        "name":      "Sharjah Industrial Zone",
        "location":  "Industrial Area 18, Sharjah, UAE",
        "latitude":  25.3211,
        "longitude": 55.3913,
    },
]


async def seed() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    try:
        async with engine.begin() as conn:
            count: int = (
                await conn.execute(text("SELECT COUNT(*) FROM sites"))
            ).scalar_one()

            if count > 0:
                log.info("%d site(s) already exist — skipping seed", count)
                return

            for site in SITES:
                await conn.execute(
                    text(
                        "INSERT INTO sites (name, location, latitude, longitude) "
                        "VALUES (:name, :location, :latitude, :longitude) "
                        "ON CONFLICT (name) DO NOTHING"
                    ),
                    site,
                )

            log.info("Inserted %d sites successfully", len(SITES))

            for row in (await conn.execute(text("SELECT id, name FROM sites ORDER BY id"))).all():
                log.info("  site_id=%-3d  %s", row[0], row[1])
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
