"""Regression tests for the business database watchdog."""
import os
import sys
import unittest
from unittest.mock import patch

CURRENT_DIR = os.path.dirname(__file__)
BACKEND_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

IMPORT_ERROR = None

try:
    from app.services.health_watchdog import (
        _env_flag,
        business_database_watchdog,
        get_process_rss_bytes,
        memory_watchdog,
        start_business_database_watchdog,
        start_memory_watchdog,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
    IMPORT_ERROR = exc


@unittest.skipIf(IMPORT_ERROR is not None, f"backend dependencies unavailable: {IMPORT_ERROR}")
class HealthWatchdogTests(unittest.IsolatedAsyncioTestCase):
    def test_env_flag_parses_common_values(self):
        with patch.dict(os.environ, {"UNIT_FLAG": "true"}):
            self.assertTrue(_env_flag("UNIT_FLAG", default=False))
        with patch.dict(os.environ, {"UNIT_FLAG": "0"}):
            self.assertFalse(_env_flag("UNIT_FLAG", default=True))
        with patch.dict(os.environ, {"UNIT_FLAG": "unexpected"}):
            self.assertTrue(_env_flag("UNIT_FLAG", default=True))

    def test_watchdog_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(start_business_database_watchdog())
            self.assertIsNone(start_memory_watchdog())

    def test_process_rss_reader_returns_an_integer(self):
        self.assertGreaterEqual(get_process_rss_bytes(), 0)

    async def test_watchdog_exits_after_consecutive_failures(self):
        exits = []

        async def failing_ping():
            raise TimeoutError("unit timeout")

        def fake_exit(code):
            exits.append(code)

        await business_database_watchdog(
            interval_seconds=0,
            timeout_seconds=0.1,
            max_failures=2,
            startup_grace_seconds=0,
            exit_code=12,
            ping=failing_ping,
            exit_fn=fake_exit,
        )

        self.assertEqual(exits, [12])

    async def test_memory_watchdog_exits_when_limit_is_exceeded(self):
        exits = []

        def fake_exit(code):
            exits.append(code)

        await memory_watchdog(
            interval_seconds=0,
            limit_bytes=100,
            exit_code=13,
            rss_reader=lambda: 101,
            exit_fn=fake_exit,
        )

        self.assertEqual(exits, [13])


if __name__ == "__main__":
    unittest.main()
