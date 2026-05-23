-- DM8 incremental schema for split rainfall actual/forecast storage.
-- Run once after 20260522_weather_rainfall.sql and before deploying code that writes the split tables.

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

INSERT INTO rainfall_actual_hourly (
    station_id,
    hour_time,
    rainfall_mm,
    source_endpoint,
    raw_time_label,
    source_updated_at,
    first_seen_at,
    last_seen_at,
    created_at,
    updated_at
)
SELECT
    src.station_id,
    src.hour_time,
    src.rainfall_mm,
    src.source_endpoint,
    src.raw_time_label,
    src.source_updated_at,
    src.created_at,
    src.updated_at,
    src.created_at,
    src.updated_at
FROM (
    SELECT
        r.station_id,
        r.hour_time,
        r.rainfall_mm,
        r.source_endpoint,
        r.raw_time_label,
        r.source_updated_at,
        r.created_at,
        r.updated_at,
        ROW_NUMBER() OVER (
            PARTITION BY r.station_id, r.hour_time
            ORDER BY r.updated_at DESC, r.created_at DESC, r.id DESC
        ) AS rn
    FROM rainfall_hourly r
    WHERE r.data_type = 'actual'
) src
WHERE src.rn = 1
  AND NOT EXISTS (
      SELECT 1
      FROM rainfall_actual_hourly existing
      WHERE existing.station_id = src.station_id
        AND existing.hour_time = src.hour_time
  );

INSERT INTO rainfall_forecast_hourly (
    station_id,
    hour_time,
    rainfall_mm,
    batch_time,
    forecast_issued_at,
    source_endpoint,
    raw_time_label,
    source_updated_at,
    created_at,
    updated_at
)
SELECT
    r.station_id,
    r.hour_time,
    r.rainfall_mm,
    r.batch_time,
    r.forecast_issued_at,
    r.source_endpoint,
    r.raw_time_label,
    r.source_updated_at,
    r.created_at,
    r.updated_at
FROM rainfall_hourly r
JOIN (
    SELECT station_id, MAX(batch_time) AS latest_batch
    FROM rainfall_hourly
    WHERE data_type = 'forecast'
    GROUP BY station_id
) latest
    ON latest.station_id = r.station_id
   AND latest.latest_batch = r.batch_time
WHERE r.data_type = 'forecast'
  AND NOT EXISTS (
      SELECT 1
      FROM rainfall_forecast_hourly existing
      WHERE existing.station_id = r.station_id
        AND existing.hour_time = r.hour_time
  );
