from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, PrimaryKeyConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PumpHealthScore(Base):
    __tablename__ = "pump_health_scores"
    __table_args__ = (
        PrimaryKeyConstraint("site_id", "timestamp"),
        Index("ix_pump_health_scores_site_id", "site_id"),
    )

    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    contributing_factors: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    site: Mapped["Site"] = relationship(back_populates="pump_health_scores")
