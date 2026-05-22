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
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database import BusinessBase
    from app.models import RainfallHourly, Sensor, WeatherStation, WebhookGroup
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


if __name__ == "__main__":
    unittest.main()
