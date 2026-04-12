-- MySQL 存储过程和事件调度器

USE flood_monitoring;

DELIMITER //

CREATE PROCEDURE IF NOT EXISTS ArchiveOldData()
BEGIN
    DECLARE retention_days INT DEFAULT 14;
    SELECT CAST(config_value AS UNSIGNED) INTO retention_days
    FROM system_config WHERE config_key = 'data_retention_days';
    IF retention_days IS NULL THEN
        SET retention_days = 14;
    END IF;

    START TRANSACTION;
    INSERT INTO sensor_readings_archive
    SELECT * FROM sensor_readings
    WHERE recorded_at < DATE_SUB(NOW(), INTERVAL retention_days DAY);
    DELETE FROM sensor_readings
    WHERE recorded_at < DATE_SUB(NOW(), INTERVAL retention_days DAY);
    COMMIT;
END //

CREATE PROCEDURE IF NOT EXISTS CalculateHourlySummary(IN target_date DATE, IN target_hour TINYINT)
BEGIN
    INSERT INTO sensor_summary_hourly (
        sensor_id, summary_date, summary_hour, reading_count,
        avg_water_level, max_water_level, min_water_level,
        water_detected_count, alarm_count, warning_count, avg_battery_level
    )
    SELECT
        s.sensor_id,
        target_date,
        target_hour,
        COUNT(*),
        AVG(CASE WHEN s.sensor_type = 'ultrasonic' THEN sr.water_level END),
        MAX(CASE WHEN s.sensor_type = 'ultrasonic' THEN sr.water_level END),
        MIN(CASE WHEN s.sensor_type = 'ultrasonic' THEN sr.water_level END),
        SUM(CASE WHEN s.sensor_type = 'immersion' AND sr.water_detected = TRUE THEN 1 ELSE 0 END),
        SUM(CASE WHEN sr.status IN ('danger', 'alarm') THEN 1 ELSE 0 END),
        SUM(CASE WHEN sr.status = 'warning' THEN 1 ELSE 0 END),
        AVG(sr.battery_level)
    FROM sensors s
    LEFT JOIN sensor_readings sr ON s.sensor_id = sr.sensor_id
        AND DATE(sr.recorded_at) = target_date
        AND HOUR(sr.recorded_at) = target_hour
    WHERE s.is_active = TRUE
    GROUP BY s.sensor_id
    ON DUPLICATE KEY UPDATE
        reading_count = VALUES(reading_count),
        avg_water_level = VALUES(avg_water_level),
        max_water_level = VALUES(max_water_level),
        min_water_level = VALUES(min_water_level),
        water_detected_count = VALUES(water_detected_count),
        alarm_count = VALUES(alarm_count),
        warning_count = VALUES(warning_count),
        avg_battery_level = VALUES(avg_battery_level),
        updated_at = NOW();
END //

CREATE PROCEDURE IF NOT EXISTS CalculateDailySummary(IN target_date DATE)
BEGIN
    INSERT INTO sensor_summary_daily (
        sensor_id, summary_date, reading_count,
        avg_water_level, max_water_level, min_water_level,
        water_detected_duration, alarm_count, warning_count, avg_battery_level
    )
    SELECT
        s.sensor_id,
        target_date,
        COUNT(*),
        AVG(CASE WHEN s.sensor_type = 'ultrasonic' THEN sr.water_level END),
        MAX(CASE WHEN s.sensor_type = 'ultrasonic' THEN sr.water_level END),
        MIN(CASE WHEN s.sensor_type = 'ultrasonic' THEN sr.water_level END),
        SUM(CASE WHEN s.sensor_type = 'immersion' AND sr.water_detected = TRUE THEN COALESCE(sr.duration, 120) ELSE 0 END) / 60,
        SUM(CASE WHEN sr.status IN ('danger', 'alarm') THEN 1 ELSE 0 END),
        SUM(CASE WHEN sr.status = 'warning' THEN 1 ELSE 0 END),
        AVG(sr.battery_level)
    FROM sensors s
    LEFT JOIN sensor_readings sr ON s.sensor_id = sr.sensor_id
        AND DATE(sr.recorded_at) = target_date
    WHERE s.is_active = TRUE
    GROUP BY s.sensor_id
    ON DUPLICATE KEY UPDATE
        reading_count = VALUES(reading_count),
        avg_water_level = VALUES(avg_water_level),
        max_water_level = VALUES(max_water_level),
        min_water_level = VALUES(min_water_level),
        water_detected_duration = VALUES(water_detected_duration),
        alarm_count = VALUES(alarm_count),
        warning_count = VALUES(warning_count),
        avg_battery_level = VALUES(avg_battery_level),
        updated_at = NOW();
END //

CREATE PROCEDURE IF NOT EXISTS CheckOfflineSensors()
BEGIN
    DECLARE offline_timeout INT DEFAULT 60;
    SELECT CAST(config_value AS UNSIGNED) INTO offline_timeout
    FROM system_config WHERE config_key = 'offline_timeout_minutes';
    IF offline_timeout IS NULL THEN
        SET offline_timeout = 60;
    END IF;

    INSERT INTO alerts (sensor_id, alert_type, severity, message, details)
    SELECT
        s.sensor_id,
        'sensor_offline',
        'high',
        CONCAT('传感器 ', s.sensor_id, ' 已离线超过 ', offline_timeout, ' 分钟'),
        JSON_OBJECT(
            'last_seen', (SELECT MAX(recorded_at) FROM sensor_readings WHERE sensor_id = s.sensor_id),
            'location', s.location,
            'timeout_minutes', offline_timeout
        )
    FROM sensors s
    WHERE s.is_active = TRUE
    AND NOT EXISTS (
        SELECT 1 FROM alerts a
        WHERE a.sensor_id = s.sensor_id
        AND a.alert_type = 'sensor_offline'
        AND a.is_resolved = FALSE
        AND a.created_at > DATE_SUB(NOW(), INTERVAL offline_timeout MINUTE)
    )
    AND (
        SELECT MAX(recorded_at) FROM sensor_readings WHERE sensor_id = s.sensor_id
    ) < DATE_SUB(NOW(), INTERVAL offline_timeout MINUTE);
END //

CREATE PROCEDURE IF NOT EXISTS CheckLowBattery()
BEGIN
    INSERT INTO alerts (sensor_id, alert_type, severity, message, details)
    SELECT
        sr.sensor_id,
        'low_battery',
        CASE
            WHEN sr.battery_level < 10 THEN 'critical'
            WHEN sr.battery_level < 20 THEN 'high'
            ELSE 'medium'
        END,
        CONCAT('传感器 ', sr.sensor_id, ' 电量低: ', sr.battery_level, '%'),
        JSON_OBJECT(
            'battery_level', sr.battery_level,
            'location', s.location
        )
    FROM sensor_readings sr
    JOIN sensors s ON sr.sensor_id = s.sensor_id
    WHERE sr.id IN (
        SELECT MAX(id) FROM sensor_readings GROUP BY sensor_id
    )
    AND sr.battery_level < 20
    AND s.is_active = TRUE
    AND NOT EXISTS (
        SELECT 1 FROM alerts a
        WHERE a.sensor_id = sr.sensor_id
        AND a.alert_type = 'low_battery'
        AND a.is_resolved = FALSE
        AND a.created_at > DATE_SUB(NOW(), INTERVAL 24 HOUR)
    );
END //

DELIMITER ;

SET GLOBAL event_scheduler = ON;

DROP EVENT IF EXISTS evt_archive_data;
CREATE EVENT evt_archive_data ON SCHEDULE EVERY 1 HOUR DO CALL ArchiveOldData();

DROP EVENT IF EXISTS evt_hourly_summary;
CREATE EVENT evt_hourly_summary ON SCHEDULE EVERY 1 HOUR DO CALL CalculateHourlySummary(CURDATE(), HOUR(NOW()));

DROP EVENT IF EXISTS evt_daily_summary;
CREATE EVENT evt_daily_summary
    ON SCHEDULE EVERY 1 DAY STARTS '2025-01-01 01:00:00'
    DO CALL CalculateDailySummary(DATE_SUB(CURDATE(), INTERVAL 1 DAY));

DROP EVENT IF EXISTS evt_check_offline;
CREATE EVENT evt_check_offline ON SCHEDULE EVERY 10 MINUTE DO CALL CheckOfflineSensors();

DROP EVENT IF EXISTS evt_check_battery;
CREATE EVENT evt_check_battery ON SCHEDULE EVERY 1 HOUR DO CALL CheckLowBattery();
