"""Regression tests for rainfall parsing helpers."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

CURRENT_DIR = os.path.dirname(__file__)
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

IMPORT_ERROR = None

try:
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database import BusinessBase
    from app.models import (
        RainfallActualHourly,
        RainfallActualRevision,
        RainfallForecastHourly,
        WeatherStation,
    )
    from app.routers.weather import get_rainfall_history, get_rainfall_revisions
    from app.services.weather import (
        RainfallPoint,
        build_station_summary,
        floor_to_hour,
        parse_ztq_rainfall_payload,
        select_rainfall_summary_station,
        utcnow_naive,
        _upsert_rainfall_points,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
    IMPORT_ERROR = exc


@unittest.skipIf(IMPORT_ERROR is not None, f"backend dependencies unavailable: {IMPORT_ERROR}")
class WeatherParsingTests(unittest.TestCase):
    def test_parse_trend_payload_keeps_actual_and_forecast_hours(self):
        trend_data = {
            "sk_time": "05月21日19时-05月22日18时",
            "sk_list": [
                {"dt": "17时", "val": "0", "fulldt": "22日17时"},
                {"dt": "18时", "val": "0.1", "fulldt": "22日18时"},
            ],
            "yb_time": "05月22日19时-05月23日18时",
            "yb_list": [
                {"dt": "19时", "val": "0.0", "fulldt": "22日19时"},
                {"dt": "23日0时", "val": "0.3", "fulldt": "23日0时"},
            ],
        }
        current_data = {"rainfall": "0", "upt": "05-22 18:40"}

        parsed = parse_ztq_rainfall_payload(
            "58362",
            trend_data,
            current_data,
            reference_now=datetime(2026, 5, 22, 10, 45, tzinfo=timezone.utc),
        )

        self.assertEqual(len(parsed.points), 4)
        self.assertTrue(parsed.has_positive_rainfall)
        self.assertEqual(parsed.points[0].data_type, "actual")
        self.assertEqual(parsed.points[0].hour_time, datetime(2026, 5, 22, 9, 0))
        self.assertEqual(parsed.points[1].rainfall_mm, Decimal("0.1"))
        self.assertEqual(parsed.points[2].data_type, "forecast")
        self.assertEqual(parsed.points[2].hour_time, datetime(2026, 5, 22, 11, 0))
        self.assertEqual(parsed.points[2].forecast_issued_at, datetime(2026, 5, 22, 10, 0))
        self.assertEqual(parsed.source_updated_at, datetime(2026, 5, 22, 10, 40))

    def test_empty_payload_is_tolerated(self):
        parsed = parse_ztq_rainfall_payload(
            "A5151",
            {},
            {},
            reference_now=datetime(2026, 5, 22, 10, 45, tzinfo=timezone.utc),
        )

        self.assertEqual(parsed.points, [])
        self.assertFalse(parsed.has_positive_rainfall)


@unittest.skipIf(IMPORT_ERROR is not None, f"backend dependencies unavailable: {IMPORT_ERROR}")
class WeatherSummarySelectionTests(unittest.TestCase):
    def _station(self, station_id, role, *, stale=False, error=""):
        return {
            "station_id": station_id,
            "station_name": station_id,
            "role": role,
            "is_stale": stale,
            "last_error": error,
        }

    def test_selects_backup_when_primary_is_stale(self):
        selected, reason = select_rainfall_summary_station([
            self._station("A5151", "primary", stale=True),
            self._station("58362", "backup"),
        ])

        self.assertEqual(selected["station_id"], "58362")
        self.assertEqual(reason, "backup")

    def test_keeps_primary_when_backup_is_also_unavailable(self):
        selected, reason = select_rainfall_summary_station([
            self._station("A5151", "primary", stale=True),
            self._station("58362", "backup", error="接口空响应"),
        ])

        self.assertEqual(selected["station_id"], "A5151")
        self.assertEqual(reason, "primary_unavailable")

    def test_falls_back_to_backup_when_primary_is_missing(self):
        selected, reason = select_rainfall_summary_station([
            self._station("58362", "backup"),
        ])

        self.assertEqual(selected["station_id"], "58362")
        self.assertEqual(reason, "backup")


@unittest.skipIf(IMPORT_ERROR is not None, f"backend dependencies unavailable: {IMPORT_ERROR}")
class WeatherStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "weather-storage.db"
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

    def _actual_point(self, hour_time: datetime, value: str) -> RainfallPoint:
        return RainfallPoint(
            station_id="A5151",
            data_type="actual",
            hour_time=hour_time,
            rainfall_mm=Decimal(value),
            raw_time_label="23日10时",
            source_updated_at=datetime(2026, 5, 23, 10, 40),
        )

    def _forecast_point(self, hour_time: datetime, value: str, batch_time: datetime) -> RainfallPoint:
        return RainfallPoint(
            station_id="A5151",
            data_type="forecast",
            hour_time=hour_time,
            rainfall_mm=Decimal(value),
            raw_time_label="23日11时",
            forecast_issued_at=batch_time,
            source_updated_at=datetime(2026, 5, 23, 10, 40),
        )

    async def test_actual_repeat_same_value_does_not_write_revision(self):
        hour_time = datetime(2026, 5, 23, 10)
        async with self.session_factory() as session:
            await _upsert_rainfall_points(
                session,
                [self._actual_point(hour_time, "0.1")],
                reference_now=datetime(2026, 5, 23, 10, 45, tzinfo=timezone.utc),
            )
            await session.commit()
            await _upsert_rainfall_points(
                session,
                [self._actual_point(hour_time, "0.1")],
                reference_now=datetime(2026, 5, 23, 11, 5, tzinfo=timezone.utc),
            )
            await session.commit()

            actual_count = await session.scalar(select(func.count()).select_from(RainfallActualHourly))
            revision_count = await session.scalar(select(func.count()).select_from(RainfallActualRevision))
            self.assertEqual(actual_count, 1)
            self.assertEqual(revision_count, 0)

    async def test_actual_value_change_updates_latest_and_writes_revision(self):
        hour_time = datetime(2026, 5, 23, 10)
        async with self.session_factory() as session:
            await _upsert_rainfall_points(
                session,
                [self._actual_point(hour_time, "0.1")],
                reference_now=datetime(2026, 5, 23, 10, 45, tzinfo=timezone.utc),
            )
            await session.commit()
            await _upsert_rainfall_points(
                session,
                [self._actual_point(hour_time, "0.3")],
                reference_now=datetime(2026, 5, 23, 11, 5, tzinfo=timezone.utc),
            )
            await session.commit()

            actual = (await session.execute(select(RainfallActualHourly))).scalar_one()
            revision = (await session.execute(select(RainfallActualRevision))).scalar_one()
            self.assertEqual(actual.rainfall_mm, Decimal("0.3"))
            self.assertEqual(revision.old_rainfall_mm, Decimal("0.1"))
            self.assertEqual(revision.new_rainfall_mm, Decimal("0.3"))

    async def test_history_route_paginates_actual_records_with_revision_counts(self):
        revised_hour = datetime(2026, 5, 23, 10)
        previous_hour = revised_hour - timedelta(hours=1)
        async with self.session_factory() as session:
            session.add(WeatherStation(
                station_id="A5151",
                station_name="宝山大场上大附中",
                role="primary",
                is_active=True,
            ))
            await _upsert_rainfall_points(
                session,
                [
                    self._actual_point(previous_hour, "0.2"),
                    self._actual_point(revised_hour, "0.1"),
                ],
                reference_now=datetime(2026, 5, 23, 10, 45, tzinfo=timezone.utc),
            )
            await session.commit()
            await _upsert_rainfall_points(
                session,
                [self._actual_point(revised_hour, "0.3")],
                reference_now=datetime(2026, 5, 23, 11, 5, tzinfo=timezone.utc),
            )
            await session.commit()

            page_one = await get_rainfall_history(
                station_id="A5151",
                data_type="actual",
                start_time=previous_hour,
                end_time=revised_hour,
                limit=1,
                page=1,
                _={},
                db=session,
            )
            page_two = await get_rainfall_history(
                station_id="A5151",
                data_type="actual",
                start_time=previous_hour,
                end_time=revised_hour,
                limit=1,
                page=2,
                _={},
                db=session,
            )

            self.assertEqual(page_one["total"], 2)
            self.assertEqual(page_one["page_size"], 1)
            self.assertEqual(page_one["items"][0]["hour_time"], revised_hour)
            self.assertEqual(page_one["items"][0]["rainfall_mm"], Decimal("0.3"))
            self.assertEqual(page_one["items"][0]["revision_count"], 1)
            self.assertEqual(page_one["items"][0]["station_name"], "宝山大场上大附中")
            self.assertEqual(page_two["items"][0]["hour_time"], previous_hour)

    async def test_revisions_route_filters_by_revised_hour(self):
        revised_hour = datetime(2026, 5, 23, 10)
        async with self.session_factory() as session:
            session.add(WeatherStation(
                station_id="A5151",
                station_name="宝山大场上大附中",
                role="primary",
                is_active=True,
            ))
            await _upsert_rainfall_points(
                session,
                [self._actual_point(revised_hour, "0.1")],
                reference_now=datetime(2026, 5, 23, 10, 45, tzinfo=timezone.utc),
            )
            await session.commit()
            await _upsert_rainfall_points(
                session,
                [self._actual_point(revised_hour, "0.3")],
                reference_now=datetime(2026, 5, 23, 11, 5, tzinfo=timezone.utc),
            )
            await session.commit()

            response = await get_rainfall_revisions(
                station_id="A5151",
                start_time=revised_hour,
                end_time=revised_hour,
                time_field="hour_time",
                limit=10,
                page=1,
                _={},
                db=session,
            )

            self.assertEqual(response["total"], 1)
            self.assertEqual(response["items"][0]["hour_time"], revised_hour)
            self.assertEqual(response["items"][0]["old_rainfall_mm"], Decimal("0.1"))
            self.assertEqual(response["items"][0]["new_rainfall_mm"], Decimal("0.3"))
            self.assertEqual(response["items"][0]["station_name"], "宝山大场上大附中")

    async def test_forecast_keeps_latest_batch_inside_rolling_24h_window(self):
        window_start = datetime(2026, 5, 23, 0)
        first_batch = datetime(2026, 5, 22, 23)
        second_batch = datetime(2026, 5, 23, 0)
        first_points = [
            self._forecast_point(window_start + timedelta(hours=offset), "0.1", first_batch)
            for offset in range(-1, 26)
        ]
        second_points = [
            self._forecast_point(window_start + timedelta(hours=offset), "0.2", second_batch)
            for offset in range(0, 24)
        ]

        async with self.session_factory() as session:
            await _upsert_rainfall_points(
                session,
                first_points,
                reference_now=window_start.replace(tzinfo=timezone.utc),
            )
            await session.commit()
            await _upsert_rainfall_points(
                session,
                second_points,
                reference_now=window_start.replace(tzinfo=timezone.utc),
            )
            await session.commit()

            count = await session.scalar(select(func.count()).select_from(RainfallForecastHourly))
            min_value = await session.scalar(select(func.min(RainfallForecastHourly.rainfall_mm)))
            max_batch = await session.scalar(select(func.max(RainfallForecastHourly.batch_time)))
            self.assertEqual(count, 24)
            self.assertEqual(min_value, Decimal("0.2"))
            self.assertEqual(max_batch, second_batch)

    async def test_summary_uses_split_forecast_table_for_totals(self):
        now_hour = floor_to_hour(utcnow_naive())
        async with self.session_factory() as session:
            station = WeatherStation(
                station_id="A5151",
                station_name="宝山大场上大附中",
                role="primary",
                is_active=True,
                last_success_at=utcnow_naive(),
            )
            session.add(station)
            await _upsert_rainfall_points(
                session,
                [
                    self._actual_point(now_hour, "0.0"),
                    self._forecast_point(now_hour, "0.1", now_hour),
                    self._forecast_point(now_hour + timedelta(hours=1), "0.2", now_hour),
                    self._forecast_point(now_hour + timedelta(hours=2), "0.3", now_hour),
                ],
                reference_now=now_hour.replace(tzinfo=timezone.utc),
            )
            await session.commit()

            summary = await build_station_summary(session, station)
            self.assertEqual(summary["forecast_totals"]["next_1h"], 0.1)
            self.assertEqual(summary["forecast_totals"]["next_3h"], 0.6)


if __name__ == "__main__":
    unittest.main()
