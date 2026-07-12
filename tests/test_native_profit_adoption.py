from __future__ import annotations

import unittest
from unittest.mock import patch

from app.native_profit_reconcile import reconcile_native_profit_orders


class AdoptionClient:
    def __init__(self) -> None:
        self.orders: dict[str, dict] = {}
        self.position = {
            "symbol": "SOLUSDT",
            "side": "Sell",
            "size": "47.9",
            "avgPrice": "76.5",
            "markPrice": "75.75",
            "stopLoss": "76.91",
            "takeProfit": "75.27",
        }

    def safe_fetch_positions(self):
        return True, [dict(self.position)], None

    def safe_fetch_symbol_info(self, symbol: str):
        return True, [{
            "symbol": symbol,
            "qtyStep": "0.1",
            "tickSize": "0.01",
            "minNotionalValue": "5",
        }], None

    def normalize_quantity(self, value: float, qty_step: str):
        step = float(qty_step)
        normalized = int(value / step) * step
        return f"{normalized:.8f}".rstrip("0").rstrip(".")

    def normalize_price(self, value: float, tick_size: str):
        step = float(tick_size)
        normalized = int(value / step) * step
        return f"{normalized:.8f}".rstrip("0").rstrip(".")

    def place_reduce_only_limit_order(self, symbol: str, side: str, qty: str, price: str, order_link_id: str):
        order = {
            "orderId": f"order-{len(self.orders) + 1}",
            "orderLinkId": order_link_id,
            "orderStatus": "New",
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "cumExecQty": "0",
            "leavesQty": qty,
            "price": price,
        }
        self.orders[order_link_id] = order
        return order

    def safe_fetch_order_by_link_id(self, symbol: str, order_link_id: str):
        return True, self.orders.get(order_link_id), None


class NativeProfitAdoptionTests(unittest.TestCase):
    def test_existing_full_size_trade_is_adopted_after_restart(self) -> None:
        client = AdoptionClient()
        trade = {
            "journal_id": "legacy-sol-trade",
            "symbol": "SOLUSDT",
            "direction": "short",
            "entry": 76.5,
            "stop_loss": 76.91,
            "take_profit": 75.27,
            "quantity": 47.9,
            "status": "active",
            "management": {
                "initial_quantity": 47.9,
                "remaining_quantity": 47.9,
                "tp1": 75.68,
                "tp2": 75.475,
                "runner_target": 75.27,
                "tp1_done": False,
                "tp2_done": False,
                "break_even_set": False,
                "trailing_stop": None,
            },
            "exchange_metadata": {
                "management": {
                    "initial_quantity": 47.9,
                    "remaining_quantity": 47.9,
                    "tp1": 75.68,
                    "tp2": 75.475,
                    "runner_target": 75.27,
                    "tp1_done": False,
                    "tp2_done": False,
                    "break_even_set": False,
                    "trailing_stop": None,
                }
            },
        }
        saved: dict = {}

        with (
            patch("app.native_profit_reconcile.get_active_trades", return_value=[trade]),
            patch("app.native_profit_orders.update_active_trade", side_effect=lambda journal_id, updates: saved.update(updates)),
            patch("app.native_profit_orders.update_trade_entry", return_value={"journal_id": trade["journal_id"]}),
            patch("app.native_profit_orders.append_trade_event"),
        ):
            result = reconcile_native_profit_orders(client)

        self.assertTrue(result["ok"])
        self.assertTrue(any(item["action"] == "NATIVE_TP_ORDERS_ADOPTED" for item in result["actions"]))
        self.assertEqual(len(client.orders), 2)
        self.assertTrue(saved["management"]["native_tp_enabled"])
        self.assertEqual(saved["management"]["tp1_quantity"], 23.9)
        self.assertEqual(saved["management"]["tp2_quantity"], 11.9)
        self.assertTrue(all(order["side"] == "Buy" for order in client.orders.values()))

    def test_partially_reduced_legacy_trade_is_not_adopted_with_stale_full_size_plan(self) -> None:
        client = AdoptionClient()
        client.position["size"] = "20"
        trade = {
            "journal_id": "legacy-partial",
            "symbol": "SOLUSDT",
            "direction": "short",
            "entry": 76.5,
            "stop_loss": 76.91,
            "take_profit": 75.27,
            "quantity": 20.0,
            "status": "active",
            "management": {
                "initial_quantity": 47.9,
                "remaining_quantity": 20.0,
                "tp1": 75.68,
                "tp2": 75.475,
                "runner_target": 75.27,
                "tp1_done": False,
                "tp2_done": False,
            },
            "exchange_metadata": {},
        }

        with patch("app.native_profit_reconcile.get_active_trades", return_value=[trade]):
            result = reconcile_native_profit_orders(client)

        self.assertTrue(result["ok"])
        self.assertEqual(result["managed"], 0)
        self.assertEqual(client.orders, {})


if __name__ == "__main__":
    unittest.main()
