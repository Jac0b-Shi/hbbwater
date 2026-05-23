"""SQLAlchemy models for database tables."""
import enum
import json
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    DECIMAL,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import relationship

from app.database import BusinessBase, ControlBase


class SensorType(str, enum.Enum):
    ULTRASONIC = "ultrasonic"
    IMMERSION = "immersion"


class ReportMethod(str, enum.Enum):
    HTTP_API = "http_api"
    WEBHOOK = "webhook"
    MQTT = "mqtt"
    COAP = "coap"
    UDP_BINARY = "udp_binary"


class Status(str, enum.Enum):
    NORMAL = "normal"
    WARNING = "warning"
    DANGER = "danger"
    ALARM = "alarm"
    OFFLINE = "offline"


class Severity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertType(str, enum.Enum):
    HIGH_WATER = "high_water"
    WATER_DETECTED = "water_detected"
    SENSOR_OFFLINE = "sensor_offline"
    LOW_BATTERY = "low_battery"


class JSONText(TypeDecorator):
    """Database-portable JSON storage backed by TEXT."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value, dialect):
        if value in (None, ""):
            return None
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value


class Sensor(BusinessBase):
    __tablename__ = "sensors"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    sensor_id = Column(String(50), unique=True, nullable=False, index=True)
    sensor_type = Column(String(20), nullable=False)
    location = Column(String(100), nullable=False)
    description = Column(Text)
    warning_level = Column(DECIMAL(10, 2))
    danger_level = Column(DECIMAL(10, 2))
    threshold_condition = Column(String(32), nullable=True)
    measurement_unit = Column(String(8), default="cm")
    water_level_baseline = Column(DECIMAL(10, 2), nullable=True)
    map_x = Column(DECIMAL(6, 3), nullable=True)
    map_y = Column(DECIMAL(6, 3), nullable=True)
    map_locked = Column(Boolean, default=False)
    normal_interval = Column(Integer, default=1800)
    alert_interval = Column(Integer, default=300)
    is_active = Column(Boolean, default=True)
    report_method = Column(String(20), default="http_api")
    webhook_token = Column(String(64), unique=True, index=True, nullable=True)
    webhook_group_id = Column(Integer, ForeignKey("webhook_groups.id", ondelete="SET NULL"), nullable=True, index=True)
    webhook_group_token = Column(String(64), index=True, nullable=True)
    device_imei = Column(String(32), unique=True, index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    webhook_group = relationship("WebhookGroup", back_populates="sensors")
    readings = relationship("SensorReading", back_populates="sensor", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="sensor", cascade="all, delete-orphan")

    @property
    def webhook_group_name(self) -> Optional[str]:
        return self.webhook_group.name if self.webhook_group else None

    @property
    def effective_webhook_group_token(self) -> Optional[str]:
        if self.webhook_group:
            return self.webhook_group.webhook_token
        return self.webhook_group_token


class WebhookGroup(BusinessBase):
    __tablename__ = "webhook_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    webhook_token = Column(String(64), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sensors = relationship("Sensor", back_populates="webhook_group")


class SensorReading(BusinessBase):
    __tablename__ = "sensor_readings"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sensor_id = Column(String(50), ForeignKey("sensors.sensor_id", ondelete="CASCADE"), nullable=False)
    sensor_type = Column(String(20), nullable=False)
    # Ultrasonic fields
    water_level = Column(DECIMAL(10, 2))
    # Immersion fields
    water_detected = Column(Boolean)
    duration = Column(Integer)
    severity = Column(String(20))
    # Common fields
    status = Column(String(20), default="normal")
    battery_level = Column(DECIMAL(5, 2))
    signal_strength = Column(Integer)
    raw_data = Column(JSONText)
    recorded_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    sensor = relationship("Sensor", back_populates="readings")

    @property
    def external_powered(self) -> bool:
        raw_data = self.raw_data if isinstance(self.raw_data, dict) else {}
        return bool(raw_data.get("external_powered"))
    
    __table_args__ = (
        Index("idx_sensor_time", "sensor_id", "recorded_at"),
        Index("idx_time", "recorded_at"),
        Index("idx_status", "status"),
    )


class Alert(BusinessBase):
    __tablename__ = "alerts"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sensor_id = Column(String(50), ForeignKey("sensors.sensor_id", ondelete="CASCADE"), nullable=False)
    alert_type = Column(String(20), nullable=False)
    severity = Column(String(20), default="medium")
    message = Column(Text, nullable=False)
    details = Column(JSONText)
    is_resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime)
    resolved_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    sensor = relationship("Sensor", back_populates="alerts")
    
    __table_args__ = (
        Index("idx_sensor", "sensor_id"),
        Index("idx_type", "alert_type"),
        Index("idx_severity", "severity"),
        Index("idx_created", "created_at"),
        Index("idx_resolved", "is_resolved"),
    )


class WeatherStation(BusinessBase):
    __tablename__ = "weather_stations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    station_id = Column(String(50), unique=True, nullable=False, index=True)
    station_name = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False, default="primary")
    longitude = Column(DECIMAL(11, 7))
    latitude = Column(DECIMAL(10, 7))
    is_active = Column(Boolean, default=True)
    last_success_at = Column(DateTime, nullable=True)
    last_error = Column(String(1000), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_weather_stations_role", "role"),
        Index("idx_weather_stations_active", "is_active"),
    )


class RainfallHourly(BusinessBase):
    __tablename__ = "rainfall_hourly"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    station_id = Column(String(50), nullable=False, index=True)
    data_type = Column(String(20), nullable=False)
    hour_time = Column(DateTime, nullable=False)
    rainfall_mm = Column(DECIMAL(10, 2), nullable=False)
    batch_time = Column(DateTime, nullable=False)
    forecast_issued_at = Column(DateTime, nullable=True)
    source_endpoint = Column(String(100), nullable=False, default="fycx_trend_sta")
    raw_time_label = Column(String(50), default="")
    source_updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_rainfall_station_type_hour", "station_id", "data_type", "hour_time"),
        Index("idx_rainfall_station_batch", "station_id", "data_type", "batch_time"),
        Index(
            "uk_rainfall_station_type_hour_batch",
            "station_id",
            "data_type",
            "hour_time",
            "batch_time",
            unique=True,
        ),
    )


class RainfallActualHourly(BusinessBase):
    __tablename__ = "rainfall_actual_hourly"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    station_id = Column(String(50), nullable=False, index=True)
    hour_time = Column(DateTime, nullable=False)
    rainfall_mm = Column(DECIMAL(10, 2), nullable=False)
    source_endpoint = Column(String(100), nullable=False, default="fycx_trend_sta")
    raw_time_label = Column(String(50), default="")
    source_updated_at = Column(DateTime, nullable=True)
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("uk_rainfall_actual_station_hour", "station_id", "hour_time", unique=True),
        Index("idx_rainfall_actual_station_hour", "station_id", "hour_time"),
        Index("idx_rainfall_actual_last_seen", "last_seen_at"),
    )


class RainfallForecastHourly(BusinessBase):
    __tablename__ = "rainfall_forecast_hourly"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    station_id = Column(String(50), nullable=False, index=True)
    hour_time = Column(DateTime, nullable=False)
    rainfall_mm = Column(DECIMAL(10, 2), nullable=False)
    batch_time = Column(DateTime, nullable=False)
    forecast_issued_at = Column(DateTime, nullable=True)
    source_endpoint = Column(String(100), nullable=False, default="fycx_trend_sta")
    raw_time_label = Column(String(50), default="")
    source_updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("uk_rainfall_forecast_station_hour", "station_id", "hour_time", unique=True),
        Index("idx_rainfall_forecast_station_hour", "station_id", "hour_time"),
        Index("idx_rainfall_forecast_station_batch", "station_id", "batch_time"),
    )


class RainfallActualRevision(BusinessBase):
    __tablename__ = "rainfall_actual_revisions"

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    station_id = Column(String(50), nullable=False, index=True)
    hour_time = Column(DateTime, nullable=False)
    old_rainfall_mm = Column(DECIMAL(10, 2), nullable=False)
    new_rainfall_mm = Column(DECIMAL(10, 2), nullable=False)
    previous_source_updated_at = Column(DateTime, nullable=True)
    source_updated_at = Column(DateTime, nullable=True)
    detected_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    source_endpoint = Column(String(100), nullable=False, default="fycx_trend_sta")
    raw_time_label = Column(String(50), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_rainfall_revision_station_hour", "station_id", "hour_time"),
        Index("idx_rainfall_revision_detected", "detected_at"),
    )


class SystemConfig(ControlBase):
    __tablename__ = "system_config"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(100), unique=True, nullable=False)
    config_value = Column(Text)
    description = Column(String(255))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AdminUser(ControlBase):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    display_name = Column(String(50), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    phone = Column(String(32), default="")
    role = Column("ROLE", String(50), default="系统管理员")
    password_hash = Column(String(255), default="")
    auth_provider = Column(String(32), default="local")
    external_subject = Column(String(128), nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BusinessDbProfile(ControlBase):
    __tablename__ = "business_db_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_key = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=False)
    dialect = Column(String(20), nullable=False)
    driver = Column(String(50), nullable=False)
    host = Column(String(255), default="")
    port = Column(String(16), default="")
    service_name = Column(String(128), default="")
    database_name = Column(String(255), nullable=False)
    username = Column(String(255), nullable=False)
    password = Column(Text, default="")
    dm_home = Column(String(255), default="")
    dm_svc_path = Column(String(255), default="")
    auto_create_schema = Column(Boolean, default=False)
    is_active = Column(Boolean, default=False, index=True)
    last_tested_at = Column(DateTime, nullable=True)
    last_error = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
