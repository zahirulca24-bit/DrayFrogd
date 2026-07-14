from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from app.scalping_cooldown import sync_scalping_reentry_cooldowns


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self.rows)


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.closed = False

    def query(self, *_args, **_kwargs):
        return _FakeQuery(self.rows)

    def close(self):
        self.closed = True


class ScalpingCooldownFailureTests(unittest.TestCase):
    def test_database_open_failure_returns_fail_closed_result(self) -> None:
        with patch("app.scalping_cooldown.SessionLocal", side_effect=RuntimeError("database unavailable")), patch(
            "app.scalping_cooldown.start_loss_cooldown"
        ) as start_cooldown:
            result = sync_scalping_reentry_cooldowns(now=datetime(2026, 7, 14, 12, 0, tzinfo=UTC))

        self.assertFalse(result["ok"])
        self.assertEqual(result["active_symbols"], [])
        self.assertIn("database unavailable", result["error"])
        start_cooldown.assert_not_called()

    def test_journal_session_is_closed_before_risk_cooldown_write(self) -> None:
        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
        session = _FakeSession(
            [
                SimpleNamespace(
                    symbol="BTCUSDT",
                    closed_at=(now - timedelta(minutes=5)).isoformat(),
                    exchange_metadata=json.dumps({"management": {"trade_type": "scalping"}}),
                )
            ]
        )

        def assert_closed_before_write(**_kwargs):
            self.assertTrue(session.closed)

        with patch("app.scalping_cooldown.SessionLocal", return_value=session), patch(
            "app.scalping_cooldown.start_loss_cooldown", side_effect=assert_closed_before_write
        ) as start_cooldown:
            result = sync_scalping_reentry_cooldowns(now=now)

        self.assertTrue(result["ok"])
        self.assertEqual(result["active_symbols"], ["BTCUSDT"])
        start_cooldown.assert_called_once()


if __name__ == "__main__":
    unittest.main()
