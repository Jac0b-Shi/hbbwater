"""Shared helpers for system configuration and maintenance."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import MetaData, and_, delete, exists, insert, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SystemConfig


async def get_config_value(db: AsyncSession, key: str, default: str = "") -> str:
    """Get config value by key."""
    result = await db.execute(select(SystemConfig).where(SystemConfig.config_key == key))
    config = result.scalar_one_or_none()
    return config.config_value if config and config.config_value is not None else default


async def set_config_value(db: AsyncSession, key: str, value: str, description: str = "") -> None:
    """Create or update a config value by key."""
    result = await db.execute(select(SystemConfig).where(SystemConfig.config_key == key))
    config = result.scalar_one_or_none()

    if config:
        config.config_value = value
        if description:
            config.description = description
        config.updated_at = datetime.utcnow()
        await db.flush()
        return

    db.add(
        SystemConfig(
            config_key=key,
            config_value=value,
            description=description,
        )
    )
    await db.flush()


async def get_int_config(db: AsyncSession, key: str, default: int) -> int:
    value = await get_config_value(db, key, str(default))
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def get_bool_config(db: AsyncSession, key: str, default: bool) -> bool:
    value = await get_config_value(db, key, str(default).lower())
    return str(value).lower() == "true"


async def get_offline_timeout_minutes(db: AsyncSession, default: int = 60) -> int:
    """Return the effective offline timeout configured in minutes."""
    return await get_int_config(db, "offline_timeout_minutes", default)


async def get_database_stats(db: AsyncSession) -> dict[str, int]:
    """Collect record counts for operational tables."""
    tables = {
        "readings_count": "sensor_readings",
        "archive_count": "sensor_readings_archive",
        "hourly_count": "sensor_summary_hourly",
        "daily_count": "sensor_summary_daily",
    }
    stats: dict[str, int] = {}

    for field, table_name in tables.items():
        result = await db.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
        stats[field] = int(result.scalar() or 0)

    return stats


async def _reflect_tables(db: AsyncSession, *table_names: str) -> MetaData:
    metadata = MetaData()
    connection = await db.connection()
    await connection.run_sync(lambda sync_conn: metadata.reflect(sync_conn, only=list(table_names)))
    return metadata


def _null_safe_equals(left, right):
    return or_(left == right, and_(left.is_(None), right.is_(None)))


async def run_database_maintenance(db: AsyncSession) -> dict[str, Any]:
    """Move expired hot data into archive and optionally purge old archive data."""
    retention_days = await get_int_config(db, "data_retention_days", 14)
    archive_enabled = await get_bool_config(db, "archive_enabled", True)
    cutoff = datetime.utcnow() - timedelta(days=retention_days)

    archived_rows = 0
    deleted_rows = 0

    if archive_enabled:
        metadata = await _reflect_tables(db, "sensor_readings", "sensor_readings_archive")
        sensor_readings = metadata.tables["sensor_readings"]
        sensor_readings_archive = metadata.tables["sensor_readings_archive"]
        archive_column_names = [
            "sensor_id",
            "sensor_type",
            "water_level",
            "water_detected",
            "duration",
            "severity",
            "status",
            "battery_level",
            "signal_strength",
            "raw_data",
            "recorded_at",
            "created_at",
        ]
        source_select = (
            select(*(sensor_readings.c[column_name] for column_name in archive_column_names))
            .where(sensor_readings.c.recorded_at < cutoff)
            .where(
                ~exists(
                    select(1).where(
                        and_(
                            sensor_readings_archive.c.sensor_id == sensor_readings.c.sensor_id,
                            sensor_readings_archive.c.recorded_at == sensor_readings.c.recorded_at,
                            _null_safe_equals(
                                sensor_readings_archive.c.water_level,
                                sensor_readings.c.water_level,
                            ),
                            _null_safe_equals(
                                sensor_readings_archive.c.water_detected,
                                sensor_readings.c.water_detected,
                            ),
                            _null_safe_equals(
                                sensor_readings_archive.c.duration,
                                sensor_readings.c.duration,
                            ),
                            _null_safe_equals(
                                sensor_readings_archive.c.severity,
                                sensor_readings.c.severity,
                            ),
                        )
                    )
                )
            )
        )
        insert_result = await db.execute(
            insert(sensor_readings_archive).from_select(archive_column_names, source_select)
        )
        archived_rows = int(insert_result.rowcount or 0)

    metadata = await _reflect_tables(db, "sensor_readings")
    sensor_readings = metadata.tables["sensor_readings"]
    delete_result = await db.execute(delete(sensor_readings).where(sensor_readings.c.recorded_at < cutoff))
    deleted_rows = int(delete_result.rowcount or 0)

    await db.commit()

    return {
        "retention_days": retention_days,
        "archive_enabled": archive_enabled,
        "cutoff": cutoff.isoformat(),
        "archived_rows": archived_rows,
        "deleted_rows": deleted_rows,
        "stats": await get_database_stats(db),
    }


async def optimize_database_tables(db: AsyncSession) -> dict[str, Any]:
    """Run OPTIMIZE TABLE on operational tables."""
    dialect_name = db.get_bind().dialect.name
    tables = [
        "sensor_readings",
        "sensor_readings_archive",
        "sensor_summary_hourly",
        "sensor_summary_daily",
        "alerts",
        "system_config",
    ]
    results = []

    if dialect_name != "mysql":
        return {
            "optimized_tables": 0,
            "results": [],
            "skipped": True,
            "reason": f"{dialect_name} 未实现 OPTIMIZE TABLE 兼容策略",
            "stats": await get_database_stats(db),
        }

    for table_name in tables:
        optimize_result = await db.execute(text(f"OPTIMIZE TABLE {table_name}"))
        rows = optimize_result.fetchall()
        results.append({
            "table": table_name,
            "messages": [dict(row._mapping) for row in rows],
        })

    await db.commit()
    return {
        "optimized_tables": len(tables),
        "results": results,
        "stats": await get_database_stats(db),
    }
