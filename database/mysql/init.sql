-- 校园水浸监测系统数据库初始化脚本
-- MySQL 8.0+

-- 创建数据库
CREATE DATABASE IF NOT EXISTS flood_monitoring
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE flood_monitoring;

-- 创建数据库用户（本地访问）
CREATE USER IF NOT EXISTS 'flood_user'@'localhost' IDENTIFIED BY 'flood_monitoring_2025';
GRANT ALL PRIVILEGES ON flood_monitoring.* TO 'flood_user'@'localhost';

-- 创建数据库用户（Docker 网络访问，允许任何主机）
CREATE USER IF NOT EXISTS 'flood_user'@'%' IDENTIFIED BY 'flood_monitoring_2025';
GRANT ALL PRIVILEGES ON flood_monitoring.* TO 'flood_user'@'%';

FLUSH PRIVILEGES;

-- Webhook 组配置表
CREATE TABLE IF NOT EXISTS webhook_groups (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL COMMENT '组名称',
    description TEXT COMMENT '组描述',
    webhook_token VARCHAR(64) NOT NULL COMMENT '组Webhook标识',
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_webhook_groups_token (webhook_token)
) ENGINE=InnoDB COMMENT='Webhook组配置表';

-- 传感器配置表
CREATE TABLE IF NOT EXISTS sensors (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sensor_id VARCHAR(50) NOT NULL UNIQUE COMMENT '传感器唯一标识',
    sensor_type ENUM('ultrasonic', 'immersion') NOT NULL COMMENT '传感器类型',
    location VARCHAR(100) NOT NULL COMMENT '安装位置',
    description TEXT COMMENT '描述信息',
    warning_level DECIMAL(10,2) DEFAULT NULL COMMENT '预警水位值(cm)',
    danger_level DECIMAL(10,2) DEFAULT NULL COMMENT '危险水位值(cm)',
    threshold_condition VARCHAR(32) DEFAULT 'greater_or_equal' COMMENT '阈值比较方向',
    measurement_unit VARCHAR(8) DEFAULT 'cm' COMMENT '传感器返回值单位(cm/mm)',
    water_level_baseline DECIMAL(10,2) DEFAULT NULL COMMENT '基准测距值(cm)，用于换算相对水位',
    map_x DECIMAL(6,3) DEFAULT NULL COMMENT '地图点位X百分比',
    map_y DECIMAL(6,3) DEFAULT NULL COMMENT '地图点位Y百分比',
    map_locked BOOLEAN DEFAULT FALSE COMMENT '地图点位是否锁定',
    normal_interval INT DEFAULT 1800 COMMENT '正常模式上报间隔(秒),默认30分钟',
    alert_interval INT DEFAULT 300 COMMENT '预警模式上报间隔(秒),默认5分钟',
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    report_method ENUM('http_api', 'webhook', 'mqtt', 'coap', 'udp_binary') DEFAULT 'http_api' COMMENT '数据上报方式',
    webhook_token VARCHAR(64) DEFAULT NULL COMMENT 'Webhook唯一标识',
    webhook_group_id INT DEFAULT NULL COMMENT '所属Webhook组ID',
    webhook_group_token VARCHAR(64) DEFAULT NULL COMMENT '组Webhook标识，共享给同一类UDP设备',
    device_imei VARCHAR(32) DEFAULT NULL COMMENT '绑定的设备IMEI',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_type (sensor_type),
    INDEX idx_active (is_active),
    INDEX idx_sensors_webhook_group_id (webhook_group_id),
    INDEX idx_webhook_group_token (webhook_group_token),
    INDEX idx_device_imei (device_imei),
    UNIQUE KEY uk_webhook_token (webhook_token),
    UNIQUE KEY uk_device_imei (device_imei)
) ENGINE=InnoDB COMMENT='传感器配置表';

CREATE TABLE IF NOT EXISTS weather_stations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    station_id VARCHAR(50) NOT NULL UNIQUE COMMENT '知天气站点ID',
    station_name VARCHAR(100) NOT NULL COMMENT '站点名称',
    role VARCHAR(20) NOT NULL DEFAULT 'primary' COMMENT '站点角色(primary/backup)',
    longitude DECIMAL(11,7) DEFAULT NULL COMMENT '经度',
    latitude DECIMAL(10,7) DEFAULT NULL COMMENT '纬度',
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否启用采集',
    last_success_at TIMESTAMP NULL DEFAULT NULL COMMENT '最近成功采集时间',
    last_error VARCHAR(1000) COMMENT '最近采集错误',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_weather_stations_role (role),
    INDEX idx_weather_stations_active (is_active)
) ENGINE=InnoDB COMMENT='气象雨量站配置表';

CREATE TABLE IF NOT EXISTS rainfall_hourly (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    station_id VARCHAR(50) NOT NULL COMMENT '知天气站点ID',
    data_type VARCHAR(20) NOT NULL COMMENT 'actual=实况, forecast=预测',
    hour_time TIMESTAMP NOT NULL COMMENT '小时起始时间(UTC)',
    rainfall_mm DECIMAL(10,2) NOT NULL COMMENT '小时雨量(mm)',
    batch_time TIMESTAMP NOT NULL COMMENT '幂等批次时间',
    forecast_issued_at TIMESTAMP NULL DEFAULT NULL COMMENT '预报批次发布时间',
    source_endpoint VARCHAR(100) NOT NULL DEFAULT 'fycx_trend_sta' COMMENT '来源接口',
    raw_time_label VARCHAR(50) DEFAULT '' COMMENT '源接口原始时次标签',
    source_updated_at TIMESTAMP NULL DEFAULT NULL COMMENT '源接口更新时间',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_rainfall_station_type_hour_batch (station_id, data_type, hour_time, batch_time),
    INDEX idx_rainfall_station_type_hour (station_id, data_type, hour_time),
    INDEX idx_rainfall_station_batch (station_id, data_type, batch_time)
) ENGINE=InnoDB COMMENT='小时雨量实况与预测表';

CREATE TABLE IF NOT EXISTS rainfall_actual_hourly (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    station_id VARCHAR(50) NOT NULL COMMENT '知天气站点ID',
    hour_time TIMESTAMP NOT NULL COMMENT '小时起始时间(UTC)',
    rainfall_mm DECIMAL(10,2) NOT NULL COMMENT '小时实况雨量(mm)',
    source_endpoint VARCHAR(100) NOT NULL DEFAULT 'fycx_trend_sta' COMMENT '来源接口',
    raw_time_label VARCHAR(50) DEFAULT '' COMMENT '源接口原始时次标签',
    source_updated_at TIMESTAMP NULL DEFAULT NULL COMMENT '源接口更新时间',
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '首次采集到该小时值的时间',
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '最近一次采集到该小时值的时间',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_rainfall_actual_station_hour (station_id, hour_time),
    INDEX idx_rainfall_actual_station_hour (station_id, hour_time),
    INDEX idx_rainfall_actual_last_seen (last_seen_at)
) ENGINE=InnoDB COMMENT='小时雨量实况最新值表';

CREATE TABLE IF NOT EXISTS rainfall_forecast_hourly (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    station_id VARCHAR(50) NOT NULL COMMENT '知天气站点ID',
    hour_time TIMESTAMP NOT NULL COMMENT '小时起始时间(UTC)',
    rainfall_mm DECIMAL(10,2) NOT NULL COMMENT '小时预报雨量(mm)',
    batch_time TIMESTAMP NOT NULL COMMENT '当前保留的预报批次时间',
    forecast_issued_at TIMESTAMP NULL DEFAULT NULL COMMENT '预报批次发布时间',
    source_endpoint VARCHAR(100) NOT NULL DEFAULT 'fycx_trend_sta' COMMENT '来源接口',
    raw_time_label VARCHAR(50) DEFAULT '' COMMENT '源接口原始时次标签',
    source_updated_at TIMESTAMP NULL DEFAULT NULL COMMENT '源接口更新时间',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_rainfall_forecast_station_hour (station_id, hour_time),
    INDEX idx_rainfall_forecast_station_hour (station_id, hour_time),
    INDEX idx_rainfall_forecast_station_batch (station_id, batch_time)
) ENGINE=InnoDB COMMENT='未来24小时滚动雨量预报表';

CREATE TABLE IF NOT EXISTS rainfall_actual_revisions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    station_id VARCHAR(50) NOT NULL COMMENT '知天气站点ID',
    hour_time TIMESTAMP NOT NULL COMMENT '被修正的小时起始时间(UTC)',
    old_rainfall_mm DECIMAL(10,2) NOT NULL COMMENT '旧实况雨量(mm)',
    new_rainfall_mm DECIMAL(10,2) NOT NULL COMMENT '新实况雨量(mm)',
    previous_source_updated_at TIMESTAMP NULL DEFAULT NULL COMMENT '旧值来源更新时间',
    source_updated_at TIMESTAMP NULL DEFAULT NULL COMMENT '新值来源更新时间',
    detected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '发现修正的时间',
    source_endpoint VARCHAR(100) NOT NULL DEFAULT 'fycx_trend_sta' COMMENT '来源接口',
    raw_time_label VARCHAR(50) DEFAULT '' COMMENT '源接口原始时次标签',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_rainfall_revision_station_hour (station_id, hour_time),
    INDEX idx_rainfall_revision_detected (detected_at)
) ENGINE=InnoDB COMMENT='小时雨量实况修正记录表';

-- 传感器原始数据表（热数据，≤14天）
CREATE TABLE IF NOT EXISTS sensor_readings (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    sensor_id VARCHAR(50) NOT NULL,
    sensor_type ENUM('ultrasonic', 'immersion') NOT NULL,
    water_level DECIMAL(10,2) DEFAULT NULL COMMENT '水位(cm)',
    water_detected BOOLEAN DEFAULT NULL COMMENT '是否检测到水',
    duration INT DEFAULT NULL COMMENT '浸水持续时间(秒)',
    severity ENUM('low', 'medium', 'high') DEFAULT NULL COMMENT '严重程度',
    status ENUM('normal', 'warning', 'danger', 'alarm', 'offline') NOT NULL DEFAULT 'normal',
    battery_level DECIMAL(5,2) DEFAULT NULL COMMENT '电池电量(%)',
    signal_strength INT DEFAULT NULL COMMENT '信号强度(dBm)',
    raw_data JSON COMMENT '原始JSON数据',
    recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sensor_time (sensor_id, recorded_at),
    INDEX idx_time (recorded_at),
    INDEX idx_status (status),
    INDEX idx_sensor_type (sensor_type),
    INDEX idx_recorded_sensor (recorded_at, sensor_id)
) ENGINE=InnoDB COMMENT='传感器原始数据表（热数据）';

CREATE TABLE IF NOT EXISTS sensor_readings_archive (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    sensor_id VARCHAR(50) NOT NULL,
    sensor_type ENUM('ultrasonic', 'immersion') NOT NULL,
    water_level DECIMAL(10,2) DEFAULT NULL,
    water_detected BOOLEAN DEFAULT NULL,
    duration INT DEFAULT NULL,
    severity ENUM('low', 'medium', 'high') DEFAULT NULL,
    status ENUM('normal', 'warning', 'danger', 'alarm', 'offline') NOT NULL,
    battery_level DECIMAL(5,2) DEFAULT NULL,
    signal_strength INT DEFAULT NULL,
    raw_data JSON,
    recorded_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sensor_time (sensor_id, recorded_at),
    INDEX idx_time (recorded_at),
    INDEX idx_sensor_type (sensor_type)
) ENGINE=InnoDB COMMENT='传感器数据归档表';

CREATE TABLE IF NOT EXISTS sensor_summary_hourly (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    sensor_id VARCHAR(50) NOT NULL,
    summary_date DATE NOT NULL,
    summary_hour TINYINT NOT NULL CHECK (summary_hour >= 0 AND summary_hour <= 23),
    reading_count INT DEFAULT 0 COMMENT '读数次数',
    avg_water_level DECIMAL(10,2) DEFAULT NULL,
    max_water_level DECIMAL(10,2) DEFAULT NULL,
    min_water_level DECIMAL(10,2) DEFAULT NULL,
    water_detected_count INT DEFAULT 0 COMMENT '检测到水次数',
    alarm_count INT DEFAULT 0 COMMENT '告警次数',
    warning_count INT DEFAULT 0 COMMENT '预警次数',
    avg_battery_level DECIMAL(5,2) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_sensor_hour (sensor_id, summary_date, summary_hour),
    INDEX idx_date (summary_date)
) ENGINE=InnoDB COMMENT='小时汇总数据表';

CREATE TABLE IF NOT EXISTS sensor_summary_daily (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    sensor_id VARCHAR(50) NOT NULL,
    summary_date DATE NOT NULL,
    reading_count INT DEFAULT 0,
    avg_water_level DECIMAL(10,2) DEFAULT NULL,
    max_water_level DECIMAL(10,2) DEFAULT NULL,
    min_water_level DECIMAL(10,2) DEFAULT NULL,
    water_detected_duration INT DEFAULT 0 COMMENT '浸水持续时间(分钟)',
    alarm_count INT DEFAULT 0,
    warning_count INT DEFAULT 0,
    avg_battery_level DECIMAL(5,2) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_sensor_date (sensor_id, summary_date),
    INDEX idx_date (summary_date)
) ENGINE=InnoDB COMMENT='日汇总数据表';

CREATE TABLE IF NOT EXISTS alerts (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    sensor_id VARCHAR(50) NOT NULL,
    alert_type ENUM('high_water', 'forecast_high_water', 'water_detected', 'sensor_offline', 'low_battery') NOT NULL,
    severity ENUM('low', 'medium', 'high', 'critical') NOT NULL DEFAULT 'medium',
    message TEXT NOT NULL,
    details JSON COMMENT '详细信息',
    is_resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMP NULL,
    resolved_by VARCHAR(50) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sensor (sensor_id),
    INDEX idx_type (alert_type),
    INDEX idx_severity (severity),
    INDEX idx_created (created_at),
    INDEX idx_resolved (is_resolved)
) ENGINE=InnoDB COMMENT='告警记录表';

CREATE TABLE IF NOT EXISTS forecast_alert_profiles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sensor_id VARCHAR(50) NOT NULL UNIQUE COMMENT '超声波传感器ID',
    is_enabled BOOLEAN DEFAULT FALSE COMMENT '是否启用预报告警',
    station_id VARCHAR(50) DEFAULT NULL COMMENT '指定雨量站，为空则使用系统选择',
    horizon_hours INT DEFAULT 6 COMMENT '预测窗口小时数',
    warning_rise_mm DECIMAL(10,2) DEFAULT NULL COMMENT '上涨量预警覆盖阈值(mm)',
    critical_rise_mm DECIMAL(10,2) DEFAULT NULL COMMENT '上涨量危险覆盖阈值(mm)',
    model_params JSON COMMENT '模型参数覆盖',
    pump_params JSON COMMENT '泵参数覆盖',
    actuator_binding_id VARCHAR(100) DEFAULT NULL COMMENT '未来泵控执行绑定ID',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_forecast_profile_enabled (is_enabled),
    INDEX idx_forecast_profile_station (station_id)
) ENGINE=InnoDB COMMENT='预报型告警传感器配置表';

CREATE TABLE IF NOT EXISTS forecast_prediction_runs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    trigger_type VARCHAR(20) NOT NULL DEFAULT 'manual' COMMENT 'manual/scheduled/rainfall_collector',
    dry_run BOOLEAN DEFAULT TRUE COMMENT '是否仅演练',
    status VARCHAR(20) NOT NULL DEFAULT 'completed' COMMENT '评估状态',
    message TEXT COMMENT '评估摘要或错误信息',
    forecast_issued_at TIMESTAMP NULL DEFAULT NULL COMMENT '使用的预报批次时间',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '评估开始时间',
    completed_at TIMESTAMP NULL DEFAULT NULL COMMENT '评估完成时间',
    created_by VARCHAR(50) DEFAULT NULL COMMENT '触发人',
    source JSON COMMENT '评估来源信息',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_forecast_run_started (started_at),
    INDEX idx_forecast_run_status (status),
    INDEX idx_forecast_run_dry_run (dry_run)
) ENGINE=InnoDB COMMENT='预报型水位预测评估批次表';

CREATE TABLE IF NOT EXISTS forecast_prediction_results (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id BIGINT NOT NULL COMMENT '评估批次ID',
    sensor_id VARCHAR(50) NOT NULL COMMENT '传感器ID',
    station_id VARCHAR(50) DEFAULT NULL COMMENT '雨量站ID（兼容旧字段）',
    actual_station_id VARCHAR(50) DEFAULT NULL COMMENT '实况雨量站，优先A5151',
    forecast_station_id VARCHAR(50) DEFAULT NULL COMMENT '预报雨量站',
    rain_source_degraded BOOLEAN DEFAULT FALSE COMMENT '雨量源是否降级',
    degraded_reason VARCHAR(100) DEFAULT NULL COMMENT '降级原因',
    data_status VARCHAR(20) NOT NULL DEFAULT 'available' COMMENT '数据状态: available/degraded/unavailable',
    risk_level VARCHAR(20) NOT NULL DEFAULT 'normal' COMMENT '生效风险等级',
    model_risk VARCHAR(20) DEFAULT NULL COMMENT '模型自身风险',
    policy_floor VARCHAR(20) DEFAULT NULL COMMENT '安全策略下限',
    effective_risk VARCHAR(20) DEFAULT NULL COMMENT '最终生效风险',
    policy_reason VARCHAR(100) DEFAULT NULL COMMENT '策略触发原因',
    can_auto_resolve BOOLEAN DEFAULT FALSE COMMENT '是否允许自动解除告警',
    risk_no_pump VARCHAR(20) DEFAULT NULL COMMENT '无泵场景风险',
    risk_q2_scenario VARCHAR(20) DEFAULT NULL COMMENT '两泵假设场景风险',
    scenario_pump_count INT DEFAULT NULL COMMENT '模型假设的泵数',
    pump_assumption VARCHAR(50) DEFAULT NULL COMMENT '泵效假设标识',
    advisory_only BOOLEAN DEFAULT FALSE COMMENT '是否仅供诊断参考',
    should_notify BOOLEAN DEFAULT FALSE COMMENT '是否需要通知',
    notification_sent BOOLEAN DEFAULT FALSE COMMENT '是否已触发通知',
    alert_id BIGINT DEFAULT NULL COMMENT '关联告警ID',
    horizon_hours INT DEFAULT 6 COMMENT '预测窗口小时数',
    forecast_issued_at TIMESTAMP NULL DEFAULT NULL COMMENT '预报批次时间',
    peak_time TIMESTAMP NULL DEFAULT NULL COMMENT '预计峰值时间',
    predicted_free_rise_mm DECIMAL(10,2) DEFAULT NULL COMMENT '无泵等效上涨(mm)',
    predicted_observed_rise_mm DECIMAL(10,2) DEFAULT NULL COMMENT '考虑泵削峰后上涨(mm)',
    projected_distance_cm DECIMAL(10,2) DEFAULT NULL COMMENT '预计最低测距(cm)',
    latest_distance_cm DECIMAL(10,2) DEFAULT NULL COMMENT '最新测距(cm)',
    confidence DECIMAL(5,2) DEFAULT NULL COMMENT '置信度',
    features JSON COMMENT '模型输入特征',
    series JSON COMMENT '滚动预测序列',
    control_recommendation JSON COMMENT '泵控建议，仅建议不执行',
    decision_reason TEXT COMMENT '决策原因',
    model_version VARCHAR(64) NOT NULL DEFAULT 'heuristic_pressure_v1',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_forecast_result_run (run_id),
    INDEX idx_forecast_result_sensor (sensor_id),
    INDEX idx_forecast_result_station (station_id),
    INDEX idx_forecast_result_actual_station (actual_station_id),
    INDEX idx_forecast_result_forecast_station (forecast_station_id),
    INDEX idx_forecast_result_alert (alert_id),
    INDEX idx_forecast_result_sensor_created (sensor_id, created_at),
    INDEX idx_forecast_result_risk (risk_level),
    INDEX idx_forecast_result_data_status (data_status)
) ENGINE=InnoDB COMMENT='预报型水位预测结果表';

CREATE TABLE IF NOT EXISTS system_config (
    id INT AUTO_INCREMENT PRIMARY KEY,
    config_key VARCHAR(100) NOT NULL UNIQUE,
    config_value TEXT,
    description VARCHAR(255),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB COMMENT='系统配置表';

CREATE TABLE IF NOT EXISTS admin_users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE COMMENT '登录名',
    display_name VARCHAR(50) NOT NULL COMMENT '显示名称',
    email VARCHAR(255) NOT NULL UNIQUE COMMENT '邮箱',
    phone VARCHAR(32) DEFAULT '' COMMENT '手机号',
    role VARCHAR(50) DEFAULT '系统管理员' COMMENT '角色名称',
    password_hash VARCHAR(255) DEFAULT '' COMMENT '本地密码哈希',
    auth_provider VARCHAR(32) DEFAULT 'local' COMMENT '认证提供者',
    external_subject VARCHAR(128) DEFAULT NULL COMMENT '外部身份主体标识',
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_admin_auth_provider (auth_provider),
    INDEX idx_admin_external_subject (external_subject)
) ENGINE=InnoDB COMMENT='管理员账户表';

INSERT INTO system_config (config_key, config_value, description) VALUES
('data_retention_days', '14', '热数据保留天数'),
('archive_enabled', '1', '是否启用自动归档'),
('summary_enabled', '1', '是否启用数据统计'),
('alert_cooldown_minutes', '30', '相同告警冷却时间(分钟)'),
('offline_timeout_minutes', '60', '传感器离线判定时间(分钟)'),
('account_provider', 'local', '当前账户认证提供者'),
('account_local_user_id', '1', '本地账户用户ID'),
('account_local_username', 'admin', '本地账户登录名'),
('account_local_display_name', '管理员', '本地账户显示名称'),
('account_local_email', 'admin@example.com', '本地账户邮箱'),
('account_local_phone', '', '本地账户手机号'),
('account_local_role', '系统管理员', '本地账户角色'),
('account_local_password_hash', '', '本地账户密码哈希'),
('account_local_created_at', '2024-01-01T00:00:00', '本地账户创建时间');

INSERT INTO admin_users (username, display_name, email, phone, role, password_hash, auth_provider, is_active)
VALUES ('admin', '管理员', 'admin@example.com', '', '系统管理员', '', 'local', TRUE)
ON DUPLICATE KEY UPDATE
display_name = VALUES(display_name),
email = VALUES(email),
phone = VALUES(phone),
role = VALUES(role),
auth_provider = VALUES(auth_provider),
is_active = VALUES(is_active);

INSERT INTO weather_stations (station_id, station_name, role, longitude, latitude, is_active)
VALUES
('A5151', '宝山大场上大附中', 'primary', 121.3900000, 31.3100000, TRUE),
('58362', '宝山', 'backup', 121.4447222, 31.3908333, TRUE)
ON DUPLICATE KEY UPDATE
station_name = VALUES(station_name),
role = VALUES(role),
longitude = VALUES(longitude),
latitude = VALUES(latitude),
is_active = VALUES(is_active);
