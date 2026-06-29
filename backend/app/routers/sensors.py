from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.sensor import Sensor

router = APIRouter(prefix="/sensors", tags=["sensors"])


class SensorCreate(BaseModel):
    name: str
    location: str
    latitude: float | None = None
    longitude: float | None = None
    description: str | None = None


class SensorResponse(BaseModel):
    id: int
    name: str
    location: str
    latitude: float | None
    longitude: float | None
    description: str | None

    model_config = {"from_attributes": True}


@router.get("/", response_model=list[SensorResponse])
async def list_sensors(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Sensor))
    return result.scalars().all()


@router.get("/{sensor_id}", response_model=SensorResponse)
async def get_sensor(sensor_id: int, db: AsyncSession = Depends(get_db)):
    sensor = await db.get(Sensor, sensor_id)
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")
    return sensor


@router.post("/", response_model=SensorResponse, status_code=201)
async def create_sensor(payload: SensorCreate, db: AsyncSession = Depends(get_db)):
    sensor = Sensor(**payload.model_dump())
    db.add(sensor)
    await db.commit()
    await db.refresh(sensor)
    return sensor


@router.delete("/{sensor_id}", status_code=204)
async def delete_sensor(sensor_id: int, db: AsyncSession = Depends(get_db)):
    sensor = await db.get(Sensor, sensor_id)
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")
    await db.delete(sensor)
    await db.commit()
