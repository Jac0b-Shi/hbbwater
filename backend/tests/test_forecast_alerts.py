"""Regression tests for forecast-driven water level alerts."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
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

    from app.database import BusinessBase, ControlBase
    from app.models import (
        Alert,
        ForecastAlertProfile,
        ForecastPredictionResult,
        RainfallForecastHourly,
        Sensor,
        SensorReading,
        WeatherStation,
    )
    from app.services.forecast_alerts import (
        FORECAST_ALERT_ENABLED_KEY,
        evaluate_forecast_alerts,
    )
    from app.services.system_config import set_config_value
except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
    IMPORT_ERROR = exc


@unittest.skipIf(IMPORT_ERROR is not None, f"backend dependencies unavailable: {IMPORT_ERROR}")
class ForecastAlertTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.business_path = Path(self.temp_dir.name) / "business.db"
        self.control_path = Path(self.temp_dir.name) / "control.db"
        self.business_engine = create_async_engine(
            f"sqlite+aiosqlite:///{self.business_path.as_posix()}",
            future=True,
        )
        self.control_engine = create_async_engine(
            f"sqlite+aiosqlite:///{self.control_path.as_posix()}",
            future=True,
        )
        self.business_session_factory = async_sessionmaker(
            self.business_engine,
            expire_on_commit=False,
        )
        self.control_session_factory = async_sessionmaker(
            self.control_engine,
            expire_on_commit=False,
        )
        async with self.business_engine.begin() as conn:
            await conn.run_sync(BusinessBase.metadata.create_all)
        async with self.control_engine.begin() as conn:
            await conn.run_sync(ControlBase.metadata.create_all)

    async def asyncTearDown(self):
        await self.business_engine.dispose()
        await self.control_engine.dispose()
        self.temp_dir.cleanup()

    async def _seed_sensor_and_forecast(self, session, *, heavy=True):
        now_hour = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        station = WeatherStation(
            station_id="A5151",
            station_name="宝山大场上大附中",
            role="primary",
            is_active=True,
            last_success_at=datetime.utcnow(),
        )
        sensor = Sensor(
            sensor_id="ultrasonic_002",
            sensor_type="ultrasonic",
            location="D楼",
            warning_level=Decimal("95"),
            danger_level=Decimal("90"),
            threshold_condition="less_or_equal",
            water_level_baseline=Decimal("100"),
            is_active=True,
        )
        reading = SensorReading(
            sensor_id="ultrasonic_002",
            sensor_type="ultrasonic",
            water_level=Decimal("100"),
            status="normal",
            recorded_at=now_hour,
        )
        profile = ForecastAlertProfile(
            sensor_id="ultrasonic_002",
            is_enabled=True,
            station_id="A5151",
            horizon_hours=6,
        )
        session.add_all([station, sensor, reading, profile])
        values = [15, 15, 12, 0, 0, 0] if heavy else [0, 0, 0, 0, 0, 0]
        for offset, value in enumerate(values):
            session.add(
                RainfallForecastHourly(
                    station_id="A5151",
                    hour_time=now_hour + timedelta(hours=offset),
                    rainfall_mm=Decimal(str(value)),
                    batch_time=now_hour,
                    forecast_issued_at=now_hour,
                )
            )
        await session.commit()

    async def test_dry_run_records_critical_prediction_without_creating_alert(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_sensor_and_forecast(session, heavy=True)

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            self.assertEqual(result.risk_level, "critical")
            self.assertGreaterEqual(result.predicted_free_rise_mm, Decimal("300"))
            self.assertTrue(result.should_notify)
            self.assertIsNone(result.alert_id)
            alert_count = await session.scalar(select(Alert))
            self.assertIsNone(alert_count)

    async def test_non_dry_run_creates_and_resolves_forecast_alert(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_sensor_and_forecast(session, heavy=True)
            await set_config_value(control, FORECAST_ALERT_ENABLED_KEY, "true", "forecast alerts")
            await control.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=False)
            await session.commit()
            result = (
                await session.execute(select(ForecastPredictionResult).where(ForecastPredictionResult.run_id == run.id))
            ).scalar_one()
            self.assertIsNotNone(result.alert_id)

            forecasts = (await session.execute(select(RainfallForecastHourly))).scalars().all()
            for row in forecasts:
                row.rainfall_mm = Decimal("0")
            await session.commit()

            await evaluate_forecast_alerts(session, control, dry_run=False)
            await session.commit()
            alert = (await session.execute(select(Alert))).scalar_one()
            self.assertTrue(alert.is_resolved)
            self.assertEqual(alert.resolved_by, "system:auto")


if __name__ == "__main__":
    unittest.main()
