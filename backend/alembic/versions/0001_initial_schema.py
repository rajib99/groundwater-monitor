"""Initial schema: sites, sensor_readings (hypertable), alerts, pump_health_scores

Revision ID: 0001
Revises:
Create Date: 2026-06-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # sites
    # ------------------------------------------------------------------
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # ------------------------------------------------------------------
    # sensor_readings — will be converted to a TimescaleDB hypertable.
    # Composite PK (site_id, timestamp) is required because TimescaleDB
    # demands the partition column appear in every unique constraint.
    # ------------------------------------------------------------------
    op.create_table(
        "sensor_readings",
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("water_level_m", sa.Float(), nullable=False),
        sa.Column("flow_rate_lpm", sa.Float(), nullable=True),
        sa.Column("pump_pressure_bar", sa.Float(), nullable=True),
        sa.Column("turbidity_ntu", sa.Float(), nullable=True),
        sa.Column("conductivity_us_cm", sa.Float(), nullable=True),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("site_id", "timestamp"),
    )

    op.create_index("ix_sensor_readings_site_id", "sensor_readings", ["site_id"])

    # Partition sensor_readings by timestamp into 7-day chunks.
    # if_not_exists guards against re-running on an already-migrated DB.
    op.execute(
        "SELECT create_hypertable("
        "  'sensor_readings', 'timestamp',"
        "  chunk_time_interval => INTERVAL '7 days',"
        "  if_not_exists => TRUE"
        ")"
    )

    # ------------------------------------------------------------------
    # alerts
    # ------------------------------------------------------------------
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "triggered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_alerts_site_id", "alerts", ["site_id"])
    op.create_index("ix_alerts_triggered_at", "alerts", ["triggered_at"])

    # ------------------------------------------------------------------
    # pump_health_scores
    # ------------------------------------------------------------------
    op.create_table(
        "pump_health_scores",
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "contributing_factors",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("site_id", "timestamp"),
    )

    op.create_index("ix_pump_health_scores_site_id", "pump_health_scores", ["site_id"])


def downgrade() -> None:
    op.drop_index("ix_pump_health_scores_site_id", table_name="pump_health_scores")
    op.drop_table("pump_health_scores")

    op.drop_index("ix_alerts_triggered_at", table_name="alerts")
    op.drop_index("ix_alerts_site_id", table_name="alerts")
    op.drop_table("alerts")

    # DROP TABLE handles hypertable cleanup automatically in TimescaleDB.
    op.drop_index("ix_sensor_readings_site_id", table_name="sensor_readings")
    op.drop_table("sensor_readings")

    op.drop_table("sites")
