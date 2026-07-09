import unittest
from datetime import UTC, datetime, timedelta

from app.trade_management_rules import evaluate_management_action


class TradeManagementRulesTests(unittest.TestCase):
    def base_trade(self) -> dict:
        now = datetime.now(UTC)
        return {
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 95.0,
            "opened_at": now.isoformat(),
            "management": {
                "tp1": 110.0,
                "tp2": 112.5,
                "tp1_done": False,
                "tp2_done": False,
                "break_even_set": False,
                "trailing_stop": None,
            },
        }

    def test_tp1_action_when_first_target_hit(self) -> None:
        trade = self.base_trade()
        action = evaluate_management_action(trade, 110.1, datetime.now(UTC))
        self.assertEqual(action["action"], "tp1")

    def test_gap_through_tp2_still_executes_tp1_first(self) -> None:
        trade = self.base_trade()
        action = evaluate_management_action(trade, 113.0, datetime.now(UTC))
        self.assertEqual(action["action"], "tp1")

    def test_break_even_retry_blocks_tp2(self) -> None:
        trade = self.base_trade()
        trade["management"]["tp1_done"] = True
        action = evaluate_management_action(trade, 113.0, datetime.now(UTC))
        self.assertEqual(action["action"], "retry_break_even")

    def test_tp2_action_after_tp1_and_break_even_confirmed(self) -> None:
        trade = self.base_trade()
        trade["management"]["tp1_done"] = True
        trade["management"]["break_even_set"] = True
        action = evaluate_management_action(trade, 113.0, datetime.now(UTC))
        self.assertEqual(action["action"], "tp2")

    def test_trailing_setup_retry_after_tp2(self) -> None:
        trade = self.base_trade()
        trade["management"]["tp1_done"] = True
        trade["management"]["break_even_set"] = True
        trade["management"]["tp2_done"] = True
        action = evaluate_management_action(trade, 114.0, datetime.now(UTC))
        self.assertEqual(action["action"], "retry_trailing")

    def test_trailing_action_after_trailing_stop_confirmed(self) -> None:
        trade = self.base_trade()
        trade["management"]["tp1_done"] = True
        trade["management"]["break_even_set"] = True
        trade["management"]["tp2_done"] = True
        trade["management"]["trailing_stop"] = 108.0
        action = evaluate_management_action(trade, 114.0, datetime.now(UTC))
        self.assertEqual(action["action"], "trail")

    def test_stagnant_action_after_one_hour_without_progress(self) -> None:
        trade = self.base_trade()
        trade["opened_at"] = (datetime.now(UTC) - timedelta(minutes=70)).isoformat()
        action = evaluate_management_action(trade, 100.5, datetime.now(UTC))
        self.assertEqual(action["action"], "stagnant_close")

    def test_max_hold_action_after_four_hours(self) -> None:
        trade = self.base_trade()
        trade["opened_at"] = (datetime.now(UTC) - timedelta(hours=4, minutes=1)).isoformat()
        action = evaluate_management_action(trade, 120.0, datetime.now(UTC))
        self.assertEqual(action["action"], "max_hold_close")


if __name__ == "__main__":
    unittest.main()
