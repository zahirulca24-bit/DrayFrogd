from __future__ import annotations

import unittest
from unittest.mock import patch

from app.native_profit_reconcile import reconcile_native_profit_orders


class FakeProfiledNativeClient:
    def __init__(self) -> None:
        self.position = {
            "symbol": "BTCUSDT",
            "side": "Buy",
            "size": "10",
            "avgPrice": "100",
            "markPrice": "102",
            "stopLoss": "98",
            "takeProfit": "105",
        }
        self.orders = {
            "df-t1": {
                "orderId": "order-1",
                "orderLinkId": "df-t1",
                "orderStatus": "New",
                "qty": "5",
                "cumExecQty": "0",
                "leavesQty": "5",
                "price": "103",
            },
            "df-t2": {
                "orderId": "order-2",
                "orderLinkId": "df-t2",
                "orderStatus": "New",
                "qty": "2.5",
                "cumExecQty": "0",
                "leavesQty": "2.5",
                "price": "104",
            },
        }

    def safe_fetch_positions(self):
        return True, [dict(self.position)], None

    def safe_fetch_order_by_link_id(self, symbol: str, order_link_id: str):
        return True, dict(self.orders[order_link_id]), None

    def normalize_price(self, value: float, tick_size: str):
        return f"{float(value):.2f}"

    def set_trading_stop(self, symbol: str, take_profit: str, stop_loss: str):
        self.position["takeProfit"] = take_profit
        self.position["stopLoss"] = stop_loss
        return {"ok": True}


class ProfiledNativeProfitReconcileTests(unittest.TestCase):
    def scalping_trade(self) -> dict:
        management = {
            "profile_name": "scalping_v2",
            "trade_type": "scalping",
            "initial_quantity": 10.0,
            "remaining_quantity": 10.0,
            "tp1": 103.0,
            "tp2": 104.0,
            "runner_target": 105.0,
            "break_even_trigger_r": 1.0,
            "break_even_price": 100.1,
            "tp1_done": False,
            "tp2_done": False,
            "break_even_set": False,
            "trailing_enabled": False,
            "trailing_stop": None,
            "profit_lock_stop": None,
            "native_tp_enabled": True,
            "native_tp_degraded": False,
            "native_tp_qty_step": "0.1",
            "native_tp_tick_size": "0.01",
            "tp1_order_link_id": "df-t1",
            "tp2_order_link_id": "df-t2",
            "tp1_quantity": 5.0,
            "tp2_quantity": 2.5,
        }
        return {
            "journal_id": "profiled-native",
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 98.0,
            "take_profit": 105.0,
            "quantity": 10.0,
            "remaining_quantity": 10.0,
            "status": "active",
            "management": management,
            "exchange_metadata": {"trade_type": "scalping", "management": management},
        }

    def test_scalping_one_r_moves_stop_to_fee_safe_break_even(self) -> None:
        client = FakeProfiledNativeClient()
        trade = self.scalping_trade()
        saved: dict = {}

        with (
            patch("app.native_profit_reconcile.get_active_trades", return_value=[trade]),
            patch("app.native_profit_orders.update_active_trade", side_effect=lambda journal_id, updates: saved.update(updates)),
            patch("app.native_profit_orders.update_trade_entry", return_value={"journal_id": trade["journal_id"]}),
            patch("app.native_profit_orders.append_trade_event"),
        ):
            result = reconcile_native_profit_orders(client)

        self.assertTrue(result["ok"])
        self.assertTrue(any(item["action"] == "SCALPING_1R_BREAK_EVEN_SET" for item in result["actions"]))
        self.assertTrue(saved["management"]["break_even_set"])
        self.assertEqual(saved["management"]["break_even_stop"], 100.1)
        self.assertEqual(float(client.position["stopLoss"]), 100.1)

    def test_scalping_tp2_fill_locks_remaining_stop_at_tp1_without_trailing(self) -> None:
        client = FakeProfiledNativeClient()
        trade = self.scalping_trade()
        trade["management"]["break_even_set"] = True
        trade["management"]["break_even_stop"] = 100.1
        for order in client.orders.values():
            order["orderStatus"] = "Filled"
            order["cumExecQty"] = order["qty"]
            order["leavesQty"] = "0"
        client.position["size"] = "2.5"
        client.position["markPrice"] = "104"
        saved: dict = {}

        with (
            patch("app.native_profit_reconcile.get_active_trades", return_value=[trade]),
            patch("app.native_profit_orders.update_active_trade", side_effect=lambda journal_id, updates: saved.update(updates)),
            patch("app.native_profit_orders.update_trade_entry", return_value={"journal_id": trade["journal_id"]}),
            patch("app.native_profit_orders.append_trade_event"),
        ):
            result = reconcile_native_profit_orders(client)

        self.assertTrue(result["ok"])
        self.assertTrue(any(item["action"] == "SCALPING_TP2_PROFIT_LOCK_SET" for item in result["actions"]))
        self.assertTrue(saved["management"]["tp1_done"])
        self.assertTrue(saved["management"]["tp2_done"])
        self.assertEqual(saved["management"]["profit_lock_stop"], 103.0)
        self.assertIsNone(saved["management"]["trailing_stop"])
        self.assertEqual(float(client.position["stopLoss"]), 103.0)
        self.assertEqual(float(client.position["takeProfit"]), 105.0)
        self.assertEqual(saved["remaining_quantity"], 2.5)


if __name__ == "__main__":
    unittest.main()
