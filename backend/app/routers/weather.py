"""Weather and rainfall API routes."""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    RainfallActualHourly,
    RainfallActualRevision,
    RainfallForecastHourly,
    WeatherStation,
)
from app.schemas import (
    RainfallActualRevisionList,
    RainfallHourlyList,
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


def _inclusive_time_range(start_time: datetime, end_time: datetime) -> tuple[datetime, datetime]:
    return (
        start_time - timedelta(microseconds=1),
        end_time + timedelta(microseconds=1),
    )


def _actual_history_response(
    row: RainfallActualHourly,
    station_name: str | None = None,
    revision_count: int = 0,
) -> dict:
    return {
        "station_id": row.station_id,
        "station_name": station_name,
        "data_type": "actual",
        "hour_time": row.hour_time,
        "rainfall_mm": row.rainfall_mm,
        "batch_time": row.hour_time,
        "forecast_issued_at": None,
        "source_endpoint": row.source_endpoint,
        "raw_time_label": row.raw_time_label,
        "source_updated_at": row.source_updated_at,
        "first_seen_at": row.first_seen_at,
        "last_seen_at": row.last_seen_at,
        "revision_count": revision_count,
    }


def _forecast_history_response(row: RainfallForecastHourly, station_name: str | None = None) -> dict:
    return {
        "station_id": row.station_id,
        "station_name": station_name,
        "data_type": "forecast",
        "hour_time": row.hour_time,
        "rainfall_mm": row.rainfall_mm,
        "batch_time": row.batch_time,
        "forecast_issued_at": row.forecast_issued_at,
        "source_endpoint": row.source_endpoint,
        "raw_time_label": row.raw_time_label,
        "source_updated_at": row.source_updated_at,
        "first_seen_at": None,
        "last_seen_at": None,
        "revision_count": 0,
    }


def _revision_response(row: RainfallActualRevision, station_name: str | None = None) -> dict:
    return {
        "station_id": row.station_id,
        "station_name": station_name,
        "hour_time": row.hour_time,
        "old_rainfall_mm": row.old_rainfall_mm,
        "new_rainfall_mm": row.new_rainfall_mm,
        "previous_source_updated_at": row.previous_source_updated_at,
        "source_updated_at": row.source_updated_at,
        "detected_at": row.detected_at,
        "source_endpoint": row.source_endpoint,
        "raw_time_label": row.raw_time_label,
    }


async def _station_name_map(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(select(WeatherStation.station_id, WeatherStation.station_name))
    return {station_id: station_name for station_id, station_name in result.all()}


async def _rainfall_revision_counts(
    db: AsyncSession,
    start_time: datetime,
    end_time: datetime,
    station_id: str | None,
) -> dict[tuple[str, datetime], int]:
    query_start_time, query_end_time = _inclusive_time_range(start_time, end_time)
    query = (
        select(
            RainfallActualRevision.station_id,
            RainfallActualRevision.hour_time,
            func.count().label("revision_count"),
        )
        .where(
            RainfallActualRevision.hour_time >= query_start_time,
            RainfallActualRevision.hour_time <= query_end_time,
        )
        .group_by(RainfallActualRevision.station_id, RainfallActualRevision.hour_time)
    )
    if station_id:
        query = query.where(RainfallActualRevision.station_id == station_id)

    result = await db.execute(query)
    return {
        (row.station_id, row.hour_time): int(row.revision_count or 0)
        for row in result.all()
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


@router.get("/history", response_model=RainfallHourlyList)
async def get_rainfall_history(
    station_id: Optional[str] = Query(default=None, max_length=50),
    data_type: Optional[str] = Query(default=None, pattern="^(actual|forecast)$"),
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    hours: int = Query(default=48, ge=1, le=24 * 30),
    limit: int = Query(default=1000, ge=1, le=5000),
    page: int = Query(default=1, ge=1),
    _: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return hourly rainfall records for chart overlays and later agent workflows."""
    default_end_time = end_time is None
    now = utcnow_naive()
    if end_time is None:
        end_time = now + timedelta(hours=24) if data_type in (None, "forecast") else now
    else:
        end_time = _normalize_query_time(end_time)
    if start_time is None:
        start_time = now if default_end_time and data_type == "forecast" else end_time - timedelta(hours=hours)
    else:
        start_time = _normalize_query_time(start_time)

    query_start_time, query_end_time = _inclusive_time_range(start_time, end_time)
    station_names = await _station_name_map(db)
    revision_counts = await _rainfall_revision_counts(db, start_time, end_time, station_id)

    rows: list[dict] = []
    if data_type in (None, "actual"):
        actual_query = select(RainfallActualHourly).where(
            RainfallActualHourly.hour_time >= query_start_time,
            RainfallActualHourly.hour_time <= query_end_time,
        )
        if station_id:
            actual_query = actual_query.where(RainfallActualHourly.station_id == station_id)
        actual_query = actual_query.order_by(
            RainfallActualHourly.station_id,
            RainfallActualHourly.hour_time,
        )
        actual_result = await db.execute(actual_query)
        rows.extend(
            _actual_history_response(
                row,
                station_names.get(row.station_id),
                revision_counts.get((row.station_id, row.hour_time), 0),
            )
            for row in actual_result.scalars().all()
        )

    if data_type in (None, "forecast"):
        forecast_query = select(RainfallForecastHourly).where(
            RainfallForecastHourly.hour_time >= query_start_time,
            RainfallForecastHourly.hour_time <= query_end_time,
        )
        if station_id:
            forecast_query = forecast_query.where(RainfallForecastHourly.station_id == station_id)
        forecast_query = forecast_query.order_by(
            RainfallForecastHourly.station_id,
            RainfallForecastHourly.hour_time,
        )
        forecast_result = await db.execute(forecast_query)
        rows.extend(
            _forecast_history_response(row, station_names.get(row.station_id))
            for row in forecast_result.scalars().all()
        )

    rows.sort(
        key=lambda item: (
            item["hour_time"],
            item["station_id"],
            item["data_type"] == "actual",
        ),
        reverse=True,
    )
    total = len(rows)
    offset = (page - 1) * limit
    return {
        "items": rows[offset:offset + limit],
        "total": total,
        "page": page,
        "page_size": limit,
    }


@router.get("/revisions", response_model=RainfallActualRevisionList)
async def get_rainfall_revisions(
    station_id: Optional[str] = Query(default=None, max_length=50),
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    hours: int = Query(default=24 * 7, ge=1, le=24 * 90),
    limit: int = Query(default=1000, ge=1, le=5000),
    page: int = Query(default=1, ge=1),
    time_field: str = Query(default="hour_time", pattern="^(hour_time|detected_at)$"),
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

    query_start_time, query_end_time = _inclusive_time_range(start_time, end_time)
    time_column = (
        RainfallActualRevision.detected_at
        if time_field == "detected_at"
        else RainfallActualRevision.hour_time
    )
    query = select(RainfallActualRevision).where(
        time_column >= query_start_time,
        time_column <= query_end_time,
    )
    if station_id:
        query = query.where(RainfallActualRevision.station_id == station_id)

    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)
    offset = (page - 1) * limit
    query = query.order_by(
        RainfallActualRevision.detected_at.desc(),
        RainfallActualRevision.station_id,
        RainfallActualRevision.hour_time,
    ).offset(offset).limit(limit)
    result = await db.execute(query)
    station_names = await _station_name_map(db)
    return {
        "items": [
            _revision_response(row, station_names.get(row.station_id))
            for row in result.scalars().all()
        ],
        "total": int(total or 0),
        "page": page,
        "page_size": limit,
    }
