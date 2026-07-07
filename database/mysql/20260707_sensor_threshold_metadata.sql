-- Add threshold provenance metadata columns to sensors.
-- Required for deployments that already created sensors before threshold metadata existed.

USE flood_monitoring;

ALTER TABLE sensors
    ADD COLUMN threshold_status VARCHAR(32) NULL COMMENT '阈值状态: provisional/empirical/surveyed/approved',
    ADD COLUMN threshold_source VARCHAR(100) NULL COMMENT '阈值来源',
    ADD COLUMN threshold_version VARCHAR(50) NULL COMMENT '阈值版本',
    ADD COLUMN threshold_updated_at TIMESTAMP NULL DEFAULT NULL COMMENT '阈值更新时间',
    ADD COLUMN threshold_note TEXT NULL COMMENT '阈值备注';
