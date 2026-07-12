from __future__ import annotations

import unittest
from unittest.mock import patch

from app.scalping_profit_lock_guard import enforce_scalping_tp2_profit_locks


class FakeProfitLockClient:
    def __init__(self, *, failures: int = 0, stop_loss: str = "98") -> None:
        self.failures = failures
        self.set_calls = 0
        self.position = {
            "symbol": "BTCUSDT",
            "side": "Buy",
            "size": "2.5",
            "avgPrice": "100",
            "markPrice": "104",
            "stopLoss": stop_loss,
            "takeProfit": "105",
        }

    def safe_fetch_positions(self):
        return True, [dict(self.position)], None

    def normalize_price(self, value: float, tick_size: str):
        return f"{float(value):.2f}"

    def set_trading_stop(self, symbol: str, take_profit: str, stop_loss: str):
        self.set_calls += 1
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("temporary stop amendment failure")
        self.position["takeProfit"] = take_profit
        self.position["stopLoss"] = stop_loss
        return {"ok": True}


class ScalpingProfitLockGuardTests(unittest.TestCase):
    def scalping_trade(self) -> dict:
        management = {
            "profile_name": "scalping_v2",
            "trade_type": "scalping",
            "initial_quantity": 10.0,
            "remaining_quantity": 2.5,
            "tp1": 103.0,
            "tp2": 104.0,
            "runner_target": 105.0,
            "tp1_done": True,
            "tp2_done": True,
            "native_tp_enabled": True,
            "native_tp_qty_step": "0.1",
            "native_tp_tick_size": "0.01",
            "tp1_quantity": 5.0,
            "tp2_quantity": 2.5,
            "trailing_enabled": False,
            "trailing_stop": None,
            "profit_lock_stop": None,
            "profit_lock_verified": False,
        }
        return {
            "journal_id": "profit-lock-trade",
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 98.0,
            "take_profit": 105.0,
            "quantity": 2.5,
            "remaining_quantity": 2.5,
            "status": "active",
            "management": management,
            "exchange_metadata": {"trade_type": "scalping", "management": management},
        }

    def _patch_persistence(self, trade: dict):
        def apply_active_update(journal_id: str, updates: dict):
            self.assertEqual(journal_id, trade["journal_id"])
            trade.update(updates)
            return trade

        return (
            patch("app.scalping_profit_lock_guard.get_active_trades", return_value=[trade]),
            patch("app.native_profit_orders.update_active_trade", side_effect=apply_active_update),
            patch("app.native_profit_orders.update_trade_entry", return_value={"journal_id": trade["journal_id"]}),
            patch("app.native_profit_orders.append_trade_event"),
        )

    def test_failed_profit_lock_is_retried_after_tp2_done_was_already_saved(self) -> None:
        client = FakeProfitLockClient(failures=1)
        trade = self.scalping_trade()
        patches = self._patch_persistence(trade)

        with patches[0], patches[1], patches[2], patches[3]:
            first = enforce_scalping_tp2_profit_locks(client)
            second = enforce_scalping_tp2_profit_locks(client)

        self.assertFalse(first["ok"])
        self.assertTrue(any(item["action"] == "SCALPING_TP2_PROFIT_LOCK_RETRY_PENDING" for item in first["actions"]))
        self.assertTrue(second["ok"])
        self.assertTrue(any(item["action"] == "SCALPING_TP2_PROFIT_LOCK_REPAIRED" for item in second["actions"]))
        self.assertEqual(client.set_calls, 2)
        self.assertEqual(float(client.position["stopLoss"]), 103.0)
        self.assertTrue(trade["management"]["tp2_done"])
        self.assertTrue(trade["management"]["profit_lock_verified"])
        self.assertEqual(trade["management"]["profit_lock_stop"], 103.0)
        self.assertEqual(trade["management"]["profit_lock_retry_count"], 2)
        self.assertIsNone(trade["management"]["trailing_stop"])

    def test_existing_tp1_price_stop_is_confirmed_without_exchange_amendment(self) -> None:
        client = FakeProfitLockClient(stop_loss="103")
        trade = self.scalping_trade()
        patches = self._patch_persistence(trade)

        with patches[0], patches[1], patches[2], patches[3]:
            result = enforce_scalping_tp2_profit_locks(client)

        self.assertTrue(result["ok"])
        self.assertEqual(client.set_calls, 0)
        self.assertTrue(any(item["action"] == "SCALPING_TP2_PROFIT_LOCK_CONFIRMED" for item in result["actions"]))
        self.assertTrue(trade["management"]["profit_lock_verified"])
        self.assertEqual(trade["management"]["profit_lock_stop"], 103.0)

    def test_position_size_inference_can_trigger_profit_lock_before_tp2_done_is_persisted(self) -> None:
        client = FakeProfitLockClient()
        trade = self.scalping_trade()
        trade["management"]["tp2_done"] = False
        patches = self._patch_persistence(trade)

        with patches[0], patches[1], patches[2], patches[3]:
            result = enforce_scalping_tp2_profit_locks(client)

        self.assertTrue(result["ok"])
        self.assertEqual(client.set_calls, 1)
        self.assertTrue(trade["management"]["tp2_done"])
        self.assertEqual(float(client.position["stopLoss"]), 103.0)

    def test_unknown_management_profile_is_not_silently_treated_as_scalping(self) -> None:
        client = FakeProfitLockClient()
        trade = self.scalping_trade()
        trade["management"]["profile_name"] = "unknown"

        with patch("app.scalping_profit_lock_guard.get_active_trades", return_value=[trade]):
            result = enforce_scalping_tp2_profit_locks(client)

        self.assertTrue(result["ok"])
        self.assertEqual(result["managed"], 0)
        self.assertEqual(client.set_calls, 0)
        self.assertEqual(float(client.position["stopLoss"]), 98.0)


if __name__ == "__main__":
    unittest.main()
