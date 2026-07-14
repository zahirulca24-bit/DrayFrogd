import unittest
from datetime import UTC, datetime, timedelta

from app.trade_management_rules import evaluate_management_action


class TradeManagementRulesTests(unittest.TestCase):
    def base_trade(self, trade_type: str = "intraday") -> dict:
        now = datetime.now(UTC)
        scalping = trade_type == "scalping"
        return {
            "trade_type": trade_type,
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 95.0,
            "opened_at": now.isoformat(),
            "management": {
                "profile_name": "scalping_v2" if scalping else "intraday_v1",
                "trade_type": trade_type,
                "tp1": 107.5 if scalping else 110.0,
                "tp2": 110.0 if scalping else 112.5,
                "runner_target": 112.5 if scalping else 115.0,
                "break_even_trigger_r": 1.0 if scalping else 2.0,
                "max_hold_seconds": 30 * 60 if scalping else 6 * 60 * 60,
                "trailing_enabled": not scalping,
                "tp1_done": False,
                "tp2_done": False,
                "break_even_set": False,
                "trailing_stop": None,
                "profit_lock_stop": None,
            },
        }

    def test_scalping_moves_to_break_even_at_one_r_before_tp1(self) -> None:
        trade = self.base_trade("scalping")
        action = evaluate_management_action(trade, 105.0, datetime.now(UTC))
        self.assertEqual(action["action"], "retry_break_even")

    def test_scalping_native_orders_own_tp_after_break_even(self) -> None:
        trade = self.base_trade("scalping")
        trade["management"].update(
            {
                "break_even_set": True,
                "native_tp_enabled": True,
                "native_tp_degraded": False,
                "tp1_order_link_id": "df-t1-key",
                "tp2_order_link_id": "df-t2-key",
            }
        )
        action = evaluate_management_action(trade, 111.0, datetime.now(UTC))
        self.assertEqual(action["action"], "hold")

    def test_scalping_degraded_tp1_uses_one_point_five_r(self) -> None:
        trade = self.base_trade("scalping")
        trade["management"].update(
            {
                "break_even_set": True,
                "native_tp_enabled": True,
                "native_tp_degraded": True,
            }
        )
        action = evaluate_management_action(trade, 107.5, datetime.now(UTC))
        self.assertEqual(action["action"], "tp1")

    def test_scalping_tp2_requires_tp1_price_profit_lock_not_trailing(self) -> None:
        trade = self.base_trade("scalping")
        trade["management"].update(
            {
                "tp1_done": True,
                "tp2_done": True,
                "break_even_set": True,
                "profit_lock_stop": None,
            }
        )
        action = evaluate_management_action(trade, 111.0, datetime.now(UTC))
        self.assertEqual(action["action"], "retry_profit_lock")

        trade["management"]["profit_lock_stop"] = 107.5
        action = evaluate_management_action(trade, 111.0, datetime.now(UTC))
        self.assertEqual(action["action"], "hold")

    def test_scalping_max_hold_is_thirty_minutes(self) -> None:
        trade = self.base_trade("scalping")
        trade["opened_at"] = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
        action = evaluate_management_action(trade, 106.0, datetime.now(UTC))
        self.assertEqual(action["action"], "max_hold_close")

    def test_intraday_tp1_action_when_first_target_hit(self) -> None:
        trade = self.base_trade("intraday")
        action = evaluate_management_action(trade, 110.1, datetime.now(UTC))
        self.assertEqual(action["action"], "tp1")

    def test_intraday_gap_through_tp2_still_executes_tp1_first(self) -> None:
        trade = self.base_trade("intraday")
        action = evaluate_management_action(trade, 113.0, datetime.now(UTC))
        self.assertEqual(action["action"], "tp1")

    def test_intraday_break_even_retry_blocks_tp2(self) -> None:
        trade = self.base_trade("intraday")
        trade["management"]["tp1_done"] = True
        action = evaluate_management_action(trade, 113.0, datetime.now(UTC))
        self.assertEqual(action["action"], "retry_break_even")

    def test_intraday_tp2_action_after_tp1_and_break_even(self) -> None:
        trade = self.base_trade("intraday")
        trade["management"]["tp1_done"] = True
        trade["management"]["break_even_set"] = True
        action = evaluate_management_action(trade, 113.0, datetime.now(UTC))
        self.assertEqual(action["action"], "tp2")

    def test_intraday_trailing_setup_retry_after_tp2(self) -> None:
        trade = self.base_trade("intraday")
        trade["management"]["tp1_done"] = True
        trade["management"]["break_even_set"] = True
        trade["management"]["tp2_done"] = True
        action = evaluate_management_action(trade, 114.0, datetime.now(UTC))
        self.assertEqual(action["action"], "retry_trailing")

    def test_intraday_trailing_action_after_stop_confirmed(self) -> None:
        trade = self.base_trade("intraday")
        trade["management"]["tp1_done"] = True
        trade["management"]["break_even_set"] = True
        trade["management"]["tp2_done"] = True
        trade["management"]["trailing_stop"] = 108.0
        action = evaluate_management_action(trade, 114.0, datetime.now(UTC))
        self.assertEqual(action["action"], "trail")

    def test_intraday_max_hold_is_six_hours(self) -> None:
        trade = self.base_trade("intraday")
        trade["opened_at"] = (datetime.now(UTC) - timedelta(hours=6)).isoformat()
        action = evaluate_management_action(trade, 120.0, datetime.now(UTC))
        self.assertEqual(action["action"], "max_hold_close")

    def test_intraday_before_six_hours_can_continue(self) -> None:
        trade = self.base_trade("intraday")
        trade["opened_at"] = (datetime.now(UTC) - timedelta(hours=5, minutes=59)).isoformat()
        trade["management"].update(
            {
                "tp1_done": True,
                "tp2_done": True,
                "break_even_set": True,
                "trailing_stop": 110.0,
            }
        )
        action = evaluate_management_action(trade, 114.0, datetime.now(UTC))
        self.assertEqual(action["action"], "trail")


if __name__ == "__main__":
    unittest.main()
