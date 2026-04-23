from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, AlertType, Sensor, SensorReading, SensorType
from app.services.notifications import dispatch_alert_notifications
from app.services.system_config import get_int_config

THRESHOLD_CONDITION_GREATER_OR_EQUAL = "greater_or_equal"
THRESHOLD_CONDITION_LESS_OR_EQUAL = "less_or_equal"
DEFAULT_THRESHOLD_CONDITION = THRESHOLD_CONDITION_GREATER_OR_EQUAL
AUTO_RESOLVE_ACTOR = "system:auto"


def _normalize_datetime_to_utc_naive(value: datetime) -> datetime:
    """Keep alert calculations compatible with naive UTC DB timestamps."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def get_sensor_type_value(sensor_type: SensorType | str) -> str:
    return sensor_type.value if isinstance(sensor_type, SensorType) else str(sensor_type)


def normalize_threshold_condition(value: Optional[str]) -> str:
    if value == THRESHOLD_CONDITION_LESS_OR_EQUAL:
        return THRESHOLD_CONDITION_LESS_OR_EQUAL
    return THRESHOLD_CONDITION_GREATER_OR_EQUAL


def get_sensor_threshold_condition(sensor: Sensor) -> str:
    return normalize_threshold_condition(getattr(sensor, "threshold_condition", None))


def get_threshold_condition_label(value: Optional[str]) -> str:
    condition = normalize_threshold_condition(value)
    if condition == THRESHOLD_CONDITION_LESS_OR_EQUAL:
        return "小于等于阈值触发"
    return "大于等于阈值触发"


def is_threshold_configuration_valid(
    warning_level: Optional[Decimal | float],
    danger_level: Optional[Decimal | float],
    condition: Optional[str],
) -> bool:
    if warning_level is None or danger_level is None:
        return True

    warning = float(warning_level)
    danger = float(danger_level)
    if normalize_threshold_condition(condition) == THRESHOLD_CONDITION_LESS_OR_EQUAL:
        return danger <= warning
    return danger >= warning


def get_threshold_configuration_error(condition: Optional[str]) -> str:
    if normalize_threshold_condition(condition) == THRESHOLD_CONDITION_LESS_OR_EQUAL:
        return "当前比较方式为“小于等于阈值触发”，危险阈值必须小于或等于预警阈值"
    return "当前比较方式为“大于等于阈值触发”，危险阈值必须大于或等于预警阈值"


def compare_threshold(value: float, threshold: Optional[Decimal | float], condition: Optional[str]) -> bool:
    if threshold is None:
        return False

    threshold_value = float(threshold)
    if normalize_threshold_condition(condition) == THRESHOLD_CONDITION_LESS_OR_EQUAL:
        return value <= threshold_value
    return value >= threshold_value


def _normalize_status(status: Optional[str]) -> str:
    if status in {"warning", "danger", "alarm", "offline"}:
        return str(status)
    return "normal"


def infer_ultrasonic_status(
    sensor: Sensor,
    water_level: float,
    fallback_status: Optional[str] = None,
) -> str:
    condition = get_sensor_threshold_condition(sensor)

    if compare_threshold(water_level, sensor.danger_level, condition):
        return "danger"
    if compare_threshold(water_level, sensor.warning_level, condition):
        return "warning"
    return _normalize_status(fallback_status)


async def _resolve_active_alerts(
    db: AsyncSession,
    *,
    sensor_id: str,
    alert_type: str,
    resolved_at: datetime,
) -> None:
    resolved_at = _normalize_datetime_to_utc_naive(resolved_at)
    result = await db.execute(
        select(Alert).where(
            Alert.sensor_id == sensor_id,
            Alert.alert_type == alert_type,
            Alert.is_resolved == False,
        )
    )
    for alert in result.scalars().all():
        alert.is_resolved = True
        alert.resolved_at = resolved_at
        alert.resolved_by = AUTO_RESOLVE_ACTOR


async def _get_latest_active_alert(
    db: AsyncSession,
    *,
    sensor_id: str,
    alert_type: str,
    severity: str,
) -> Optional[Alert]:
    result = await db.execute(
        select(Alert)
        .where(
            Alert.sensor_id == sensor_id,
            Alert.alert_type == alert_type,
            Alert.severity == severity,
            Alert.is_resolved == False,
        )
        .order_by(desc(Alert.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _upsert_active_alert(
    db: AsyncSession,
    control_db: AsyncSession,
    *,
    sensor: Sensor,
    reading: SensorReading,
    alert_type: str,
    severity: str,
    message: str,
    details: dict,
) -> Optional[Alert]:
    reading.recorded_at = _normalize_datetime_to_utc_naive(reading.recorded_at)
    cooldown_minutes = await get_int_config(control_db, "alert_cooldown_minutes", 30)
    active_alert = await _get_latest_active_alert(
        db,
        sensor_id=sensor.sensor_id,
        alert_type=alert_type,
        severity=severity,
    )
    if active_alert:
        active_created_at = _normalize_datetime_to_utc_naive(active_alert.created_at)
        if (reading.recorded_at - active_created_at).total_seconds() < cooldown_minutes * 60:
            return active_alert

    await _resolve_active_alerts(
        db,
        sensor_id=sensor.sensor_id,
        alert_type=alert_type,
        resolved_at=reading.recorded_at,
    )

    alert = Alert(
        sensor_id=sensor.sensor_id,
        alert_type=alert_type,
        severity=severity,
        message=message,
        details=details,
        created_at=reading.recorded_at,
    )
    db.add(alert)
    await db.flush()

    try:
        await dispatch_alert_notifications(
            control_db,
            sensor=sensor,
            alert=alert,
            reading=reading,
        )
    except Exception:
        pass

    return alert


async def handle_sensor_reading_alerts(
    db: AsyncSession,
    control_db: AsyncSession,
    *,
    sensor: Sensor,
    reading: SensorReading,
) -> Optional[Alert]:
    sensor_type = get_sensor_type_value(sensor.sensor_type)
    if sensor_type == SensorType.ULTRASONIC.value:
        return await _handle_ultrasonic_alerts(db, control_db, sensor=sensor, reading=reading)
    return await _handle_immersion_alerts(db, control_db, sensor=sensor, reading=reading)


async def _handle_ultrasonic_alerts(
    db: AsyncSession,
    control_db: AsyncSession,
    *,
    sensor: Sensor,
    reading: SensorReading,
) -> Optional[Alert]:
    if reading.water_level is None:
        return None

    status = infer_ultrasonic_status(sensor, float(reading.water_level), fallback_status=reading.status)
    reading.status = status

    if status not in {"warning", "danger"}:
        await _resolve_active_alerts(
            db,
            sensor_id=sensor.sensor_id,
            alert_type=AlertType.HIGH_WATER.value,
            resolved_at=reading.recorded_at,
        )
        return None

    threshold_value = sensor.warning_level if status == "warning" else sensor.danger_level
    severity = "high" if status == "warning" else "critical"
    condition = get_sensor_threshold_condition(sensor)
    threshold_text = f"{float(threshold_value):.2f} cm" if threshold_value is not None else "未配置"
    message = (
        f"传感器 {sensor.sensor_id} 当前测距 {float(reading.water_level):.2f} cm，"
        f"已达到{'预警' if status == 'warning' else '危险'}阈值 {threshold_text}"
        f"（{get_threshold_condition_label(condition)}）"
    )
    details = {
        "status": status,
        "water_level": float(reading.water_level),
        "threshold_value": float(threshold_value) if threshold_value is not None else None,
        "threshold_condition": condition,
        "threshold_condition_label": get_threshold_condition_label(condition),
        "reading_id": reading.id,
        "recorded_at": reading.recorded_at.isoformat(),
    }
    return await _upsert_active_alert(
        db,
        control_db,
        sensor=sensor,
        reading=reading,
        alert_type=AlertType.HIGH_WATER.value,
        severity=severity,
        message=message,
        details=details,
    )


async def _handle_immersion_alerts(
    db: AsyncSession,
    control_db: AsyncSession,
    *,
    sensor: Sensor,
    reading: SensorReading,
) -> Optional[Alert]:
    water_detected = bool(reading.water_detected)
    reading.status = "warning" if water_detected else "normal"

    if not water_detected:
        await _resolve_active_alerts(
            db,
            sensor_id=sensor.sensor_id,
            alert_type=AlertType.WATER_DETECTED.value,
            resolved_at=reading.recorded_at,
        )
        return None

    message = f"传感器 {sensor.sensor_id} 在 {sensor.location or '未知位置'} 检测到浸水。"
    details = {
        "water_detected": True,
        "duration": reading.duration,
        "severity": reading.severity,
        "reading_id": reading.id,
        "recorded_at": reading.recorded_at.isoformat(),
    }
    return await _upsert_active_alert(
        db,
        control_db,
        sensor=sensor,
        reading=reading,
        alert_type=AlertType.WATER_DETECTED.value,
        severity="critical",
        message=message,
        details=details,
    )
