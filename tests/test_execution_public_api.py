from __future__ import annotations

import unittest
from unittest.mock import patch

from app.execution import execute_signal


class PublicExecutionApiTests(unittest.TestCase):
    def test_unconfirmed_fill_is_emergency_closed_before_returning(self) -> None:
        client = object()
        pending_trade = {
            "journal_id": "exec-unconfirmed",
            "symbol": "BTCUSDT",
            "direction": "long",
            "quantity": "1",
            "status": "fill_confirmation_pending",
            "exchange_metadata": {"fill_confirmation_error": "order snapshot unavailable"},
        }
        safe_trade = {
            **pending_trade,
            "status": "close_pending_sync",
            "result": "execution_safety_close",
            "close_reason": "FILL_CONFIRMATION_UNAVAILABLE",
        }

        with (
            patch("app.execution._execute_signal_authoritatively", return_value={
                "ok": False,
                "error": "FILL_CONFIRMATION_UNAVAILABLE",
                "trade": pending_trade,
                "sizing": {"quantity": "1"},
            }),
            patch("app.execution._emergency_close_pending_sync", return_value={
                "ok": False,
                "error": "FILL_CONFIRMATION_UNAVAILABLE",
                "trade": safe_trade,
                "sizing": {"quantity": "1"},
            }) as emergency_close,
            patch("app.execution.update_active_trade") as update_active,
        ):
            result = execute_signal(client, {"symbol": "BTCUSDT"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["trade"]["status"], "close_pending_sync")
        emergency_close.assert_called_once()
        update_active.assert_called_once()

    def test_confirmed_execution_result_passes_through_unchanged(self) -> None:
        expected = {"ok": True, "trade": {"status": "active"}}
        with patch("app.execution._execute_signal_authoritatively", return_value=expected):
            result = execute_signal(object(), {"symbol": "BTCUSDT"})
        self.assertIs(result, expected)


if __name__ == "__main__":
    unittest.main()
