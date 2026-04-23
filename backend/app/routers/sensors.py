"""Sensor data API routes."""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_control_db, get_db
from app.models import Sensor, SensorReading, SensorType, ReportMethod, WebhookGroup
from app.schemas import (
    SensorCreate, SensorUpdate, SensorResponse,
    SensorDataInput, SensorReadingResponse, SensorReadingList,
    SensorStatus, SensorTimeSeries, TimeSeriesPoint,
    WebhookDataInput, GroupWebhookDataInput,
    WebhookGroupCreate, WebhookGroupUpdate, WebhookGroupResponse, WebhookGroupDetail,
    normalize_datetime_to_utc_naive,
)
from app.services.alerting import (
    get_threshold_configuration_error,
    handle_sensor_reading_alerts,
    infer_ultrasonic_status,
    is_threshold_configuration_valid,
)
from app.services.auth import get_current_user, require_roles
from app.services.system_config import get_offline_timeout_minutes
import uuid

router = APIRouter(prefix="/sensors", tags=["sensors"])
require_sensor_manager = require_roles("super_admin", "admin")

WEBHOOK_REPORT_METHODS = {
    ReportMethod.WEBHOOK.value,
    ReportMethod.MQTT.value,
    ReportMethod.COAP.value,
}

MEASUREMENT_UNIT_CM = "cm"
MEASUREMENT_UNIT_MM = "mm"


def generate_webhook_token() -> str:
    """Generate a short webhook token for externally pushed sensors."""
    return uuid.uuid4().hex[:16]


def get_sensor_type_value(sensor_type: SensorType | str) -> str:
    """Return the plain string value for a SQLAlchemy enum-backed sensor type."""
    return sensor_type.value if isinstance(sensor_type, SensorType) else str(sensor_type)


def get_measurement_unit(sensor: Sensor) -> str:
    """Return the configured raw ultrasonic measurement unit."""
    unit = getattr(sensor, "measurement_unit", None)
    return unit if unit in {MEASUREMENT_UNIT_CM, MEASUREMENT_UNIT_MM} else MEASUREMENT_UNIT_CM


def normalize_water_level(sensor: Sensor, value: Decimal | float | int | str) -> Decimal:
    """Convert the incoming ultrasonic reading into centimeters for storage."""
    measurement = value if isinstance(value, Decimal) else Decimal(str(value))
    if get_measurement_unit(sensor) == MEASUREMENT_UNIT_MM:
        return measurement / Decimal("10")
    return measurement


def prepare_sensor_payload(sensor_data: dict, existing_sensor: Optional[Sensor] = None) -> dict:
    """Normalize sensor config before persisting it."""
    report_method = sensor_data.get("report_method")
    webhook_token = sensor_data.get("webhook_token")
    webhook_group_id = sensor_data.get("webhook_group_id")
    webhook_group_token = sensor_data.get("webhook_group_token")
    device_imei = sensor_data.get("device_imei")
    measurement_unit = sensor_data.get("measurement_unit")

    if isinstance(webhook_token, str):
        webhook_token = webhook_token.strip() or None
        sensor_data["webhook_token"] = webhook_token
    if webhook_group_id == "":
        webhook_group_id = None
    if webhook_group_id is not None:
        sensor_data["webhook_group_id"] = webhook_group_id
    if isinstance(webhook_group_token, str):
        webhook_group_token = webhook_group_token.strip() or None
        sensor_data["webhook_group_token"] = webhook_group_token
    if isinstance(device_imei, str):
        device_imei = device_imei.strip() or None
        sensor_data["device_imei"] = device_imei
    if isinstance(measurement_unit, str):
        sensor_data["measurement_unit"] = measurement_unit.strip() or MEASUREMENT_UNIT_CM

    current_token = existing_sensor.webhook_token if existing_sensor else None
    current_group_id = existing_sensor.webhook_group_id if existing_sensor else None
    current_group_token = existing_sensor.webhook_group_token if existing_sensor else None

    if sensor_data.get("webhook_group_id") or current_group_id:
        sensor_data["webhook_group_id"] = sensor_data.get("webhook_group_id") or current_group_id
        sensor_data["report_method"] = ReportMethod.WEBHOOK.value
        sensor_data["webhook_token"] = None
        sensor_data["webhook_group_token"] = None
    elif report_method in WEBHOOK_REPORT_METHODS:
        sensor_data["webhook_token"] = webhook_token or current_token or generate_webhook_token()
        sensor_data["webhook_group_id"] = None
        sensor_data["webhook_group_token"] = None
    elif report_method == ReportMethod.UDP_BINARY.value:
        sensor_data["webhook_token"] = None
        sensor_data["webhook_group_id"] = webhook_group_id or current_group_id
        sensor_data["webhook_group_token"] = webhook_group_token or current_group_token or generate_webhook_token()
    elif report_method is not None:
        sensor_data["webhook_token"] = None
        sensor_data["webhook_group_id"] = None
        sensor_data["webhook_group_token"] = None

    return sensor_data


def validate_sensor_payload(sensor_data: dict, existing_sensor: Optional[Sensor] = None) -> None:
    """Validate combinations of sensor settings that the current system supports."""
    report_method = sensor_data.get("report_method", existing_sensor.report_method if existing_sensor else None)
    webhook_group_id = sensor_data.get("webhook_group_id", existing_sensor.webhook_group_id if existing_sensor else None)
    device_imei = sensor_data.get("device_imei", existing_sensor.device_imei if existing_sensor else None)
    sensor_type = sensor_data.get("sensor_type", existing_sensor.sensor_type if existing_sensor else None)
    warning_level = sensor_data.get("warning_level", existing_sensor.warning_level if existing_sensor else None)
    danger_level = sensor_data.get("danger_level", existing_sensor.danger_level if existing_sensor else None)
    threshold_condition = sensor_data.get(
        "threshold_condition",
        existing_sensor.threshold_condition if existing_sensor else None,
    )

    if report_method == ReportMethod.UDP_BINARY.value and not device_imei:
        raise HTTPException(status_code=400, detail="UDP binary group webhook requires a bound device IMEI")
    if webhook_group_id and not device_imei:
        raise HTTPException(status_code=400, detail="Grouped sensors require a bound device IMEI")
    if sensor_type == SensorType.ULTRASONIC.value and not is_threshold_configuration_valid(
        warning_level,
        danger_level,
        threshold_condition,
    ):
        raise HTTPException(status_code=400, detail=get_threshold_configuration_error(threshold_condition))


def extract_device_imei(payload: GroupWebhookDataInput) -> Optional[str]:
    """Return the best-effort IMEI from group webhook payloads."""
    for value in (payload.device_imei, payload.imei, payload.device_id):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_water_detected(payload: GroupWebhookDataInput) -> Optional[bool]:
    """Normalize water detection from the proxy payload."""
    if payload.water_detected is not None:
        return bool(payload.water_detected)
    if payload.water_status is not None:
        return bool(payload.water_status)
    if payload.water_status_text:
        return payload.water_status_text.strip() in {"有水", "浸水", "wet", "true", "1"}
    return None


def extract_group_water_level(payload: GroupWebhookDataInput) -> Optional[float]:
    """Normalize the measurement field used for ultrasonic sensors."""
    for value in (payload.water_level, payload.measurement_value, payload.sensor_value):
        if value is not None:
            return float(value)
    if payload.adc_raw is not None:
        return float(payload.adc_raw)
    return None


def get_recorded_at(timestamp: Optional[datetime]) -> datetime:
    """Normalize inbound timestamps before comparing or persisting them."""
    return normalize_datetime_to_utc_naive(timestamp) or datetime.utcnow()


def build_group_sensor_reading(sensor: Sensor, payload: GroupWebhookDataInput, device_imei: str) -> SensorReading:
    """Convert a group webhook payload into a normalized reading."""
    sensor_type = get_sensor_type_value(sensor.sensor_type)
    recorded_at = get_recorded_at(payload.timestamp)
    raw_data = payload.model_dump(mode="json", exclude_none=True)
    raw_data["device_imei"] = device_imei

    if sensor_type == SensorType.ULTRASONIC.value:
        raw_water_level = extract_group_water_level(payload)
        if raw_water_level is None:
            raise HTTPException(status_code=422, detail="Ultrasonic group webhook data requires water_level or another measurement field")
        water_level = normalize_water_level(sensor, raw_water_level)
        raw_data["measurement_unit"] = get_measurement_unit(sensor)
        raw_data["normalized_water_level_cm"] = float(water_level)
        status = infer_ultrasonic_status(sensor, float(water_level), fallback_status=payload.status)
        return SensorReading(
            sensor_id=sensor.sensor_id,
            sensor_type=sensor_type,
            status=status,
            water_level=water_level,
            raw_data=raw_data,
            recorded_at=recorded_at,
        )

    water_detected = extract_water_detected(payload)
    if water_detected is None:
        raise HTTPException(status_code=422, detail="Immersion group webhook data requires water status")
    status = payload.status or ("warning" if water_detected else "normal")
    return SensorReading(
        sensor_id=sensor.sensor_id,
        sensor_type=sensor_type,
        status=status,
        water_detected=water_detected,
        raw_data=raw_data,
        recorded_at=recorded_at,
    )


def serialize_group(group: WebhookGroup) -> WebhookGroupDetail:
    """Build a webhook group response including its member sensors."""
    return WebhookGroupDetail(
        id=group.id,
        name=group.name,
        description=group.description,
        webhook_token=group.webhook_token,
        is_active=group.is_active,
        created_at=group.created_at,
        updated_at=group.updated_at,
        sensors=list(group.sensors),
    )


@router.get("/groups", response_model=List[WebhookGroupDetail])
async def list_webhook_groups(
    _: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List webhook groups with their member sensors."""
    result = await db.execute(
        select(WebhookGroup)
        .options(selectinload(WebhookGroup.sensors))
        .order_by(WebhookGroup.created_at.desc())
    )
    groups = result.scalars().unique().all()
    return [serialize_group(group) for group in groups]


@router.post("/groups", response_model=WebhookGroupResponse, status_code=201)
async def create_webhook_group(
    group: WebhookGroupCreate,
    _: dict = Depends(require_sensor_manager),
    db: AsyncSession = Depends(get_db),
):
    """Create a standalone webhook group."""
    token = (group.webhook_token or generate_webhook_token()).strip()
    token_result = await db.execute(select(WebhookGroup).where(WebhookGroup.webhook_token == token))
    if token_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Webhook group token already exists")

    db_group = WebhookGroup(
        name=group.name,
        description=group.description,
        webhook_token=token,
        is_active=group.is_active,
    )
    db.add(db_group)
    await db.commit()
    await db.refresh(db_group)
    return db_group


@router.patch("/groups/{group_id}", response_model=WebhookGroupResponse)
async def update_webhook_group(
    group_id: int,
    group_update: WebhookGroupUpdate,
    _: dict = Depends(require_sensor_manager),
    db: AsyncSession = Depends(get_db),
):
    """Update a webhook group."""
    result = await db.execute(select(WebhookGroup).where(WebhookGroup.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Webhook group not found")

    update_data = group_update.model_dump(exclude_unset=True)
    token = update_data.get("webhook_token")
    if token:
        token = token.strip()
        token_result = await db.execute(
            select(WebhookGroup).where(and_(WebhookGroup.webhook_token == token, WebhookGroup.id != group_id))
        )
        if token_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Webhook group token already exists")
        update_data["webhook_token"] = token

    for field, value in update_data.items():
        setattr(group, field, value)

    await db.commit()
    await db.refresh(group)
    return group


@router.delete("/groups/{group_id}", status_code=204)
async def delete_webhook_group(
    group_id: int,
    _: dict = Depends(require_sensor_manager),
    db: AsyncSession = Depends(get_db),
):
    """Delete a webhook group and detach member sensors."""
    result = await db.execute(select(WebhookGroup).where(WebhookGroup.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Webhook group not found")

    sensors_result = await db.execute(select(Sensor).where(Sensor.webhook_group_id == group_id))
    sensors = sensors_result.scalars().all()
    for sensor in sensors:
        sensor.report_method = ReportMethod.HTTP_API.value
        sensor.webhook_group_id = None
        sensor.webhook_group_token = None
        sensor.device_imei = None

    await db.delete(group)
    await db.commit()


def build_sensor_reading(sensor: Sensor, payload: SensorDataInput | WebhookDataInput) -> SensorReading:
    """Convert sensor payloads into a normalized reading model."""
    sensor_type = get_sensor_type_value(sensor.sensor_type)
    recorded_at = get_recorded_at(payload.timestamp)
    reading_data = {
        "sensor_id": sensor.sensor_id,
        "sensor_type": sensor_type,
        "status": payload.status,
        "recorded_at": recorded_at,
        "raw_data": payload.model_dump(mode="json", exclude_none=True),
    }

    if sensor_type == SensorType.ULTRASONIC.value:
        if payload.water_level is None:
            raise HTTPException(status_code=422, detail="Ultrasonic sensor data requires water_level")
        water_level = normalize_water_level(sensor, payload.water_level)
        reading_data["raw_data"]["measurement_unit"] = get_measurement_unit(sensor)
        reading_data["raw_data"]["normalized_water_level_cm"] = float(water_level)
        reading_data["status"] = infer_ultrasonic_status(
            sensor,
            float(water_level),
            fallback_status=payload.status,
        )
        reading_data.update({
            "water_level": water_level,
            "battery_level": payload.battery_level,
            "signal_strength": payload.signal_strength,
        })
    else:
        if payload.water_detected is None:
            raise HTTPException(status_code=422, detail="Immersion sensor data requires water_detected")
        reading_data["status"] = "warning" if payload.water_detected else (payload.status or "normal")
        reading_data.update({
            "water_detected": payload.water_detected,
            "duration": payload.duration,
            "severity": payload.severity,
            "battery_level": payload.battery_level,
            "signal_strength": payload.signal_strength,
        })

    return SensorReading(**reading_data)


@router.get("/", response_model=List[SensorResponse])
async def list_sensors(
    sensor_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    _: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all sensors with optional filtering."""
    query = select(Sensor).options(selectinload(Sensor.webhook_group))
    
    if sensor_type:
        query = query.where(Sensor.sensor_type == sensor_type)
    if is_active is not None:
        query = query.where(Sensor.is_active == is_active)
    
    result = await db.execute(query.order_by(Sensor.created_at.desc()))
    return result.scalars().all()


@router.get("/{sensor_id}", response_model=SensorResponse)
async def get_sensor(
    sensor_id: str,
    _: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific sensor by ID."""
    result = await db.execute(
        select(Sensor).options(selectinload(Sensor.webhook_group)).where(Sensor.sensor_id == sensor_id)
    )
    sensor = result.scalar_one_or_none()
    
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")
    return sensor


@router.post("/", response_model=SensorResponse, status_code=201)
async def create_sensor(
    sensor: SensorCreate,
    _: dict = Depends(require_sensor_manager),
    db: AsyncSession = Depends(get_db),
):
    """Create a new sensor."""
    # Check if sensor_id already exists
    result = await db.execute(select(Sensor).where(Sensor.sensor_id == sensor.sensor_id))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Sensor ID already exists")
    
    sensor_data = prepare_sensor_payload(sensor.model_dump())
    validate_sensor_payload(sensor_data)

    webhook_group_id = sensor_data.get("webhook_group_id")
    if webhook_group_id:
        group_result = await db.execute(select(WebhookGroup).where(WebhookGroup.id == webhook_group_id))
        group = group_result.scalar_one_or_none()
        if not group:
            raise HTTPException(status_code=400, detail="Webhook group not found")
        sensor_data["webhook_group_token"] = group.webhook_token

    webhook_token = sensor_data.get("webhook_token")
    if webhook_token:
        token_result = await db.execute(select(Sensor).where(Sensor.webhook_token == webhook_token))
        if token_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Webhook token already exists")

    device_imei = sensor_data.get("device_imei")
    if device_imei:
        imei_result = await db.execute(select(Sensor).where(Sensor.device_imei == device_imei))
        if imei_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Device IMEI already bound to another sensor")
    
    db_sensor = Sensor(**sensor_data)
    db.add(db_sensor)
    await db.commit()
    result = await db.execute(
        select(Sensor).options(selectinload(Sensor.webhook_group)).where(Sensor.id == db_sensor.id)
    )
    return result.scalar_one()


@router.patch("/{sensor_id}", response_model=SensorResponse)
async def update_sensor(
    sensor_id: str, 
    sensor_update: SensorUpdate, 
    _: dict = Depends(require_sensor_manager),
    db: AsyncSession = Depends(get_db)
):
    """Update a sensor configuration."""
    result = await db.execute(select(Sensor).where(Sensor.sensor_id == sensor_id))
    sensor = result.scalar_one_or_none()
    
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")
    
    update_data = prepare_sensor_payload(sensor_update.model_dump(exclude_unset=True), existing_sensor=sensor)
    validate_sensor_payload(update_data, existing_sensor=sensor)

    webhook_group_id = update_data.get("webhook_group_id")
    if webhook_group_id:
        group_result = await db.execute(select(WebhookGroup).where(WebhookGroup.id == webhook_group_id))
        group = group_result.scalar_one_or_none()
        if not group:
            raise HTTPException(status_code=400, detail="Webhook group not found")
        update_data["webhook_group_token"] = group.webhook_token

    webhook_token = update_data.get("webhook_token")
    if webhook_token:
        token_result = await db.execute(
            select(Sensor).where(
                and_(Sensor.webhook_token == webhook_token, Sensor.sensor_id != sensor_id)
            )
        )
        if token_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Webhook token already exists")

    device_imei = update_data.get("device_imei")
    if device_imei:
        imei_result = await db.execute(
            select(Sensor).where(
                and_(Sensor.device_imei == device_imei, Sensor.sensor_id != sensor_id)
            )
        )
        if imei_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Device IMEI already bound to another sensor")
    
    for field, value in update_data.items():
        setattr(sensor, field, value)
    
    await db.commit()
    result = await db.execute(
        select(Sensor).options(selectinload(Sensor.webhook_group)).where(Sensor.id == sensor.id)
    )
    return result.scalar_one()


@router.delete("/{sensor_id}", status_code=204)
async def delete_sensor(
    sensor_id: str,
    _: dict = Depends(require_sensor_manager),
    db: AsyncSession = Depends(get_db),
):
    """Delete a sensor."""
    result = await db.execute(select(Sensor).where(Sensor.sensor_id == sensor_id))
    sensor = result.scalar_one_or_none()
    
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")
    
    await db.delete(sensor)
    await db.commit()


@router.post("/data", response_model=dict, status_code=201)
async def receive_sensor_data(
    data: SensorDataInput,
    db: AsyncSession = Depends(get_db),
    control_db: AsyncSession = Depends(get_control_db),
):
    """Receive sensor data from devices."""
    # Check if sensor exists
    result = await db.execute(select(Sensor).where(Sensor.sensor_id == data.sensor_id))
    sensor = result.scalar_one_or_none()
    
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not registered")
    
    if not sensor.is_active:
        raise HTTPException(status_code=400, detail="Sensor is inactive")

    registered_type = get_sensor_type_value(sensor.sensor_type)
    if data.sensor_type != registered_type:
        raise HTTPException(status_code=400, detail="Sensor type does not match registered sensor")

    reading = build_sensor_reading(sensor, data)
    db.add(reading)
    await db.flush()
    await handle_sensor_reading_alerts(
        db,
        control_db,
        sensor=sensor,
        reading=reading,
    )
    await db.commit()
    await db.refresh(reading)
    
    return {
        "success": True,
        "message": "Data received successfully",
        "reading_id": reading.id
    }


@router.get("/status/all", response_model=List[SensorStatus])
async def get_all_sensors_status(
    _: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    control_db: AsyncSession = Depends(get_control_db),
):
    """Get current status of all sensors."""
    # Get all sensors with their latest reading
    query = select(Sensor).where(Sensor.is_active == True)
    result = await db.execute(query)
    sensors = result.scalars().all()
    
    offline_timeout_minutes = await get_offline_timeout_minutes(control_db)
    offline_threshold = datetime.utcnow() - timedelta(minutes=offline_timeout_minutes)
    statuses = []
    
    for sensor in sensors:
        # Get latest reading
        reading_query = select(SensorReading).where(
            SensorReading.sensor_id == sensor.sensor_id
        ).order_by(desc(SensorReading.recorded_at)).limit(1)
        
        reading_result = await db.execute(reading_query)
        latest_reading = reading_result.scalar_one_or_none()
        
        is_online = (
            latest_reading is not None and 
            latest_reading.recorded_at > offline_threshold
        )
        
        statuses.append(SensorStatus(
            sensor_id=sensor.sensor_id,
            sensor_type=get_sensor_type_value(sensor.sensor_type),
            location=sensor.location,
            status=latest_reading.status if latest_reading else "offline",
            last_reading=latest_reading.recorded_at if latest_reading else None,
            battery_level=latest_reading.battery_level if latest_reading else None,
            external_powered=latest_reading.external_powered if latest_reading else False,
            water_level=latest_reading.water_level if latest_reading else None,
            water_detected=latest_reading.water_detected if latest_reading else None,
            is_online=is_online
        ))
    
    return statuses


@router.post("/webhook/{token}", response_model=dict, status_code=201)
async def receive_webhook_data(
    token: str,
    data: WebhookDataInput,
    db: AsyncSession = Depends(get_db),
    control_db: AsyncSession = Depends(get_control_db),
):
    """Receive sensor data via webhook token."""
    result = await db.execute(select(Sensor).where(Sensor.webhook_token == token))
    sensor = result.scalar_one_or_none()

    if not sensor:
        raise HTTPException(status_code=404, detail="Invalid webhook token")

    if not sensor.is_active:
        raise HTTPException(status_code=400, detail="Sensor is inactive")

    reading = build_sensor_reading(sensor, data)
    db.add(reading)
    await db.flush()
    await handle_sensor_reading_alerts(
        db,
        control_db,
        sensor=sensor,
        reading=reading,
    )
    await db.commit()
    await db.refresh(reading)

    return {
        "success": True,
        "message": "Data received successfully",
        "sensor_id": sensor.sensor_id,
        "reading_id": reading.id
    }


@router.post("/group-webhook/{token}", response_model=dict, status_code=201)
async def receive_group_webhook_data(
    token: str,
    data: GroupWebhookDataInput,
    db: AsyncSession = Depends(get_db),
    control_db: AsyncSession = Depends(get_control_db),
):
    """Receive a shared webhook payload and route it to a sensor via device IMEI."""
    device_imei = extract_device_imei(data)
    if not device_imei:
        raise HTTPException(status_code=422, detail="Group webhook data requires device IMEI")

    group_result = await db.execute(select(WebhookGroup).where(WebhookGroup.webhook_token == token))
    group = group_result.scalar_one_or_none()
    if not group or not group.is_active:
        raise HTTPException(status_code=404, detail="Webhook group not found")

    result = await db.execute(
        select(Sensor).where(
            and_(
                Sensor.webhook_group_id == group.id,
                Sensor.device_imei == device_imei,
            )
        )
    )
    sensor = result.scalar_one_or_none()

    if not sensor:
        raise HTTPException(status_code=404, detail="No sensor binding found for this IMEI in the webhook group")

    if not sensor.is_active:
        raise HTTPException(status_code=400, detail="Sensor is inactive")

    reading = build_group_sensor_reading(sensor, data, device_imei)
    db.add(reading)
    await db.flush()
    await handle_sensor_reading_alerts(
        db,
        control_db,
        sensor=sensor,
        reading=reading,
    )
    await db.commit()
    await db.refresh(reading)

    return {
        "success": True,
        "message": "Group webhook data received successfully",
        "sensor_id": sensor.sensor_id,
        "device_imei": device_imei,
        "reading_id": reading.id,
    }


@router.get("/{sensor_id}/readings", response_model=SensorReadingList)
async def get_sensor_readings(
    sensor_id: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = Query(100, ge=1, le=10000),
    page: int = Query(1, ge=1),
    _: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get readings for a specific sensor with time range filtering."""
    result = await db.execute(select(Sensor).where(Sensor.sensor_id == sensor_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Sensor not found")

    query = select(SensorReading).where(SensorReading.sensor_id == sensor_id)
    start_time = normalize_datetime_to_utc_naive(start_time)
    end_time = normalize_datetime_to_utc_naive(end_time)

    if start_time:
        query = query.where(SensorReading.recorded_at >= start_time)
    if end_time:
        query = query.where(SensorReading.recorded_at <= end_time)

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    offset = (page - 1) * limit
    query = query.order_by(desc(SensorReading.recorded_at)).offset(offset).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": limit
    }


@router.get("/{sensor_id}/timeseries", response_model=SensorTimeSeries)
async def get_sensor_timeseries(
    sensor_id: str,
    field: str = Query("water_level", pattern="^(water_level|battery_level|signal_strength|water_detected)$"),
    hours: int = Query(24, ge=1, le=168),
    _: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get time series data for a sensor (for charting)."""
    result = await db.execute(select(Sensor).where(Sensor.sensor_id == sensor_id))
    sensor = result.scalar_one_or_none()

    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")

    start_time = datetime.utcnow() - timedelta(hours=hours)

    query = select(
        SensorReading.recorded_at,
        getattr(SensorReading, field)
    ).where(
        and_(
            SensorReading.sensor_id == sensor_id,
            SensorReading.recorded_at >= start_time
        )
    ).order_by(SensorReading.recorded_at)

    result = await db.execute(query)
    rows = result.all()

    data = [TimeSeriesPoint(timestamp=row[0], value=row[1]) for row in rows]

    return SensorTimeSeries(
        sensor_id=sensor_id,
        sensor_type=get_sensor_type_value(sensor.sensor_type),
        location=sensor.location,
        data=data
    )
