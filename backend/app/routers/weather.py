"""Weather and rainfall API routes."""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    RainfallActualHourly,
    RainfallActualRevision,
    RainfallForecastHourly,
    WeatherStation,
)
from app.schemas import (
    RainfallActualRevisionResponse,
    RainfallHourlyResponse,
    RainfallStationResponse,
    RainfallSummary,
)
from app.services.auth import get_current_user
from app.services.weather import build_rainfall_summary, utcnow_naive

router = APIRouter(prefix="/weather/rainfall", tags=["weather"])


def _normalize_query_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _actual_history_response(row: RainfallActualHourly) -> dict:
    return {
        "station_id": row.station_id,
        "data_type": "actual",
        "hour_time": row.hour_time,
        "rainfall_mm": row.rainfall_mm,
        "batch_time": row.hour_time,
        "forecast_issued_at": None,
        "source_endpoint": row.source_endpoint,
        "raw_time_label": row.raw_time_label,
        "source_updated_at": row.source_updated_at,
    }


def _forecast_history_response(row: RainfallForecastHourly) -> dict:
    return {
        "station_id": row.station_id,
        "data_type": "forecast",
        "hour_time": row.hour_time,
        "rainfall_mm": row.rainfall_mm,
        "batch_time": row.batch_time,
        "forecast_issued_at": row.forecast_issued_at,
        "source_endpoint": row.source_endpoint,
        "raw_time_label": row.raw_time_label,
        "source_updated_at": row.source_updated_at,
    }


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

    rows: list[dict] = []
    if data_type in (None, "actual"):
        actual_query = select(RainfallActualHourly).where(
            RainfallActualHourly.hour_time >= start_time,
            RainfallActualHourly.hour_time <= end_time,
        )
        if station_id:
            actual_query = actual_query.where(RainfallActualHourly.station_id == station_id)
        actual_query = actual_query.order_by(
            RainfallActualHourly.station_id,
            RainfallActualHourly.hour_time,
        ).limit(limit)
        actual_result = await db.execute(actual_query)
        rows.extend(_actual_history_response(row) for row in actual_result.scalars().all())

    if data_type in (None, "forecast"):
        forecast_query = select(RainfallForecastHourly).where(
            RainfallForecastHourly.hour_time >= start_time,
            RainfallForecastHourly.hour_time <= end_time,
        )
        if station_id:
            forecast_query = forecast_query.where(RainfallForecastHourly.station_id == station_id)
        forecast_query = forecast_query.order_by(
            RainfallForecastHourly.station_id,
            RainfallForecastHourly.hour_time,
        ).limit(limit)
        forecast_result = await db.execute(forecast_query)
        rows.extend(_forecast_history_response(row) for row in forecast_result.scalars().all())

    rows.sort(key=lambda item: (item["station_id"], item["data_type"], item["hour_time"]))
    return rows[:limit]


@router.get("/revisions", response_model=List[RainfallActualRevisionResponse])
async def get_rainfall_revisions(
    station_id: Optional[str] = Query(default=None, max_length=50),
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    hours: int = Query(default=24 * 7, ge=1, le=24 * 90),
    limit: int = Query(default=1000, ge=1, le=5000),
    _: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return actual rainfall value changes detected after initial ingest."""
    if end_time is None:
        end_time = utcnow_naive()
    else:
        end_time = _normalize_query_time(end_time)
    if start_time is None:
        start_time = end_time - timedelta(hours=hours)
    else:
        start_time = _normalize_query_time(start_time)

    query = select(RainfallActualRevision).where(
        RainfallActualRevision.detected_at >= start_time,
        RainfallActualRevision.detected_at <= end_time,
    )
    if station_id:
        query = query.where(RainfallActualRevision.station_id == station_id)

    query = query.order_by(
        RainfallActualRevision.detected_at.desc(),
        RainfallActualRevision.station_id,
        RainfallActualRevision.hour_time,
    ).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()
