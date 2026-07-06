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
    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database import BusinessBase, ControlBase
    from app.models import (
        Alert,
        AlertType,
        ForecastAlertProfile,
        ForecastPredictionResult,
        RainfallActualHourly,
        RainfallForecastHourly,
        Sensor,
        SensorReading,
        Severity,
        WeatherStation,
    )
    from app.services.forecast_alerts import (
        FORECAST_ALERT_ENABLED_KEY,
        evaluate_forecast_alerts,
        upsert_forecast_alert_profiles,
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

    async def _seed_station(self, session, station_id, role="primary"):
        station = WeatherStation(
            station_id=station_id,
            station_name=station_id,
            role=role,
            is_active=True,
            last_success_at=datetime.utcnow(),
        )
        session.add(station)
        return station

    async def _seed_sensor(self, session, *, baseline=Decimal("100"), latest=Decimal("100"), warning=Decimal("95"), danger=Decimal("90")):
        now = datetime.utcnow()
        sensor = Sensor(
            sensor_id="ultrasonic_002",
            sensor_type="ultrasonic",
            location="D楼",
            warning_level=warning,
            danger_level=danger,
            threshold_condition="less_or_equal",
            water_level_baseline=baseline,
            normal_interval=300,
            is_active=True,
        )
        reading = SensorReading(
            sensor_id="ultrasonic_002",
            sensor_type="ultrasonic",
            water_level=latest,
            status="normal",
            recorded_at=now,
        )
        profile = ForecastAlertProfile(
            sensor_id="ultrasonic_002",
            is_enabled=True,
            station_id="A5151",
            horizon_hours=6,
        )
        session.add_all([sensor, reading, profile])
        return sensor, reading, profile

    async def _seed_forecast(self, session, station_id, values):
        now_hour = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        for offset, value in enumerate(values):
            session.add(
                RainfallForecastHourly(
                    station_id=station_id,
                    hour_time=now_hour + timedelta(hours=offset),
                    rainfall_mm=Decimal(str(value)) if value is not None else Decimal("0"),
                    batch_time=now_hour,
                    forecast_issued_at=now_hour,
                )
            )
        return now_hour

    async def _seed_actual(self, session, station_id, values, now_hour):
        for offset, value in enumerate(values):
            session.add(
                RainfallActualHourly(
                    station_id=station_id,
                    hour_time=now_hour - timedelta(hours=len(values) - offset),
                    rainfall_mm=Decimal(str(value)),
                )
            )

    async def test_dry_run_records_critical_effective_risk_without_creating_alert(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            await self._seed_sensor(session)
            await self._seed_forecast(session, "A5151", [15, 15, 12, 0, 0, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            self.assertEqual(result.risk_level, "critical")
            self.assertEqual(result.model_version, "heuristic_pressure_v1")
            self.assertTrue(result.should_notify)
            self.assertEqual(result.data_status, "available")
            self.assertEqual(result.policy_floor, "critical")
            self.assertEqual(result.policy_reason, "EXTREME_RAINFALL")
            self.assertEqual(result.effective_risk, "critical")
            # Model prediction must not be overwritten by the safety policy floor.
            self.assertLess(result.predicted_free_rise_mm, Decimal("300"))
            self.assertIsNone(result.alert_id)
            alert_count = await session.scalar(select(Alert))
            self.assertIsNone(alert_count)

    async def test_non_dry_run_creates_and_resolves_forecast_alert(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            await self._seed_sensor(session)
            await self._seed_forecast(session, "A5151", [15, 15, 12, 0, 0, 0])
            await session.commit()

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

    async def test_no_rain_does_not_double_count_baseline(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            await self._seed_sensor(session, baseline=Decimal("100"), latest=Decimal("96"))
            await self._seed_forecast(session, "A5151", [0, 0, 0, 0, 0, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            # Baseline 100 cm, latest 96 cm -> existing rise 40 mm.
            # No future rain -> predicted rise should be exactly 40 mm, not 80 mm.
            self.assertEqual(result.predicted_free_rise_mm, Decimal("40"))
            self.assertEqual(result.predicted_observed_rise_mm, Decimal("40"))
            # Projected distance = baseline - predicted_rise / 10 = 100 - 4 = 96 cm.
            self.assertEqual(result.projected_distance_cm, Decimal("96"))
            self.assertEqual(result.risk_level, "normal")

    async def test_data_missing_does_not_auto_resolve_active_alert(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            await self._seed_sensor(session)
            await self._seed_forecast(session, "A5151", [15, 15, 12, 0, 0, 0])
            await session.commit()

            await set_config_value(control, FORECAST_ALERT_ENABLED_KEY, "true", "forecast alerts")
            await control.commit()

            await evaluate_forecast_alerts(session, control, dry_run=False)
            await session.commit()
            alert = (await session.execute(select(Alert))).scalar_one()
            self.assertFalse(alert.is_resolved)

            # Remove all forecast data -> unavailable.
            await session.execute(select(RainfallForecastHourly))
            forecasts = (await session.execute(select(RainfallForecastHourly))).scalars().all()
            for row in forecasts:
                await session.delete(row)
            await session.commit()

            await evaluate_forecast_alerts(session, control, dry_run=False)
            await session.commit()
            alert = (await session.execute(select(Alert))).scalar_one()
            self.assertFalse(alert.is_resolved)

            result = (await session.execute(
                select(ForecastPredictionResult).order_by(ForecastPredictionResult.id.desc())
            )).scalars().first()
            self.assertEqual(result.data_status, "unavailable")
            self.assertEqual(result.risk_level, "unknown")
            self.assertFalse(result.should_notify)

    async def test_a5151_downgrade_to_backup_is_recorded(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            await self._seed_station(session, "58362", role="backup")
            await self._seed_sensor(session)
            # Only backup has forecast data.
            await self._seed_forecast(session, "58362", [0, 0, 0, 0, 0, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            self.assertEqual(result.actual_station_id, "A5151")
            self.assertEqual(result.forecast_station_id, "58362")
            self.assertTrue(result.rain_source_degraded)
            self.assertEqual(result.degraded_reason, "A5151_FORECAST_MISSING")

    async def test_forecast_gaps_produce_degraded_data_status(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            await self._seed_sensor(session)
            now_hour = await self._seed_forecast(session, "A5151", [5, 0, 0, 0, 0, 0])
            # Insert a gap at hour 2 by deleting the row.
            gap_row = await session.scalar(
                select(RainfallForecastHourly).where(RainfallForecastHourly.station_id == "A5151").where(
                    RainfallForecastHourly.hour_time == now_hour + timedelta(hours=2)
                )
            )
            if gap_row:
                await session.delete(gap_row)
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            self.assertEqual(result.data_status, "degraded")
            features = result.features or {}
            gap_hours = features.get("forecast_gap_hours", [])
            self.assertEqual(len(gap_hours), 1)
            # The gap hour should be the second hour of the window.
            self.assertEqual(
                gap_hours[0],
                (now_hour + timedelta(hours=2)).isoformat(),
            )

    async def test_invalid_model_params_fall_back_to_defaults(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            _, _, profile = await self._seed_sensor(session)
            profile.model_params = {
                "lambda_decay": 5.0,  # out of range
                "critical_rise_mm": 1.0,  # violates ordering
                "pump_capacity_mm_per_min": 100.0,  # legacy key must be rejected
            }
            await self._seed_forecast(session, "A5151", [0, 0, 0, 0, 0, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            features = result.features or {}
            # Legacy key should be stripped and defaults restored.
            self.assertNotIn("pump_capacity_mm_per_min", features.get("validated_params", {}))
            self.assertEqual(result.risk_level, "normal")

    async def test_q2_is_not_multiplied_by_pump_count(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            _, _, profile = await self._seed_sensor(session)
            # Strong rainfall that triggers the two-pump drawdown scenario.
            await self._seed_forecast(session, "A5151", [20, 20, 20, 0, 0, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            series = result.series or []
            pump_outputs = [s.get("pump_output_mm", 0) for s in series if s.get("scenario_pump_count")]
            self.assertTrue(pump_outputs)
            # q2 is ~62.3 mm/h (6.23 cm/h). It must not be a per-pump capacity scaled by count.
            for output in pump_outputs:
                self.assertAlmostEqual(output, 62.3, places=0)
            # The assumption must be explicit, not pretending to be actual pump state.
            active = [s for s in series if s.get("scenario_pump_count")]
            for step in active:
                self.assertEqual(step.get("pump_assumption"), "inferred_q2")
                self.assertEqual(step.get("actual_pump_state"), "unknown")

    async def test_sensor_consistency_diagnosis_is_shadow_mode_only(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            await self._seed_sensor(session)
            # Add a companion sensor 003 reading so consistency diagnosis can run.
            now_hour = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
            sensor_003 = Sensor(
                sensor_id="ultrasonic_003",
                sensor_type="ultrasonic",
                location="D楼3号",
                warning_level=Decimal("70.6"),
                danger_level=Decimal("60.0"),
                threshold_condition="less_or_equal",
                water_level_baseline=Decimal("80"),
                normal_interval=300,
                is_active=True,
            )
            reading_003 = SensorReading(
                sensor_id="ultrasonic_003",
                sensor_type="ultrasonic",
                water_level=Decimal("85.0"),
                status="normal",
                recorded_at=now_hour,
            )
            session.add_all([sensor_003, reading_003])
            await self._seed_forecast(session, "A5151", [0, 0, 0, 0, 0, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            features = result.features or {}
            diagnosis = features.get("sensor_consistency_diagnosis")
            self.assertIsNotNone(diagnosis)
            self.assertTrue(diagnosis.get("diagnostic_only"))
            # Must not affect risk conclusion.
            self.assertEqual(result.risk_level, "normal")

    async def test_provisional_vertical_thresholds_are_recorded(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            await self._seed_sensor(session, baseline=Decimal("100"), latest=Decimal("100"), warning=Decimal("81.2"), danger=Decimal("70.6"))
            await self._seed_forecast(session, "A5151", [0, 0, 0, 0, 0, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            features = result.features or {}
            provenance = features.get("threshold_provenance")
            self.assertIsNotNone(provenance)
            self.assertTrue(provenance.get("provisional_vertical_assumption"))
            self.assertIn("not final PLC setpoints", provenance.get("reason", ""))

    async def test_a5151_forced_priority_over_profile_station_id(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            # A5151 and 58362 both have forecasts, but the profile requests 58362.
            await self._seed_station(session, "A5151")
            await self._seed_station(session, "58362")
            _, _, profile = await self._seed_sensor(session)
            profile.station_id = "58362"
            now_hour = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
            for i, v in enumerate([5, 5, 5, 0, 0, 0]):
                session.add(RainfallForecastHourly(station_id="A5151", hour_time=now_hour + timedelta(hours=i), rainfall_mm=Decimal(str(v)), batch_time=now_hour, forecast_issued_at=now_hour))
            for i, v in enumerate([0, 0, 0, 0, 0, 0]):
                session.add(RainfallForecastHourly(station_id="58362", hour_time=now_hour + timedelta(hours=i), rainfall_mm=Decimal(str(v)), batch_time=now_hour, forecast_issued_at=now_hour))
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            # A5151 must be forced priority even when the profile asks for 58362.
            self.assertEqual(result.forecast_station_id, "A5151")
            self.assertFalse(result.rain_source_degraded)

    async def test_degraded_data_does_not_auto_resolve_active_alert(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            sensor, reading, profile = await self._seed_sensor(session)
            await self._seed_forecast(session, "A5151", [20, 20, 20, 0, 0, 0])
            await session.commit()

            await set_config_value(control, FORECAST_ALERT_ENABLED_KEY, "true", "forecast alerts")
            await control.commit()

            # Create an active forecast alert first.
            alert = Alert(
                sensor_id="ultrasonic_002",
                alert_type=AlertType.FORECAST_HIGH_WATER.value,
                severity=Severity.HIGH.value,
                message="existing alert",
                details={},
                created_at=datetime.utcnow(),
                is_resolved=False,
            )
            session.add(alert)
            await session.commit()

            # Make the latest reading stale; this yields a degraded result.
            reading.recorded_at = datetime.utcnow() - timedelta(seconds=sensor.normal_interval * 3)
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=False)
            await session.commit()

            result = (
                await session.execute(
                    select(ForecastPredictionResult)
                    .where(ForecastPredictionResult.run_id == run.id)
                    .order_by(ForecastPredictionResult.id.desc())
                )
            ).scalars().first()
            self.assertEqual(result.data_status, "degraded")
            self.assertFalse(result.can_auto_resolve)
            self.assertEqual(result.risk_level, "unknown")
            # Active alert must not be auto-resolved by degraded data.
            active = (await session.execute(select(Alert).where(Alert.id == alert.id))).scalar_one()
            self.assertFalse(active.is_resolved)

    async def test_stale_reading_returns_unknown(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            sensor, reading, profile = await self._seed_sensor(session)
            # Make the reading stale (older than 2x normal_interval).
            reading.recorded_at = datetime.utcnow() - timedelta(seconds=sensor.normal_interval * 3)
            await self._seed_forecast(session, "A5151", [0, 0, 0, 0, 0, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            self.assertTrue(result.features.get("reading_stale"))
            self.assertEqual(result.data_status, "degraded")
            self.assertEqual(result.risk_level, "unknown")
            self.assertFalse(result.can_auto_resolve)
            self.assertTrue(result.advisory_only)

    async def test_severe_forecast_gaps_return_unknown(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            await self._seed_sensor(session)
            now_hour = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
            # Only 1 out of 6 hours has data: gap ratio 5/6 > 0.25 threshold.
            for i in [0]:
                session.add(RainfallForecastHourly(station_id="A5151", hour_time=now_hour + timedelta(hours=i), rainfall_mm=Decimal("5"), batch_time=now_hour, forecast_issued_at=now_hour))
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            self.assertEqual(result.data_status, "unavailable")
            self.assertEqual(result.risk_level, "unknown")
            self.assertFalse(result.can_auto_resolve)

    async def test_invalid_profile_pump_params_rejected(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            await self._seed_sensor(session)
            await session.commit()

            # Schema-level strict validation must reject negative drawdowns.
            from app.schemas import ForecastPumpParams
            with self.assertRaises(ValueError):
                ForecastPumpParams(
                    net_drawdown_by_pump_count_cm_per_h={
                        "0": 0.0,
                        "1": None,
                        "2": -5.0,
                        "3": None,
                    }
                )

            # Zero-pump drawdown must be exactly 0.
            with self.assertRaises(ValueError):
                ForecastPumpParams(
                    net_drawdown_by_pump_count_cm_per_h={
                        "0": 1.0,
                        "1": None,
                        "2": 6.23,
                        "3": None,
                    }
                )


if __name__ == "__main__":
    unittest.main()
