"""Pydantic schemas for request/response validation."""
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Union
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator


def normalize_datetime_to_utc_naive(value: Optional[datetime]) -> Optional[datetime]:
    """Store timestamps as naive UTC to match existing database columns."""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def parse_datetime_to_utc_naive(value):
    if isinstance(value, str):
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return normalize_datetime_to_utc_naive(datetime.fromisoformat(value))
    if isinstance(value, datetime):
        return normalize_datetime_to_utc_naive(value)
    return value


# ==================== Sensor Schemas ====================

class SensorBase(BaseModel):
    sensor_id: str = Field(..., max_length=50)
    sensor_type: str = Field(..., pattern="^(ultrasonic|immersion)$")
    location: str = Field(..., max_length=100)
    description: Optional[str] = None
    warning_level: Optional[Decimal] = None
    danger_level: Optional[Decimal] = None
    threshold_condition: str = Field(default="greater_or_equal", pattern="^(greater_or_equal|less_or_equal)$")
    measurement_unit: str = Field(default="cm", pattern="^(cm|mm)$")
    water_level_baseline: Optional[Decimal] = Field(None, ge=0)
    map_x: Optional[Decimal] = Field(None, ge=0, le=100)
    map_y: Optional[Decimal] = Field(None, ge=0, le=100)
    map_locked: bool = False
    normal_interval: int = Field(default=1800, ge=60)
    alert_interval: int = Field(default=300, ge=60)
    is_active: bool = True
    report_method: str = Field(default="http_api", pattern="^(http_api|webhook|mqtt|coap|udp_binary)$")
    webhook_token: Optional[str] = Field(None, max_length=64)
    webhook_group_id: Optional[int] = None
    webhook_group_token: Optional[str] = Field(None, max_length=64)
    device_imei: Optional[str] = Field(None, max_length=32)

    @field_validator("threshold_condition", mode="before")
    @classmethod
    def default_threshold_condition(cls, value):
        return value or "greater_or_equal"

    @field_validator("measurement_unit", mode="before")
    @classmethod
    def default_measurement_unit(cls, value):
        return value or "cm"


class SensorCreate(SensorBase):
    pass


class SensorUpdate(BaseModel):
    sensor_type: Optional[str] = Field(None, pattern="^(ultrasonic|immersion)$")
    location: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    warning_level: Optional[Decimal] = None
    danger_level: Optional[Decimal] = None
    threshold_condition: Optional[str] = Field(None, pattern="^(greater_or_equal|less_or_equal)$")
    measurement_unit: Optional[str] = Field(None, pattern="^(cm|mm)$")
    water_level_baseline: Optional[Decimal] = Field(None, ge=0)
    map_x: Optional[Decimal] = Field(None, ge=0, le=100)
    map_y: Optional[Decimal] = Field(None, ge=0, le=100)
    map_locked: Optional[bool] = None
    normal_interval: Optional[int] = Field(None, ge=60)
    alert_interval: Optional[int] = Field(None, ge=60)
    is_active: Optional[bool] = None
    report_method: Optional[str] = Field(None, pattern="^(http_api|webhook|mqtt|coap|udp_binary)$")
    webhook_token: Optional[str] = Field(None, max_length=64)
    webhook_group_id: Optional[int] = None
    webhook_group_token: Optional[str] = Field(None, max_length=64)
    device_imei: Optional[str] = Field(None, max_length=32)


class SensorResponse(SensorBase):
    id: int
    webhook_group_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# ==================== Sensor Reading Schemas ====================

class UltrasonicReading(BaseModel):
    water_level: Decimal = Field(..., description="超声波读数，单位按传感器配置换算后以厘米存储")
    battery_level: Optional[Decimal] = Field(None, ge=0, le=100)
    external_powered: Optional[bool] = False
    signal_strength: Optional[int] = None


class ImmersionReading(BaseModel):
    water_detected: bool
    duration: Optional[int] = Field(None, ge=0, description="持续时间(秒)")
    severity: Optional[str] = Field(None, pattern="^(low|medium|high)$")
    external_powered: Optional[bool] = False


class SensorDataInput(BaseModel):
    sensor_id: str
    sensor_type: str = Field(..., pattern="^(ultrasonic|immersion)$")
    timestamp: Optional[datetime] = None
    status: str = Field(default="normal", pattern="^(normal|warning|danger|alarm|offline)$")
    location: Optional[str] = None
    # Ultrasonic fields
    water_level: Optional[Decimal] = None
    battery_level: Optional[Decimal] = Field(None, ge=0, le=100)
    external_powered: Optional[bool] = False
    signal_strength: Optional[int] = None
    # Immersion fields
    water_detected: Optional[bool] = None
    duration: Optional[int] = None
    severity: Optional[str] = None
    
    @field_validator('timestamp', mode='before')
    @classmethod
    def parse_timestamp(cls, v):
        return parse_datetime_to_utc_naive(v)


class WebhookDataInput(BaseModel):
    """JSON payload received via sensor webhook."""
    timestamp: Optional[datetime] = None
    status: str = Field(default="normal", pattern="^(normal|warning|danger|alarm|offline)$")
    # Ultrasonic fields
    water_level: Optional[Decimal] = None
    battery_level: Optional[Decimal] = Field(None, ge=0, le=100)
    external_powered: Optional[bool] = False
    signal_strength: Optional[int] = None
    # Immersion fields
    water_detected: Optional[bool] = None
    duration: Optional[int] = None
    severity: Optional[str] = None
    
    @field_validator('timestamp', mode='before')
    @classmethod
    def parse_timestamp(cls, v):
        return parse_datetime_to_utc_naive(v)


class GroupWebhookDataInput(BaseModel):
    """Payload received from a shared/group webhook that routes by device IMEI."""
    timestamp: Optional[datetime] = None
    sensor_type: Optional[str] = Field(None, pattern="^(ultrasonic|immersion)$")
    device_imei: Optional[str] = Field(None, max_length=32)
    imei: Optional[str] = Field(None, max_length=32)
    device_id: Optional[str] = Field(None, max_length=32)
    source: Optional[str] = None
    source_ip: Optional[str] = None
    source_port: Optional[int] = None
    event_id: Optional[str] = Field(None, max_length=64)
    msg_type: Optional[int] = None
    msg_type_name: Optional[str] = None
    water_level: Optional[Decimal] = None
    measurement_value: Optional[Decimal] = None
    sensor_value: Optional[Decimal] = None
    water_detected: Optional[bool] = None
    water_status: Optional[int] = None
    water_status_text: Optional[str] = None
    adc_raw: Optional[int] = None
    voltage: Optional[Decimal] = None
    raw_hex: Optional[str] = None
    packet_size: Optional[int] = None
    status: Optional[str] = Field(None, pattern="^(normal|warning|danger|alarm|offline)$")

    @field_validator('timestamp', mode='before')
    @classmethod
    def parse_group_timestamp(cls, v):
        return parse_datetime_to_utc_naive(v)


class SensorReadingResponse(BaseModel):
    id: int
    sensor_id: str
    sensor_type: str
    water_level: Optional[Decimal]
    water_detected: Optional[bool]
    duration: Optional[int]
    severity: Optional[str]
    status: str
    battery_level: Optional[Decimal]
    external_powered: bool = False
    signal_strength: Optional[int]
    recorded_at: datetime
    created_at: datetime
    
    class Config:
        from_attributes = True


class SensorReadingList(BaseModel):
    items: List[SensorReadingResponse]
    total: int
    page: int
    page_size: int


class WebhookGroupBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    is_active: bool = True


class WebhookGroupCreate(WebhookGroupBase):
    webhook_token: Optional[str] = Field(None, max_length=64)


class WebhookGroupUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    webhook_token: Optional[str] = Field(None, max_length=64)


class WebhookGroupResponse(WebhookGroupBase):
    id: int
    webhook_token: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WebhookGroupDetail(WebhookGroupResponse):
    sensors: List[SensorResponse]


# ==================== Alert Schemas ====================

class AlertCreate(BaseModel):
    sensor_id: str
    alert_type: str = Field(..., pattern="^(high_water|water_detected|sensor_offline|low_battery)$")
    severity: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    message: str
    details: Optional[Dict[str, Any]] = None


class AlertResponse(BaseModel):
    id: int
    sensor_id: str
    alert_type: str
    severity: str
    message: str
    details: Optional[Dict[str, Any]]
    is_resolved: bool
    resolved_at: Optional[datetime]
    resolved_by: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


class AlertResolveRequest(BaseModel):
    resolved_by: str = Field(..., max_length=50)


# ==================== Dashboard Schemas ====================

class SensorStatus(BaseModel):
    sensor_id: str
    sensor_type: str
    location: str
    status: str
    last_reading: Optional[datetime]
    battery_level: Optional[Decimal]
    external_powered: bool = False
    water_level: Optional[Decimal]
    water_detected: Optional[bool]
    is_online: bool


class DashboardStats(BaseModel):
    total_sensors: int
    online_sensors: int
    offline_sensors: int
    active_alerts: int
    today_readings: int
    ultrasonic_sensors: int
    immersion_sensors: int


class TimeSeriesPoint(BaseModel):
    timestamp: datetime
    value: Union[Decimal, int, bool, None]


class SensorTimeSeries(BaseModel):
    sensor_id: str
    sensor_type: str
    location: str
    data: List[TimeSeriesPoint]


# ==================== Weather/Rainfall Schemas ====================

class RainfallStationSummary(BaseModel):
    station_id: str
    station_name: str
    role: str
    longitude: Optional[float]
    latitude: Optional[float]
    is_active: bool
    last_success_at: Optional[datetime]
    last_error: str = ""
    is_stale: bool
    current_actual_mm: Optional[float]
    current_actual_time: Optional[datetime]
    source_updated_at: Optional[datetime]
    latest_forecast_issued_at: Optional[datetime]
    forecast_totals: Dict[str, float]


class RainfallSummary(BaseModel):
    stations: List[RainfallStationSummary]
    selected_station_id: Optional[str]
    selected_reason: str
    updated_at: datetime
    stale_after_seconds: int


class RainfallStationResponse(BaseModel):
    station_id: str
    station_name: str
    role: str
    longitude: Optional[Decimal]
    latitude: Optional[Decimal]
    is_active: bool
    last_success_at: Optional[datetime]
    last_error: Optional[str] = ""

    class Config:
        from_attributes = True


class RainfallHourlyResponse(BaseModel):
    station_id: str
    data_type: str
    hour_time: datetime
    rainfall_mm: Decimal
    batch_time: datetime
    forecast_issued_at: Optional[datetime]
    source_endpoint: str
    raw_time_label: Optional[str] = ""
    source_updated_at: Optional[datetime]

    class Config:
        from_attributes = True


# ==================== System Config Schemas ====================

class SystemConfigResponse(BaseModel):
    config_key: str
    config_value: str
    description: Optional[str]
    updated_at: datetime
    
    class Config:
        from_attributes = True


# ==================== Generic Response ====================

class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Any] = None


class HealthCheck(BaseModel):
    status: str
    version: str
    database: str
    timestamp: datetime
