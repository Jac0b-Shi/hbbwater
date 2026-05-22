"""Rainfall collection and query helpers backed by Shanghai ZhiTianQi."""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import business_session_scope
from app.models import RainfallHourly, WeatherStation
from app.services.schema import DEFAULT_WEATHER_STATIONS

SHANGHAI_TZ = timezone(timedelta(hours=8))
DEFAULT_ZTQ_ENDPOINT = "http://ztq.soweather.com:8096/ztq_sh_jc/service.do"
ZTQ_APP_ID = "com.pcs.ztqsh"
ZTQ_APP_VERSION = "1.3.7"
ZTQ_ANDROID_CODE = "34"


@dataclass(frozen=True)
class WeatherStationConfig:
    station_id: str
    station_name: str
    role: str
    longitude: float
    latitude: float
    is_active: bool = True


@dataclass(frozen=True)
class RainfallPoint:
    station_id: str
    data_type: str
    hour_time: datetime
    rainfall_mm: Decimal
    raw_time_label: str
    forecast_issued_at: datetime | None = None
    source_updated_at: datetime | None = None

    @property
    def batch_time(self) -> datetime:
        return self.forecast_issued_at or self.hour_time


@dataclass(frozen=True)
class StationRainfallPayload:
    station_id: str
    points: list[RainfallPoint]
    source_updated_at: datetime | None
    current_rainfall_mm: Decimal | None
    has_positive_rainfall: bool


@dataclass(frozen=True)
class RainfallCollectionResult:
    collected_at: datetime
    station_count: int
    point_count: int
    has_positive_rainfall: bool


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def utcnow_naive() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


def floor_to_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def local_to_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=SHANGHAI_TZ)
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def utc_naive_to_local(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SHANGHAI_TZ)


def _to_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _build_local_datetime(year: int, month: int, day: int, hour: int) -> datetime:
    return datetime(year, month, day, hour, tzinfo=SHANGHAI_TZ)


def _parse_range_bounds(range_text: str, reference_now: datetime) -> tuple[datetime, datetime] | None:
    match = re.search(
        r"(\d{1,2})月(\d{1,2})日(\d{1,2})时-(\d{1,2})月(\d{1,2})日(\d{1,2})时",
        range_text or "",
    )
    if not match:
        return None

    start_month, start_day, start_hour, end_month, end_day, end_hour = map(int, match.groups())
    year = reference_now.astimezone(SHANGHAI_TZ).year
    start = _build_local_datetime(year, start_month, start_day, start_hour)
    end = _build_local_datetime(year, end_month, end_day, end_hour)
    if end < start:
        end = _build_local_datetime(year + 1, end_month, end_day, end_hour)
    if start > reference_now.astimezone(SHANGHAI_TZ) + timedelta(days=30):
        start = _build_local_datetime(year - 1, start_month, start_day, start_hour)
        end = _build_local_datetime(year - 1, end_month, end_day, end_hour)
        if end < start:
            end = _build_local_datetime(year, end_month, end_day, end_hour)
    return start, end


def _parse_item_hour(label: str, bounds: tuple[datetime, datetime] | None, reference_now: datetime) -> datetime | None:
    match = re.search(r"(?:(\d{1,2})月)?(\d{1,2})日(\d{1,2})时", label or "")
    if not match:
        return None

    explicit_month, day_text, hour_text = match.groups()
    day = int(day_text)
    hour = int(hour_text)
    local_now = reference_now.astimezone(SHANGHAI_TZ)

    candidate_months: list[int]
    if explicit_month:
        candidate_months = [int(explicit_month)]
    elif bounds is not None:
        candidate_months = [bounds[0].month, bounds[1].month]
    else:
        candidate_months = [local_now.month]

    candidates: list[datetime] = []
    for month in dict.fromkeys(candidate_months):
        for year in {local_now.year - 1, local_now.year, local_now.year + 1}:
            try:
                candidates.append(_build_local_datetime(year, month, day, hour))
            except ValueError:
                continue

    if not candidates:
        return None

    if bounds is not None:
        start, end = bounds
        in_range = [candidate for candidate in candidates if start <= candidate <= end]
        if in_range:
            return min(in_range, key=lambda candidate: abs(candidate - local_now))

    return min(candidates, key=lambda candidate: abs(candidate - local_now))


def _parse_source_update_time(value: str | None, reference_now: datetime) -> datetime | None:
    match = re.search(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})", value or "")
    if not match:
        return None
    month, day, hour, minute = map(int, match.groups())
    local_now = reference_now.astimezone(SHANGHAI_TZ)
    try:
        parsed = datetime(local_now.year, month, day, hour, minute, tzinfo=SHANGHAI_TZ)
    except ValueError:
        return None
    if parsed > local_now + timedelta(days=1):
        parsed = parsed.replace(year=parsed.year - 1)
    return local_to_utc_naive(parsed)


def parse_ztq_rainfall_payload(
    station_id: str,
    trend_data: dict[str, Any] | None,
    current_data: dict[str, Any] | None = None,
    *,
    reference_now: datetime | None = None,
) -> StationRainfallPayload:
    """Parse ZhiTianQi actual and forecast hourly rainfall lists."""
    if reference_now is None:
        reference_now = datetime.now(SHANGHAI_TZ)
    elif reference_now.tzinfo is None:
        reference_now = reference_now.replace(tzinfo=timezone.utc).astimezone(SHANGHAI_TZ)

    trend_data = trend_data or {}
    current_data = current_data or {}
    source_updated_at = _parse_source_update_time(current_data.get("upt"), reference_now)
    current_rainfall_mm = (
        _to_decimal(current_data["rainfall"]) if "rainfall" in current_data else None
    )

    points: list[RainfallPoint] = []
    actual_bounds = _parse_range_bounds(str(trend_data.get("sk_time", "")), reference_now)
    forecast_bounds = _parse_range_bounds(str(trend_data.get("yb_time", "")), reference_now)

    for item in trend_data.get("sk_list") or []:
        local_hour = _parse_item_hour(str(item.get("fulldt") or item.get("dt") or ""), actual_bounds, reference_now)
        if local_hour is None:
            continue
        points.append(
            RainfallPoint(
                station_id=station_id,
                data_type="actual",
                hour_time=local_to_utc_naive(local_hour),
                rainfall_mm=_to_decimal(item.get("val")),
                raw_time_label=str(item.get("fulldt") or item.get("dt") or ""),
                source_updated_at=source_updated_at,
            )
        )

    latest_actual_hour = max((point.hour_time for point in points), default=None)
    forecast_issued_at = latest_actual_hour or floor_to_hour(local_to_utc_naive(reference_now))
    for item in trend_data.get("yb_list") or []:
        local_hour = _parse_item_hour(str(item.get("fulldt") or item.get("dt") or ""), forecast_bounds, reference_now)
        if local_hour is None:
            continue
        points.append(
            RainfallPoint(
                station_id=station_id,
                data_type="forecast",
                hour_time=local_to_utc_naive(local_hour),
                rainfall_mm=_to_decimal(item.get("val")),
                raw_time_label=str(item.get("fulldt") or item.get("dt") or ""),
                forecast_issued_at=forecast_issued_at,
                source_updated_at=source_updated_at,
            )
        )

    has_positive_rainfall = any(point.rainfall_mm > 0 for point in points)
    if current_rainfall_mm is not None and current_rainfall_mm > 0:
        has_positive_rainfall = True

    return StationRainfallPayload(
        station_id=station_id,
        points=points,
        source_updated_at=source_updated_at,
        current_rainfall_mm=current_rainfall_mm,
        has_positive_rainfall=has_positive_rainfall,
    )


def get_weather_station_configs() -> list[WeatherStationConfig]:
    configured = os.getenv("ZTQ_RAINFALL_STATIONS", "").strip()
    if configured:
        try:
            data = json.loads(configured)
            return [
                WeatherStationConfig(
                    station_id=str(item["station_id"]),
                    station_name=str(item["station_name"]),
                    role=str(item.get("role") or "primary"),
                    longitude=float(item.get("longitude") or 0),
                    latitude=float(item.get("latitude") or 0),
                    is_active=bool(item.get("is_active", True)),
                )
                for item in data
            ]
        except (TypeError, ValueError, KeyError):
            print(f"[{datetime.utcnow()}] Invalid ZTQ_RAINFALL_STATIONS, using defaults.")

    return [
        WeatherStationConfig(
            station_id=str(item["station_id"]),
            station_name=str(item["station_name"]),
            role=str(item["role"]),
            longitude=float(item["longitude"]),
            latitude=float(item["latitude"]),
        )
        for item in DEFAULT_WEATHER_STATIONS
    ]


class ZtqWeatherClient:
    """Small async client for the ZhiTianQi POST-with-json-form protocol."""

    def __init__(self, *, endpoint: str | None = None, timeout_seconds: float | None = None):
        self.endpoint = endpoint or os.getenv("ZTQ_RAINFALL_ENDPOINT", DEFAULT_ZTQ_ENDPOINT)
        self.timeout_seconds = timeout_seconds or _env_float("ZTQ_RAINFALL_REQUEST_TIMEOUT_SECONDS", 8.0)
        self.pid = os.getenv("ZTQ_RAINFALL_PID", "").strip()
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "ZtqWeatherClient":
        self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError("ZtqWeatherClient must be used as an async context manager")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        response = await self._client.post(self.endpoint, data={"p": encoded})
        response.raise_for_status()
        data = response.json()
        header = data.get("h") or {}
        if header.get("is") not in (0, "0", None):
            raise RuntimeError(header.get("error") or "ZhiTianQi API returned an error")
        return data

    async def ensure_pid(self) -> str:
        if self.pid:
            return self.pid
        payload = {
            "h": {"p": ""},
            "b": {
                "init": {
                    "app": ZTQ_APP_ID,
                    "imei": "",
                    "sv": ZTQ_APP_VERSION,
                    "xh": "hbbwater",
                    "c": "",
                    "sim": "",
                    "meid": "",
                    "androidCode": ZTQ_ANDROID_CODE,
                }
            },
        }
        data = await self._post(payload)
        self.pid = str(((data.get("b") or {}).get("init") or {}).get("pid") or "")
        if not self.pid:
            raise RuntimeError("ZhiTianQi init did not return pid")
        return self.pid

    async def fetch_station_payloads(
        self,
        stations: list[WeatherStationConfig],
    ) -> dict[str, tuple[dict[str, Any] | None, dict[str, Any] | None]]:
        pid = await self.ensure_pid()
        body: dict[str, Any] = {}
        for station in stations:
            body[f"fycx_trend_sta#2_{station.station_id}_10"] = {
                "channel": "2",
                "stationid": station.station_id,
                "type": "10",
            }
            body[f"fycx_sstq#{station.station_id}"] = {
                "stationid": station.station_id,
                "townsid": "",
                "type": "pd",
            }

        data = await self._post({"h": {"p": pid}, "b": body})
        response_body = data.get("b") or {}
        return {
            station.station_id: (
                response_body.get(f"fycx_trend_sta#2_{station.station_id}_10"),
                response_body.get(f"fycx_sstq#{station.station_id}"),
            )
            for station in stations
        }


async def ensure_weather_station_rows(db: AsyncSession, configs: list[WeatherStationConfig]) -> list[WeatherStation]:
    rows: list[WeatherStation] = []
    for config in configs:
        result = await db.execute(
            select(WeatherStation).where(WeatherStation.station_id == config.station_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = WeatherStation(
                station_id=config.station_id,
                station_name=config.station_name,
                role=config.role,
                longitude=Decimal(str(config.longitude)),
                latitude=Decimal(str(config.latitude)),
                is_active=config.is_active,
            )
            db.add(row)
        else:
            row.station_name = config.station_name
            row.role = config.role
            row.longitude = Decimal(str(config.longitude))
            row.latitude = Decimal(str(config.latitude))
        rows.append(row)
    await db.flush()
    return rows


def _rainfall_point_key(point: RainfallPoint) -> tuple[str, str, datetime, datetime]:
    return (point.station_id, point.data_type, point.hour_time, point.batch_time)


def _rainfall_row_key(row: RainfallHourly) -> tuple[str, str, datetime, datetime]:
    return (row.station_id, row.data_type, row.hour_time, row.batch_time)


async def _upsert_rainfall_points(db: AsyncSession, points: list[RainfallPoint]) -> int:
    """Upsert rainfall points with one bounded lookup instead of a SELECT per point."""
    if not points:
        return 0

    result = await db.execute(
        select(RainfallHourly).where(
            RainfallHourly.station_id.in_({point.station_id for point in points}),
            RainfallHourly.data_type.in_({point.data_type for point in points}),
            RainfallHourly.hour_time.in_({point.hour_time for point in points}),
            RainfallHourly.batch_time.in_({point.batch_time for point in points}),
        )
    )
    rows_by_key = {
        _rainfall_row_key(row): row
        for row in result.scalars().all()
    }
    now = utcnow_naive()
    inserted = 0
    for point in points:
        row = rows_by_key.get(_rainfall_point_key(point))
        if row is None:
            db.add(
                RainfallHourly(
                    station_id=point.station_id,
                    data_type=point.data_type,
                    hour_time=point.hour_time,
                    rainfall_mm=point.rainfall_mm,
                    batch_time=point.batch_time,
                    forecast_issued_at=point.forecast_issued_at,
                    source_endpoint="fycx_trend_sta",
                    raw_time_label=point.raw_time_label,
                    source_updated_at=point.source_updated_at,
                    created_at=now,
                    updated_at=now,
                )
            )
            inserted += 1
            continue

        row.rainfall_mm = point.rainfall_mm
        row.forecast_issued_at = point.forecast_issued_at
        row.raw_time_label = point.raw_time_label
        row.source_updated_at = point.source_updated_at
        row.updated_at = now

    return inserted


async def _mark_weather_station_success(db: AsyncSession, station_id: str, collected_at: datetime) -> None:
    await db.execute(
        text(
            """
            UPDATE weather_stations
            SET last_success_at = :last_success_at,
                last_error = '',
                updated_at = :updated_at
            WHERE station_id = :station_id
            """
        ),
        {
            "station_id": station_id,
            "last_success_at": collected_at,
            "updated_at": collected_at,
        },
    )


async def _mark_weather_station_error(
    db: AsyncSession,
    station_id: str,
    message: str,
    collected_at: datetime,
) -> None:
    await db.execute(
        text(
            """
            UPDATE weather_stations
            SET last_error = :last_error,
                updated_at = :updated_at
            WHERE station_id = :station_id
            """
        ),
        {
            "station_id": station_id,
            "last_error": message[:1000],
            "updated_at": collected_at,
        },
    )


async def collect_rainfall_once(
    *,
    client: ZtqWeatherClient | None = None,
    reference_now: datetime | None = None,
) -> RainfallCollectionResult:
    """Fetch both configured stations and persist actual/forecast hourly rainfall."""
    collected_at = utcnow_naive()
    station_configs = get_weather_station_configs()

    async with business_session_scope() as db:
        station_rows = await ensure_weather_station_rows(db, station_configs)
        active_ids = {row.station_id for row in station_rows if row.is_active}

    active_configs = [config for config in station_configs if config.station_id in active_ids and config.is_active]
    if not active_configs:
        return RainfallCollectionResult(collected_at, 0, 0, False)

    owns_client = client is None
    if owns_client:
        client = ZtqWeatherClient()
        await client.__aenter__()

    try:
        assert client is not None
        raw_payloads = await client.fetch_station_payloads(active_configs)
    finally:
        if owns_client and client is not None:
            await client.__aexit__(None, None, None)

    point_count = 0
    has_positive_rainfall = False
    async with business_session_scope() as db:
        for config in active_configs:
            trend_data, current_data = raw_payloads.get(config.station_id, ({}, {}))
            if not trend_data or not (trend_data.get("sk_list") or trend_data.get("yb_list")):
                await _mark_weather_station_error(
                    db,
                    config.station_id,
                    "知天气趋势接口未返回雨量时序",
                    collected_at,
                )
                continue

            payload = parse_ztq_rainfall_payload(
                config.station_id,
                trend_data,
                current_data,
                reference_now=reference_now,
            )
            await _upsert_rainfall_points(db, payload.points)
            point_count += len(payload.points)
            has_positive_rainfall = has_positive_rainfall or payload.has_positive_rainfall

            await _mark_weather_station_success(db, config.station_id, collected_at)

    return RainfallCollectionResult(
        collected_at=collected_at,
        station_count=len(active_configs),
        point_count=point_count,
        has_positive_rainfall=has_positive_rainfall,
    )


def get_rainfall_stale_seconds() -> int:
    dry_interval = max(
        get_min_rainfall_interval_seconds(),
        _env_int("ZTQ_RAINFALL_DRY_INTERVAL_SECONDS", 10800),
    )
    configured = _env_int("ZTQ_RAINFALL_STALE_SECONDS", dry_interval * 2)
    return max(get_min_rainfall_interval_seconds(), configured)


def get_min_rainfall_interval_seconds() -> int:
    return max(300, _env_int("ZTQ_RAINFALL_MIN_INTERVAL_SECONDS", 300))


def get_next_collection_interval_seconds(has_positive_rainfall: bool) -> int:
    min_interval = get_min_rainfall_interval_seconds()
    if has_positive_rainfall:
        return max(min_interval, _env_int("ZTQ_RAINFALL_ACTIVE_INTERVAL_SECONDS", 1800))
    return max(min_interval, _env_int("ZTQ_RAINFALL_DRY_INTERVAL_SECONDS", 10800))


async def rainfall_collector_loop() -> None:
    has_positive_rainfall = False
    while True:
        try:
            result = await collect_rainfall_once()
            has_positive_rainfall = result.has_positive_rainfall
            print(
                f"[{datetime.utcnow()}] Rainfall collector stored "
                f"{result.point_count} points for {result.station_count} stations."
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[{datetime.utcnow()}] Rainfall collector failed: {exc}")

        await asyncio.sleep(get_next_collection_interval_seconds(has_positive_rainfall))


def start_rainfall_collector() -> asyncio.Task[None] | None:
    if not _env_flag("ZTQ_RAINFALL_ENABLED", default=True):
        return None
    print(f"[{datetime.utcnow()}] Rainfall collector enabled.")
    return asyncio.create_task(rainfall_collector_loop())


async def build_station_summary(db: AsyncSession, station: WeatherStation) -> dict[str, Any]:
    now = utcnow_naive()
    current_result = await db.execute(
        select(RainfallHourly)
        .where(RainfallHourly.station_id == station.station_id)
        .where(RainfallHourly.data_type == "actual")
        .order_by(desc(RainfallHourly.hour_time))
        .limit(1)
    )
    current = current_result.scalar_one_or_none()

    latest_batch_result = await db.execute(
        select(RainfallHourly.batch_time)
        .where(RainfallHourly.station_id == station.station_id)
        .where(RainfallHourly.data_type == "forecast")
        .order_by(desc(RainfallHourly.batch_time))
        .limit(1)
    )
    latest_batch = latest_batch_result.scalar_one_or_none()
    forecast_rows: list[RainfallHourly] = []
    if latest_batch is not None:
        forecast_result = await db.execute(
            select(RainfallHourly)
            .where(RainfallHourly.station_id == station.station_id)
            .where(RainfallHourly.data_type == "forecast")
            .where(RainfallHourly.batch_time == latest_batch)
            .order_by(RainfallHourly.hour_time)
        )
        forecast_rows = list(forecast_result.scalars().all())

    now_hour = floor_to_hour(now)
    forecast_totals: dict[str, float] = {}
    for hours in (1, 3, 6, 24):
        end_time = now_hour + timedelta(hours=hours)
        total = sum(
            Decimal(row.rainfall_mm or 0)
            for row in forecast_rows
            if now_hour <= row.hour_time < end_time
        )
        forecast_totals[f"next_{hours}h"] = float(total)

    last_success_at = station.last_success_at
    stale_after = timedelta(seconds=get_rainfall_stale_seconds())
    is_stale = not last_success_at or last_success_at < now - stale_after

    return {
        "station_id": station.station_id,
        "station_name": station.station_name,
        "role": station.role,
        "longitude": float(station.longitude) if station.longitude is not None else None,
        "latitude": float(station.latitude) if station.latitude is not None else None,
        "is_active": bool(station.is_active),
        "last_success_at": last_success_at,
        "last_error": station.last_error or "",
        "is_stale": is_stale,
        "current_actual_mm": float(current.rainfall_mm) if current is not None else None,
        "current_actual_time": current.hour_time if current is not None else None,
        "source_updated_at": current.source_updated_at if current is not None else None,
        "latest_forecast_issued_at": latest_batch,
        "forecast_totals": forecast_totals,
    }


def select_rainfall_summary_station(
    station_summaries: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    primary = next((item for item in station_summaries if item["role"] == "primary"), None)
    backup = next((item for item in station_summaries if item["role"] == "backup"), None)

    if primary is not None and not primary["is_stale"] and not primary["last_error"]:
        return primary, "primary"
    if backup is not None and not backup["is_stale"] and not backup["last_error"]:
        return backup, "backup"
    if primary is not None:
        return primary, "primary_unavailable"
    if backup is not None:
        return backup, "backup_unavailable"
    if station_summaries:
        return station_summaries[0], "fallback"
    return None, "none"


async def build_rainfall_summary(db: AsyncSession) -> dict[str, Any]:
    station_configs = get_weather_station_configs()
    await ensure_weather_station_rows(db, station_configs)
    result = await db.execute(
        select(WeatherStation).order_by(WeatherStation.role.desc(), WeatherStation.station_id)
    )
    stations = [
        station for station in result.scalars().all()
        if station.station_id in {config.station_id for config in station_configs}
    ]
    station_summaries = [await build_station_summary(db, station) for station in stations]
    selected, reason = select_rainfall_summary_station(station_summaries)

    return {
        "stations": station_summaries,
        "selected_station_id": selected["station_id"] if selected else None,
        "selected_reason": reason if selected else "none",
        "updated_at": utcnow_naive(),
        "stale_after_seconds": get_rainfall_stale_seconds(),
    }
