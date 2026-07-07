"""Regression tests for forecast-driven water level alerts."""
import json
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
        save_forecast_alert_global_config,
        upsert_forecast_alert_profiles,
    )
    from app.services.system_config import set_config_value
    from app.schemas import ForecastAlertGlobalConfig, SensorConsistencyModelConfig
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
            sensor, reading, _profile = await self._seed_sensor(session)
            # Add a companion sensor 003 reading at the same time so alignment is exact.
            now = reading.recorded_at
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
                water_level=Decimal("89.14"),
                status="normal",
                recorded_at=now,
            )
            session.add_all([sensor_003, reading_003])
            await self._seed_forecast(session, "A5151", [0, 0, 0, 0, 0, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            features = result.features or {}
            diagnoses = features.get("sensor_consistency_diagnoses") or []
            self.assertEqual(len(diagnoses), 1)
            diagnosis = diagnoses[0]
            self.assertIsNotNone(diagnosis)
            self.assertTrue(diagnosis.get("diagnostic_only"))
            self.assertEqual(diagnosis.get("alignment_status"), "aligned")
            self.assertEqual(diagnosis.get("alignment_delta_seconds"), 0)
            self.assertEqual(diagnosis.get("sensor_health"), "unknown")
            self.assertIn(diagnosis.get("instantaneous_consistency"), {"normal", "warning"})
            # Must not affect risk conclusion.
            self.assertEqual(result.risk_level, "normal")

    async def test_threshold_metadata_is_recorded(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            sensor, _reading, _profile = await self._seed_sensor(
                session, baseline=Decimal("100"), latest=Decimal("100"), warning=Decimal("90.0"), danger=Decimal("81.2")
            )
            sensor.threshold_status = "provisional"
            sensor.threshold_source = "field_measurement"
            sensor.threshold_version = "2026-07-v1"
            sensor.threshold_note = "danger 为首次越堤线；声轴姿态尚未完成测量"
            await self._seed_forecast(session, "A5151", [0, 0, 0, 0, 0, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            features = result.features or {}
            provenance = features.get("threshold_provenance")
            self.assertIsNotNone(provenance)
            self.assertEqual(provenance.get("threshold_status"), "provisional")
            self.assertEqual(provenance.get("threshold_source"), "field_measurement")
            self.assertEqual(provenance.get("threshold_version"), "2026-07-v1")
            self.assertIn("首次越堤线", provenance.get("threshold_note", ""))

    async def test_sensor_consistency_models_load_from_system_config(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            sensor, reading, _profile = await self._seed_sensor(session)
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
                water_level=Decimal("89.00"),
                status="normal",
                recorded_at=reading.recorded_at,
            )
            session.add_all([sensor_003, reading_003])
            await self._seed_forecast(session, "A5151", [0, 0, 0, 0, 0, 0])
            await session.commit()

            custom_config = [
                {
                    "reference_sensor_id": "ultrasonic_002",
                    "target_sensor_id": "ultrasonic_003",
                    "slope": 0.9840,
                    "intercept_cm": -9.26,
                    "normal_abs_residual_cm": 0.1,
                    "warning_abs_residual_cm": 0.2,
                    "calibration_version": "config-test-v1",
                    "is_enabled": True,
                }
            ]
            await set_config_value(control, "sensor_consistency_models", json.dumps(custom_config))
            await control.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            diagnoses = result.features.get("sensor_consistency_diagnoses") or []
            self.assertEqual(len(diagnoses), 1)
            diagnosis = diagnoses[0]
            self.assertIsNotNone(diagnosis)
            self.assertEqual(diagnosis.get("normal_abs_residual_cm"), 0.1)
            self.assertEqual(diagnosis.get("warning_abs_residual_cm"), 0.2)
            self.assertEqual(diagnosis.get("calibration_version"), "config-test-v1")
            # Residual is ~0.14 cm, so it should fall into warning with the custom thresholds.
            self.assertEqual(diagnosis.get("instantaneous_consistency"), "warning")

    async def test_sensor_consistency_models_explicit_empty_list_disables_diagnosis(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            await self._seed_sensor(session)
            await self._seed_forecast(session, "A5151", [0, 0, 0, 0, 0, 0])
            await set_config_value(control, "sensor_consistency_models", "[]")
            await control.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            self.assertEqual(result.features.get("sensor_consistency_diagnoses"), [])
            self.assertEqual(run.diagnostics, [])

    async def test_sensor_consistency_models_all_disabled_disables_diagnosis(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            await self._seed_sensor(session)
            await self._seed_forecast(session, "A5151", [0, 0, 0, 0, 0, 0])
            disabled_config = [
                {
                    "reference_sensor_id": "ultrasonic_002",
                    "target_sensor_id": "ultrasonic_003",
                    "slope": 0.9840,
                    "intercept_cm": -9.26,
                    "is_enabled": False,
                }
            ]
            await set_config_value(control, "sensor_consistency_models", json.dumps(disabled_config))
            await control.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            self.assertEqual(result.features.get("sensor_consistency_diagnoses"), [])
            self.assertEqual(run.diagnostics, [])

    async def test_sensor_consistency_models_invalid_config_raises(self):
        async with self.control_session_factory() as control:
            invalid_config = [
                {
                    "reference_sensor_id": "ultrasonic_002",
                    "target_sensor_id": "ultrasonic_002",
                    "slope": 0.9840,
                    "intercept_cm": -9.26,
                }
            ]
            await set_config_value(control, "sensor_consistency_models", json.dumps(invalid_config))
            await control.commit()

            from app.services.forecast_alerts import _get_sensor_consistency_models
            with self.assertRaises(ValueError) as ctx:
                await _get_sensor_consistency_models(control)
            self.assertIn("reference_sensor_id", str(ctx.exception).lower())

    async def test_sensor_consistency_config_rejects_extra_nonfinite_and_duplicate_pairs(self):
        base = {
            "reference_sensor_id": "ultrasonic_002",
            "target_sensor_id": "ultrasonic_003",
            "slope": 0.9840,
            "intercept_cm": -9.26,
        }
        with self.assertRaises(Exception):
            SensorConsistencyModelConfig.model_validate({**base, "unexpected": True})
        with self.assertRaises(Exception):
            SensorConsistencyModelConfig.model_validate({**base, "slope": float("inf")})
        with self.assertRaises(Exception):
            SensorConsistencyModelConfig.model_validate({**base, "median_abs_residual_cm": -0.1})
        with self.assertRaises(Exception):
            SensorConsistencyModelConfig.model_validate({**base, "calibration_sample_size": -1})
        with self.assertRaises(Exception):
            ForecastAlertGlobalConfig(
                sensor_consistency_models=[
                    base,
                    {
                        "reference_sensor_id": "ultrasonic_003",
                        "target_sensor_id": "ultrasonic_002",
                        "slope": 1.0,
                        "intercept_cm": 0.0,
                    },
                ]
            )

    async def test_sensor_consistency_config_requires_existing_ultrasonic_sensors(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            session.add_all(
                [
                    Sensor(
                        sensor_id="ultrasonic_002",
                        sensor_type="ultrasonic",
                        location="D楼",
                        is_active=True,
                    ),
                    Sensor(
                        sensor_id="immersion_001",
                        sensor_type="immersion",
                        location="低洼点",
                        is_active=True,
                    ),
                ]
            )
            await session.commit()

            with self.assertRaisesRegex(ValueError, "missing sensor"):
                await save_forecast_alert_global_config(
                    control,
                    {
                        "sensor_consistency_models": [
                            {
                                "reference_sensor_id": "ultrasonic_002",
                                "target_sensor_id": "missing_003",
                                "slope": 0.9840,
                                "intercept_cm": -9.26,
                            }
                        ]
                    },
                    db=session,
                )

            with self.assertRaisesRegex(ValueError, "ultrasonic sensors only"):
                await save_forecast_alert_global_config(
                    control,
                    {
                        "sensor_consistency_models": [
                            {
                                "reference_sensor_id": "ultrasonic_002",
                                "target_sensor_id": "immersion_001",
                                "slope": 0.9840,
                                "intercept_cm": -9.26,
                            }
                        ]
                    },
                    db=session,
                )

    async def test_sensor_consistency_run_diagnostics_store_all_models(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            sensor, reading, _profile = await self._seed_sensor(session)
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
                water_level=Decimal("89.14"),
                status="normal",
                recorded_at=reading.recorded_at,
            )
            session.add_all([sensor_003, reading_003])
            await self._seed_forecast(session, "A5151", [0, 0, 0, 0, 0, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            self.assertIsNotNone(run.diagnostics)
            self.assertEqual(len(run.diagnostics), 1)
            self.assertEqual(run.diagnostics[0].get("reference_sensor_id"), "ultrasonic_002")
            self.assertEqual(run.diagnostics[0].get("target_sensor_id"), "ultrasonic_003")

    async def test_sensor_consistency_result_only_contains_related_diagnoses(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            await self._seed_sensor(session)
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
                water_level=Decimal("89.14"),
                status="normal",
                recorded_at=datetime.utcnow(),
            )
            session.add_all([sensor_003, reading_003])
            await self._seed_forecast(session, "A5151", [0, 0, 0, 0, 0, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            for result in run.results:
                diagnoses = result.features.get("sensor_consistency_diagnoses") or []
                for diagnosis in diagnoses:
                    self.assertIn(
                        result.sensor_id,
                        [diagnosis.get("reference_sensor_id"), diagnosis.get("target_sensor_id")],
                    )

    async def test_unavailable_sensor_filters_unrelated_consistency_diagnoses(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            sensor_002, reading_002, _profile = await self._seed_sensor(session)
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
                water_level=Decimal("89.14"),
                status="normal",
                recorded_at=reading_002.recorded_at,
            )
            unavailable_sensor = Sensor(
                sensor_id="ultrasonic_004",
                sensor_type="ultrasonic",
                location="无读数点位",
                warning_level=Decimal("70.0"),
                danger_level=Decimal("60.0"),
                threshold_condition="less_or_equal",
                normal_interval=300,
                is_active=True,
            )
            session.add_all([sensor_003, reading_003, unavailable_sensor])
            await self._seed_forecast(session, "A5151", [0, 0, 0, 0, 0, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            self.assertTrue(run.diagnostics)
            self.assertEqual(run.diagnostics[0].get("reference_sensor_id"), "ultrasonic_002")
            self.assertEqual(run.diagnostics[0].get("target_sensor_id"), "ultrasonic_003")
            results_by_sensor = {result.sensor_id: result for result in run.results}
            result = results_by_sensor["ultrasonic_004"]
            self.assertEqual(result.data_status, "unavailable")
            self.assertEqual(result.features.get("sensor_consistency_diagnoses"), [])

    async def test_sensor_consistency_async_sampling(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            sensor, reading, _profile = await self._seed_sensor(session)
            base_time = reading.recorded_at
            # Reference level 100.0 cm predicts target level 89.14 cm.
            reference_level = Decimal("100.0")
            expected_target = 0.9840 * float(reference_level) - 9.26
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
                water_level=Decimal(str(round(expected_target, 2))),
                status="normal",
                recorded_at=base_time,
            )
            reading.water_level = reference_level
            session.add_all([sensor_003, reading_003])
            await self._seed_forecast(session, "A5151", [0, 0, 0, 0, 0, 0])
            await session.commit()

            # Same time: aligned.
            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            result = run.results[0]
            diagnoses = result.features.get("sensor_consistency_diagnoses") or []
            self.assertTrue(diagnoses)
            diagnosis = diagnoses[0]
            self.assertEqual(diagnosis.get("alignment_status"), "aligned")
            self.assertEqual(diagnosis.get("alignment_delta_seconds"), 0)
            self.assertIsNotNone(diagnosis.get("residual_cm"))
            self.assertLess(abs(diagnosis.get("residual_cm")), 0.1)

            # 2-minute offset: still aligned.
            reading_003.recorded_at = base_time + timedelta(seconds=120)
            await session.commit()
            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            result = run.results[0]
            diagnoses = result.features.get("sensor_consistency_diagnoses") or []
            self.assertTrue(diagnoses)
            diagnosis = diagnoses[0]
            self.assertEqual(diagnosis.get("alignment_status"), "aligned")
            self.assertEqual(diagnosis.get("alignment_delta_seconds"), 120)
            self.assertIsNotNone(diagnosis.get("residual_cm"))

            # 5-minute offset: degraded (relaxed tolerance).
            reading_003.recorded_at = base_time + timedelta(seconds=300)
            await session.commit()
            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            result = run.results[0]
            diagnoses = result.features.get("sensor_consistency_diagnoses") or []
            self.assertTrue(diagnoses)
            diagnosis = diagnoses[0]
            self.assertEqual(diagnosis.get("alignment_status"), "degraded")
            self.assertEqual(diagnosis.get("alignment_delta_seconds"), 300)
            self.assertIsNotNone(diagnosis.get("residual_cm"))

            # 6-minute offset: no consistency conclusion.
            reading_003.recorded_at = base_time + timedelta(seconds=360)
            await session.commit()
            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            result = run.results[0]
            diagnoses = result.features.get("sensor_consistency_diagnoses") or []
            self.assertTrue(diagnoses)
            diagnosis = diagnoses[0]
            self.assertEqual(diagnosis.get("alignment_status"), "unavailable")
            self.assertIsNone(diagnosis.get("residual_cm"))

            # Rapid water level change: target samples at base_time + 60s and +300s
            # bracket the reference sample at base_time + 180s. Without interpolation,
            # either target sample would show a ~0.6 cm residual; interpolation to the
            # common time cancels the change and keeps the residual near zero.
            reading_003.recorded_at = base_time + timedelta(seconds=60)
            reading_003.water_level = Decimal(str(round(expected_target - 0.6, 2)))
            later_003 = SensorReading(
                sensor_id="ultrasonic_003",
                sensor_type="ultrasonic",
                water_level=Decimal(str(round(expected_target + 0.6, 2))),
                status="normal",
                recorded_at=base_time + timedelta(seconds=300),
            )
            reference_mid = SensorReading(
                sensor_id="ultrasonic_002",
                sensor_type="ultrasonic",
                water_level=reference_level,
                status="normal",
                recorded_at=base_time + timedelta(seconds=180),
            )
            session.add_all([later_003, reference_mid])
            await session.commit()
            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            result = run.results[0]
            diagnoses = result.features.get("sensor_consistency_diagnoses") or []
            self.assertTrue(diagnoses)
            diagnosis = diagnoses[0]
            self.assertEqual(diagnosis.get("alignment_status"), "aligned")
            # Interpolation to the common time (base_time + 180s) should cancel the drift.
            self.assertLess(abs(diagnosis.get("residual_cm")), 0.1)

    async def test_a5151_coverage_downgrade_to_backup(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            await self._seed_station(session, "58362", role="backup")
            await self._seed_sensor(session)
            now_hour = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
            # A5151 only has 1/6 hours, below 75% coverage. 58362 is complete.
            session.add(RainfallForecastHourly(
                station_id="A5151",
                hour_time=now_hour,
                rainfall_mm=Decimal("5"),
                batch_time=now_hour,
                forecast_issued_at=now_hour,
            ))
            for i in range(6):
                session.add(RainfallForecastHourly(
                    station_id="58362",
                    hour_time=now_hour + timedelta(hours=i),
                    rainfall_mm=Decimal("0"),
                    batch_time=now_hour,
                    forecast_issued_at=now_hour,
                ))
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            self.assertEqual(result.forecast_station_id, "58362")
            self.assertTrue(result.rain_source_degraded)
            self.assertEqual(result.degraded_reason, "A5151_COVERAGE_INSUFFICIENT")

    async def test_non_numeric_drawdown_value_is_sanitized(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            _sensor, _reading, profile = await self._seed_sensor(session)
            profile.model_params = {
                "net_drawdown_by_pump_count_cm_per_h": {
                    "0": 0.0,
                    "1": None,
                    "2": "not a number",
                    "3": None,
                },
            }
            await self._seed_forecast(session, "A5151", [0, 0, 0, 0, 0, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            features = result.features or {}
            validated = features.get("validated_params", {})
            drawdown = validated.get("net_drawdown_by_pump_count_cm_per_h", {})
            # Non-numeric q2 should be replaced by the default.
            self.assertEqual(drawdown.get("2"), 6.23)
            self.assertEqual(result.data_status, "available")
            self.assertEqual(result.risk_level, "normal")

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

    async def test_degraded_data_returns_hold_manual_review(self):
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            sensor, reading, _profile = await self._seed_sensor(session)
            # Make the reading stale so data_status becomes degraded.
            reading.recorded_at = datetime.utcnow() - timedelta(seconds=sensor.normal_interval * 3)
            await self._seed_forecast(session, "A5151", [20, 20, 20, 0, 0, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            self.assertEqual(result.data_status, "degraded")
            self.assertEqual(result.effective_risk, "unknown")
            recommendation = result.control_recommendation or {}
            self.assertEqual(recommendation.get("action"), "hold_manual_review")
            self.assertEqual(recommendation.get("reason"), "DATA_DEGRADED")
            self.assertFalse(recommendation.get("executable"))

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

    async def test_forecast_config_accepts_frontend_pump_threshold_payload(self):
        from app.schemas import ForecastAlertConfigUpdate

        payload = ForecastAlertConfigUpdate.model_validate({
            "global_config": {
                "enabled": True,
                "default_horizon_hours": 6,
                "cooldown_minutes": 120,
                "model_params": {},
            },
            "profiles": [
                {
                    "sensor_id": "ultrasonic_002",
                    "is_enabled": True,
                    "station_id": None,
                    "horizon_hours": 6,
                    "warning_rise_mm": None,
                    "critical_rise_mm": None,
                    "model_params": None,
                    "pump_params": {
                        "pump_trigger_anchor": "danger",
                        "pump_trigger_offset_mm": 50,
                        "scenario_pump_count": 2,
                        "net_drawdown_by_pump_count_cm_per_h": {
                            "0": 0,
                            "1": None,
                            "2": 6.23,
                            "3": None,
                        },
                        "drawdown_parameter_status": {
                            "0": "defined",
                            "1": "unknown",
                            "2": "inferred",
                            "3": "unknown",
                        },
                    },
                    "actuator_binding_id": None,
                }
            ],
        })

        pump_params = payload.profiles[0].pump_params
        self.assertIsNotNone(pump_params)
        self.assertEqual(pump_params.pump_trigger_anchor, "danger")
        self.assertEqual(pump_params.pump_trigger_offset_mm, 50)
        self.assertEqual(pump_params.scenario_pump_count, 2)

    async def test_legacy_pump_on_rise_mm_is_migrated(self):
        """Old pump_params with pump_on_rise_mm must be accepted and migrated."""
        from app.schemas import ForecastPumpParams

        migrated = ForecastPumpParams.model_validate({
            "pump_on_rise_mm": 50,
            "net_drawdown_by_pump_count_cm_per_h": {
                "0": 0,
                "1": None,
                "2": 6.23,
                "3": None,
            },
            "drawdown_parameter_status": {
                "0": "defined",
                "1": "unknown",
                "2": "inferred",
                "3": "unknown",
            },
        })
        self.assertEqual(migrated.pump_trigger_anchor, "warning")
        self.assertEqual(migrated.pump_trigger_offset_mm, 0)
        self.assertEqual(migrated.scenario_pump_count, 2)

    async def test_scenario_pump_count_is_normalized_to_zero_or_two(self):
        """Until q1/q3 are calibrated, 1 or 3 are normalized to 2."""
        from app.schemas import ForecastPumpParams

        for invalid in (1, 3):
            normalized = ForecastPumpParams(scenario_pump_count=invalid)
            self.assertEqual(normalized.scenario_pump_count, 2)

        zero = ForecastPumpParams(scenario_pump_count=0)
        self.assertEqual(zero.scenario_pump_count, 0)
        two = ForecastPumpParams(scenario_pump_count=2)
        self.assertEqual(two.scenario_pump_count, 2)

    async def test_legacy_scenario_pump_count_one_or_three_is_migrated(self):
        """Old configs with 1 or 3 pumps must be normalized to 2 for GET responses."""
        from app.schemas import ForecastAlertProfileResponse

        for invalid_count in (1, 3):
            response = ForecastAlertProfileResponse(
                sensor_id="ultrasonic_002",
                is_enabled=True,
                pump_params={
                    "pump_trigger_anchor": "warning",
                    "pump_trigger_offset_mm": 0,
                    "scenario_pump_count": invalid_count,
                    "net_drawdown_by_pump_count_cm_per_h": {"0": 0, "1": None, "2": 6.23, "3": None},
                    "drawdown_parameter_status": {"0": "defined", "1": "unknown", "2": "inferred", "3": "unknown"},
                },
            )
            self.assertEqual(response.pump_params.scenario_pump_count, 2)

    async def test_greater_or_equal_pump_threshold_direction(self):
        """For greater_or_equal, the derived threshold is below the anchor level."""
        from app.services.forecast_alerts import _derived_pump_threshold_cm
        from app.models import Sensor
        from decimal import Decimal

        sensor = Sensor(
            sensor_id="ultrasonic_002",
            sensor_type="ultrasonic",
            location="D楼",
            warning_level=Decimal("20.0"),
            danger_level=Decimal("30.0"),
            threshold_condition="greater_or_equal",
        )
        params = {"pump_trigger_anchor": "warning", "pump_trigger_offset_mm": 50}
        # warning=20cm, offset=50mm=5cm, greater_or_equal -> trigger = 20 - 5 = 15cm
        self.assertEqual(_derived_pump_threshold_cm(sensor, params), 15.0)

        params_danger = {"pump_trigger_anchor": "danger", "pump_trigger_offset_mm": 50}
        # danger=30cm, offset=50mm=5cm, greater_or_equal -> trigger = 30 - 5 = 25cm
        self.assertEqual(_derived_pump_threshold_cm(sensor, params_danger), 25.0)

    async def test_pump_assumption_derived_from_drawdown_status(self):
        """pump_assumption should follow drawdown_parameter_status, not a separate field."""
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            sensor, _reading, profile = await self._seed_sensor(
                session, baseline=Decimal("100"), latest=Decimal("100"),
                warning=Decimal("95"), danger=Decimal("90")
            )
            profile.pump_params = {
                "pump_trigger_anchor": "warning",
                "pump_trigger_offset_mm": 0,
                "scenario_pump_count": 2,
                "net_drawdown_by_pump_count_cm_per_h": {"0": 0, "1": None, "2": 6.23, "3": None},
                "drawdown_parameter_status": {"0": "defined", "1": "unknown", "2": "measured", "3": "unknown"},
            }
            await self._seed_forecast(session, "A5151", [20, 20, 20, 0, 0, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            self.assertEqual(result.pump_assumption, "measured_q2")
            series = result.series or []
            active = [s for s in series if s.get("scenario_pump_count")]
            for step in active:
                self.assertEqual(step.get("pump_assumption"), "measured_q2")

    async def test_pump_scenario_triggered_by_sensor_warning_level(self):
        """Pump scenario should activate when projected distance reaches warning level."""
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            # warning=95cm, danger=90cm, condition=less_or_equal, baseline=100cm, latest=100cm
            # Derived threshold = warning + 0mm = 95cm.
            sensor, _reading, _profile = await self._seed_sensor(
                session, baseline=Decimal("100"), latest=Decimal("100"),
                warning=Decimal("95"), danger=Decimal("90")
            )
            # Rainfall pressure should push projected distance below 95cm.
            await self._seed_forecast(session, "A5151", [20, 20, 20, 0, 0, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            series = result.series or []
            active_steps = [s for s in series if s.get("scenario_pump_count")]
            self.assertTrue(active_steps)
            for step in active_steps:
                self.assertEqual(step.get("pump_assumption"), "inferred_q2")
                self.assertEqual(step.get("actual_pump_state"), "unknown")
            # The peak projected distance should be at or below the 95cm trigger line.
            features = result.features or {}
            self.assertEqual(features.get("validated_params", {}).get("derived_pump_threshold_cm"), 95.0)

    async def test_pump_scenario_includes_existing_rise(self):
        """If current level is already close to warning, a small future rise should trigger pumps."""
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            # warning=95cm, danger=90cm, baseline=100cm, latest=96cm (already 4cm rise)
            # Derived threshold = 95cm. Projected distance starts at 96cm, so only 1cm more rise triggers.
            sensor, _reading, _profile = await self._seed_sensor(
                session, baseline=Decimal("100"), latest=Decimal("96"),
                warning=Decimal("95"), danger=Decimal("90")
            )
            # Small rainfall: only 10mm total rise, but h_start already 40mm.
            await self._seed_forecast(session, "A5151", [2, 2, 2, 2, 2, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            series = result.series or []
            # Because h_start is included, the scenario should eventually trigger.
            active_steps = [s for s in series if s.get("scenario_pump_count")]
            self.assertTrue(active_steps)

    async def test_pump_scenario_holds_to_end_once_triggered(self):
        """Once the pump scenario triggers, it should remain active for the rest of the window."""
        async with self.business_session_factory() as session, self.control_session_factory() as control:
            await self._seed_station(session, "A5151")
            sensor, _reading, _profile = await self._seed_sensor(
                session, baseline=Decimal("100"), latest=Decimal("100"),
                warning=Decimal("95"), danger=Decimal("90")
            )
            # Heavy rain first two hours, then stops. Without hold logic the scenario would switch off.
            await self._seed_forecast(session, "A5151", [25, 25, 0, 0, 0, 0])
            await session.commit()

            run = await evaluate_forecast_alerts(session, control, dry_run=True)
            await session.commit()

            result = run.results[0]
            series = result.series or []
            self.assertTrue(any(s.get("scenario_pump_count") for s in series))
            # Once triggered, every subsequent hour must remain active (no on-off chatter).
            triggered = False
            for step in series:
                if step.get("scenario_pump_count"):
                    triggered = True
                if triggered:
                    self.assertGreater(step.get("scenario_pump_count", 0), 0)


if __name__ == "__main__":
    unittest.main()
