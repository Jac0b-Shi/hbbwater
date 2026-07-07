"""Pydantic schemas for request/response validation."""
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Union
from decimal import Decimal
import math
from pydantic import BaseModel, Field, field_validator, model_validator


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
    threshold_status: Optional[str] = Field(default=None, pattern="^(provisional|empirical|surveyed|approved|unknown)$")
    threshold_source: Optional[str] = Field(None, max_length=100)
    threshold_version: Optional[str] = Field(None, max_length=50)
    threshold_updated_at: Optional[datetime] = None
    threshold_note: Optional[str] = None
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
    threshold_status: Optional[str] = Field(default=None, pattern="^(provisional|empirical|surveyed|approved|unknown)$")
    threshold_source: Optional[str] = Field(None, max_length=100)
    threshold_version: Optional[str] = Field(None, max_length=50)
    threshold_updated_at: Optional[datetime] = None
    threshold_note: Optional[str] = None
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

class ForecastPumpParams(BaseModel):
    """Strict schema for pump scenario parameters."""

    model_config = {"extra": "forbid"}

    pump_trigger_anchor: str = Field(default="warning", pattern="^(warning|danger)$")
    pump_trigger_offset_mm: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    scenario_pump_count: int = Field(default=2, ge=0, le=3)
    net_drawdown_by_pump_count_cm_per_h: Dict[str, Optional[float]] = Field(
        default_factory=lambda: {"0": 0.0, "1": None, "2": 6.23, "3": None},
    )
    drawdown_parameter_status: Dict[str, Optional[str]] = Field(
        default_factory=lambda: {"0": "defined", "1": "unknown", "2": "inferred", "3": "unknown"},
    )
    calibration_version: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_pump_on_rise_mm(cls, values: Any) -> Any:
        """Migrate legacy pump_params into the anchor/offset/count model.

        pump_on_rise_mm cannot be represented exactly in the new absolute-
        threshold model, so it is converted to the current safe default:
        warning anchor, zero offset, two-pump scenario.

        Previous versions also allowed 1 or 3 pumps; q1/q3 are not yet
        calibrated, so those counts are normalized to 2.
        """
        if not isinstance(values, dict):
            return values
        values = dict(values)
        if "pump_on_rise_mm" in values:
            values.pop("pump_on_rise_mm", None)
            values.setdefault("pump_trigger_anchor", "warning")
            values.setdefault("pump_trigger_offset_mm", 0.0)
            values.setdefault("scenario_pump_count", 2)
        count = values.get("scenario_pump_count")
        try:
            count = int(count) if count is not None else 2
        except (TypeError, ValueError):
            count = 2
        if count not in (0, 2):
            values["scenario_pump_count"] = 2
        return values

    @field_validator("net_drawdown_by_pump_count_cm_per_h", mode="after")
    @classmethod
    def validate_drawdown_table(cls, v: Dict[str, Optional[float]]) -> Dict[str, Optional[float]]:
        for key in ("0", "1", "2", "3"):
            if key not in v:
                raise ValueError(f"net_drawdown_by_pump_count_cm_per_h must include pump count {key}")
            value = v.get(key)
            if value is not None:
                if not isinstance(value, (int, float)):
                    raise ValueError(f"drawdown for pump count {key} must be a number or null")
                if value < 0:
                    raise ValueError(f"drawdown for pump count {key} must be non-negative or null")
            if key == "0" and value != 0:
                raise ValueError("drawdown for pump count 0 must be exactly 0")
        # Adjacent non-null values must be strictly increasing.
        qs = [v.get(str(i)) for i in range(1, 4)]
        non_null = [(i, q) for i, q in enumerate(qs, start=1) if q is not None]
        for i in range(len(non_null) - 1):
            if non_null[i][1] >= non_null[i + 1][1]:
                raise ValueError(f"q{non_null[i][0]} must be less than q{non_null[i + 1][0]}")
        return v


class ForecastModelParams(BaseModel):
    """Strict schema for heuristic forecast model parameters."""

    model_config = {"extra": "forbid"}

    lambda_decay: float = Field(default=0.97, ge=0, le=1)
    watch_rise_mm: float = Field(default=80.0, ge=0)
    warning_rise_mm: float = Field(default=120.0, ge=0)
    critical_rise_mm: float = Field(default=250.0, ge=0)
    pump_assumption: str = Field(default="inferred_q2", pattern="^(inferred_q2|measured_q2|none)$")
    forecast_gap_ratio_threshold: float = Field(default=0.25, ge=0, le=1)

    @model_validator(mode="after")
    def validate_rise_order(self):
        if not (self.watch_rise_mm < self.warning_rise_mm < self.critical_rise_mm):
            raise ValueError("watch_rise_mm < warning_rise_mm < critical_rise_mm is required")
        return self


class SensorConsistencyModelConfig(BaseModel):
    model_config = {"extra": "forbid"}

    reference_sensor_id: str = Field(..., max_length=50)
    target_sensor_id: str = Field(..., max_length=50)
    slope: float = Field(..., allow_inf_nan=False)
    intercept_cm: float = Field(..., allow_inf_nan=False)
    normal_abs_residual_cm: float = Field(default=0.5, gt=0, allow_inf_nan=False)
    warning_abs_residual_cm: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    median_abs_residual_cm: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    p95_abs_residual_cm: Optional[float] = Field(None, ge=0, allow_inf_nan=False)
    calibration_sample_size: Optional[int] = Field(None, ge=0)
    calibration_version: Optional[str] = Field(None, max_length=50)
    is_enabled: bool = True

    @field_validator(
        "slope",
        "intercept_cm",
        "normal_abs_residual_cm",
        "warning_abs_residual_cm",
        "median_abs_residual_cm",
        "p95_abs_residual_cm",
    )
    @classmethod
    def validate_finite_number(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not math.isfinite(value):
            raise ValueError("numeric values must be finite")
        return value

    @model_validator(mode="after")
    def validate_model(self):
        if self.reference_sensor_id == self.target_sensor_id:
            raise ValueError("reference_sensor_id and target_sensor_id must be different")
        if self.normal_abs_residual_cm >= self.warning_abs_residual_cm:
            raise ValueError("normal_abs_residual_cm must be strictly less than warning_abs_residual_cm")
        return self


class ForecastAlertGlobalConfig(BaseModel):
    enabled: bool = False
    cooldown_minutes: int = Field(default=120, ge=5, le=1440)
    default_horizon_hours: int = Field(default=6, ge=1, le=24)
    model_params: Dict[str, Any] = Field(default_factory=dict)
    sensor_consistency_models: List[SensorConsistencyModelConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_sensor_consistency_pairs(self):
        seen_pairs: set[tuple[str, str]] = set()
        for model in self.sensor_consistency_models:
            pair = tuple(sorted((model.reference_sensor_id, model.target_sensor_id)))
            if pair in seen_pairs:
                raise ValueError(
                    "duplicate sensor consistency pair is not allowed, including reverse direction"
                )
            seen_pairs.add(pair)
        return self

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
                if value is not None:
                    if not isinstance(value, (int, float)):
                        raise ValueError(f"drawdown for pump count {key} must be a number or null")
                    if value < 0:
                        raise ValueError(f"drawdown for pump count {key} must be non-negative or null")
                if key == "0" and value != 0:
                    raise ValueError("drawdown for pump count 0 must be exactly 0")
            qs = [drawdown.get(str(i)) for i in range(1, 4)]
            non_null = [(i, q) for i, q in enumerate(qs, start=1) if q is not None]
            for i in range(len(non_null) - 1):
                if non_null[i][1] >= non_null[i + 1][1]:
                    raise ValueError(f"q{non_null[i][0]} must be less than q{non_null[i + 1][0]}")

        # Validate lambda_decay
        if "lambda_decay" in v:
            ld = v["lambda_decay"]
            if not isinstance(ld, (int, float)) or not (0.0 <= ld <= 1.0):
                raise ValueError("lambda_decay must be between 0 and 1")

        # Validate pump_assumption
        if "pump_assumption" in v:
            if v["pump_assumption"] not in ("inferred_q2", "measured_q2", "none"):
                raise ValueError("pump_assumption must be inferred_q2, measured_q2, or none")

        # Validate forecast_gap_ratio_threshold
        if "forecast_gap_ratio_threshold" in v:
            gt = v["forecast_gap_ratio_threshold"]
            if not isinstance(gt, (int, float)) or not (0.0 <= gt <= 1.0):
                raise ValueError("forecast_gap_ratio_threshold must be between 0 and 1")

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
    model_params: Optional[ForecastModelParams] = None
    pump_params: Optional[ForecastPumpParams] = None
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
    risk_no_pump: Optional[str]
    risk_q2_scenario: Optional[str]
    policy_floor: Optional[str]
    effective_risk: Optional[str]
    policy_reason: Optional[str]
    can_auto_resolve: bool = False
    advisory_only: bool = False
    scenario_pump_count: Optional[int]
    pump_assumption: Optional[str]
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
    diagnostics: Optional[List[Dict[str, Any]]] = None
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
