"""Regression tests for rainfall parsing helpers."""
import os
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal

CURRENT_DIR = os.path.dirname(__file__)
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

IMPORT_ERROR = None

try:
    from app.services.weather import parse_ztq_rainfall_payload, select_rainfall_summary_station
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


if __name__ == "__main__":
    unittest.main()
