-- DM8 incremental schema for ZhiTianQi hourly rainfall collection.
-- Run once before deploying an API version that requires weather_stations/rainfall_hourly.

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
