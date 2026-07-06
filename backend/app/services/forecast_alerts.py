from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import business_session_scope, ControlSessionLocal
from app.models import (
    Alert,
    AlertType,
    ForecastAlertProfile,
    ForecastPredictionResult,
    ForecastPredictionRun,
    RainfallActualHourly,
    RainfallForecastHourly,
    Sensor,
    SensorReading,
    SensorType,
    Severity,
    WeatherStation,
)
from app.services.alerting import (
    AUTO_RESOLVE_ACTOR,
    compare_threshold,
    get_sensor_threshold_condition,
)
from app.services.notifications import dispatch_alert_notifications
from app.services.pump_control import PumpControlContext, get_pump_controller
from app.services.system_config import (
    get_bool_config,
    get_config_value,
    get_int_config,
    set_config_value,
)
from app.services.weather import floor_to_hour, utcnow_naive

FORECAST_ALERT_ENABLED_KEY = "forecast_alert_enabled"
FORECAST_ALERT_COOLDOWN_KEY = "forecast_alert_cooldown_minutes"
FORECAST_ALERT_HORIZON_KEY = "forecast_alert_default_horizon_hours"
FORECAST_ALERT_MODEL_PARAMS_KEY = "forecast_alert_model_params"
MODEL_VERSION = "heuristic_pressure_v1"
PRIMARY_OBSERVED_STATION = "A5151"

SENSOR_CONSISTENCY_MODEL = {
    "reference_sensor_id": "ultrasonic_002",
    "target_sensor_id": "ultrasonic_003",
    "slope": 0.9840,
    "intercept_cm": -9.26,
    "median_abs_residual_cm": 0.11,
    "p95_abs_residual_cm": 0.42,
    "calibration_sample_size": 3145,
}

PROVISIONAL_VERTICAL_THRESHOLDS_CM = {
    "ultrasonic_002": {"warning_level_cm": 81.2, "danger_level_cm": 70.6},
    "ultrasonic_003": {"warning_level_cm": 70.6, "danger_level_cm": 60.0},
}

DEFAULT_MODEL_PARAMS: dict[str, Any] = {
    "lambda_decay": 0.97,
    "pump_on_rise_mm": 50.0,
    "pump_assumption": "inferred_q2",
    "forecast_gap_ratio_threshold": 0.25,
    "net_drawdown_by_pump_count_cm_per_h": {
        "0": 0.0,
        "1": None,
        "2": 6.23,
        "3": None,
    },
    "drawdown_parameter_status": {
        "0": "defined",
        "1": "unknown",
        "2": "inferred",
        "3": "unknown",
    },
    "weak_rain_pressure_mm": 8.0,
    "moderate_rain_pressure_mm": 24.0,
    "heavy_rain_pressure_mm": 55.0,
    "strong_event_min_rise_mm": 110.0,
    "extreme_event_min_rise_mm": 300.0,
    "warning_rise_mm": 120.0,
    "critical_rise_mm": 250.0,
    "watch_rise_mm": 80.0,
}

RISK_ORDER = {"unknown": 0, "normal": 1, "watch": 2, "warning": 3, "critical": 4}
SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(round(value, 2)))


def _normalize_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _validate_model_params(params: dict[str, Any]) -> dict[str, Any]:
    """Reject dangerous or nonsensical model parameter overrides."""
    validated = dict(DEFAULT_MODEL_PARAMS)
    validated.update(params)

    lambda_decay = validated.get("lambda_decay")
    if lambda_decay is not None:
        try:
            lambda_decay = float(lambda_decay)
        except (TypeError, ValueError):
            lambda_decay = 0.97
        if not (0.0 <= lambda_decay <= 1.0):
            lambda_decay = 0.97
        validated["lambda_decay"] = lambda_decay

    pump_on_rise = validated.get("pump_on_rise_mm")
    if pump_on_rise is not None:
        try:
            pump_on_rise = float(pump_on_rise)
        except (TypeError, ValueError):
            pump_on_rise = None
        if pump_on_rise is None or pump_on_rise < 0:
            pump_on_rise = 50.0
        validated["pump_on_rise_mm"] = pump_on_rise

    for key in ("watch_rise_mm", "warning_rise_mm", "critical_rise_mm"):
        value = validated.get(key)
        if value is not None:
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = None
            if value is None or value < 0:
                value = DEFAULT_MODEL_PARAMS.get(key)
            validated[key] = value

    watch = _to_float(validated.get("watch_rise_mm"), 80.0)
    warning = _to_float(validated.get("warning_rise_mm"), 120.0)
    critical = _to_float(validated.get("critical_rise_mm"), 250.0)
    if not (watch < warning < critical):
        validated["watch_rise_mm"] = 80.0
        validated["warning_rise_mm"] = 120.0
        validated["critical_rise_mm"] = 250.0

    drawdown = _normalize_json_object(validated.get("net_drawdown_by_pump_count_cm_per_h"))
    default_drawdown = DEFAULT_MODEL_PARAMS["net_drawdown_by_pump_count_cm_per_h"]
    for pump_count in ("0", "1", "2", "3"):
        if pump_count not in drawdown:
            drawdown[pump_count] = default_drawdown.get(pump_count)
        value = drawdown[pump_count]
        if value is not None and not isinstance(value, (int, float)):
            drawdown[pump_count] = default_drawdown.get(pump_count)
        if pump_count == "0" and drawdown[pump_count] != 0:
            drawdown[pump_count] = 0.0
        if value is not None and value < 0:
            drawdown[pump_count] = default_drawdown.get(pump_count)
    # Adjacent non-null values must be strictly increasing.
    qs = [drawdown.get(str(i)) for i in range(1, 4)]
    non_null = [(i, q) for i, q in enumerate(qs, start=1) if q is not None]
    for i in range(len(non_null) - 1):
        if non_null[i][1] >= non_null[i + 1][1]:
            drawdown[str(non_null[i + 1][0])] = default_drawdown.get(str(non_null[i + 1][0]))
    validated["net_drawdown_by_pump_count_cm_per_h"] = drawdown

    # Ensure pump_assumption is one of the allowed values.
    pump_assumption = validated.get("pump_assumption")
    if pump_assumption not in ("inferred_q2", "measured_q2", "none"):
        validated["pump_assumption"] = DEFAULT_MODEL_PARAMS["pump_assumption"]

    # Ensure forecast gap ratio threshold is within [0, 1].
    gap_threshold = validated.get("forecast_gap_ratio_threshold")
    try:
        gap_threshold = float(gap_threshold)
    except (TypeError, ValueError):
        gap_threshold = DEFAULT_MODEL_PARAMS["forecast_gap_ratio_threshold"]
    if not (0.0 <= gap_threshold <= 1.0):
        gap_threshold = DEFAULT_MODEL_PARAMS["forecast_gap_ratio_threshold"]
    validated["forecast_gap_ratio_threshold"] = gap_threshold

    # Reject the legacy single-pump-capacity field if present; replace with inferred table.
    if "pump_capacity_mm_per_min" in validated or "pump_capacity_mm_per_hour" in validated:
        validated.pop("pump_capacity_mm_per_min", None)
        validated.pop("pump_capacity_mm_per_hour", None)

    return validated


def _merge_params(*items: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_MODEL_PARAMS)
    for item in items:
        if item:
            merged.update(item)
    return _validate_model_params(merged)


def _rolling_max(values: list[float], window: int) -> float:
    if not values:
        return 0.0
    return max(sum(values[max(0, index - window + 1):index + 1]) for index in range(len(values)))


def _rainfall_pressure_mm(rainfall_mm: float, params: dict[str, Any]) -> float:
    if rainfall_mm < 1:
        return 0.0
    if rainfall_mm < 3:
        return _to_float(params.get("weak_rain_pressure_mm"), 8.0)
    if rainfall_mm < 10:
        return _to_float(params.get("moderate_rain_pressure_mm"), 24.0)
    return _to_float(params.get("heavy_rain_pressure_mm"), 55.0)


async def get_forecast_alert_global_config(control_db: AsyncSession) -> dict[str, Any]:
    return {
        "enabled": await get_bool_config(control_db, FORECAST_ALERT_ENABLED_KEY, False),
        "cooldown_minutes": await get_int_config(control_db, FORECAST_ALERT_COOLDOWN_KEY, 120),
        "default_horizon_hours": await get_int_config(control_db, FORECAST_ALERT_HORIZON_KEY, 6),
        "model_params": _normalize_json_object(
            await get_config_value(control_db, FORECAST_ALERT_MODEL_PARAMS_KEY, "{}")
        ),
    }


async def save_forecast_alert_global_config(control_db: AsyncSession, config: dict[str, Any]) -> None:
    if "enabled" in config:
        await set_config_value(
            control_db,
            FORECAST_ALERT_ENABLED_KEY,
            str(bool(config["enabled"])).lower(),
            "预报型水位告警总开关",
        )
    if "cooldown_minutes" in config:
        await set_config_value(
            control_db,
            FORECAST_ALERT_COOLDOWN_KEY,
            str(int(config["cooldown_minutes"])),
            "预报型告警冷却时间(分钟)",
        )
    if "default_horizon_hours" in config:
        await set_config_value(
            control_db,
            FORECAST_ALERT_HORIZON_KEY,
            str(int(config["default_horizon_hours"])),
            "预报型告警默认预测窗口(小时)",
        )
    if "model_params" in config:
        await set_config_value(
            control_db,
            FORECAST_ALERT_MODEL_PARAMS_KEY,
            json.dumps(config["model_params"] or {}, ensure_ascii=False),
            "预报型告警模型参数",
        )


async def list_forecast_alert_config(
    db: AsyncSession,
    control_db: AsyncSession,
) -> dict[str, Any]:
    global_config = await get_forecast_alert_global_config(control_db)
    sensor_result = await db.execute(
        select(Sensor)
        .where(Sensor.sensor_type == SensorType.ULTRASONIC.value)
        .order_by(Sensor.sensor_id)
    )
    sensors = sensor_result.scalars().all()
    profile_result = await db.execute(select(ForecastAlertProfile))
    profiles = {profile.sensor_id: profile for profile in profile_result.scalars().all()}
    station_result = await db.execute(
        select(WeatherStation).order_by(WeatherStation.role.desc(), WeatherStation.station_id)
    )

    return {
        "global_config": global_config,
        "profiles": [
            serialize_profile_for_sensor(sensor, profiles.get(sensor.sensor_id), global_config["default_horizon_hours"])
            for sensor in sensors
        ],
        "stations": station_result.scalars().all(),
    }


def serialize_profile_for_sensor(
    sensor: Sensor,
    profile: ForecastAlertProfile | None,
    default_horizon_hours: int,
) -> dict[str, Any]:
    return {
        "id": profile.id if profile else None,
        "sensor_id": sensor.sensor_id,
        "sensor_location": sensor.location,
        "sensor_type": sensor.sensor_type,
        "is_enabled": bool(profile.is_enabled) if profile else False,
        "station_id": profile.station_id if profile else None,
        "horizon_hours": int(profile.horizon_hours or default_horizon_hours) if profile else default_horizon_hours,
        "warning_rise_mm": profile.warning_rise_mm if profile else None,
        "critical_rise_mm": profile.critical_rise_mm if profile else None,
        "model_params": profile.model_params if profile else None,
        "pump_params": profile.pump_params if profile else None,
        "actuator_binding_id": profile.actuator_binding_id if profile else None,
        "created_at": profile.created_at if profile else None,
        "updated_at": profile.updated_at if profile else None,
    }


async def upsert_forecast_alert_profiles(
    db: AsyncSession,
    payloads: Iterable[dict[str, Any]],
) -> None:
    for payload in payloads:
        sensor_id = payload["sensor_id"]
        sensor = await db.scalar(select(Sensor).where(Sensor.sensor_id == sensor_id))
        if sensor is None:
            raise ValueError(f"传感器不存在: {sensor_id}")
        if sensor.sensor_type != SensorType.ULTRASONIC.value:
            raise ValueError(f"预报型水位告警仅支持超声波传感器: {sensor_id}")

        profile = await db.scalar(
            select(ForecastAlertProfile).where(ForecastAlertProfile.sensor_id == sensor_id)
        )
        if profile is None:
            profile = ForecastAlertProfile(sensor_id=sensor_id)
            db.add(profile)

        profile.is_enabled = bool(payload.get("is_enabled", False))
        profile.station_id = (payload.get("station_id") or None)
        profile.horizon_hours = int(payload.get("horizon_hours") or 6)
        profile.warning_rise_mm = payload.get("warning_rise_mm")
        profile.critical_rise_mm = payload.get("critical_rise_mm")
        profile.model_params = payload.get("model_params") or None
        profile.pump_params = payload.get("pump_params") or None
        profile.actuator_binding_id = payload.get("actuator_binding_id") or None
        profile.updated_at = datetime.utcnow()

    await db.flush()


async def _latest_sensor_reading(
    db: AsyncSession,
    sensor_id: str,
    *,
    now: datetime,
    max_age_seconds: int | None = None,
) -> dict[str, Any] | None:
    """Return latest reading with freshness check.

    max_age_seconds defaults to 2 * sensor.normal_interval if the sensor
    exists; otherwise 3600 seconds. If the reading is stale, it is still
    returned so the caller can record a degraded/unavailable data status.
    """
    sensor = await db.scalar(select(Sensor).where(Sensor.sensor_id == sensor_id))
    if max_age_seconds is None:
        max_age_seconds = int((sensor.normal_interval if sensor else 1800) * 2)

    reading = await db.scalar(
        select(SensorReading)
        .where(SensorReading.sensor_id == sensor_id)
        .where(SensorReading.water_level.is_not(None))
        .order_by(desc(SensorReading.recorded_at))
        .limit(1)
    )
    if reading is None:
        return None

    age_seconds = (now - reading.recorded_at).total_seconds()
    is_stale = age_seconds > max_age_seconds
    return {
        "reading": reading,
        "age_seconds": age_seconds,
        "is_stale": is_stale,
        "max_age_seconds": max_age_seconds,
    }


async def _select_rain_source(
    db: AsyncSession,
    requested_station_id: str | None,
    *,
    now_hour: datetime,
    horizon_hours: int,
) -> dict[str, Any]:
    """Choose observed and forecast rainfall sources independently.

    Observed rainfall is fixed to A5151 when possible. Forecast rainfall
    falls back to 58362 only when A5151 has no forecast data, and the
    downgrade is explicitly flagged.
    """
    actual_station_id = PRIMARY_OBSERVED_STATION

    stations = (
        await db.execute(
            select(WeatherStation)
            .where(WeatherStation.is_active == True)
            .order_by(WeatherStation.role.desc(), WeatherStation.station_id)
        )
    ).scalars().all()
    if not stations:
        return {
            "actual_station_id": None,
            "forecast_station_id": None,
            "rain_source_degraded": False,
            "degraded_reason": None,
        }

    # If A5151 is not an active station, observed source is degraded.
    active_station_ids = {s.station_id for s in stations}
    if PRIMARY_OBSERVED_STATION not in active_station_ids:
        actual_station_id = next(
            (s.station_id for s in stations if s.role == "primary"),
            stations[0].station_id,
        )

    end_time = now_hour + timedelta(hours=horizon_hours)

    # A5151 is the forced-priority forecast source. The profile's requested station
    # (e.g. 58362) may only be used as an explicit fallback when A5151 is missing.
    candidate_station_ids = [PRIMARY_OBSERVED_STATION]
    if requested_station_id and requested_station_id != PRIMARY_OBSERVED_STATION:
        candidate_station_ids.append(requested_station_id)
    for station in stations:
        if station.station_id not in candidate_station_ids:
            candidate_station_ids.append(station.station_id)

    forecast_station_id = None
    fallback_station_id = None
    for station_id in candidate_station_ids:
        count = await db.scalar(
            select(func.count())
            .select_from(RainfallForecastHourly)
            .where(RainfallForecastHourly.station_id == station_id)
            .where(RainfallForecastHourly.hour_time >= now_hour)
            .where(RainfallForecastHourly.hour_time < end_time)
        )
        if count:
            forecast_station_id = station_id
            break

    rain_source_degraded = forecast_station_id != PRIMARY_OBSERVED_STATION
    degraded_reason = None
    if forecast_station_id is None:
        degraded_reason = "NO_FORECAST_AVAILABLE"
    elif rain_source_degraded:
        degraded_reason = "A5151_FORECAST_MISSING"

    return {
        "actual_station_id": actual_station_id,
        "forecast_station_id": forecast_station_id,
        "rain_source_degraded": rain_source_degraded,
        "degraded_reason": degraded_reason,
    }


async def _forecast_rows(
    db: AsyncSession,
    station_id: str,
    *,
    now_hour: datetime,
    horizon_hours: int,
) -> list[RainfallForecastHourly]:
    end_time = now_hour + timedelta(hours=horizon_hours)
    return (
        await db.execute(
            select(RainfallForecastHourly)
            .where(RainfallForecastHourly.station_id == station_id)
            .where(RainfallForecastHourly.hour_time >= now_hour)
            .where(RainfallForecastHourly.hour_time < end_time)
            .order_by(RainfallForecastHourly.hour_time)
        )
    ).scalars().all()


async def _actual_total(
    db: AsyncSession,
    station_id: str,
    *,
    now_hour: datetime,
    hours: int,
) -> float:
    start_time = now_hour - timedelta(hours=hours)
    total = await db.scalar(
        select(func.sum(RainfallActualHourly.rainfall_mm))
        .where(RainfallActualHourly.station_id == station_id)
        .where(RainfallActualHourly.hour_time >= start_time)
        .where(RainfallActualHourly.hour_time < now_hour)
    )
    return _to_float(total, 0.0)


def _hourly_forecast_series(
    rows: list[RainfallForecastHourly],
    *,
    now_hour: datetime,
    horizon_hours: int,
) -> dict[str, Any]:
    """Build hourly forecast series while distinguishing real zeros from missing hours."""
    row_by_hour = {row.hour_time: row for row in rows}
    series = []
    gap_hours = []
    for offset in range(horizon_hours):
        hour_time = now_hour + timedelta(hours=offset)
        row = row_by_hour.get(hour_time)
        if row is None:
            gap_hours.append(hour_time.isoformat())
            series.append({
                "hour_time": hour_time,
                "rainfall_mm": None,
                "is_gap": True,
            })
        else:
            series.append({
                "hour_time": hour_time,
                "rainfall_mm": _to_float(row.rainfall_mm, 0.0),
                "is_gap": False,
            })
    return {
        "series": series,
        "forecast_gap_hours": gap_hours,
        "has_gaps": bool(gap_hours),
    }


def _risk_from_thresholds(
    sensor: Sensor,
    projected_distance_cm: float | None,
) -> str:
    if projected_distance_cm is None:
        return "normal"
    condition = get_sensor_threshold_condition(sensor)
    if compare_threshold(projected_distance_cm, sensor.danger_level, condition):
        return "critical"
    if compare_threshold(projected_distance_cm, sensor.warning_level, condition):
        return "warning"
    return "normal"


def _risk_from_rise_single(
    rise_mm: float,
    profile: ForecastAlertProfile | None,
    params: dict[str, Any],
) -> str:
    """Risk level from a single predicted rise value."""
    critical = _to_float(
        profile.critical_rise_mm if profile and profile.critical_rise_mm is not None else params.get("critical_rise_mm"),
        250.0,
    )
    warning = _to_float(
        profile.warning_rise_mm if profile and profile.warning_rise_mm is not None else params.get("warning_rise_mm"),
        120.0,
    )
    watch = _to_float(params.get("watch_rise_mm"), 80.0)
    if rise_mm >= critical:
        return "critical"
    if rise_mm >= warning:
        return "warning"
    if rise_mm >= watch:
        return "watch"
    return "normal"


def _risk_from_rise(
    predicted_free_rise_mm: float,
    predicted_observed_rise_mm: float,
    profile: ForecastAlertProfile | None,
    params: dict[str, Any],
) -> str:
    """Deprecated combined wrapper: use _risk_from_rise_single per scenario."""
    return _max_risk(
        _risk_from_rise_single(predicted_free_rise_mm, profile, params),
        _risk_from_rise_single(predicted_observed_rise_mm, profile, params),
    )


def _max_risk(*risks: str) -> str:
    return max(risks, key=lambda risk: RISK_ORDER.get(risk, 0))


def _severity_for_risk(risk_level: str) -> str:
    return Severity.CRITICAL.value if risk_level == "critical" else Severity.HIGH.value


def _drawdown_for_pump_count(params: dict[str, Any], pump_count: int) -> float | None:
    drawdown = _normalize_json_object(params.get("net_drawdown_by_pump_count_cm_per_h"))
    value = drawdown.get(str(pump_count))
    if value is None:
        return None
    return _to_float(value, None)


def _policy_floor(
    p_total: float,
    i_1h_max: float,
    params: dict[str, Any],
) -> tuple[str, str | None]:
    """Return safety policy floor risk and reason, independent of model prediction."""
    if p_total > 35 and i_1h_max > 12:
        return "critical", "EXTREME_RAINFALL"
    if p_total > 20 and i_1h_max > 7:
        return "warning", "STRONG_RAINFALL"
    return "normal", None


def _data_status_from_gaps_and_staleness(
    has_station: bool,
    has_reading: bool,
    reading_stale: bool,
    forecast_available: bool,
    has_forecast_gaps: bool,
    forecast_gap_ratio: float,
    gap_ratio_threshold: float = 0.25,
) -> str:
    if not has_station or not has_reading or not forecast_available:
        return "unavailable"
    if forecast_gap_ratio > gap_ratio_threshold:
        return "unavailable"
    if reading_stale or has_forecast_gaps:
        return "degraded"
    return "available"


async def _sensor_consistency_diagnosis(
    db: AsyncSession,
    reference_sensor_id: str,
    target_sensor_id: str,
    *,
    now: datetime,
) -> dict[str, Any] | None:
    """Compute 002->003 affine mapping residual for Shadow Mode diagnosis only.

    This result is purely diagnostic and must not be used to suppress hazard alerts.
    """
    reference = await _latest_sensor_reading(db, reference_sensor_id, now=now)
    target = await _latest_sensor_reading(db, target_sensor_id, now=now)
    if reference is None or target is None:
        return None

    reference_level = _to_float(reference["reading"].water_level, None)
    target_level = _to_float(target["reading"].water_level, None)
    if reference_level is None or target_level is None:
        return None

    model = SENSOR_CONSISTENCY_MODEL
    expected_target = model["slope"] * reference_level + model["intercept_cm"]
    residual = target_level - expected_target
    return {
        "reference_sensor_id": reference_sensor_id,
        "target_sensor_id": target_sensor_id,
        "reference_level_cm": round(reference_level, 2),
        "target_level_cm": round(target_level, 2),
        "expected_target_cm": round(expected_target, 2),
        "residual_cm": round(residual, 2),
        "median_abs_residual_cm": model["median_abs_residual_cm"],
        "p95_abs_residual_cm": model["p95_abs_residual_cm"],
        "calibration_sample_size": model["calibration_sample_size"],
        "diagnostic_only": True,
    }


def _threshold_provenance(sensor: Sensor) -> dict[str, Any]:
    """Mark whether the configured thresholds are provisional vertical-install assumptions."""
    warning = _to_float(sensor.warning_level, None)
    danger = _to_float(sensor.danger_level, None)
    provisional = PROVISIONAL_VERTICAL_THRESHOLDS_CM.get(sensor.sensor_id)
    if provisional is None:
        return {
            "provisional_vertical_assumption": False,
            "reason": "No known provisional threshold mapping for this sensor.",
        }
    warning_match = warning is not None and abs(warning - provisional["warning_level_cm"]) < 0.05
    danger_match = danger is not None and abs(danger - provisional["danger_level_cm"]) < 0.05
    return {
        "provisional_vertical_assumption": warning_match and danger_match,
        "reason": (
            "Thresholds match the first-overflow vertical-install assumption; not final PLC setpoints."
            if (warning_match and danger_match)
            else "Configured thresholds do not match the provisional vertical assumption."
        ),
        "expected_warning_cm": provisional["warning_level_cm"],
        "expected_danger_cm": provisional["danger_level_cm"],
    }


async def _compute_prediction(
    db: AsyncSession,
    *,
    sensor: Sensor,
    profile: ForecastAlertProfile | None,
    global_params: dict[str, Any],
    horizon_hours: int,
    now: datetime,
) -> dict[str, Any]:
    now_hour = floor_to_hour(now)
    model_params = _merge_params(
        global_params,
        profile.model_params if profile else None,
        profile.pump_params if profile else None,
    )
    gap_ratio_threshold = _to_float(model_params.get("forecast_gap_ratio_threshold"), 0.25)

    rain_source = await _select_rain_source(
        db,
        profile.station_id if profile else None,
        now_hour=now_hour,
        horizon_hours=horizon_hours,
    )
    actual_station_id = rain_source["actual_station_id"]
    forecast_station_id = rain_source["forecast_station_id"]
    rain_source_degraded = rain_source["rain_source_degraded"]
    degraded_reason = rain_source["degraded_reason"]

    latest_reading_info = await _latest_sensor_reading(
        db, sensor.sensor_id, now=now
    )
    has_reading = latest_reading_info is not None
    reading_stale = latest_reading_info["is_stale"] if latest_reading_info else False
    latest_reading = latest_reading_info["reading"] if latest_reading_info else None

    has_forecast_station = forecast_station_id is not None
    rows = await _forecast_rows(
        db, forecast_station_id, now_hour=now_hour, horizon_hours=horizon_hours
    ) if has_forecast_station else []
    forecast_available = bool(rows)

    forecast_series_result = _hourly_forecast_series(
        rows, now_hour=now_hour, horizon_hours=horizon_hours
    )
    forecast_series = forecast_series_result["series"]
    has_forecast_gaps = forecast_series_result["has_gaps"]
    forecast_gap_hours = forecast_series_result["forecast_gap_hours"]
    forecast_gap_ratio = len(forecast_gap_hours) / max(horizon_hours, 1)

    data_status = _data_status_from_gaps_and_staleness(
        has_station=actual_station_id is not None,
        has_reading=has_reading,
        reading_stale=reading_stale,
        forecast_available=forecast_available,
        has_forecast_gaps=has_forecast_gaps,
        forecast_gap_ratio=forecast_gap_ratio,
        gap_ratio_threshold=gap_ratio_threshold,
    )

    can_auto_resolve = data_status == "available"
    advisory_only = data_status != "available"

    # Shadow Mode sensor-consistency diagnosis; never used to suppress hazard alerts.
    consistency_diagnosis = await _sensor_consistency_diagnosis(
        db,
        SENSOR_CONSISTENCY_MODEL["reference_sensor_id"],
        SENSOR_CONSISTENCY_MODEL["target_sensor_id"],
        now=now,
    )
    threshold_provenance = _threshold_provenance(sensor)

    # If data is unavailable, do not create new risk conclusions or clear existing alerts.
    if data_status == "unavailable":
        return {
            "sensor": sensor,
            "actual_station_id": actual_station_id,
            "forecast_station_id": forecast_station_id,
            "rain_source_degraded": rain_source_degraded,
            "degraded_reason": degraded_reason,
            "data_status": data_status,
            "risk_level": "unknown",
            "model_risk": "unknown",
            "risk_no_pump": "unknown",
            "risk_q2_scenario": "unknown",
            "policy_floor": "normal",
            "effective_risk": "unknown",
            "policy_reason": None,
            "can_auto_resolve": False,
            "advisory_only": True,
            "scenario_pump_count": None,
            "pump_assumption": None,
            "should_notify": False,
            "decision_reason": "输入数据不可用，不生成风险结论",
            "latest_distance_cm": _to_float(latest_reading.water_level, None) if latest_reading else None,
            "features": {
                "actual_station_id": actual_station_id,
                "forecast_station_id": forecast_station_id,
                "rain_source_degraded": rain_source_degraded,
                "degraded_reason": degraded_reason,
                "forecast_gap_hours": forecast_gap_hours,
                "forecast_gap_ratio": round(forecast_gap_ratio, 2),
                "reading_stale": reading_stale,
                "can_auto_resolve": False,
                "advisory_only": True,
                "sensor_consistency_diagnosis": consistency_diagnosis,
                "threshold_provenance": threshold_provenance,
            },
            "series": [],
            "control_recommendation": {"mode": "recommendation_only", "executable": False, "action": "none"},
            "model_version": MODEL_VERSION,
        }

    # Reading is required for a distance-based prediction.
    if latest_reading is None:
        # This branch is defensive; data_status should already be unavailable.
        return {
            "sensor": sensor,
            "actual_station_id": actual_station_id,
            "forecast_station_id": forecast_station_id,
            "rain_source_degraded": rain_source_degraded,
            "degraded_reason": degraded_reason,
            "data_status": "unavailable",
            "risk_level": "unknown",
            "model_risk": "unknown",
            "risk_no_pump": "unknown",
            "risk_q2_scenario": "unknown",
            "policy_floor": "normal",
            "effective_risk": "unknown",
            "policy_reason": None,
            "can_auto_resolve": False,
            "advisory_only": True,
            "scenario_pump_count": None,
            "pump_assumption": None,
            "should_notify": False,
            "decision_reason": "没有可用于预测的最新超声波测距读数",
            "features": {
                "actual_station_id": actual_station_id,
                "forecast_station_id": forecast_station_id,
                "rain_source_degraded": rain_source_degraded,
                "sensor_consistency_diagnosis": consistency_diagnosis,
                "threshold_provenance": threshold_provenance,
            },
            "series": [],
            "control_recommendation": {"mode": "recommendation_only", "executable": False, "action": "none"},
            "model_version": MODEL_VERSION,
        }

    rainfall_values = [item["rainfall_mm"] for item in forecast_series if item["rainfall_mm"] is not None]
    p_total = sum(rainfall_values)
    i_1h_max = max(rainfall_values) if rainfall_values else 0.0
    p_3h_max = _rolling_max(rainfall_values, 3)
    p_6h_max = _rolling_max(rainfall_values, 6)
    api_24h = await _actual_total(db, actual_station_id, now_hour=now_hour, hours=24)
    api_72h = await _actual_total(db, actual_station_id, now_hour=now_hour, hours=72)
    forecast_issued_at = max((row.forecast_issued_at or row.batch_time for row in rows), default=None)

    latest_distance_cm = _to_float(latest_reading.water_level, 0.0)
    baseline_cm = _to_float(sensor.water_level_baseline, latest_distance_cm)
    has_baseline = sensor.water_level_baseline is not None
    h_start_mm = max(0.0, (baseline_cm - latest_distance_cm) * 10)
    lambda_decay = _to_float(model_params.get("lambda_decay"), 0.97)
    pump_on_rise_mm = _to_float(model_params.get("pump_on_rise_mm"), 50.0)
    q2_cm_per_h = _drawdown_for_pump_count(model_params, 2)
    if q2_cm_per_h is None:
        q2_cm_per_h = 6.23
    q2_mm_per_h = q2_cm_per_h * 10.0

    free_level = 0.0
    observed_level = 0.0
    peak_free = 0.0
    peak_observed = 0.0
    peak_time = forecast_series[0]["hour_time"] if forecast_series else now_hour
    predicted_series: list[dict[str, Any]] = []

    for item in forecast_series:
        if item["is_gap"]:
            # Gaps advance time decay without adding rainfall pressure.
            free_level = max(0.0, free_level * lambda_decay)
            observed_level = max(0.0, observed_level * lambda_decay)
            scenario_pump_count = 2 if observed_level > pump_on_rise_mm else 0
            pump_output_mm = 0.0
            if scenario_pump_count > 0:
                pump_output_mm = q2_mm_per_h
                observed_level = max(0.0, observed_level - pump_output_mm)
            if free_level > peak_free:
                peak_free = free_level
                peak_time = item["hour_time"]
            peak_observed = max(peak_observed, observed_level)
            predicted_series.append({
                "hour_time": item["hour_time"].isoformat(),
                "rainfall_mm": None,
                "rainfall_pressure_mm": None,
                "free_rise_mm": round(free_level, 2),
                "observed_rise_mm": round(observed_level, 2),
                "scenario_pump_count": scenario_pump_count,
                "pump_assumption": "inferred_q2" if scenario_pump_count > 0 else "none",
                "actual_pump_state": "unknown",
                "pump_output_mm": round(pump_output_mm, 2),
                "is_gap": True,
            })
            continue

        pressure = _rainfall_pressure_mm(item["rainfall_mm"], model_params)
        free_level = max(0.0, free_level * lambda_decay + pressure)
        observed_level = max(0.0, observed_level * lambda_decay + pressure)
        scenario_pump_count = 2 if observed_level > pump_on_rise_mm else 0
        pump_output_mm = 0.0
        if scenario_pump_count > 0:
            pump_output_mm = q2_mm_per_h
            observed_level = max(0.0, observed_level - pump_output_mm)

        if free_level > peak_free:
            peak_free = free_level
            peak_time = item["hour_time"]
        peak_observed = max(peak_observed, observed_level)
        predicted_series.append({
            "hour_time": item["hour_time"].isoformat(),
            "rainfall_mm": item["rainfall_mm"],
            "rainfall_pressure_mm": round(pressure, 2),
            "free_rise_mm": round(free_level, 2),
            "observed_rise_mm": round(observed_level, 2),
            "scenario_pump_count": scenario_pump_count,
            "pump_assumption": "inferred_q2" if scenario_pump_count > 0 else "none",
            "actual_pump_state": "unknown",
            "pump_output_mm": round(pump_output_mm, 2),
        })

    # Total predicted rise relative to baseline includes existing h_start + future rise.
    predicted_free_rise_mm = h_start_mm + peak_free
    predicted_observed_rise_mm = h_start_mm + peak_observed

    projected_distance_no_pump_cm = baseline_cm - predicted_free_rise_mm / 10
    projected_distance_q2_cm = baseline_cm - predicted_observed_rise_mm / 10

    risk_no_pump = _max_risk(
        _risk_from_thresholds(sensor, projected_distance_no_pump_cm),
        _risk_from_rise_single(predicted_free_rise_mm, profile, model_params),
    )
    risk_q2_scenario = _max_risk(
        _risk_from_thresholds(sensor, projected_distance_q2_cm),
        _risk_from_rise_single(predicted_observed_rise_mm, profile, model_params),
    )
    model_risk = _max_risk(risk_no_pump, risk_q2_scenario)

    policy_floor, policy_reason = _policy_floor(p_total, i_1h_max, model_params)

    # Degraded or unavailable data must not produce new safety conclusions.
    if data_status != "available":
        effective_risk = "unknown"
        should_notify = False
        risk_level_for_lifecycle = "unknown"
    else:
        effective_risk = _max_risk(model_risk, policy_floor)
        should_notify = effective_risk in {"warning", "critical"}
        risk_level_for_lifecycle = effective_risk

    confidence = 0.75
    if not has_baseline:
        confidence -= 0.15
    if len(rows) < horizon_hours:
        confidence -= 0.15
    if has_forecast_gaps:
        confidence -= 0.15
    if data_status == "degraded":
        confidence -= 0.1
    if policy_reason:
        # Policy floor indicates model uncertainty, not higher confidence.
        confidence -= 0.1
    confidence = max(0.2, min(0.9, confidence))

    projected_distance_cm = baseline_cm - predicted_observed_rise_mm / 10

    features = {
        "actual_station_id": actual_station_id,
        "forecast_station_id": forecast_station_id,
        "rain_source_degraded": rain_source_degraded,
        "degraded_reason": degraded_reason,
        "data_status": data_status,
        "can_auto_resolve": can_auto_resolve,
        "advisory_only": advisory_only,
        "forecast_hours_available": len(rows),
        "forecast_gap_hours": forecast_gap_hours,
        "forecast_gap_ratio": round(forecast_gap_ratio, 2),
        "p_total_mm": round(p_total, 2),
        "i_1h_max_mm": round(i_1h_max, 2),
        "p_3h_max_mm": round(p_3h_max, 2),
        "p_6h_max_mm": round(p_6h_max, 2),
        "api_24h_mm": round(api_24h, 2),
        "api_72h_mm": round(api_72h, 2),
        "h_start_mm": round(h_start_mm, 2),
        "has_baseline": has_baseline,
        "model_risk": model_risk,
        "risk_no_pump": risk_no_pump,
        "risk_q2_scenario": risk_q2_scenario,
        "policy_floor": policy_floor,
        "effective_risk": effective_risk,
        "policy_reason": policy_reason,
        "reading_stale": reading_stale,
        "sensor_consistency_diagnosis": consistency_diagnosis,
        "threshold_provenance": threshold_provenance,
        "validated_params": {
            "lambda_decay": model_params.get("lambda_decay"),
            "pump_on_rise_mm": model_params.get("pump_on_rise_mm"),
            "forecast_gap_ratio_threshold": gap_ratio_threshold,
            "net_drawdown_by_pump_count_cm_per_h": model_params.get("net_drawdown_by_pump_count_cm_per_h"),
            "drawdown_parameter_status": model_params.get("drawdown_parameter_status"),
        },
    }

    decision_reason = (
        f"未来{horizon_hours}小时累计雨量 {p_total:.1f} mm，峰值小时雨强 {i_1h_max:.1f} mm/h，"
        f"当前相对 baseline 上涨 {h_start_mm:.1f} mm，"
        f"预计无泵等效上涨 {predicted_free_rise_mm:.1f} mm，"
        f"考虑泵削峰后上涨 {predicted_observed_rise_mm:.1f} mm"
    )
    if policy_reason:
        decision_reason += f"，安全策略下限已触发：{policy_reason}"
    if rain_source_degraded:
        decision_reason += f"，雨量源降级：{degraded_reason}"
    if data_status == "degraded":
        decision_reason += "，数据状态降级"

    recommendation = await get_pump_controller().build_recommendation(
        PumpControlContext(
            sensor_id=sensor.sensor_id,
            risk_level=effective_risk,
            predicted_free_rise_mm=predicted_free_rise_mm,
            predicted_observed_rise_mm=predicted_observed_rise_mm,
            pump_on_rise_mm=pump_on_rise_mm,
            actuator_binding_id=profile.actuator_binding_id if profile else None,
        )
    )

    return {
        "sensor": sensor,
        "actual_station_id": actual_station_id,
        "forecast_station_id": forecast_station_id,
        "rain_source_degraded": rain_source_degraded,
        "degraded_reason": degraded_reason,
        "data_status": data_status,
        "risk_level": effective_risk,
        "model_risk": model_risk,
        "risk_no_pump": risk_no_pump,
        "risk_q2_scenario": risk_q2_scenario,
        "policy_floor": policy_floor,
        "effective_risk": effective_risk,
        "policy_reason": policy_reason,
        "can_auto_resolve": can_auto_resolve,
        "advisory_only": advisory_only,
        "scenario_pump_count": 2 if (predicted_observed_rise_mm < predicted_free_rise_mm) else 0,
        "pump_assumption": "inferred_q2" if (predicted_observed_rise_mm < predicted_free_rise_mm) else "none",
        "should_notify": should_notify,
        "horizon_hours": horizon_hours,
        "forecast_issued_at": forecast_issued_at,
        "peak_time": peak_time,
        "predicted_free_rise_mm": predicted_free_rise_mm,
        "predicted_observed_rise_mm": predicted_observed_rise_mm,
        "projected_distance_cm": projected_distance_cm,
        "latest_distance_cm": latest_distance_cm,
        "confidence": confidence,
        "features": features,
        "series": predicted_series,
        "control_recommendation": recommendation,
        "decision_reason": decision_reason,
        "model_version": MODEL_VERSION,
    }


async def _active_forecast_alerts(db: AsyncSession, sensor_id: str) -> list[Alert]:
    return (
        await db.execute(
            select(Alert)
            .where(Alert.sensor_id == sensor_id)
            .where(Alert.alert_type == AlertType.FORECAST_HIGH_WATER.value)
            .where(Alert.is_resolved == False)
            .order_by(desc(Alert.created_at))
        )
    ).scalars().all()


async def _resolve_forecast_alerts(db: AsyncSession, sensor_id: str, resolved_at: datetime) -> None:
    for alert in await _active_forecast_alerts(db, sensor_id):
        alert.is_resolved = True
        alert.resolved_at = resolved_at
        alert.resolved_by = AUTO_RESOLVE_ACTOR


def _build_alert_message(result: ForecastPredictionResult, sensor: Sensor) -> str:
    return (
        f"预报显示传感器 {sensor.sensor_id}（{sensor.location or '未知位置'}）未来 "
        f"{result.horizon_hours} 小时可能出现高水位风险："
        f"无泵等效上涨约 {float(result.predicted_free_rise_mm or 0):.1f} mm，"
        f"考虑泵削峰后上涨约 {float(result.predicted_observed_rise_mm or 0):.1f} mm，"
        f"预计最低测距约 {float(result.projected_distance_cm or 0):.2f} cm。"
    )


def _build_alert_details(result: ForecastPredictionResult) -> dict[str, Any]:
    return {
        "prediction_result_id": result.id,
        "prediction_run_id": result.run_id,
        "station_id": result.station_id,
        "actual_station_id": result.actual_station_id,
        "forecast_station_id": result.forecast_station_id,
        "rain_source_degraded": result.rain_source_degraded,
        "degraded_reason": result.degraded_reason,
        "data_status": result.data_status,
        "risk_level": result.risk_level,
        "model_risk": result.model_risk,
        "risk_no_pump": result.risk_no_pump,
        "risk_q2_scenario": result.risk_q2_scenario,
        "policy_floor": result.policy_floor,
        "effective_risk": result.effective_risk,
        "policy_reason": result.policy_reason,
        "can_auto_resolve": result.can_auto_resolve,
        "advisory_only": result.advisory_only,
        "horizon_hours": result.horizon_hours,
        "forecast_issued_at": result.forecast_issued_at.isoformat() if result.forecast_issued_at else None,
        "peak_time": result.peak_time.isoformat() if result.peak_time else None,
        "predicted_free_rise_mm": float(result.predicted_free_rise_mm or 0),
        "predicted_observed_rise_mm": float(result.predicted_observed_rise_mm or 0),
        "projected_distance_cm": float(result.projected_distance_cm or 0),
        "latest_distance_cm": float(result.latest_distance_cm or 0),
        "confidence": float(result.confidence or 0),
        "features": result.features,
        "control_recommendation": result.control_recommendation,
        "model_version": result.model_version,
        "decision_reason": result.decision_reason,
    }


async def _handle_forecast_alert_lifecycle(
    db: AsyncSession,
    control_db: AsyncSession,
    *,
    sensor: Sensor,
    result: ForecastPredictionResult,
    now: datetime,
) -> tuple[Alert | None, bool]:
    active_alerts = await _active_forecast_alerts(db, sensor.sensor_id)
    if not result.can_auto_resolve or result.risk_level in {"unknown"}:
        # Degraded/unavailable data must not create new conclusions or auto-clear existing alerts.
        return None, False
    if not result.should_notify:
        await _resolve_forecast_alerts(db, sensor.sensor_id, now)
        return None, False

    severity = _severity_for_risk(result.risk_level)
    cooldown_minutes = await get_int_config(control_db, FORECAST_ALERT_COOLDOWN_KEY, 120)
    if active_alerts:
        latest = active_alerts[0]
        latest_created = latest.created_at
        if latest_created and (now - latest_created).total_seconds() < cooldown_minutes * 60:
            if SEVERITY_ORDER.get(severity, 0) <= SEVERITY_ORDER.get(latest.severity, 0):
                return latest, False

    await _resolve_forecast_alerts(db, sensor.sensor_id, now)
    alert = Alert(
        sensor_id=sensor.sensor_id,
        alert_type=AlertType.FORECAST_HIGH_WATER.value,
        severity=severity,
        message=_build_alert_message(result, sensor),
        details=_build_alert_details(result),
        created_at=now,
    )
    db.add(alert)
    await db.flush()

    notification_sent = False
    try:
        outcomes = await dispatch_alert_notifications(control_db, sensor=sensor, alert=alert)
        notification_sent = any(success for success, _message in outcomes.values())
    except Exception:
        notification_sent = False
    return alert, notification_sent


async def evaluate_forecast_alerts(
    db: AsyncSession,
    control_db: AsyncSession,
    *,
    dry_run: bool = True,
    trigger_type: str = "manual",
    sensor_ids: list[str] | None = None,
    horizon_hours: int | None = None,
    created_by: str | None = None,
) -> ForecastPredictionRun:
    now = utcnow_naive()
    global_config = await get_forecast_alert_global_config(control_db)
    run = ForecastPredictionRun(
        trigger_type=trigger_type,
        dry_run=dry_run,
        status="running",
        started_at=now,
        created_by=created_by,
        source={
            "sensor_ids": sensor_ids,
            "requested_horizon_hours": horizon_hours,
            "global_enabled": global_config["enabled"],
        },
    )
    db.add(run)
    await db.flush()

    if not dry_run and not global_config["enabled"]:
        run.status = "skipped"
        run.message = "预报型水位告警未启用"
        run.completed_at = utcnow_naive()
        return run

    query = (
        select(Sensor)
        .where(Sensor.sensor_type == SensorType.ULTRASONIC.value)
        .where(Sensor.is_active == True)
        .options(selectinload(Sensor.forecast_alert_profile))
        .order_by(Sensor.sensor_id)
    )
    if sensor_ids:
        query = query.where(Sensor.sensor_id.in_(sensor_ids))
    sensors = (await db.execute(query)).scalars().unique().all()
    results: list[ForecastPredictionResult] = []
    latest_forecast_issued_at: datetime | None = None
    global_params = global_config.get("model_params") or {}
    any_failed = False

    for sensor in sensors:
        try:
            profile = sensor.forecast_alert_profile
            if not dry_run and (profile is None or not profile.is_enabled):
                continue
            effective_horizon = int(
                horizon_hours
                or (profile.horizon_hours if profile and profile.horizon_hours else global_config["default_horizon_hours"])
                or 6
            )
            effective_horizon = max(1, min(24, effective_horizon))
            prediction = await _compute_prediction(
                db,
                sensor=sensor,
                profile=profile,
                global_params=global_params,
                horizon_hours=effective_horizon,
                now=now,
            )
            latest_forecast_issued_at = max(
                [value for value in (latest_forecast_issued_at, prediction.get("forecast_issued_at")) if value],
                default=None,
            )
            result = ForecastPredictionResult(
                run_id=run.id,
                sensor_id=sensor.sensor_id,
                station_id=prediction.get("forecast_station_id") or prediction.get("station_id"),
                actual_station_id=prediction.get("actual_station_id"),
                forecast_station_id=prediction.get("forecast_station_id"),
                rain_source_degraded=bool(prediction.get("rain_source_degraded")),
                degraded_reason=prediction.get("degraded_reason"),
                data_status=prediction.get("data_status", "unavailable"),
                risk_level=prediction.get("risk_level", "unknown"),
                model_risk=prediction.get("model_risk"),
                risk_no_pump=prediction.get("risk_no_pump"),
                risk_q2_scenario=prediction.get("risk_q2_scenario"),
                policy_floor=prediction.get("policy_floor"),
                effective_risk=prediction.get("effective_risk"),
                policy_reason=prediction.get("policy_reason"),
                can_auto_resolve=bool(prediction.get("can_auto_resolve", False)),
                advisory_only=bool(prediction.get("advisory_only", True)),
                scenario_pump_count=prediction.get("scenario_pump_count"),
                pump_assumption=prediction.get("pump_assumption"),
                should_notify=bool(prediction.get("should_notify")),
                notification_sent=False,
                horizon_hours=prediction.get("horizon_hours") or effective_horizon,
                forecast_issued_at=prediction.get("forecast_issued_at"),
                peak_time=prediction.get("peak_time"),
                predicted_free_rise_mm=_to_decimal(prediction.get("predicted_free_rise_mm")),
                predicted_observed_rise_mm=_to_decimal(prediction.get("predicted_observed_rise_mm")),
                projected_distance_cm=_to_decimal(prediction.get("projected_distance_cm")),
                latest_distance_cm=_to_decimal(_to_float(prediction.get("latest_distance_cm"), 0.0)) if prediction.get("latest_distance_cm") is not None else None,
                confidence=_to_decimal(prediction.get("confidence")),
                features=prediction.get("features") or {},
                series=prediction.get("series") or [],
                control_recommendation=prediction.get("control_recommendation") or {},
                decision_reason=prediction.get("decision_reason"),
                model_version=MODEL_VERSION,
                created_at=now,
            )
            db.add(result)
            await db.flush()

            if not dry_run:
                alert, notification_sent = await _handle_forecast_alert_lifecycle(
                    db,
                    control_db,
                    sensor=sensor,
                    result=result,
                    now=now,
                )
                result.alert_id = alert.id if alert else None
                result.notification_sent = notification_sent

            results.append(result)
        except Exception as exc:
            error_result = ForecastPredictionResult(
                run_id=run.id,
                sensor_id=sensor.sensor_id,
                risk_level="unknown",
                data_status="unavailable",
                should_notify=False,
                decision_reason=f"预测运行异常: {exc}",
                features={"error": str(exc)},
                model_version=MODEL_VERSION,
                created_at=now,
            )
            db.add(error_result)
            await db.flush()
            results.append(error_result)
            any_failed = True

    run.status = "partial" if any_failed else "completed"
    run.message = f"已评估 {len(results)} 个传感器"
    run.forecast_issued_at = latest_forecast_issued_at
    run.completed_at = utcnow_naive()
    await db.flush()
    # Eagerly load results to avoid lazy-loading issues for callers.
    run_with_results = (
        await db.execute(
            select(ForecastPredictionRun)
            .where(ForecastPredictionRun.id == run.id)
            .options(selectinload(ForecastPredictionRun.results))
        )
    ).scalar_one()
    return run_with_results


async def run_scheduled_forecast_evaluation() -> None:
    async with ControlSessionLocal() as control_db:
        enabled = await get_bool_config(control_db, FORECAST_ALERT_ENABLED_KEY, False)
        if not enabled:
            return
        async with business_session_scope() as db:
            await evaluate_forecast_alerts(
                db,
                control_db,
                dry_run=False,
                trigger_type="rainfall_collector",
                created_by="system:rainfall_collector",
            )
