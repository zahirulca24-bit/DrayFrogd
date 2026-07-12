from __future__ import annotations

import unittest
from unittest.mock import patch

from app.native_profit_orders import install_native_profit_orders
from app.native_profit_reconcile import reconcile_native_profit_orders


class FakeNativeClient:
    def __init__(self) -> None:
        self.placed: list[dict] = []
        self.cancelled: list[dict] = []
        self.orders: dict[str, dict] = {}
        self.position = {
            "symbol": "BTCUSDT",
            "side": "Buy",
            "size": "10",
            "avgPrice": "100",
            "markPrice": "100",
            "stopLoss": "98",
            "takeProfit": "106",
        }

    def safe_fetch_symbol_info(self, symbol: str):
        return True, [{
            "symbol": symbol,
            "qtyStep": "0.1",
            "tickSize": "0.1",
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
            "orderId": f"order-{len(self.placed) + 1}",
            "orderLinkId": order_link_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "reduceOnly": True,
        }
        self.placed.append(order)
        self.orders[order_link_id] = {
            **order,
            "orderStatus": "New",
            "cumExecQty": "0",
            "leavesQty": qty,
        }
        return order

    def cancel_order(self, symbol: str, order_id=None, order_link_id=None):
        self.cancelled.append({"symbol": symbol, "order_id": order_id, "order_link_id": order_link_id})
        return {"ok": True}

    def safe_fetch_order_by_link_id(self, symbol: str, order_link_id: str):
        return True, self.orders.get(order_link_id), None

    def safe_fetch_positions(self):
        return True, [dict(self.position)], None

    def set_trading_stop(self, symbol: str, take_profit: str, stop_loss: str):
        self.position["takeProfit"] = take_profit
        self.position["stopLoss"] = stop_loss
        return {"ok": True}


class NativeProfitOrderTests(unittest.TestCase):
    def base_trade(self) -> dict:
        return {
            "journal_id": "exec-native-1",
            "execution_key": "a" * 64,
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 98.0,
            "take_profit": 106.0,
            "quantity": 10.0,
            "management": {
                "initial_quantity": 10.0,
                "remaining_quantity": 10.0,
                "tp1": 104.0,
                "tp2": 105.0,
                "runner_target": 106.0,
                "tp1_done": False,
                "tp2_done": False,
                "break_even_set": False,
                "trailing_stop": None,
            },
            "exchange_metadata": {},
        }

    def install(self, client: FakeNativeClient, trade: dict) -> dict:
        result = install_native_profit_orders(client, trade)
        self.assertTrue(result["ok"])
        return {
            **trade,
            "management": result["management"],
            "exchange_metadata": {
                **trade.get("exchange_metadata", {}),
                "management": result["management"],
                "native_profit_orders": result["orders"],
            },
        }

    def test_installs_reduce_only_tp1_and_tp2_orders_with_deterministic_links(self) -> None:
        client = FakeNativeClient()
        result = install_native_profit_orders(client, self.base_trade())

        self.assertTrue(result["ok"])
        self.assertEqual(len(client.placed), 2)
        self.assertEqual(client.placed[0]["side"], "Sell")
        self.assertEqual(client.placed[0]["qty"], "5")
        self.assertEqual(client.placed[0]["price"], "104")
        self.assertEqual(client.placed[1]["qty"], "2.5")
        self.assertEqual(client.placed[1]["price"], "105")
        self.assertTrue(all(order["reduceOnly"] for order in client.placed))
        self.assertLessEqual(len(result["management"]["tp1_order_link_id"]), 36)
        self.assertLessEqual(len(result["management"]["tp2_order_link_id"]), 36)
        self.assertTrue(result["management"]["native_tp_enabled"])

    def test_tp1_exchange_fill_books_profit_and_moves_remaining_stop_to_break_even(self) -> None:
        client = FakeNativeClient()
        trade = self.install(client, self.base_trade())
        management = trade["management"]
        client.orders[management["tp1_order_link_id"]]["orderStatus"] = "Filled"
        client.orders[management["tp1_order_link_id"]]["cumExecQty"] = "5"
        client.orders[management["tp1_order_link_id"]]["leavesQty"] = "0"
        client.position["size"] = "5"
        client.position["markPrice"] = "104.2"

        saved: dict = {}
        with (
            patch("app.native_profit_reconcile.get_active_trades", return_value=[trade]),
            patch("app.native_profit_orders.update_active_trade", side_effect=lambda journal_id, updates: saved.update(updates)),
            patch("app.native_profit_orders.update_trade_entry", return_value={"journal_id": trade["journal_id"]}),
            patch("app.native_profit_orders.append_trade_event"),
        ):
            result = reconcile_native_profit_orders(client)

        self.assertTrue(result["ok"])
        self.assertEqual(result["actions"][0]["action"], "NATIVE_TP1_FILLED_BREAK_EVEN_SET")
        self.assertTrue(saved["management"]["tp1_done"])
        self.assertTrue(saved["management"]["break_even_set"])
        self.assertFalse(saved["management"]["tp2_done"])
        self.assertEqual(saved["remaining_quantity"], 5.0)
        self.assertEqual(float(client.position["stopLoss"]), 100.0)

    def test_gap_fill_of_both_native_orders_activates_runner_trailing_stop(self) -> None:
        client = FakeNativeClient()
        trade = self.install(client, self.base_trade())
        management = trade["management"]
        for prefix in ("tp1", "tp2"):
            order = client.orders[management[f"{prefix}_order_link_id"]]
            order["orderStatus"] = "Filled"
            order["cumExecQty"] = order["qty"]
            order["leavesQty"] = "0"
        client.position["size"] = "2.5"
        client.position["markPrice"] = "105.0"

        saved: dict = {}
        with (
            patch("app.native_profit_reconcile.get_active_trades", return_value=[trade]),
            patch("app.native_profit_orders.update_active_trade", side_effect=lambda journal_id, updates: saved.update(updates)),
            patch("app.native_profit_orders.update_trade_entry", return_value={"journal_id": trade["journal_id"]}),
            patch("app.native_profit_orders.append_trade_event"),
        ):
            result = reconcile_native_profit_orders(client)

        self.assertTrue(result["ok"])
        self.assertTrue(saved["management"]["tp1_done"])
        self.assertTrue(saved["management"]["tp2_done"])
        self.assertTrue(saved["management"]["break_even_set"])
        self.assertEqual(saved["management"]["trailing_stop"], 103.0)
        self.assertEqual(saved["remaining_quantity"], 2.5)
        self.assertEqual(float(client.position["stopLoss"]), 103.0)

    def test_cancelled_native_order_enables_legacy_mark_price_fallback(self) -> None:
        client = FakeNativeClient()
        trade = self.install(client, self.base_trade())
        management = trade["management"]
        client.orders[management["tp1_order_link_id"]]["orderStatus"] = "Cancelled"

        saved: dict = {}
        with (
            patch("app.native_profit_reconcile.get_active_trades", return_value=[trade]),
            patch("app.native_profit_orders.update_active_trade", side_effect=lambda journal_id, updates: saved.update(updates)),
            patch("app.native_profit_orders.update_trade_entry", return_value={"journal_id": trade["journal_id"]}),
            patch("app.native_profit_orders.append_trade_event"),
        ):
            reconcile_native_profit_orders(client)

        self.assertTrue(saved["management"]["native_tp_degraded"])
        self.assertIn("TP1", saved["management"]["native_tp_degraded_reason"])

    def test_unchanged_order_snapshots_do_not_rewrite_trade_state(self) -> None:
        client = FakeNativeClient()
        trade = self.install(client, self.base_trade())
        management = trade["management"]
        management["tp1_order_status"] = "New"
        management["tp2_order_status"] = "New"
        management["tp1_order_snapshot"] = {
            key: client.orders[management["tp1_order_link_id"]].get(key)
            for key in ("orderId", "orderLinkId", "orderStatus", "qty", "cumExecQty", "leavesQty", "price")
        }
        management["tp2_order_snapshot"] = {
            key: client.orders[management["tp2_order_link_id"]].get(key)
            for key in ("orderId", "orderLinkId", "orderStatus", "qty", "cumExecQty", "leavesQty", "price")
        }
        trade["management"] = management
        trade["exchange_metadata"]["management"] = management

        with (
            patch("app.native_profit_reconcile.get_active_trades", return_value=[trade]),
            patch("app.native_profit_orders.update_active_trade") as update_active,
            patch("app.native_profit_orders.update_trade_entry") as update_journal,
        ):
            result = reconcile_native_profit_orders(client)

        self.assertTrue(result["ok"])
        update_active.assert_not_called()
        update_journal.assert_not_called()


if __name__ == "__main__":
    unittest.main()
