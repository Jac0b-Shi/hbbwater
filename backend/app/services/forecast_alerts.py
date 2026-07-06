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
MODEL_VERSION = "segmented_pressure_v1"

DEFAULT_MODEL_PARAMS: dict[str, Any] = {
    "lambda_decay": 0.97,
    "pump_on_rise_mm": 50.0,
    "pump_capacity_mm_per_min": 1.05,
    "weak_rain_pressure_mm": 8.0,
    "moderate_rain_pressure_mm": 24.0,
    "heavy_rain_pressure_mm": 55.0,
    "strong_event_min_rise_mm": 110.0,
    "extreme_event_min_rise_mm": 300.0,
    "warning_rise_mm": 120.0,
    "critical_rise_mm": 250.0,
    "watch_rise_mm": 80.0,
}

RISK_ORDER = {"normal": 0, "watch": 1, "warning": 2, "critical": 3}
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


def _merge_params(*items: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_MODEL_PARAMS)
    for item in items:
        if item:
            merged.update(item)
    return merged


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


async def _latest_sensor_reading(db: AsyncSession, sensor_id: str) -> SensorReading | None:
    return await db.scalar(
        select(SensorReading)
        .where(SensorReading.sensor_id == sensor_id)
        .where(SensorReading.water_level.is_not(None))
        .order_by(desc(SensorReading.recorded_at))
        .limit(1)
    )


async def _select_station_id(
    db: AsyncSession,
    requested_station_id: str | None,
    *,
    now_hour: datetime,
    horizon_hours: int,
) -> str | None:
    if requested_station_id:
        return requested_station_id

    stations = (
        await db.execute(
            select(WeatherStation)
            .where(WeatherStation.is_active == True)
            .order_by(WeatherStation.role.desc(), WeatherStation.station_id)
        )
    ).scalars().all()
    if not stations:
        return None

    end_time = now_hour + timedelta(hours=horizon_hours)
    for station in stations:
        count = await db.scalar(
            select(func.count())
            .select_from(RainfallForecastHourly)
            .where(RainfallForecastHourly.station_id == station.station_id)
            .where(RainfallForecastHourly.hour_time >= now_hour)
            .where(RainfallForecastHourly.hour_time < end_time)
        )
        if count:
            return station.station_id
    return stations[0].station_id


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
) -> list[dict[str, Any]]:
    row_by_hour = {row.hour_time: row for row in rows}
    series = []
    for offset in range(horizon_hours):
        hour_time = now_hour + timedelta(hours=offset)
        row = row_by_hour.get(hour_time)
        series.append({
            "hour_time": hour_time,
            "rainfall_mm": _to_float(row.rainfall_mm if row else 0, 0.0),
        })
    return series


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


def _risk_from_rise(
    predicted_free_rise_mm: float,
    predicted_observed_rise_mm: float,
    profile: ForecastAlertProfile | None,
    params: dict[str, Any],
) -> str:
    critical = _to_float(
        profile.critical_rise_mm if profile and profile.critical_rise_mm is not None else params.get("critical_rise_mm"),
        250.0,
    )
    warning = _to_float(
        profile.warning_rise_mm if profile and profile.warning_rise_mm is not None else params.get("warning_rise_mm"),
        120.0,
    )
    watch = _to_float(params.get("watch_rise_mm"), 80.0)
    risk_basis = max(predicted_observed_rise_mm, predicted_free_rise_mm)
    if risk_basis >= critical:
        return "critical"
    if risk_basis >= warning:
        return "warning"
    if predicted_observed_rise_mm >= watch or predicted_free_rise_mm >= watch:
        return "watch"
    return "normal"


def _max_risk(*risks: str) -> str:
    return max(risks, key=lambda risk: RISK_ORDER.get(risk, 0))


def _severity_for_risk(risk_level: str) -> str:
    return Severity.CRITICAL.value if risk_level == "critical" else Severity.HIGH.value


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
    station_id = await _select_station_id(
        db,
        profile.station_id if profile else None,
        now_hour=now_hour,
        horizon_hours=horizon_hours,
    )
    latest_reading = await _latest_sensor_reading(db, sensor.sensor_id)

    if not station_id:
        return {
            "sensor": sensor,
            "station_id": None,
            "risk_level": "normal",
            "should_notify": False,
            "decision_reason": "没有可用雨量站",
            "features": {},
            "series": [],
            "control_recommendation": {"mode": "recommendation_only", "executable": False, "action": "none"},
        }
    if latest_reading is None:
        return {
            "sensor": sensor,
            "station_id": station_id,
            "risk_level": "normal",
            "should_notify": False,
            "decision_reason": "没有可用于预测的最新超声波测距读数",
            "features": {"station_id": station_id},
            "series": [],
            "control_recommendation": {"mode": "recommendation_only", "executable": False, "action": "none"},
        }

    rows = await _forecast_rows(db, station_id, now_hour=now_hour, horizon_hours=horizon_hours)
    if not rows:
        return {
            "sensor": sensor,
            "station_id": station_id,
            "risk_level": "normal",
            "should_notify": False,
            "decision_reason": "没有可用于预测的未来小时雨量预报",
            "latest_distance_cm": latest_reading.water_level,
            "features": {"station_id": station_id},
            "series": [],
            "control_recommendation": {"mode": "recommendation_only", "executable": False, "action": "none"},
        }

    forecast_series = _hourly_forecast_series(rows, now_hour=now_hour, horizon_hours=horizon_hours)
    rainfall_values = [item["rainfall_mm"] for item in forecast_series]
    p_total = sum(rainfall_values)
    i_1h_max = max(rainfall_values) if rainfall_values else 0.0
    p_3h_max = _rolling_max(rainfall_values, 3)
    p_6h_max = _rolling_max(rainfall_values, 6)
    api_24h = await _actual_total(db, station_id, now_hour=now_hour, hours=24)
    api_72h = await _actual_total(db, station_id, now_hour=now_hour, hours=72)
    forecast_issued_at = max((row.forecast_issued_at or row.batch_time for row in rows), default=None)

    latest_distance_cm = _to_float(latest_reading.water_level, 0.0)
    baseline_cm = _to_float(sensor.water_level_baseline, latest_distance_cm)
    has_baseline = sensor.water_level_baseline is not None
    h_start_mm = max(0.0, (baseline_cm - latest_distance_cm) * 10)
    lambda_decay = _to_float(model_params.get("lambda_decay"), 0.97)
    pump_on_rise_mm = _to_float(model_params.get("pump_on_rise_mm"), 50.0)
    pump_capacity_mm_per_min = _to_float(model_params.get("pump_capacity_mm_per_min"), 1.05)

    free_level = h_start_mm
    observed_level = h_start_mm
    peak_free = h_start_mm
    peak_observed = h_start_mm
    peak_time = forecast_series[0]["hour_time"] if forecast_series else now_hour
    predicted_series: list[dict[str, Any]] = []

    for item in forecast_series:
        pressure = _rainfall_pressure_mm(item["rainfall_mm"], model_params)
        free_level = max(0.0, free_level * lambda_decay + pressure)
        observed_level = max(0.0, observed_level * lambda_decay + pressure)
        pump_active = observed_level > pump_on_rise_mm
        pump_output_mm = 0.0
        if pump_active:
            pump_output_mm = pump_capacity_mm_per_min * 60
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
            "pump_active": pump_active,
            "pump_output_mm": round(pump_output_mm, 2),
        })

    lower_bound_reason = ""
    if p_total > 35 and i_1h_max > 12:
        lower_bound = _to_float(model_params.get("extreme_event_min_rise_mm"), 300.0)
        lower_bound_reason = "暴雨事件下限"
    elif p_total > 20 and i_1h_max > 7:
        lower_bound = _to_float(model_params.get("strong_event_min_rise_mm"), 110.0)
        lower_bound_reason = "强降雨事件下限"
    else:
        lower_bound = 0.0
    if lower_bound and peak_free < lower_bound:
        peak_free = lower_bound
        peak_time = max(forecast_series, key=lambda item: item["rainfall_mm"])["hour_time"]
        peak_observed = max(peak_observed, min(peak_free, pump_on_rise_mm + 10.0))

    projected_distance_cm = latest_distance_cm - peak_observed / 10
    threshold_risk = _risk_from_thresholds(sensor, projected_distance_cm)
    rise_risk = _risk_from_rise(peak_free, peak_observed, profile, model_params)
    risk_level = _max_risk(threshold_risk, rise_risk)
    should_notify = risk_level in {"warning", "critical"}

    confidence = 0.75
    if not has_baseline:
        confidence -= 0.15
    if len(rows) < horizon_hours:
        confidence -= 0.15
    if lower_bound_reason:
        confidence = max(confidence, 0.7)
    confidence = max(0.35, min(0.9, confidence))

    features = {
        "station_id": station_id,
        "forecast_hours_available": len(rows),
        "p_total_mm": round(p_total, 2),
        "i_1h_max_mm": round(i_1h_max, 2),
        "p_3h_max_mm": round(p_3h_max, 2),
        "p_6h_max_mm": round(p_6h_max, 2),
        "api_24h_mm": round(api_24h, 2),
        "api_72h_mm": round(api_72h, 2),
        "h_start_mm": round(h_start_mm, 2),
        "has_baseline": has_baseline,
        "threshold_risk": threshold_risk,
        "rise_risk": rise_risk,
        "lower_bound_reason": lower_bound_reason,
    }
    decision_reason = (
        f"未来{horizon_hours}小时累计雨量 {p_total:.1f} mm，峰值小时雨强 {i_1h_max:.1f} mm/h，"
        f"预计无泵等效上涨 {peak_free:.1f} mm，考虑泵削峰后上涨 {peak_observed:.1f} mm"
    )
    if lower_bound_reason:
        decision_reason += f"，已应用{lower_bound_reason}"

    recommendation = await get_pump_controller().build_recommendation(
        PumpControlContext(
            sensor_id=sensor.sensor_id,
            risk_level=risk_level,
            predicted_free_rise_mm=peak_free,
            predicted_observed_rise_mm=peak_observed,
            pump_on_rise_mm=pump_on_rise_mm,
            actuator_binding_id=profile.actuator_binding_id if profile else None,
        )
    )

    return {
        "sensor": sensor,
        "station_id": station_id,
        "risk_level": risk_level,
        "should_notify": should_notify,
        "horizon_hours": horizon_hours,
        "forecast_issued_at": forecast_issued_at,
        "peak_time": peak_time,
        "predicted_free_rise_mm": peak_free,
        "predicted_observed_rise_mm": peak_observed,
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
        "risk_level": result.risk_level,
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

    for sensor in sensors:
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
            station_id=prediction.get("station_id"),
            risk_level=prediction.get("risk_level", "normal"),
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

    run.status = "completed"
    run.message = f"已评估 {len(results)} 个传感器"
    run.forecast_issued_at = latest_forecast_issued_at
    run.completed_at = utcnow_naive()
    await db.flush()
    await db.refresh(run, attribute_names=["results"])
    return run


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
