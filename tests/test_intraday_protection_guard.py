from __future__ import annotations

import unittest
from unittest.mock import patch

from app.intraday_protection_guard import enforce_intraday_protection


class FakeIntradayClient:
    def __init__(self, *, failures: int = 0) -> None:
        self.failures = failures
        self.set_calls: list[dict] = []
        self.position = {
            "symbol": "LABUSDT",
            "side": "Sell",
            "size": "5",
            "avgPrice": "100",
            "markPrice": "96",
            "stopLoss": "102",
            "takeProfit": "94",
        }

    def safe_fetch_positions(self):
        return True, [dict(self.position)], None

    def normalize_price(self, value: float, tick_size: str):
        step = float(tick_size)
        normalized = round(float(value) / step) * step
        return f"{normalized:.8f}".rstrip("0").rstrip(".")

    def set_trading_stop(self, symbol: str, take_profit: str, stop_loss: str):
        self.set_calls.append({"symbol": symbol, "take_profit": take_profit, "stop_loss": stop_loss})
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("temporary Bybit amendment failure")
        self.position["takeProfit"] = take_profit
        self.position["stopLoss"] = stop_loss
        return {"ok": True}


class IntradayProtectionGuardTests(unittest.TestCase):
    def base_trade(self) -> dict:
        management = {
            "profile_name": "intraday_v1",
            "trade_type": "intraday",
            "initial_quantity": 10.0,
            "remaining_quantity": 5.0,
            "tp1_quantity": 5.0,
            "tp2_quantity": 2.5,
            "tp1_fraction": 0.50,
            "tp2_fraction": 0.25,
            "tp1_done": True,
            "tp2_done": False,
            "break_even_price": 100.0,
            "break_even_set": False,
            "break_even_verified": False,
            "trailing_enabled": True,
            "trailing_stop": None,
            "runner_target": 94.0,
            "native_tp_tick_size": "0.1",
        }
        return {
            "journal_id": "jrnl-lab-1",
            "symbol": "LABUSDT",
            "direction": "short",
            "trade_type": "intraday",
            "entry": 100.0,
            "stop_loss": 102.0,
            "take_profit": 94.0,
            "quantity": 5.0,
            "remaining_quantity": 5.0,
            "status": "active",
            "management": management,
            "exchange_metadata": {"management": management, "trade_type": "intraday"},
        }

    def run_guard(self, client: FakeIntradayClient, trade: dict) -> tuple[dict, dict]:
        saved: dict = {}

        def persist(_trade: dict, management: dict, remaining_quantity: float) -> None:
            saved.update({"management": dict(management), "remaining_quantity": remaining_quantity})

        with (
            patch("app.intraday_protection_guard.get_active_trades", return_value=[trade]),
            patch("app.intraday_protection_guard._persist_management_state", side_effect=persist),
            patch("app.intraday_protection_guard._safe_event"),
        ):
            result = enforce_intraday_protection(client)
        return result, saved

    def test_tp1_break_even_failure_retries_after_tp1_done(self) -> None:
        client = FakeIntradayClient(failures=1)
        trade = self.base_trade()

        first, first_saved = self.run_guard(client, trade)
        self.assertFalse(first["ok"])
        self.assertFalse(first_saved["management"]["break_even_verified"])
        self.assertEqual(first_saved["management"]["break_even_retry_count"], 1)
        self.assertTrue(first_saved["management"]["tp1_done"])

        retried_trade = {
            **trade,
            "management": first_saved["management"],
            "exchange_metadata": {"management": first_saved["management"], "trade_type": "intraday"},
        }
        second, second_saved = self.run_guard(client, retried_trade)

        self.assertTrue(second["ok"])
        self.assertTrue(second_saved["management"]["break_even_set"])
        self.assertTrue(second_saved["management"]["break_even_verified"])
        self.assertEqual(float(client.position["stopLoss"]), 100.0)
        self.assertEqual(len(client.set_calls), 2)

    def test_tp2_trailing_failure_retries_after_tp2_done(self) -> None:
        client = FakeIntradayClient(failures=1)
        client.position.update({"size": "2.5", "markPrice": "94", "stopLoss": "102"})
        trade = self.base_trade()
        trade["management"].update({"remaining_quantity": 2.5, "tp2_done": True, "break_even_set": True})

        first, first_saved = self.run_guard(client, trade)
        self.assertFalse(first["ok"])
        self.assertFalse(first_saved["management"]["trailing_verified"])
        self.assertEqual(first_saved["management"]["trailing_retry_count"], 1)

        retried_trade = {
            **trade,
            "management": first_saved["management"],
            "exchange_metadata": {"management": first_saved["management"], "trade_type": "intraday"},
        }
        second, second_saved = self.run_guard(client, retried_trade)

        self.assertTrue(second["ok"])
        self.assertTrue(second_saved["management"]["trailing_verified"])
        self.assertEqual(second_saved["management"]["trailing_stop"], 96.0)
        self.assertEqual(float(client.position["stopLoss"]), 96.0)
        self.assertEqual(len(client.set_calls), 2)

    def test_tp2_quantity_inference_activates_trailing_after_restart(self) -> None:
        client = FakeIntradayClient()
        client.position.update({"size": "2.5", "markPrice": "94", "stopLoss": "102"})
        trade = self.base_trade()
        trade["management"].update({"tp1_done": False, "tp2_done": False, "remaining_quantity": 2.5})

        result, saved = self.run_guard(client, trade)

        self.assertTrue(result["ok"])
        self.assertTrue(saved["management"]["tp1_done"])
        self.assertTrue(saved["management"]["tp2_done"])
        self.assertTrue(saved["management"]["trailing_verified"])
        self.assertEqual(float(client.position["stopLoss"]), 96.0)

    def test_existing_better_trailing_stop_is_confirmed_without_amendment(self) -> None:
        client = FakeIntradayClient()
        client.position.update({"size": "2.5", "markPrice": "94", "stopLoss": "95"})
        trade = self.base_trade()
        trade["management"].update({"tp2_done": True, "remaining_quantity": 2.5})

        result, saved = self.run_guard(client, trade)

        self.assertTrue(result["ok"])
        self.assertTrue(saved["management"]["trailing_verified"])
        self.assertEqual(saved["management"]["trailing_stop"], 95.0)
        self.assertEqual(client.set_calls, [])

    def test_unknown_or_scalping_profile_is_not_managed(self) -> None:
        client = FakeIntradayClient()
        trade = self.base_trade()
        trade["trade_type"] = None
        trade["management"].update({"profile_name": "", "trade_type": None})
        trade["exchange_metadata"] = {"management": trade["management"]}

        result, saved = self.run_guard(client, trade)

        self.assertTrue(result["ok"])
        self.assertEqual(result["managed"], 0)
        self.assertEqual(saved, {})
        self.assertEqual(client.set_calls, [])


if __name__ == "__main__":
    unittest.main()
