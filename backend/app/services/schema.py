"""Lightweight schema alignment for deployments without migrations."""
from datetime import datetime

from sqlalchemy import Integer, String, bindparam, inspect, select, table, column, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.database import DATABASE_DIALECT
from app.models import WebhookGroup


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

    if sensor_updates:
        await conn.execute(
            update(sensors)
            .where(sensors.c.id == bindparam("sensor_row_id"))
            .values(webhook_group_id=bindparam("group_id")),
            sensor_updates,
        )


async def ensure_runtime_schema(conn: AsyncConnection) -> None:
    """Add columns/indexes required by newer application versions."""
    existing_tables = await _list_existing_tables(conn)

    if DATABASE_DIALECT == "dm":
        required_tables = {
            "admin_users",
            "alerts",
            "sensor_readings",
            "sensor_readings_archive",
            "sensor_summary_daily",
            "sensor_summary_hourly",
            "sensors",
            "system_config",
            "webhook_groups",
        }
        missing_tables = sorted(required_tables - existing_tables)
        if missing_tables:
            raise RuntimeError(
                "DM schema bootstrap is incomplete. Initialize the database with "
                "'database/dm/init.sql' before starting the API. Missing tables: "
                + ", ".join(missing_tables)
            )

    if not await _table_exists(conn, "webhook_groups"):
        await conn.run_sync(lambda sync_conn: WebhookGroup.__table__.create(sync_conn, checkfirst=True))
    if not await _column_exists(conn, "sensors", "webhook_group_token"):
        await conn.execute(text(_build_add_column_sql(conn, "sensors", "webhook_group_token", String(64))))
    if not await _column_exists(conn, "sensors", "webhook_group_id"):
        await conn.execute(text(_build_add_column_sql(conn, "sensors", "webhook_group_id", Integer())))
    if not await _column_exists(conn, "sensors", "device_imei"):
        await conn.execute(text(_build_add_column_sql(conn, "sensors", "device_imei", String(32))))
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
