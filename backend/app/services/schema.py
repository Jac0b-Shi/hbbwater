"""Lightweight schema alignment for deployments without migrations."""
from datetime import datetime

from sqlalchemy import DECIMAL, Integer, String, bindparam, column, inspect, select, table, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models import (
    RainfallActualHourly,
    RainfallActualRevision,
    RainfallForecastHourly,
    RainfallHourly,
    WeatherStation,
    WebhookGroup,
)


DEFAULT_WEATHER_STATIONS = (
    {
        "station_id": "A5151",
        "station_name": "宝山大场上大附中",
        "role": "primary",
        "longitude": 121.39,
        "latitude": 31.31,
    },
    {
        "station_id": "58362",
        "station_name": "宝山",
        "role": "backup",
        "longitude": 121.4447222,
        "latitude": 31.39083333,
    },
)


async def _table_exists(conn: AsyncConnection, table_name: str) -> bool:
    return await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table(table_name))


async def _column_exists(conn: AsyncConnection, table_name: str, column_name: str) -> bool:
    return await conn.run_sync(
        lambda sync_conn: any(
            column["name"] == column_name
            for column in inspect(sync_conn).get_columns(table_name)
        )
    )


async def _index_exists(conn: AsyncConnection, table_name: str, index_name: str) -> bool:
    return await conn.run_sync(
        lambda sync_conn: any(
            index["name"] == index_name
            for index in inspect(sync_conn).get_indexes(table_name)
        )
    )


def _is_duplicate_index_error(exc: DBAPIError) -> bool:
    message = str(exc.orig)
    duplicate_markers = (
        "already exists",
        "已索引",
        "对象已存在",
    )
    return any(marker in message for marker in duplicate_markers)


async def _list_existing_tables(conn: AsyncConnection) -> set[str]:
    return set(
        await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
    )


def _build_add_column_sql(
    conn: AsyncConnection,
    table_name: str,
    column_name: str,
    column_type,
    nullable: bool = True,
) -> str:
    dialect = conn.dialect
    compiled_type = column_type.compile(dialect=dialect)
    add_keyword = "ADD COLUMN" if dialect.name in {"mysql", "postgresql", "sqlite"} else "ADD"
    nullable_sql = "" if nullable else " NOT NULL"
    return f"ALTER TABLE {table_name} {add_keyword} {column_name} {compiled_type}{nullable_sql}"


async def _sync_legacy_webhook_groups(conn: AsyncConnection) -> None:
    sensors = table(
        "sensors",
        column("id"),
        column("webhook_group_token"),
        column("webhook_group_id"),
    )
    webhook_groups = table(
        "webhook_groups",
        column("id"),
        column("name"),
        column("description"),
        column("webhook_token"),
        column("is_active"),
        column("created_at"),
        column("updated_at"),
    )

    legacy_tokens = (
        await conn.execute(
            select(sensors.c.webhook_group_token)
            .where(sensors.c.webhook_group_token.is_not(None))
            .where(sensors.c.webhook_group_token != "")
            .distinct()
        )
    ).scalars().all()

    if not legacy_tokens:
        return

    existing_tokens = set(
        (
            await conn.execute(
                select(webhook_groups.c.webhook_token).where(
                    webhook_groups.c.webhook_token.in_(legacy_tokens)
                )
            )
        ).scalars().all()
    )

    missing_tokens = [token for token in legacy_tokens if token not in existing_tokens]
    if missing_tokens:
        now = datetime.utcnow()
        insert_stmt = text(
            """
            INSERT INTO webhook_groups
                (name, description, webhook_token, is_active, created_at, updated_at)
            VALUES
                (:name, :description, :webhook_token, :is_active, :created_at, :updated_at)
            """
        )
        await conn.execute(
            insert_stmt,
            [
                {
                    "name": f"Legacy Group {token}",
                    "description": "Migrated from legacy sensor-bound group token",
                    "webhook_token": token,
                    "is_active": 1,
                    "created_at": now,
                    "updated_at": now,
                }
                for token in missing_tokens
            ],
        )

    token_to_group_id = {
        row.webhook_token: row.id
        for row in (
            await conn.execute(
                select(webhook_groups.c.id, webhook_groups.c.webhook_token).where(
                    webhook_groups.c.webhook_token.in_(legacy_tokens)
                )
            )
        )
    }

    existing_group_ids = set(
        (
            await conn.execute(select(webhook_groups.c.id))
        ).scalars().all()
    )

    sensor_updates = [
        {"sensor_row_id": row.id, "group_id": token_to_group_id[row.webhook_group_token]}
        for row in (
            await conn.execute(
                select(sensors.c.id, sensors.c.webhook_group_token)
                .where(sensors.c.webhook_group_id.is_(None))
                .where(sensors.c.webhook_group_token.is_not(None))
                .where(sensors.c.webhook_group_token != "")
            )
        )
        if row.webhook_group_token in token_to_group_id
    ]

    orphan_group_rows = (
        await conn.execute(
            select(sensors.c.id, sensors.c.webhook_group_id, sensors.c.webhook_group_token).where(
                sensors.c.webhook_group_id.is_not(None)
            )
        )
    ).all()
    for row in orphan_group_rows:
        if row.webhook_group_id in existing_group_ids:
            continue

        repaired_group_id = None
        if row.webhook_group_token and row.webhook_group_token in token_to_group_id:
            repaired_group_id = token_to_group_id[row.webhook_group_token]

        sensor_updates.append(
            {
                "sensor_row_id": row.id,
                "group_id": repaired_group_id,
            }
        )

    if sensor_updates:
        await conn.execute(
            update(sensors)
            .where(sensors.c.id == bindparam("sensor_row_id"))
            .values(webhook_group_id=bindparam("group_id")),
            sensor_updates,
        )


async def _ensure_weather_tables(conn: AsyncConnection) -> None:
    if not await _table_exists(conn, "weather_stations"):
        await conn.run_sync(lambda sync_conn: WeatherStation.__table__.create(sync_conn, checkfirst=True))
    if not await _table_exists(conn, "rainfall_hourly"):
        await conn.run_sync(lambda sync_conn: RainfallHourly.__table__.create(sync_conn, checkfirst=True))
    if not await _table_exists(conn, "rainfall_actual_hourly"):
        await conn.run_sync(lambda sync_conn: RainfallActualHourly.__table__.create(sync_conn, checkfirst=True))
    if not await _table_exists(conn, "rainfall_forecast_hourly"):
        await conn.run_sync(lambda sync_conn: RainfallForecastHourly.__table__.create(sync_conn, checkfirst=True))
    if not await _table_exists(conn, "rainfall_actual_revisions"):
        await conn.run_sync(lambda sync_conn: RainfallActualRevision.__table__.create(sync_conn, checkfirst=True))


async def _backfill_split_rainfall_tables(conn: AsyncConnection) -> None:
    if not await _table_exists(conn, "rainfall_hourly"):
        return

    await conn.execute(
        text(
            """
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
              )
            """
        )
    )
    await conn.execute(
        text(
            """
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
              )
            """
        )
    )


async def _ensure_default_weather_stations(conn: AsyncConnection) -> None:
    weather_stations = table(
        "weather_stations",
        column("station_id"),
        column("station_name"),
        column("role"),
        column("longitude"),
        column("latitude"),
        column("is_active"),
        column("created_at"),
        column("updated_at"),
    )
    existing_station_ids = set(
        (
            await conn.execute(select(weather_stations.c.station_id))
        ).scalars().all()
    )
    missing_stations = [
        station for station in DEFAULT_WEATHER_STATIONS
        if station["station_id"] not in existing_station_ids
    ]
    if not missing_stations:
        return

    now = datetime.utcnow()
    await conn.execute(
        text(
            """
            INSERT INTO weather_stations
                (station_id, station_name, role, longitude, latitude, is_active, created_at, updated_at)
            VALUES
                (:station_id, :station_name, :role, :longitude, :latitude, :is_active, :created_at, :updated_at)
            """
        ),
        [
            {
                **station,
                "is_active": 1,
                "created_at": now,
                "updated_at": now,
            }
            for station in missing_stations
        ],
    )


async def ensure_runtime_schema(conn: AsyncConnection, dialect_name: str) -> None:
    """Add columns/indexes required by newer application versions."""
    existing_tables = await _list_existing_tables(conn)

    if dialect_name == "dm":
        required_tables = {
            "alerts",
            "sensor_readings",
            "sensor_readings_archive",
            "sensor_summary_daily",
            "sensor_summary_hourly",
            "sensors",
            "webhook_groups",
            "weather_stations",
            "rainfall_hourly",
            "rainfall_actual_hourly",
            "rainfall_forecast_hourly",
            "rainfall_actual_revisions",
        }
        missing_tables = sorted(required_tables - existing_tables)
        if missing_tables:
            raise RuntimeError(
                "DM schema bootstrap is incomplete. Initialize the database with "
                "'database/dm/init.sql' before starting the API. Missing tables: "
                + ", ".join(missing_tables)
            )
    else:
        await _ensure_weather_tables(conn)

    await _backfill_split_rainfall_tables(conn)
    await _ensure_default_weather_stations(conn)

    if not await _table_exists(conn, "webhook_groups"):
        await conn.run_sync(lambda sync_conn: WebhookGroup.__table__.create(sync_conn, checkfirst=True))
    if not await _column_exists(conn, "sensors", "webhook_group_token"):
        await conn.execute(text(_build_add_column_sql(conn, "sensors", "webhook_group_token", String(64))))
    if not await _column_exists(conn, "sensors", "webhook_group_id"):
        await conn.execute(text(_build_add_column_sql(conn, "sensors", "webhook_group_id", Integer())))
    if not await _column_exists(conn, "sensors", "device_imei"):
        await conn.execute(text(_build_add_column_sql(conn, "sensors", "device_imei", String(32))))
    if not await _column_exists(conn, "sensors", "threshold_condition"):
        await conn.execute(text(_build_add_column_sql(conn, "sensors", "threshold_condition", String(32))))
    if not await _column_exists(conn, "sensors", "measurement_unit"):
        await conn.execute(text(_build_add_column_sql(conn, "sensors", "measurement_unit", String(8))))
    if not await _column_exists(conn, "sensors", "water_level_baseline"):
        await conn.execute(text(_build_add_column_sql(conn, "sensors", "water_level_baseline", DECIMAL(10, 2))))
    if not await _column_exists(conn, "sensors", "map_x"):
        await conn.execute(text(_build_add_column_sql(conn, "sensors", "map_x", DECIMAL(6, 3))))
    if not await _column_exists(conn, "sensors", "map_y"):
        await conn.execute(text(_build_add_column_sql(conn, "sensors", "map_y", DECIMAL(6, 3))))
    if not await _column_exists(conn, "sensors", "map_locked"):
        await conn.execute(text(_build_add_column_sql(conn, "sensors", "map_locked", Integer())))
    await conn.execute(
        text(
            "UPDATE sensors "
            "SET threshold_condition = 'greater_or_equal' "
            "WHERE threshold_condition IS NULL OR threshold_condition = ''"
        )
    )
    await conn.execute(
        text(
            "UPDATE sensors "
            "SET measurement_unit = 'cm' "
            "WHERE measurement_unit IS NULL OR measurement_unit = ''"
        )
    )
    await conn.execute(
        text(
            "UPDATE sensors "
            "SET map_locked = 0 "
            "WHERE map_locked IS NULL"
        )
    )
    if not await _index_exists(conn, "sensors", "idx_webhook_group_token"):
        try:
            await conn.execute(text("CREATE INDEX idx_webhook_group_token ON sensors (webhook_group_token)"))
        except DBAPIError as exc:
            if not _is_duplicate_index_error(exc):
                raise
    if not await _index_exists(conn, "sensors", "idx_sensors_webhook_group_id"):
        try:
            await conn.execute(text("CREATE INDEX idx_sensors_webhook_group_id ON sensors (webhook_group_id)"))
        except DBAPIError as exc:
            if not _is_duplicate_index_error(exc):
                raise
    if not await _index_exists(conn, "sensors", "idx_device_imei"):
        try:
            await conn.execute(text("CREATE INDEX idx_device_imei ON sensors (device_imei)"))
        except DBAPIError as exc:
            if not _is_duplicate_index_error(exc):
                raise
    await _sync_legacy_webhook_groups(conn)
