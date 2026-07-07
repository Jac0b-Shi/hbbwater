-- DM8 incremental schema for sensor threshold provenance metadata.
-- Required for deployments that already created sensors before threshold metadata existed.

ALTER TABLE sensors ADD threshold_status VARCHAR(32);
ALTER TABLE sensors ADD threshold_source VARCHAR(100);
ALTER TABLE sensors ADD threshold_version VARCHAR(50);
ALTER TABLE sensors ADD threshold_updated_at TIMESTAMP;
ALTER TABLE sensors ADD threshold_note CLOB;
