-- Add run-level diagnostics storage for forecast prediction runs.
-- Required for deployments that already created forecast_prediction_runs before diagnostics existed.

USE flood_monitoring;

ALTER TABLE forecast_prediction_runs
    ADD COLUMN diagnostics JSON NULL COMMENT '运行级完整诊断信息';
