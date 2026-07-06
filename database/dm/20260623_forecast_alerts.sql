-- DM8 incremental schema for forecast-driven water level alerts.
-- Run once after deploying code that introduces forecast prediction records.

CREATE TABLE forecast_alert_profiles (
    id INT IDENTITY(1,1) PRIMARY KEY,
    sensor_id VARCHAR(50) NOT NULL,
    is_enabled SMALLINT DEFAULT 0,
    station_id VARCHAR(50),
    horizon_hours INT DEFAULT 6,
    warning_rise_mm DECIMAL(10,2),
    critical_rise_mm DECIMAL(10,2),
    model_params CLOB,
    pump_params CLOB,
    actuator_binding_id VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_forecast_alert_profiles_sensor UNIQUE (sensor_id)
);

CREATE INDEX idx_forecast_profile_enabled ON forecast_alert_profiles (is_enabled);
CREATE INDEX idx_forecast_profile_station ON forecast_alert_profiles (station_id);

CREATE TABLE forecast_prediction_runs (
    id BIGINT IDENTITY(1,1) PRIMARY KEY,
    trigger_type VARCHAR(20) DEFAULT 'manual' NOT NULL,
    dry_run SMALLINT DEFAULT 1,
    status VARCHAR(20) DEFAULT 'completed' NOT NULL,
    message CLOB,
    forecast_issued_at TIMESTAMP,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    created_by VARCHAR(50),
    source CLOB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_forecast_run_started ON forecast_prediction_runs (started_at);
CREATE INDEX idx_forecast_run_status ON forecast_prediction_runs (status);
CREATE INDEX idx_forecast_run_dry_run ON forecast_prediction_runs (dry_run);

CREATE TABLE forecast_prediction_results (
    id BIGINT IDENTITY(1,1) PRIMARY KEY,
    run_id BIGINT NOT NULL,
    sensor_id VARCHAR(50) NOT NULL,
    station_id VARCHAR(50),
    actual_station_id VARCHAR(50),
    forecast_station_id VARCHAR(50),
    rain_source_degraded SMALLINT DEFAULT 0,
    degraded_reason VARCHAR(100),
    data_status VARCHAR(20) DEFAULT 'available' NOT NULL,
    risk_level VARCHAR(20) DEFAULT 'normal' NOT NULL,
    model_risk VARCHAR(20),
    policy_floor VARCHAR(20),
    effective_risk VARCHAR(20),
    policy_reason VARCHAR(100),
    can_auto_resolve SMALLINT DEFAULT 0,
    risk_no_pump VARCHAR(20),
    risk_q2_scenario VARCHAR(20),
    scenario_pump_count INT,
    pump_assumption VARCHAR(50),
    advisory_only SMALLINT DEFAULT 0,
    should_notify SMALLINT DEFAULT 0,
    notification_sent SMALLINT DEFAULT 0,
    alert_id BIGINT,
    horizon_hours INT DEFAULT 6,
    forecast_issued_at TIMESTAMP,
    peak_time TIMESTAMP,
    predicted_free_rise_mm DECIMAL(10,2),
    predicted_observed_rise_mm DECIMAL(10,2),
    projected_distance_cm DECIMAL(10,2),
    latest_distance_cm DECIMAL(10,2),
    confidence DECIMAL(5,2),
    features CLOB,
    series CLOB,
    control_recommendation CLOB,
    decision_reason CLOB,
    model_version VARCHAR(64) DEFAULT 'heuristic_pressure_v1' NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_forecast_result_run ON forecast_prediction_results (run_id);
CREATE INDEX idx_forecast_result_sensor ON forecast_prediction_results (sensor_id);
CREATE INDEX idx_forecast_result_station ON forecast_prediction_results (station_id);
CREATE INDEX idx_forecast_result_actual_station ON forecast_prediction_results (actual_station_id);
CREATE INDEX idx_forecast_result_forecast_station ON forecast_prediction_results (forecast_station_id);
CREATE INDEX idx_forecast_result_alert ON forecast_prediction_results (alert_id);
CREATE INDEX idx_forecast_result_sensor_created ON forecast_prediction_results (sensor_id, created_at);
CREATE INDEX idx_forecast_result_risk ON forecast_prediction_results (risk_level);
CREATE INDEX idx_forecast_result_data_status ON forecast_prediction_results (data_status);
