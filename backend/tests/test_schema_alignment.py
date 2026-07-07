"""Regression tests for schema self-healing helpers."""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

CURRENT_DIR = os.path.dirname(__file__)
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

IMPORT_ERROR = None

try:
    from sqlalchemy import inspect, select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database import BusinessBase
    from app.models import (
        ForecastAlertProfile,
        ForecastPredictionRun,
        RainfallActualHourly,
        RainfallForecastHourly,
        RainfallHourly,
        Sensor,
        WeatherStation,
        WebhookGroup,
    )
    from app.services.schema import ensure_runtime_schema
except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
    IMPORT_ERROR = exc


@unittest.skipIf(IMPORT_ERROR is not None, f"backend dependencies unavailable: {IMPORT_ERROR}")
class SchemaAlignmentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "schema-alignment.db"
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{self.db_path.as_posix()}",
            future=True,
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )

        async with self.engine.begin() as conn:
            await conn.run_sync(BusinessBase.metadata.create_all)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_ensure_runtime_schema_repairs_orphaned_group_references(self):
        async with self.session_factory() as session:
            session.add_all(
                [
                    Sensor(
                        sensor_id="grouped_sensor",
                        sensor_type="ultrasonic",
                        location="Basement A",
                        report_method="webhook",
                        webhook_group_id=999,
                        webhook_group_token="legacy-group-token",
                        threshold_condition=None,
                        measurement_unit=None,
                    ),
                    Sensor(
                        sensor_id="broken_sensor",
                        sensor_type="immersion",
                        location="Basement B",
                        report_method="http_api",
                        webhook_group_id=888,
                    ),
                ]
            )
            await session.commit()

        async with self.engine.begin() as conn:
            await ensure_runtime_schema(conn, "sqlite")

        async with self.session_factory() as session:
            group_result = await session.execute(
                select(WebhookGroup).where(WebhookGroup.webhook_token == "legacy-group-token")
            )
            group = group_result.scalar_one_or_none()
            self.assertIsNotNone(group)

            grouped_sensor_result = await session.execute(
                select(Sensor).where(Sensor.sensor_id == "grouped_sensor")
            )
            grouped_sensor = grouped_sensor_result.scalar_one()
            self.assertEqual(grouped_sensor.webhook_group_id, group.id)
            self.assertEqual(grouped_sensor.threshold_condition, "greater_or_equal")
            self.assertEqual(grouped_sensor.measurement_unit, "cm")

            broken_sensor_result = await session.execute(
                select(Sensor).where(Sensor.sensor_id == "broken_sensor")
            )
            broken_sensor = broken_sensor_result.scalar_one()
            self.assertIsNone(broken_sensor.webhook_group_id)

            station_ids = set(
                (
                    await session.execute(select(WeatherStation.station_id))
                ).scalars().all()
            )
            self.assertIn("A5151", station_ids)
            self.assertIn("58362", station_ids)

            rainfall = RainfallHourly(
                station_id="A5151",
                data_type="actual",
                hour_time=datetime(2026, 5, 22, 10),
                rainfall_mm=Decimal("0.1"),
                batch_time=datetime(2026, 5, 22, 10),
            )
            session.add(rainfall)
            await session.commit()
            self.assertIsNotNone(rainfall.id)

            forecast_profile = ForecastAlertProfile(
                sensor_id="grouped_sensor",
                is_enabled=True,
                horizon_hours=6,
            )
            forecast_run = ForecastPredictionRun(
                trigger_type="manual",
                dry_run=True,
                status="completed",
            )
            session.add_all([forecast_profile, forecast_run])
            await session.commit()
            self.assertIsNotNone(forecast_profile.id)
            self.assertIsNotNone(forecast_run.id)

            actual = RainfallActualHourly(
                station_id="A5151",
                hour_time=datetime(2026, 5, 22, 10),
                rainfall_mm=Decimal("0.1"),
            )
            forecast = RainfallForecastHourly(
                station_id="A5151",
                hour_time=datetime(2026, 5, 22, 11),
                rainfall_mm=Decimal("0.2"),
                batch_time=datetime(2026, 5, 22, 10),
            )
            session.add_all([actual, forecast])
            await session.commit()
            self.assertIsNotNone(actual.id)
            self.assertIsNotNone(forecast.id)

    async def test_ensure_runtime_schema_adds_forecast_run_diagnostics_column(self):
        async with self.engine.begin() as conn:
            await conn.execute(text("DROP TABLE forecast_prediction_results"))
            await conn.execute(text("DROP TABLE forecast_prediction_runs"))
            await conn.execute(
                text(
                    """
                    CREATE TABLE forecast_prediction_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trigger_type VARCHAR(20) NOT NULL DEFAULT 'manual',
                        dry_run BOOLEAN DEFAULT 1,
                        status VARCHAR(20) NOT NULL DEFAULT 'completed',
                        message TEXT,
                        forecast_issued_at DATETIME,
                        started_at DATETIME,
                        completed_at DATETIME,
                        created_by VARCHAR(50),
                        source TEXT,
                        created_at DATETIME
                    )
                    """
                )
            )

        async with self.engine.begin() as conn:
            await ensure_runtime_schema(conn, "sqlite")
            column_names = await conn.run_sync(
                lambda sync_conn: {
                    column["name"]
                    for column in inspect(sync_conn).get_columns("forecast_prediction_runs")
                }
            )
            self.assertIn("diagnostics", column_names)

        async with self.session_factory() as session:
            forecast_run = ForecastPredictionRun(
                trigger_type="manual",
                dry_run=True,
                status="completed",
                diagnostics=[{"reference_sensor_id": "ultrasonic_002"}],
            )
            session.add(forecast_run)
            await session.commit()
            await session.refresh(forecast_run)
            self.assertEqual(
                forecast_run.diagnostics,
                [{"reference_sensor_id": "ultrasonic_002"}],
            )

    async def test_ensure_runtime_schema_adds_sensor_threshold_metadata_columns(self):
        legacy_columns = (
            "threshold_status",
            "threshold_source",
            "threshold_version",
            "threshold_updated_at",
            "threshold_note",
        )
        async with self.engine.begin() as conn:
            for column_name in legacy_columns:
                await conn.execute(text(f"ALTER TABLE sensors DROP COLUMN {column_name}"))

        async with self.engine.begin() as conn:
            await ensure_runtime_schema(conn, "sqlite")
            column_names = await conn.run_sync(
                lambda sync_conn: {
                    column["name"]
                    for column in inspect(sync_conn).get_columns("sensors")
                }
            )
            for column_name in legacy_columns:
                self.assertIn(column_name, column_names)

        async with self.session_factory() as session:
            sensor = Sensor(
                sensor_id="threshold_meta_sensor",
                sensor_type="ultrasonic",
                location="Threshold metadata test",
                threshold_status="provisional",
                threshold_source="field_measurement",
                threshold_version="2026-07-v1",
                threshold_updated_at=datetime(2026, 7, 7, 4, 0),
                threshold_note="schema alignment regression",
            )
            session.add(sensor)
            await session.commit()
            await session.refresh(sensor)
            self.assertEqual(sensor.threshold_status, "provisional")


if __name__ == "__main__":
    unittest.main()
