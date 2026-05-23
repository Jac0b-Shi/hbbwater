-- Flood monitoring schema bootstrap for DM8
-- Scope: tables, indexes, default seed data only.
-- Notes:
-- 1. No JOB/scheduler objects are created here.
-- 2. ENUM/BOOLEAN/JSON are mapped to VARCHAR/SMALLINT/CLOB.
-- 3. This script is intended for a fresh schema.

CREATE TABLE webhook_groups (
    id INT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description CLOB,
    webhook_token VARCHAR(64) NOT NULL,
    is_active SMALLINT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_webhook_groups_token UNIQUE (webhook_token)
);

CREATE SEQUENCE seq_webhook_groups_id START WITH 1 INCREMENT BY 1;

CREATE OR REPLACE TRIGGER tri_webhook_groups_id
BEFORE INSERT ON webhook_groups
FOR EACH ROW
BEGIN
    IF :NEW.id IS NULL THEN
        SELECT seq_webhook_groups_id.NEXTVAL INTO :NEW.id;
    END IF;
END;
/

CREATE TABLE sensors (
    id INT IDENTITY(1,1) PRIMARY KEY,
    sensor_id VARCHAR(50) NOT NULL,
    sensor_type VARCHAR(20) NOT NULL,
    location VARCHAR(100) NOT NULL,
    description CLOB,
    warning_level DECIMAL(10,2),
    danger_level DECIMAL(10,2),
    threshold_condition VARCHAR(32) DEFAULT 'greater_or_equal',
    measurement_unit VARCHAR(8) DEFAULT 'cm',
    water_level_baseline DECIMAL(10,2),
    map_x DECIMAL(6,3),
    map_y DECIMAL(6,3),
    map_locked SMALLINT DEFAULT 0,
    normal_interval INT DEFAULT 1800,
    alert_interval INT DEFAULT 300,
    is_active SMALLINT DEFAULT 1,
    report_method VARCHAR(20) DEFAULT 'http_api',
    webhook_token VARCHAR(64),
    webhook_group_id INT,
    webhook_group_token VARCHAR(64),
    device_imei VARCHAR(32),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_sensors_sensor_id UNIQUE (sensor_id),
    CONSTRAINT uk_sensors_webhook_token UNIQUE (webhook_token),
    CONSTRAINT uk_sensors_device_imei UNIQUE (device_imei)
);

CREATE INDEX idx_sensors_type ON sensors (sensor_type);
CREATE INDEX idx_sensors_active ON sensors (is_active);
CREATE INDEX idx_sensors_webhook_group_id ON sensors (webhook_group_id);
CREATE INDEX idx_sensors_webhook_group_token ON sensors (webhook_group_token);
CREATE INDEX idx_sensors_device_imei ON sensors (device_imei);

CREATE TABLE weather_stations (
    id INT IDENTITY(1,1) PRIMARY KEY,
    station_id VARCHAR(50) NOT NULL,
    station_name VARCHAR(100) NOT NULL,
    role VARCHAR(20) DEFAULT 'primary' NOT NULL,
    longitude DECIMAL(11,7),
    latitude DECIMAL(10,7),
    is_active SMALLINT DEFAULT 1,
    last_success_at TIMESTAMP,
    last_error VARCHAR(1000),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_weather_stations_station_id UNIQUE (station_id)
);

CREATE INDEX idx_weather_stations_role ON weather_stations (role);
CREATE INDEX idx_weather_stations_active ON weather_stations (is_active);

CREATE TABLE rainfall_hourly (
    id BIGINT IDENTITY(1,1) PRIMARY KEY,
    station_id VARCHAR(50) NOT NULL,
    data_type VARCHAR(20) NOT NULL,
    hour_time TIMESTAMP NOT NULL,
    rainfall_mm DECIMAL(10,2) NOT NULL,
    batch_time TIMESTAMP NOT NULL,
    forecast_issued_at TIMESTAMP,
    source_endpoint VARCHAR(100) DEFAULT 'fycx_trend_sta' NOT NULL,
    raw_time_label VARCHAR(50) DEFAULT '',
    source_updated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_rainfall_station_type_hour_batch UNIQUE (station_id, data_type, hour_time, batch_time)
);

CREATE INDEX idx_rainfall_station_type_hour ON rainfall_hourly (station_id, data_type, hour_time);
CREATE INDEX idx_rainfall_station_batch ON rainfall_hourly (station_id, data_type, batch_time);

CREATE TABLE rainfall_actual_hourly (
    id BIGINT IDENTITY(1,1) PRIMARY KEY,
    station_id VARCHAR(50) NOT NULL,
    hour_time TIMESTAMP NOT NULL,
    rainfall_mm DECIMAL(10,2) NOT NULL,
    source_endpoint VARCHAR(100) DEFAULT 'fycx_trend_sta' NOT NULL,
    raw_time_label VARCHAR(50) DEFAULT '',
    source_updated_at TIMESTAMP,
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_rainfall_actual_station_hour UNIQUE (station_id, hour_time)
);

CREATE INDEX idx_rainfall_actual_station_hour ON rainfall_actual_hourly (station_id, hour_time);
CREATE INDEX idx_rainfall_actual_last_seen ON rainfall_actual_hourly (last_seen_at);

CREATE TABLE rainfall_forecast_hourly (
    id BIGINT IDENTITY(1,1) PRIMARY KEY,
    station_id VARCHAR(50) NOT NULL,
    hour_time TIMESTAMP NOT NULL,
    rainfall_mm DECIMAL(10,2) NOT NULL,
    batch_time TIMESTAMP NOT NULL,
    forecast_issued_at TIMESTAMP,
    source_endpoint VARCHAR(100) DEFAULT 'fycx_trend_sta' NOT NULL,
    raw_time_label VARCHAR(50) DEFAULT '',
    source_updated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_rainfall_forecast_station_hour UNIQUE (station_id, hour_time)
);

CREATE INDEX idx_rainfall_forecast_station_hour ON rainfall_forecast_hourly (station_id, hour_time);
CREATE INDEX idx_rainfall_forecast_station_batch ON rainfall_forecast_hourly (station_id, batch_time);

CREATE TABLE rainfall_actual_revisions (
    id BIGINT IDENTITY(1,1) PRIMARY KEY,
    station_id VARCHAR(50) NOT NULL,
    hour_time TIMESTAMP NOT NULL,
    old_rainfall_mm DECIMAL(10,2) NOT NULL,
    new_rainfall_mm DECIMAL(10,2) NOT NULL,
    previous_source_updated_at TIMESTAMP,
    source_updated_at TIMESTAMP,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    source_endpoint VARCHAR(100) DEFAULT 'fycx_trend_sta' NOT NULL,
    raw_time_label VARCHAR(50) DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_rainfall_revision_station_hour ON rainfall_actual_revisions (station_id, hour_time);
CREATE INDEX idx_rainfall_revision_detected ON rainfall_actual_revisions (detected_at);

CREATE TABLE sensor_readings (
    id BIGINT IDENTITY(1,1) PRIMARY KEY,
    sensor_id VARCHAR(50) NOT NULL,
    sensor_type VARCHAR(20) NOT NULL,
    water_level DECIMAL(10,2),
    water_detected SMALLINT,
    duration INT,
    severity VARCHAR(20),
    status VARCHAR(20) DEFAULT 'normal' NOT NULL,
    battery_level DECIMAL(5,2),
    signal_strength INT,
    raw_data CLOB,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_sensor_readings_sensor_time ON sensor_readings (sensor_id, recorded_at);
CREATE INDEX idx_sensor_readings_time ON sensor_readings (recorded_at);
CREATE INDEX idx_sensor_readings_status ON sensor_readings (status);
CREATE INDEX idx_sensor_readings_sensor_type ON sensor_readings (sensor_type);
CREATE INDEX idx_sensor_readings_recorded_sensor ON sensor_readings (recorded_at, sensor_id);

CREATE TABLE sensor_readings_archive (
    id BIGINT IDENTITY(1,1) PRIMARY KEY,
    sensor_id VARCHAR(50) NOT NULL,
    sensor_type VARCHAR(20) NOT NULL,
    water_level DECIMAL(10,2),
    water_detected SMALLINT,
    duration INT,
    severity VARCHAR(20),
    status VARCHAR(20) NOT NULL,
    battery_level DECIMAL(5,2),
    signal_strength INT,
    raw_data CLOB,
    recorded_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_sensor_readings_archive_sensor_time ON sensor_readings_archive (sensor_id, recorded_at);
CREATE INDEX idx_sensor_readings_archive_time ON sensor_readings_archive (recorded_at);
CREATE INDEX idx_sensor_readings_archive_sensor_type ON sensor_readings_archive (sensor_type);

CREATE TABLE sensor_summary_hourly (
    id BIGINT IDENTITY(1,1) PRIMARY KEY,
    sensor_id VARCHAR(50) NOT NULL,
    summary_date DATE NOT NULL,
    summary_hour SMALLINT NOT NULL,
    reading_count INT DEFAULT 0,
    avg_water_level DECIMAL(10,2),
    max_water_level DECIMAL(10,2),
    min_water_level DECIMAL(10,2),
    water_detected_count INT DEFAULT 0,
    alarm_count INT DEFAULT 0,
    warning_count INT DEFAULT 0,
    avg_battery_level DECIMAL(5,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_sensor_summary_hourly UNIQUE (sensor_id, summary_date, summary_hour),
    CONSTRAINT ck_sensor_summary_hourly_hour CHECK (summary_hour >= 0 AND summary_hour <= 23)
);

CREATE INDEX idx_sensor_summary_hourly_date ON sensor_summary_hourly (summary_date);

CREATE TABLE sensor_summary_daily (
    id BIGINT IDENTITY(1,1) PRIMARY KEY,
    sensor_id VARCHAR(50) NOT NULL,
    summary_date DATE NOT NULL,
    reading_count INT DEFAULT 0,
    avg_water_level DECIMAL(10,2),
    max_water_level DECIMAL(10,2),
    min_water_level DECIMAL(10,2),
    water_detected_duration INT DEFAULT 0,
    alarm_count INT DEFAULT 0,
    warning_count INT DEFAULT 0,
    avg_battery_level DECIMAL(5,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_sensor_summary_daily UNIQUE (sensor_id, summary_date)
);

CREATE INDEX idx_sensor_summary_daily_date ON sensor_summary_daily (summary_date);

CREATE TABLE alerts (
    id BIGINT IDENTITY(1,1) PRIMARY KEY,
    sensor_id VARCHAR(50) NOT NULL,
    alert_type VARCHAR(20) NOT NULL,
    severity VARCHAR(20) DEFAULT 'medium' NOT NULL,
    message CLOB NOT NULL,
    details CLOB,
    is_resolved SMALLINT DEFAULT 0,
    resolved_at TIMESTAMP,
    resolved_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_alerts_sensor ON alerts (sensor_id);
CREATE INDEX idx_alerts_type ON alerts (alert_type);
CREATE INDEX idx_alerts_severity ON alerts (severity);
CREATE INDEX idx_alerts_created ON alerts (created_at);
CREATE INDEX idx_alerts_resolved ON alerts (is_resolved);

CREATE TABLE system_config (
    id INT IDENTITY(1,1) PRIMARY KEY,
    config_key VARCHAR(100) NOT NULL,
    config_value CLOB,
    description VARCHAR(255),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_system_config_key UNIQUE (config_key)
);

CREATE TABLE admin_users (
    id INT IDENTITY(1,1) PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    display_name VARCHAR(50) NOT NULL,
    email VARCHAR(255) NOT NULL,
    phone VARCHAR(32) DEFAULT '',
    "ROLE" VARCHAR(50) DEFAULT 'admin',
    password_hash VARCHAR(255) DEFAULT '',
    auth_provider VARCHAR(32) DEFAULT 'local',
    external_subject VARCHAR(128),
    is_active SMALLINT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_admin_users_username UNIQUE (username),
    CONSTRAINT uk_admin_users_email UNIQUE (email)
);

CREATE INDEX idx_admin_users_auth_provider ON admin_users (auth_provider);
CREATE INDEX idx_admin_users_external_subject ON admin_users (external_subject);

ALTER TABLE sensors
    ADD CONSTRAINT fk_sensors_webhook_group
    FOREIGN KEY (webhook_group_id) REFERENCES webhook_groups(id);

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'data_retention_days', '14', 'retention days', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'data_retention_days');

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'archive_enabled', '1', 'archive enabled', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'archive_enabled');

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'summary_enabled', '1', 'summary enabled', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'summary_enabled');

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'alert_cooldown_minutes', '30', 'alert cooldown minutes', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'alert_cooldown_minutes');

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'offline_timeout_minutes', '60', 'offline timeout minutes', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'offline_timeout_minutes');

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'account_provider', 'local', 'account provider', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'account_provider');

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'account_local_user_id', '1', 'local user id', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'account_local_user_id');

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'account_local_username', 'admin', 'local username', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'account_local_username');

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'account_local_display_name', 'admin', 'local display name', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'account_local_display_name');

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'account_local_email', 'admin@example.com', 'local email', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'account_local_email');

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'account_local_phone', '', 'local phone', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'account_local_phone');

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'account_local_role', 'admin', 'local role', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'account_local_role');

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'account_local_password_hash', '', 'local password hash', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'account_local_password_hash');

INSERT INTO system_config (config_key, config_value, description, updated_at)
SELECT 'account_local_created_at', '2024-01-01T00:00:00', 'local created time', CURRENT_TIMESTAMP FROM dual
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'account_local_created_at');

INSERT INTO admin_users (
    username, display_name, email, phone, "ROLE",
    password_hash, auth_provider, is_active, created_at, updated_at
)
SELECT
    'admin', 'admin', 'admin@example.com', '', 'admin',
    '', 'local', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM dual
WHERE NOT EXISTS (SELECT 1 FROM admin_users WHERE username = 'admin');

INSERT INTO weather_stations (
    station_id, station_name, role, longitude, latitude, is_active, created_at, updated_at
)
SELECT
    'A5151', '宝山大场上大附中', 'primary', 121.3900000, 31.3100000, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM dual
WHERE NOT EXISTS (SELECT 1 FROM weather_stations WHERE station_id = 'A5151');

INSERT INTO weather_stations (
    station_id, station_name, role, longitude, latitude, is_active, created_at, updated_at
)
SELECT
    '58362', '宝山', 'backup', 121.4447222, 31.3908333, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM dual
WHERE NOT EXISTS (SELECT 1 FROM weather_stations WHERE station_id = '58362');
