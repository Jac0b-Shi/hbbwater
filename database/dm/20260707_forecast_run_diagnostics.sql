-- DM8 incremental schema for run-level forecast diagnostics.
-- Required for deployments that already created forecast_prediction_runs before diagnostics existed.

ALTER TABLE forecast_prediction_runs
    ADD diagnostics CLOB;
