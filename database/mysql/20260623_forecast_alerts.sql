-- MySQL incremental schema for forecast-driven water level alerts.

USE flood_monitoring;

ALTER TABLE alerts
    MODIFY alert_type ENUM('high_water', 'forecast_high_water', 'water_detected', 'sensor_offline', 'low_battery') NOT NULL;

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
    trigger_type VARCHAR(20) NOT NULL DEFAULT 'manual',
    dry_run BOOLEAN DEFAULT TRUE,
    status VARCHAR(20) NOT NULL DEFAULT 'completed',
    message TEXT,
    forecast_issued_at TIMESTAMP NULL DEFAULT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL DEFAULT NULL,
    created_by VARCHAR(50) DEFAULT NULL,
    source JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_forecast_run_started (started_at),
    INDEX idx_forecast_run_status (status),
    INDEX idx_forecast_run_dry_run (dry_run)
) ENGINE=InnoDB COMMENT='预报型水位预测评估批次表';

CREATE TABLE IF NOT EXISTS forecast_prediction_results (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id BIGINT NOT NULL,
    sensor_id VARCHAR(50) NOT NULL,
    station_id VARCHAR(50) DEFAULT NULL,
    actual_station_id VARCHAR(50) DEFAULT NULL COMMENT '观测雨量站ID，固定优先A5151',
    forecast_station_id VARCHAR(50) DEFAULT NULL COMMENT '预报雨量站ID，A5151优先否则降级',
    rain_source_degraded BOOLEAN DEFAULT FALSE COMMENT '雨量源是否降级',
    degraded_reason VARCHAR(100) DEFAULT NULL COMMENT '降级原因',
    data_status VARCHAR(20) NOT NULL DEFAULT 'available' COMMENT '数据状态 available/degraded/unavailable',
    risk_level VARCHAR(20) NOT NULL DEFAULT 'normal',
    model_risk VARCHAR(20) DEFAULT NULL COMMENT '模型直接风险',
    policy_floor VARCHAR(20) DEFAULT NULL COMMENT '安全策略下限风险',
    effective_risk VARCHAR(20) DEFAULT NULL COMMENT '最终生效风险',
    policy_reason VARCHAR(100) DEFAULT NULL COMMENT '策略下限触发原因',
    should_notify BOOLEAN DEFAULT FALSE,
    notification_sent BOOLEAN DEFAULT FALSE,
    alert_id BIGINT DEFAULT NULL,
    horizon_hours INT DEFAULT 6,
    forecast_issued_at TIMESTAMP NULL DEFAULT NULL,
    peak_time TIMESTAMP NULL DEFAULT NULL,
    predicted_free_rise_mm DECIMAL(10,2) DEFAULT NULL,
    predicted_observed_rise_mm DECIMAL(10,2) DEFAULT NULL,
    projected_distance_cm DECIMAL(10,2) DEFAULT NULL,
    latest_distance_cm DECIMAL(10,2) DEFAULT NULL,
    confidence DECIMAL(5,2) DEFAULT NULL,
    features JSON,
    series JSON,
    control_recommendation JSON,
    decision_reason TEXT,
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
