from __future__ import annotations

import unittest
from unittest.mock import patch

import app.execution_core as execution_core
from app.execution_service import execute_signal


SIGNAL = {
    "symbol": "BTCUSDT",
    "strategy_name": "breakout",
    "trade_type": "scalping",
    "direction": "long",
    "entry": 100.0,
    "stop_loss": 98.0,
    "take_profit": 103.0,
    "risk_reward": 1.5,
    "detected_at": "2026-07-12T00:00:00+00:00",
    "status": "active",
}

VALIDATION = {
    "allowed": True,
    "trade_type": "scalping",
    "risk_amount": 20.0,
    "risk_per_trade": 0.02,
    "leverage_cap": 20.0,
    "exposure_cap": 0.50,
    "min_risk_reward": 1.5,
    "authoritative_risk_reward": 1.5,
    "max_active_trades": 5,
}

SIZING = {
    "allowed": True,
    "quantity": "10",
    "quantity_value": 10.0,
    "selected_leverage": 4.0,
    "leverage": 4.0,
    "risk_amount": 20.0,
    "target_risk_amount": 20.0,
    "required_margin": 250.0,
}


class FakeExecutionClient:
    def __init__(self, *, fill_price: float = 100.0, fill_available: bool = True) -> None:
        self.fill_price = fill_price
        self.fill_available = fill_available
        self.leverage_calls = 0
        self.order_calls = 0
        self.protection_calls = 0
        self.close_calls = 0
        self.stop_loss = "0"
        self.take_profit = "0"

    def safe_fetch_wallet_balance(self):
        return True, {"totalEquity": "1000", "totalAvailableBalance": "1000"}, None

    def safe_fetch_symbol_info(self, symbol: str):
        return True, [{
            "symbol": symbol,
            "tickSize": "0.01",
            "qtyStep": "0.001",
            "minOrderQty": "0.001",
            "minNotionalValue": "5",
        }], None

    def safe_fetch_positions(self):
        if not self.fill_available:
            return True, [], None
        return True, [{
            "symbol": "BTCUSDT",
            "side": "Buy",
            "size": "10",
            "avgPrice": str(self.fill_price),
            "stopLoss": self.stop_loss,
            "takeProfit": self.take_profit,
        }], None

    def safe_fetch_ticker(self, symbol: str):
        return True, {"symbol": symbol, "ask1Price": "100", "markPrice": "100", "lastPrice": "100"}, None

    def normalize_quantity(self, value: float, qty_step: str):
        return str(value)

    def normalize_price(self, value: float, tick_size: str):
        return f"{value:.2f}"

    def safe_set_leverage(self, symbol: str, leverage: float):
        self.leverage_calls += 1
        return True, {"symbol": symbol, "leverage": leverage}, None

    def place_market_order(self, symbol: str, side: str, qty: str, order_link_id: str | None = None):
        self.order_calls += 1
        return {"orderId": "order-1", "orderLinkId": order_link_id}

    def safe_fetch_order_by_link_id(self, symbol: str, order_link_id: str):
        if not self.fill_available:
            return True, {"orderId": "order-1", "orderStatus": "New", "avgPrice": "", "cumExecQty": "0"}, None
        return True, {
            "orderId": "order-1",
            "orderLinkId": order_link_id,
            "orderStatus": "Filled",
            "avgPrice": str(self.fill_price),
            "cumExecQty": "10",
            "updatedTime": "1783828800000",
        }, None

    def set_trading_stop(self, symbol: str, take_profit: str, stop_loss: str):
        self.protection_calls += 1
        self.take_profit = take_profit
        self.stop_loss = stop_loss
        return {"ok": True}

    def close_position_market(self, symbol: str, side: str, qty: str):
        self.close_calls += 1
        return {"orderId": "close-1"}


class ExecutionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        execution_core.replace_active_trades([])
        with execution_core._execution_lock:
            execution_core._closed_trades.clear()

    def _common_patches(self, *, validation=VALIDATION, sizing=SIZING):
        return (
            patch("app.execution_service.can_execute", return_value=(True, "")),
            patch("app.execution_service.get_execution_mode", return_value="demo"),
            patch("app.execution_service.refresh_risk_state"),
            patch("app.execution_service.validate_trade", return_value=validation),
            patch("app.execution_service.calculate_position_size", return_value=sizing),
            patch("app.execution_service.reserve_execution_capacity", return_value={
                "reserved": True,
                "reason": "",
                "trade": {"journal_id": "exec-authoritative", "status": "pending_execution"},
            }),
            patch("app.execution_service._safe_update_trade_entry", return_value=({"journal_id": "exec-authoritative"}, None)),
            patch("app.execution_service._safe_append_trade_event"),
            patch("app.execution_service._safe_log_bot_event"),
            patch("app.execution_service.register_active_trade"),
            patch("app.execution_service.release_active_trade"),
            patch("app.execution_service.get_active_trades", return_value=[]),
        )

    def test_single_authoritative_path_sizes_once_confirms_fill_and_verifies_protection(self) -> None:
        client = FakeExecutionClient(fill_price=100.0)
        patches = self._common_patches()
        with patches[0], patches[1], patches[2], patches[3] as validate_mock, patches[4] as sizing_mock, patches[5] as reserve_mock, patches[6], patches[7], patches[8], patches[9], patches[10], patches[11]:
            result = execute_signal(client, SIGNAL)

        self.assertTrue(result["ok"])
        self.assertEqual(validate_mock.call_count, 1)
        self.assertEqual(sizing_mock.call_count, 1)
        self.assertEqual(reserve_mock.call_count, 1)
        self.assertEqual(client.leverage_calls, 1)
        self.assertEqual(client.order_calls, 1)
        self.assertEqual(client.protection_calls, 1)
        self.assertEqual(result["trade"]["entry"], 100.0)
        self.assertEqual(result["trade"]["status"], "active")
        self.assertTrue(result["trade"]["exchange_metadata"]["protection_verified"])
        self.assertEqual(result["actual_fill"]["source"], "bybit_order")

    def test_pre_order_quote_replaces_stale_signal_entry_before_validation(self) -> None:
        client = FakeExecutionClient(fill_price=100.0)
        captured: dict = {}

        def capture_validation(signal, account_equity=None):
            captured.update(signal)
            return VALIDATION

        patches = self._common_patches()
        with patches[0], patches[1], patches[2], patch("app.execution_service.validate_trade", side_effect=capture_validation), patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11]:
            result = execute_signal(client, {**SIGNAL, "entry": 99.5})

        self.assertTrue(result["ok"])
        self.assertEqual(captured["entry"], 100.0)
        self.assertEqual(result["pre_order_quote"]["source"], "ask1Price")

    def test_actual_fill_risk_violation_is_emergency_closed_and_kept_pending_sync(self) -> None:
        client = FakeExecutionClient(fill_price=100.5)
        patches = self._common_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11]:
            result = execute_signal(client, SIGNAL)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "ACTUAL_FILL_RISK_VIOLATION")
        self.assertEqual(client.close_calls, 1)
        self.assertEqual(result["trade"]["status"], "close_pending_sync")
        self.assertEqual(client.protection_calls, 0)

    def test_unconfirmed_fill_never_claims_active_or_attaches_protection(self) -> None:
        client = FakeExecutionClient(fill_available=False)
        patches = self._common_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], patch("app.execution_service.time.sleep"):
            result = execute_signal(client, SIGNAL)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "FILL_CONFIRMATION_UNAVAILABLE")
        self.assertEqual(result["trade"]["status"], "fill_confirmation_pending")
        self.assertEqual(client.protection_calls, 0)


if __name__ == "__main__":
    unittest.main()
