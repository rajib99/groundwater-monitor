from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, PrimaryKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SensorReading(Base):
    # TimescaleDB hypertable partitioned by timestamp — created via Alembic migration.
    # Composite PK required: TimescaleDB unique constraints must include the time column.
    __tablename__ = "sensor_readings"
    __table_args__ = (
        PrimaryKeyConstraint("site_id", "timestamp"),
        Index("ix_sensor_readings_site_id", "site_id"),
    )

    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    water_level_m: Mapped[float] = mapped_column(Float, nullable=False)
    flow_rate_lpm: Mapped[float | None] = mapped_column(Float)
    pump_pressure_bar: Mapped[float | None] = mapped_column(Float)
    turbidity_ntu: Mapped[float | None] = mapped_column(Float)
    conductivity_us_cm: Mapped[float | None] = mapped_column(Float)
    temperature_c: Mapped[float | None] = mapped_column(Float)

    site: Mapped["Site"] = relationship(back_populates="readings")
