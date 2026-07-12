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

    def test_confirmed_execution_installs_and_persists_native_profit_orders(self) -> None:
        trade = {
            "journal_id": "exec-native",
            "execution_key": "a" * 64,
            "symbol": "BTCUSDT",
            "direction": "long",
            "quantity": 10.0,
            "status": "active",
            "management": {"initial_quantity": 10.0, "tp1": 104.0, "tp2": 105.0},
            "exchange_metadata": {},
        }
        expected = {"ok": True, "trade": trade, "sizing": {"quantity": "10"}}
        management = {
            **trade["management"],
            "native_tp_enabled": True,
            "tp1_order_link_id": "df-t1-key",
            "tp2_order_link_id": "df-t2-key",
        }
        orders = {
            "tp1": {"order_link_id": "df-t1-key", "quantity": 5.0},
            "tp2": {"order_link_id": "df-t2-key", "quantity": 2.5},
        }

        with (
            patch("app.execution._execute_signal_authoritatively", return_value=expected),
            patch("app.execution.install_native_profit_orders", return_value={
                "ok": True,
                "management": management,
                "orders": orders,
            }) as install,
            patch("app.execution.update_trade_entry", return_value={"journal_id": "exec-native"}) as persist,
            patch("app.execution.update_active_trade") as update_active,
            patch("app.execution.append_trade_event"),
        ):
            result = execute_signal(object(), {"symbol": "BTCUSDT"})

        self.assertTrue(result["ok"])
        self.assertTrue(result["trade"]["management"]["native_tp_enabled"])
        self.assertEqual(result["native_profit_orders"], orders)
        install.assert_called_once()
        persist.assert_called_once()
        update_active.assert_called_once()

    def test_native_profit_order_failure_emergency_closes_trade(self) -> None:
        trade = {
            "journal_id": "exec-native-fail",
            "execution_key": "b" * 64,
            "symbol": "BTCUSDT",
            "direction": "long",
            "quantity": 10.0,
            "status": "active",
            "management": {"initial_quantity": 10.0, "tp1": 104.0, "tp2": 105.0},
            "exchange_metadata": {},
        }
        safe_trade = {
            **trade,
            "status": "close_pending_sync",
            "result": "execution_safety_close",
            "close_reason": "NATIVE_TP_INSTALLATION_FAILED",
        }

        with (
            patch("app.execution._execute_signal_authoritatively", return_value={"ok": True, "trade": trade, "sizing": {}}),
            patch("app.execution.install_native_profit_orders", return_value={"ok": False, "error": "order rejected"}),
            patch("app.execution.cancel_native_profit_orders") as cancel,
            patch("app.execution._emergency_close_pending_sync", return_value={
                "ok": False,
                "error": "NATIVE_TP_INSTALLATION_FAILED",
                "trade": safe_trade,
                "sizing": {},
            }) as emergency_close,
            patch("app.execution.update_active_trade"),
        ):
            result = execute_signal(object(), {"symbol": "BTCUSDT"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "NATIVE_TP_INSTALLATION_FAILED")
        cancel.assert_called_once()
        emergency_close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
