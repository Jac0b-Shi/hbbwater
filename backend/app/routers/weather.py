"""Weather and rainfall API routes."""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import RainfallHourly, WeatherStation
from app.schemas import RainfallHourlyResponse, RainfallStationResponse, RainfallSummary
from app.services.auth import get_current_user
from app.services.weather import build_rainfall_summary, utcnow_naive

router = APIRouter(prefix="/weather/rainfall", tags=["weather"])


def _normalize_query_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@router.get("/stations", response_model=List[RainfallStationResponse])
async def get_rainfall_stations(
    _: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List configured rainfall stations."""
    result = await db.execute(
        select(WeatherStation).order_by(WeatherStation.role.desc(), WeatherStation.station_id)
    )
    return result.scalars().all()


@router.get("/summary", response_model=RainfallSummary)
async def get_rainfall_summary(
    _: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current actual rainfall and latest forecast totals for dashboard views."""
    return await build_rainfall_summary(db)


@router.get("/history", response_model=List[RainfallHourlyResponse])
async def get_rainfall_history(
    station_id: Optional[str] = Query(default=None, max_length=50),
    data_type: Optional[str] = Query(default=None, pattern="^(actual|forecast)$"),
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    hours: int = Query(default=48, ge=1, le=24 * 30),
    limit: int = Query(default=1000, ge=1, le=5000),
    _: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return hourly rainfall records for chart overlays and later agent workflows."""
    if end_time is None:
        end_time = utcnow_naive() + timedelta(hours=24)
    else:
        end_time = _normalize_query_time(end_time)
    if start_time is None:
        start_time = end_time - timedelta(hours=hours)
    else:
        start_time = _normalize_query_time(start_time)

    query = select(RainfallHourly).where(
        RainfallHourly.hour_time >= start_time,
        RainfallHourly.hour_time <= end_time,
    )
    if station_id:
        query = query.where(RainfallHourly.station_id == station_id)
    if data_type:
        query = query.where(RainfallHourly.data_type == data_type)

    query = query.order_by(RainfallHourly.station_id, RainfallHourly.data_type, RainfallHourly.hour_time).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()
