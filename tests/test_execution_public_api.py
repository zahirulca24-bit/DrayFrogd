from __future__ import annotations

import unittest
from unittest.mock import patch

from app.execution import execute_signal


ALLOWED_SPREAD = {
    "allowed": True,
    "reason": "",
    "spread_bps": 10.0,
    "max_spread_bps": 50.0,
}


class PublicExecutionApiTests(unittest.TestCase):
    def test_high_spread_is_rejected_before_authoritative_execution(self) -> None:
        with (
            patch("app.execution._execution_spread_gate", return_value={
                "allowed": False,
                "reason": "Spread 75.00 bps exceeds maximum 50.00 bps",
                "spread_bps": 75.0,
                "max_spread_bps": 50.0,
            }),
            patch("app.execution._execute_signal_authoritatively") as execute,
        ):
            result = execute_signal(object(), {"symbol": "BTCUSDT"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "SPREAD_GATE_REJECTED")
        execute.assert_not_called()

    def test_unconfirmed_fill_is_emergency_closed_before_returning(self) -> None:
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
            patch("app.execution._execution_spread_gate", return_value=ALLOWED_SPREAD),
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
            result = execute_signal(object(), {"symbol": "BTCUSDT"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["trade"]["status"], "close_pending_sync")
        emergency_close.assert_called_once()
        update_active.assert_called_once()

    def test_confirmed_scalping_execution_installs_profile_and_native_orders(self) -> None:
        original_trade = {
            "journal_id": "exec-native",
            "execution_key": "a" * 64,
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 98.0,
            "take_profit": 103.0,
            "quantity": 10.0,
            "remaining_quantity": 10.0,
            "status": "active",
            "management": {},
            "exchange_metadata": {"trade_type": "scalping"},
        }
        profiled_management = {
            "profile_name": "scalping_v2",
            "trade_type": "scalping",
            "initial_quantity": 10.0,
            "tp1": 103.0,
            "tp2": 104.0,
            "runner_target": 105.0,
            "trailing_enabled": False,
        }
        profiled_trade = {
            **original_trade,
            "trade_type": "scalping",
            "take_profit": 105.0,
            "management": profiled_management,
            "exchange_metadata": {
                **original_trade["exchange_metadata"],
                "management": profiled_management,
            },
        }
        native_management = {
            **profiled_management,
            "native_tp_enabled": True,
            "tp1_order_link_id": "df-t1-key",
            "tp2_order_link_id": "df-t2-key",
        }
        orders = {
            "tp1": {"order_link_id": "df-t1-key", "quantity": 5.0},
            "tp2": {"order_link_id": "df-t2-key", "quantity": 2.5},
        }

        with (
            patch("app.execution._execution_spread_gate", return_value=ALLOWED_SPREAD),
            patch("app.execution._execute_signal_authoritatively", return_value={
                "ok": True,
                "trade": original_trade,
                "sizing": {"quantity": "10"},
            }),
            patch("app.execution._apply_management_profile", return_value={
                "ok": True,
                "trade": profiled_trade,
            }) as profile,
            patch("app.execution.install_native_profit_orders", return_value={
                "ok": True,
                "management": native_management,
                "orders": orders,
            }) as install,
            patch("app.execution.update_trade_entry", return_value={"journal_id": "exec-native"}) as persist,
            patch("app.execution.update_active_trade") as update_active,
            patch("app.execution.append_trade_event"),
        ):
            result = execute_signal(object(), {"symbol": "BTCUSDT"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["management_profile"], "scalping_v2")
        self.assertEqual(result["trade"]["take_profit"], 105.0)
        self.assertFalse(result["trade"]["management"]["trailing_enabled"])
        self.assertEqual(result["native_profit_orders"], orders)
        profile.assert_called_once()
        install.assert_called_once()
        persist.assert_called_once()
        update_active.assert_called_once()

    def test_native_profit_order_failure_emergency_closes_trade(self) -> None:
        trade = {
            "journal_id": "exec-native-fail",
            "execution_key": "b" * 64,
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 98.0,
            "take_profit": 105.0,
            "quantity": 10.0,
            "remaining_quantity": 10.0,
            "status": "active",
            "management": {"profile_name": "scalping_v2", "initial_quantity": 10.0, "tp1": 103.0, "tp2": 104.0},
            "exchange_metadata": {"trade_type": "scalping"},
        }
        safe_trade = {
            **trade,
            "status": "close_pending_sync",
            "result": "execution_safety_close",
            "close_reason": "NATIVE_TP_INSTALLATION_FAILED",
        }

        with (
            patch("app.execution._execution_spread_gate", return_value=ALLOWED_SPREAD),
            patch("app.execution._execute_signal_authoritatively", return_value={"ok": True, "trade": trade, "sizing": {}}),
            patch("app.execution._apply_management_profile", return_value={"ok": True, "trade": trade}),
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
