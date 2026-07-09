"""Regression tests for real-time alert resolution paths."""
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
    from app.models import Alert, Sensor, Severity
    from app.services.alerting import AUTO_RESOLVE_ACTOR, _resolve_active_alerts
    from app.services.forecast_alerts import _resolve_forecast_alerts
except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
    IMPORT_ERROR = exc


@unittest.skipIf(IMPORT_ERROR is not None, f"backend dependencies unavailable: {IMPORT_ERROR}")
class AlertResolutionTests(unittest.IsolatedAsyncioTestCase):
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

    async def _seed_sensor(self, session, sensor_id, sensor_type="ultrasonic"):
        sensor = Sensor(
            sensor_id=sensor_id,
            sensor_type=sensor_type,
            location="Test Location",
            warning_level=Decimal("95"),
            danger_level=Decimal("90"),
            threshold_condition="less_or_equal",
            water_level_baseline=Decimal("100"),
            normal_interval=300,
            is_active=True,
        )
        session.add(sensor)
        await session.flush()
        return sensor

    async def _seed_alerts(self, session, sensor_id, alert_type, count, severity="medium"):
        now = datetime.utcnow()
        alerts = []
        for i in range(count):
            alert = Alert(
                sensor_id=sensor_id,
                alert_type=alert_type,
                severity=severity,
                message=f"test alert {i}",
                is_resolved=False,
                created_at=now - timedelta(minutes=i),
            )
            session.add(alert)
            alerts.append(alert)
        await session.flush()
        return alerts

    async def test_resolve_active_alerts_clears_multiple_unresolved_alerts(self):
        async with self.business_session_factory() as session:
            sensor = await self._seed_sensor(session, "ultrasonic_resolve_test")
            await self._seed_alerts(session, sensor.sensor_id, "high_water", 3)
            await session.commit()

            resolved_at = datetime.utcnow()
            await _resolve_active_alerts(
                session,
                sensor_id=sensor.sensor_id,
                alert_type="high_water",
                resolved_at=resolved_at,
            )
            await session.commit()

            unresolved = (
                await session.execute(
                    select(Alert).where(
                        Alert.sensor_id == sensor.sensor_id,
                        Alert.alert_type == "high_water",
                        Alert.is_resolved == False,
                    )
                )
            ).scalars().all()
            self.assertEqual(len(unresolved), 0)

            resolved = (
                await session.execute(
                    select(Alert).where(
                        Alert.sensor_id == sensor.sensor_id,
                        Alert.alert_type == "high_water",
                        Alert.is_resolved == True,
                    )
                )
            ).scalars().all()
            self.assertEqual(len(resolved), 3)
            for alert in resolved:
                self.assertEqual(alert.resolved_by, AUTO_RESOLVE_ACTOR)
                self.assertIsNotNone(alert.resolved_at)

    async def test_resolve_forecast_alerts_clears_multiple_unresolved_alerts(self):
        async with self.business_session_factory() as session:
            sensor = await self._seed_sensor(session, "ultrasonic_forecast_resolve_test")
            await self._seed_alerts(session, sensor.sensor_id, "forecast_high_water", 3)
            await session.commit()

            resolved_at = datetime.utcnow()
            await _resolve_forecast_alerts(session, sensor.sensor_id, resolved_at)
            await session.commit()

            unresolved = (
                await session.execute(
                    select(Alert).where(
                        Alert.sensor_id == sensor.sensor_id,
                        Alert.alert_type == "forecast_high_water",
                        Alert.is_resolved == False,
                    )
                )
            ).scalars().all()
            self.assertEqual(len(unresolved), 0)

            resolved = (
                await session.execute(
                    select(Alert).where(
                        Alert.sensor_id == sensor.sensor_id,
                        Alert.alert_type == "forecast_high_water",
                        Alert.is_resolved == True,
                    )
                )
            ).scalars().all()
            self.assertEqual(len(resolved), 3)
            for alert in resolved:
                self.assertEqual(alert.resolved_by, AUTO_RESOLVE_ACTOR)
                self.assertIsNotNone(alert.resolved_at)

    async def test_resolve_active_alerts_only_targets_matching_type(self):
        async with self.business_session_factory() as session:
            sensor = await self._seed_sensor(session, "ultrasonic_type_isolation_test")
            await self._seed_alerts(session, sensor.sensor_id, "high_water", 2)
            await self._seed_alerts(session, sensor.sensor_id, "water_detected", 2)
            await session.commit()

            resolved_at = datetime.utcnow()
            await _resolve_active_alerts(
                session,
                sensor_id=sensor.sensor_id,
                alert_type="high_water",
                resolved_at=resolved_at,
            )
            await session.commit()

            high_water_unresolved = (
                await session.execute(
                    select(Alert).where(
                        Alert.sensor_id == sensor.sensor_id,
                        Alert.alert_type == "high_water",
                        Alert.is_resolved == False,
                    )
                )
            ).scalars().all()
            self.assertEqual(len(high_water_unresolved), 0)

            water_detected_unresolved = (
                await session.execute(
                    select(Alert).where(
                        Alert.sensor_id == sensor.sensor_id,
                        Alert.alert_type == "water_detected",
                        Alert.is_resolved == False,
                    )
                )
            ).scalars().all()
            self.assertEqual(len(water_detected_unresolved), 2)
