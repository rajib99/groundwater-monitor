from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.sensor import Sensor, SensorReading

router = APIRouter(prefix="/readings", tags=["readings"])


class ReadingCreate(BaseModel):
    sensor_id: int
    timestamp: datetime
    water_level_m: float
    temperature_c: float | None = None
    conductivity_us: float | None = None
    ph: float | None = None


class ReadingResponse(BaseModel):
    id: int
    sensor_id: int
    timestamp: datetime
    water_level_m: float
    temperature_c: float | None
    conductivity_us: float | None
    ph: float | None

    model_config = {"from_attributes": True}


@router.post("/", response_model=ReadingResponse, status_code=201)
async def ingest_reading(payload: ReadingCreate, db: AsyncSession = Depends(get_db)):
    sensor = await db.get(Sensor, payload.sensor_id)
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")
    reading = SensorReading(**payload.model_dump())
    db.add(reading)
    await db.commit()
    await db.refresh(reading)
    return reading


@router.get("/{sensor_id}", response_model=list[ReadingResponse])
async def get_readings(
    sensor_id: int,
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    limit: int = Query(500, le=5000),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(SensorReading)
        .where(SensorReading.sensor_id == sensor_id)
        .order_by(SensorReading.timestamp.desc())
        .limit(limit)
    )
    if start:
        stmt = stmt.where(SensorReading.timestamp >= start)
    if end:
        stmt = stmt.where(SensorReading.timestamp <= end)
    result = await db.execute(stmt)
    return result.scalars().all()
