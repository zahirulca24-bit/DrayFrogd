from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.batch2_authority import (
    config_authority_snapshot,
    database_durability_status,
    normalize_config_payload,
)
from app.database import Base, engine
import app.bot_controls as bot_controls


class Batch2AuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        Base.metadata.create_all(bind=engine)

    def test_production_sqlite_is_not_execution_safe(self) -> None:
        with (
            patch("app.batch2_authority.DATABASE_URL", "sqlite:///./runtime.db"),
            patch("app.batch2_authority.settings", SimpleNamespace(app_env="production")),
            patch("app.batch2_authority.check_database_connection", return_value=None),
        ):
            status = database_durability_status()

        self.assertEqual(status["backend"], "sqlite")
        self.assertEqual(status["durability_mode"], "ephemeral_or_unverified_sqlite")
        self.assertFalse(status["execution_safe"])
        self.assertIn("requires PostgreSQL", status["reason"])

    def test_postgresql_is_durable_when_connection_is_healthy(self) -> None:
        with (
            patch("app.batch2_authority.DATABASE_URL", "postgresql+psycopg://example/db"),
            patch("app.batch2_authority.settings", SimpleNamespace(app_env="production")),
            patch("app.batch2_authority.check_database_connection", return_value=None),
        ):
            status = database_durability_status()

        self.assertEqual(status["backend"], "postgresql")
        self.assertEqual(status["durability_mode"], "managed_postgresql")
        self.assertTrue(status["execution_safe"])
        self.assertTrue(status["connection_ok"])

    def test_normalized_config_declares_fixed_usdt_authority(self) -> None:
        with (
            patch(
                "app.batch2_authority.config_authority_snapshot",
                return_value={
                    "version": 7,
                    "source": "test",
                    "effective_at": "2026-07-18T00:00:00+00:00",
                    "authority": "backend_bot_runtime_config_v2",
                },
            ),
            patch(
                "app.batch2_authority._trade_count_snapshot",
                return_value={
                    "date": "2026-07-18",
                    "timezone": "Asia/Dhaka",
                    "configured_limit": 0,
                    "limit_enabled": False,
                    "attempted": 4,
                    "orders_accepted": 4,
                    "positions_opened": 4,
                    "active_now": 0,
                },
            ),
        ):
            payload = normalize_config_payload({"risk_per_trade": 0.0215, "max_daily_trades": 8})

        self.assertEqual(payload["risk_model"], "profile_fixed_usdt")
        self.assertEqual(payload["risk_per_trade"], 0.01)
        self.assertTrue(payload["risk_per_trade_read_only"])
        self.assertEqual(payload["risk_per_trade_authority"], "profile_fixed_usdt")
        self.assertEqual(payload["max_daily_trades"], 0)
        self.assertFalse(payload["daily_trade_limit_enabled"])
        self.assertEqual(payload["config_authority"]["version"], 7)
        self.assertEqual(payload["trade_counts"]["active_now"], 0)

    def test_conflicting_percentage_risk_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "read-only compatibility data"):
            bot_controls.update_bot_config(risk_per_trade=0.0215)

    def test_config_authority_snapshot_is_persistent_metadata(self) -> None:
        snapshot = config_authority_snapshot()
        self.assertGreaterEqual(snapshot["version"], 1)
        self.assertTrue(snapshot["source"])
        self.assertTrue(snapshot["effective_at"])
        self.assertEqual(snapshot["authority"], "backend_bot_runtime_config_v2")


if __name__ == "__main__":
    unittest.main()
