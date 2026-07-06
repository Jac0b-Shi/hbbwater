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
    alert_type: str = Field(..., pattern="^(high_water|forecast_high_water|water_detected|sensor_offline|low_battery)$")
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
    station_name: Optional[str] = None
    data_type: str
    hour_time: datetime
    rainfall_mm: Decimal
    batch_time: datetime
    forecast_issued_at: Optional[datetime]
    source_endpoint: str
    raw_time_label: Optional[str] = ""
    source_updated_at: Optional[datetime]
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    revision_count: int = 0

    class Config:
        from_attributes = True


class RainfallHourlyList(BaseModel):
    items: List[RainfallHourlyResponse]
    total: int
    page: int
    page_size: int


class RainfallActualRevisionResponse(BaseModel):
    station_id: str
    station_name: Optional[str] = None
    hour_time: datetime
    old_rainfall_mm: Decimal
    new_rainfall_mm: Decimal
    previous_source_updated_at: Optional[datetime]
    source_updated_at: Optional[datetime]
    detected_at: datetime
    source_endpoint: str
    raw_time_label: Optional[str] = ""

    class Config:
        from_attributes = True


class RainfallActualRevisionList(BaseModel):
    items: List[RainfallActualRevisionResponse]
    total: int
    page: int
    page_size: int


# ==================== Forecast Alert Schemas ====================

class ForecastAlertGlobalConfig(BaseModel):
    enabled: bool = False
    cooldown_minutes: int = Field(default=120, ge=5, le=1440)
    default_horizon_hours: int = Field(default=6, ge=1, le=24)
    model_params: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("model_params")
    @classmethod
    def validate_model_params(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not v:
            return v
        # Reject legacy single-pump-capacity keys
        if "pump_capacity_mm_per_min" in v or "pump_capacity_mm_per_hour" in v:
            raise ValueError("legacy pump_capacity keys are not allowed; use net_drawdown_by_pump_count_cm_per_h")

        # Validate drawdown table
        drawdown = v.get("net_drawdown_by_pump_count_cm_per_h")
        if drawdown is not None:
            for key in ("0", "1", "2", "3"):
                if key not in drawdown:
                    raise ValueError(f"net_drawdown_by_pump_count_cm_per_h must include pump count {key}")
                value = drawdown[key]
                if value is not None and value < 0:
                    raise ValueError(f"drawdown for pump count {key} must be non-negative or null")

        # Validate lambda_decay
        if "lambda_decay" in v:
            ld = v["lambda_decay"]
            if not isinstance(ld, (int, float)) or not (0.0 <= ld <= 1.0):
                raise ValueError("lambda_decay must be between 0 and 1")

        # Validate rise thresholds
        for key in ("watch_rise_mm", "warning_rise_mm", "critical_rise_mm"):
            if key in v:
                value = v[key]
                if not isinstance(value, (int, float)) or value < 0:
                    raise ValueError(f"{key} must be a non-negative number")

        watch = v.get("watch_rise_mm", 80.0)
        warning = v.get("warning_rise_mm", 120.0)
        critical = v.get("critical_rise_mm", 250.0)
        if not (watch < warning < critical):
            raise ValueError("watch_rise_mm < warning_rise_mm < critical_rise_mm is required")
        return v


class ForecastAlertProfilePayload(BaseModel):
    sensor_id: str = Field(..., max_length=50)
    is_enabled: bool = False
    station_id: Optional[str] = Field(None, max_length=50)
    horizon_hours: int = Field(default=6, ge=1, le=24)
    warning_rise_mm: Optional[Decimal] = Field(None, ge=0)
    critical_rise_mm: Optional[Decimal] = Field(None, ge=0)
    model_params: Optional[Dict[str, Any]] = None
    pump_params: Optional[Dict[str, Any]] = None
    actuator_binding_id: Optional[str] = Field(None, max_length=100)


class ForecastAlertProfileResponse(ForecastAlertProfilePayload):
    id: Optional[int] = None
    sensor_location: Optional[str] = None
    sensor_type: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ForecastAlertConfigResponse(BaseModel):
    global_config: ForecastAlertGlobalConfig
    profiles: List[ForecastAlertProfileResponse]
    stations: List[RainfallStationResponse]


class ForecastAlertConfigUpdate(BaseModel):
    global_config: Optional[ForecastAlertGlobalConfig] = None
    profiles: List[ForecastAlertProfilePayload] = Field(default_factory=list)


class ForecastAlertEvaluateRequest(BaseModel):
    dry_run: bool = True
    sensor_ids: Optional[List[str]] = None
    horizon_hours: Optional[int] = Field(None, ge=1, le=24)


class ForecastPredictionResultResponse(BaseModel):
    id: int
    run_id: int
    sensor_id: str
    station_id: Optional[str]
    actual_station_id: Optional[str]
    forecast_station_id: Optional[str]
    rain_source_degraded: bool = False
    degraded_reason: Optional[str]
    data_status: str = "unavailable"
    risk_level: str
    model_risk: Optional[str]
    policy_floor: Optional[str]
    effective_risk: Optional[str]
    policy_reason: Optional[str]
    should_notify: bool
    notification_sent: bool
    alert_id: Optional[int]
    horizon_hours: int
    forecast_issued_at: Optional[datetime]
    peak_time: Optional[datetime]
    predicted_free_rise_mm: Optional[Decimal]
    predicted_observed_rise_mm: Optional[Decimal]
    projected_distance_cm: Optional[Decimal]
    latest_distance_cm: Optional[Decimal]
    confidence: Optional[Decimal]
    features: Optional[Dict[str, Any]]
    series: Optional[List[Dict[str, Any]]]
    control_recommendation: Optional[Dict[str, Any]]
    decision_reason: Optional[str]
    model_version: str
    created_at: datetime

    class Config:
        from_attributes = True


class ForecastPredictionRunResponse(BaseModel):
    id: int
    trigger_type: str
    dry_run: bool
    status: str
    message: Optional[str]
    forecast_issued_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_by: Optional[str]
    source: Optional[Dict[str, Any]]
    created_at: datetime
    results: List[ForecastPredictionResultResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True


class ForecastPredictionRunList(BaseModel):
    items: List[ForecastPredictionRunResponse]
    total: int
    page: int
    page_size: int


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
