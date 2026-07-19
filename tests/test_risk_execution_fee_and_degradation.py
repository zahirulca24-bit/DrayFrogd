from __future__ import annotations

import unittest
from unittest.mock import patch

from app import risk_execution


SIGNAL = {
    "symbol": "HYPEUSDT",
    "strategy_name": "ema_pullback",
    "trade_type": "scalping",
    "direction": "long",
    "entry": 100.0,
    "stop_loss": 99.0,
    "take_profit": 102.5,
    "risk_reward": 2.5,
    "detected_at": "2026-07-19T00:00:00+00:00",
    "status": "active",
    "signal_state": "ACTIVE",
    "is_executable": True,
    "primary_signal": True,
}

TRADE = {
    "journal_id": "journal-1",
    "execution_key": "execution-1",
    "symbol": "HYPEUSDT",
    "trade_type": "scalping",
    "direction": "long",
    "entry": 100.0,
    "stop_loss": 99.0,
    "take_profit": 102.5,
    "quantity": 10.0,
    "remaining_quantity": 10.0,
    "status": "active",
    "management": {
        "profile_name": "scalping_v2",
        "trade_type": "scalping",
        "runner_target": 102.5,
        "initial_quantity": 10.0,
    },
    "exchange_metadata": {
        "protection_attached": True,
        "protection_verified": True,
    },
}


class FakeClient:
    def safe_fetch_wallet_balance(self):
        return True, {"totalEquity": "1000", "totalAvailableBalance": "1000"}, None

    def safe_fetch_symbol_info(self, *, symbol):
        return True, [{"qtyStep": "0.1", "tickSize": "0.01", "minOrderQty": "0.1"}], None

    def safe_fetch_positions(self):
        return True, [], None


class RiskExecutionFeeAndDegradationTests(unittest.TestCase):
    def test_fee_budget_rejects_high_fee_notional_before_order(self) -> None:
        with (
            patch("app.risk_execution.extract_account_equity", return_value=1000.0),
            patch(
                "app.risk_execution.validate_trade",
                return_value={
                    "allowed": True,
                    "risk_amount": 20.0,
                    "leverage_cap": 20.0,
                    "exposure_cap": 0.5,
                    "min_risk_reward": 1.5,
                },
            ),
            patch("app.risk_execution.get_active_trades", return_value=[]),
            patch(
                "app.risk_execution.calculate_position_size",
                return_value={
                    "allowed": True,
                    "estimated_round_trip_fees": 3.0,
                    "target_risk_amount": 20.0,
                    "notional": 2800.0,
                    "selected_leverage": 20.0,
                },
            ),
        ):
            outcome = risk_execution._fee_budget_preflight(FakeClient(), SIGNAL)

        self.assertFalse(outcome["allowed"])
        self.assertEqual(outcome["error"], "FEE_BUDGET_EXCEEDED")
        self.assertAlmostEqual(outcome["fee_to_risk_ratio"], 0.15)

    def test_native_tp_failure_keeps_verified_position_active(self) -> None:
        result = {
            "ok": True,
            "trade": dict(TRADE),
            "sizing": {},
            "pre_order_risk": {},
            "actual_fill": {},
        }
        with (
            patch("app.execution._with_profile_runner_target", side_effect=lambda value: dict(value)),
            patch("app.risk_execution._fee_budget_preflight", return_value={"allowed": True}),
            patch("app.execution._execution_spread_gate", return_value={"allowed": True}),
            patch("app.risk_execution._execute_signal_authoritatively", return_value=result),
            patch("app.execution._validate_actual_fill_costs", return_value={"allowed": True}),
            patch("app.execution._apply_management_profile", return_value={"ok": True, "trade": dict(TRADE)}),
            patch(
                "app.execution.install_native_profit_orders",
                return_value={"ok": False, "error": "partial TP below minimum notional"},
            ),
            patch("app.execution.cancel_native_profit_orders") as cancel_orders,
            patch("app.execution.update_trade_entry", return_value=dict(TRADE)),
            patch("app.execution.update_active_trade") as update_active,
            patch("app.execution.append_trade_event"),
            patch("app.execution._emergency_close_pending_sync") as emergency_close,
        ):
            outcome = risk_execution.execute_signal(FakeClient(), SIGNAL, True)

        self.assertTrue(outcome["ok"], outcome)
        self.assertTrue(outcome["degraded"])
        self.assertEqual(outcome["trade"]["status"], "active")
        self.assertEqual(
            outcome["trade"]["management"]["fallback_mode"],
            "verified_full_position_sl_tp",
        )
        cancel_orders.assert_called_once()
        emergency_close.assert_not_called()
        update_active.assert_called_once()

    def test_native_tp_persist_failure_cancels_partial_orders_without_closing_position(self) -> None:
        result = {
            "ok": True,
            "trade": dict(TRADE),
            "sizing": {},
            "pre_order_risk": {},
            "actual_fill": {},
        }
        management = {
            **TRADE["management"],
            "native_tp_enabled": True,
            "native_orders": {"tp1": {}, "tp2": {}},
        }
        with (
            patch("app.execution._with_profile_runner_target", side_effect=lambda value: dict(value)),
            patch("app.risk_execution._fee_budget_preflight", return_value={"allowed": True}),
            patch("app.execution._execution_spread_gate", return_value={"allowed": True}),
            patch("app.risk_execution._execute_signal_authoritatively", return_value=result),
            patch("app.execution._validate_actual_fill_costs", return_value={"allowed": True}),
            patch("app.execution._apply_management_profile", return_value={"ok": True, "trade": dict(TRADE)}),
            patch(
                "app.execution.install_native_profit_orders",
                return_value={
                    "ok": True,
                    "management": management,
                    "orders": {"tp1": {"order_id": "1"}, "tp2": {"order_id": "2"}},
                },
            ),
            patch("app.execution.update_trade_entry", return_value=None),
            patch("app.execution.cancel_native_profit_orders") as cancel_orders,
            patch("app.execution.update_active_trade"),
            patch("app.execution.append_trade_event"),
            patch("app.execution._emergency_close_pending_sync") as emergency_close,
        ):
            outcome = risk_execution.execute_signal(FakeClient(), SIGNAL, True)

        self.assertTrue(outcome["ok"], outcome)
        self.assertTrue(outcome["degraded"])
        self.assertEqual(outcome["trade"]["status"], "active")
        cancel_orders.assert_called_once()
        emergency_close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
