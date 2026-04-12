"""Lightweight smoke tests for critical helper functions."""
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
    from app.database import build_database_url, get_database_backend_name, should_auto_create_schema
    from app.models import SensorType
    from app.routers.sensors import (
        generate_webhook_token,
        get_sensor_type_value,
        extract_device_imei,
        extract_water_detected,
        extract_group_water_level,
    )
    from app.schemas import GroupWebhookDataInput
    from app.services.account import build_gravatar
    from app.services.internal_auth import get_internal_api_token
except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
    IMPORT_ERROR = exc


@unittest.skipIf(IMPORT_ERROR is not None, f"backend dependencies unavailable: {IMPORT_ERROR}")
class SmokeTests(unittest.TestCase):
    def test_build_gravatar_normalizes_email(self):
        gravatar = build_gravatar(" Admin@Example.COM ")
        self.assertEqual(gravatar["avatar_hash"], "e64c7d89f26bd1972efa854d13d7dd61")
        self.assertIn("https://www.gravatar.com/avatar/", gravatar["avatar_url"])

    def test_generate_webhook_token_length(self):
        token = generate_webhook_token()
        self.assertEqual(len(token), 16)
        self.assertTrue(token.isalnum())

    def test_get_sensor_type_value_accepts_enum_and_string(self):
        self.assertEqual(get_sensor_type_value(SensorType.ULTRASONIC), "ultrasonic")
        self.assertEqual(get_sensor_type_value("immersion"), "immersion")

    def test_group_webhook_helpers_normalize_payload(self):
        payload = GroupWebhookDataInput(device_id="863237085571598", water_status=1)
        self.assertEqual(extract_device_imei(payload), "863237085571598")
        self.assertTrue(extract_water_detected(payload))
        ultrasonic_payload = GroupWebhookDataInput(sensor_value="128.4")
        self.assertEqual(extract_group_water_level(ultrasonic_payload), 128.4)

    def test_get_internal_api_token_reads_environment(self):
        with patch.dict(os.environ, {"INTERNAL_API_TOKEN": "shared-token"}):
            self.assertEqual(get_internal_api_token(), "shared-token")

    def test_build_database_url_prefers_full_dsn(self):
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "sqlite+aiosqlite:///./runtime.db"},
            clear=False,
        ):
            self.assertEqual(build_database_url(), "sqlite+aiosqlite:///./runtime.db")
            self.assertEqual(get_database_backend_name(build_database_url()), "sqlite")

    def test_build_database_url_supports_structured_sqlite_settings(self):
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "",
                "DB_DIALECT": "sqlite",
                "DB_DRIVER": "aiosqlite",
                "DB_NAME": "./tmp/test.db",
            },
            clear=False,
        ):
            self.assertEqual(build_database_url(), "sqlite+aiosqlite:///./tmp/test.db")

    def test_should_auto_create_schema_defaults_to_false_for_dm(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AUTO_CREATE_SCHEMA", None)
            self.assertFalse(should_auto_create_schema("dm"))
            self.assertTrue(should_auto_create_schema("mysql"))

    def test_should_auto_create_schema_honors_override(self):
        with patch.dict(os.environ, {"AUTO_CREATE_SCHEMA": "true"}, clear=False):
            self.assertTrue(should_auto_create_schema("dm"))


if __name__ == "__main__":
    unittest.main()
