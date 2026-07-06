from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, Sensor, SensorReading
from app.services.email import send_alert_email
from app.services.system_config import get_notification_config_values

WEBHOOK_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
WECOM_TEXT_LIMIT = 1800


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _normalize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    return value


def build_webhook_payload(
    event: str,
    *,
    sensor: Optional[Sensor] = None,
    alert: Optional[Alert] = None,
    reading: Optional[SensorReading] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event": event,
        "source": "hbbwater",
        "sent_at": datetime.utcnow().isoformat(),
    }

    if sensor is not None:
        payload["sensor"] = {
            "sensor_id": sensor.sensor_id,
            "sensor_type": sensor.sensor_type,
            "location": sensor.location,
            "warning_level": _normalize_value(sensor.warning_level),
            "danger_level": _normalize_value(sensor.danger_level),
            "threshold_condition": getattr(sensor, "threshold_condition", None) or "greater_or_equal",
            "measurement_unit": getattr(sensor, "measurement_unit", None) or "cm",
            "is_active": sensor.is_active,
            "report_method": sensor.report_method,
            "device_imei": sensor.device_imei,
        }

    if alert is not None:
        details = _normalize_value(alert.details)
        payload["alert"] = {
            "id": alert.id,
            "sensor_id": alert.sensor_id,
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "message": alert.message,
            "details": details,
            "is_resolved": alert.is_resolved,
            "created_at": _normalize_value(alert.created_at),
        }
        if alert.alert_type == "forecast_high_water" and isinstance(details, dict):
            payload["prediction"] = {
                key: details.get(key)
                for key in (
                    "prediction_result_id",
                    "prediction_run_id",
                    "station_id",
                    "risk_level",
                    "horizon_hours",
                    "forecast_issued_at",
                    "peak_time",
                    "predicted_free_rise_mm",
                    "predicted_observed_rise_mm",
                    "projected_distance_cm",
                    "latest_distance_cm",
                    "confidence",
                    "features",
                    "control_recommendation",
                    "model_version",
                    "decision_reason",
                )
                if key in details
            }

    if reading is not None:
        payload["reading"] = {
            "id": reading.id,
            "sensor_id": reading.sensor_id,
            "sensor_type": reading.sensor_type,
            "status": reading.status,
            "water_level": _normalize_value(reading.water_level),
            "water_detected": reading.water_detected,
            "battery_level": _normalize_value(reading.battery_level),
            "signal_strength": reading.signal_strength,
            "recorded_at": _normalize_value(reading.recorded_at),
            "raw_data": _normalize_value(reading.raw_data),
        }

    if extra:
        payload.update(_normalize_value(extra))

    return payload


def _is_wecom_webhook_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.netloc.lower() == "qyapi.weixin.qq.com"
        and parsed.path.startswith("/cgi-bin/webhook/send")
    )


def _format_wecom_text(payload: dict[str, Any]) -> str:
    lines = [
        "水浸监测系统通知",
        f"事件: {payload.get('event', '-')}",
        f"时间: {payload.get('sent_at', '-')}",
    ]

    message = payload.get("message")
    if message:
        lines.append(f"内容: {message}")

    sensor = payload.get("sensor")
    if isinstance(sensor, dict):
        lines.extend(
            [
                "",
                "设备信息",
                f"传感器: {sensor.get('sensor_id', '-')}",
                f"类型: {sensor.get('sensor_type', '-')}",
                f"位置: {sensor.get('location', '-')}",
            ]
        )

    reading = payload.get("reading")
    if isinstance(reading, dict):
        lines.extend(["", "读数信息", f"状态: {reading.get('status', '-')}"])
        if reading.get("water_level") is not None:
            lines.append(f"测距/水位: {reading.get('water_level')} cm")
        if reading.get("water_detected") is not None:
            lines.append(f"浸水: {'是' if reading.get('water_detected') else '否'}")
        if reading.get("recorded_at"):
            lines.append(f"采集时间: {reading.get('recorded_at')}")

    alert = payload.get("alert")
    if isinstance(alert, dict):
        alert_type_map = {
            "high_water": "高水位",
            "forecast_high_water": "预报高水位",
            "water_detected": "浸水检测",
            "sensor_offline": "传感器离线",
            "low_battery": "低电量",
        }
        lines.extend(
            [
                "",
                "告警信息",
                f"级别: {alert.get('severity', '-')}",
                f"类型: {alert_type_map.get(alert.get('alert_type'), alert.get('alert_type', '-'))}",
                f"消息: {alert.get('message', '-')}",
            ]
        )

    prediction = payload.get("prediction")
    if isinstance(prediction, dict):
        lines.extend(
            [
                "",
                "预报信息",
                f"雨量站: {prediction.get('station_id', '-')}",
                f"预计峰值: {prediction.get('peak_time', '-')}",
                f"无泵上涨: {prediction.get('predicted_free_rise_mm', '-')} mm",
                f"泵后上涨: {prediction.get('predicted_observed_rise_mm', '-')} mm",
                f"预计测距: {prediction.get('projected_distance_cm', '-')} cm",
            ]
        )

    text = "\n".join(lines)
    return text[:WECOM_TEXT_LIMIT]


def _build_outgoing_payload(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_payload = _normalize_value(payload)
    if not _is_wecom_webhook_url(url):
        return normalized_payload
    return {
        "msgtype": "text",
        "text": {
            "content": _format_wecom_text(normalized_payload),
        },
    }


def _extract_webhook_error(response: httpx.Response) -> Optional[str]:
    try:
        body = response.json()
    except ValueError:
        return None

    if not isinstance(body, dict) or "errcode" not in body:
        return None

    errcode = body.get("errcode")
    if errcode in (0, "0", None):
        return None
    errmsg = body.get("errmsg") or body.get("message") or "unknown error"
    return f"Webhook 返回错误 errcode={errcode}: {errmsg}"


async def send_webhook_payload(
    control_db: AsyncSession,
    payload: dict[str, Any],
) -> tuple[bool, str]:
    notify_config = await get_notification_config_values(control_db)

    if not notify_config["webhook_enabled"]:
        return False, "Webhook 通知未启用"
    if not notify_config["webhook_url"]:
        return False, "Webhook URL 未配置"

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "hbbwater/1.0",
    }

    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
            response = await client.post(
                notify_config["webhook_url"],
                json=_build_outgoing_payload(notify_config["webhook_url"], payload),
                headers=headers,
            )
            response.raise_for_status()
        webhook_error = _extract_webhook_error(response)
        if webhook_error:
            return False, webhook_error
        if _is_wecom_webhook_url(notify_config["webhook_url"]):
            return True, f"企业微信 Webhook 已发送（HTTP {response.status_code}）"
        return True, f"Webhook 已发送（HTTP {response.status_code}）"
    except Exception as exc:
        return False, f"Webhook 发送失败: {exc}"


async def send_test_webhook(control_db: AsyncSession) -> tuple[bool, str]:
    payload = build_webhook_payload(
        "notification.test",
        extra={
            "message": "这是一条来自水浸监测系统的测试 Webhook。",
            "test": True,
        },
    )
    return await send_webhook_payload(control_db, payload)


async def dispatch_alert_notifications(
    control_db: AsyncSession,
    *,
    sensor: Sensor,
    alert: Alert,
    reading: Optional[SensorReading] = None,
) -> dict[str, tuple[bool, str]]:
    email_result = await send_alert_email(
        control_db=control_db,
        alert_type=alert.alert_type,
        severity=alert.severity,
        sensor_name=sensor.sensor_id,
        location=sensor.location or "未知位置",
        message=alert.message,
    )
    webhook_result = await send_webhook_payload(
        control_db,
        build_webhook_payload(
            "alert.triggered",
            sensor=sensor,
            alert=alert,
            reading=reading,
        ),
    )
    return {
        "email": email_result,
        "webhook": webhook_result,
    }
