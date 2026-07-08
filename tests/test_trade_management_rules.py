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
                "tp1": 105.0,
                "tp2": 110.0,
                "tp1_done": False,
                "tp2_done": False,
            },
        }

    def test_tp1_action_when_first_target_hit(self) -> None:
        trade = self.base_trade()
        action = evaluate_management_action(trade, 105.1, datetime.now(UTC))
        self.assertEqual(action["action"], "tp1")

    def test_tp2_action_after_tp1_done(self) -> None:
        trade = self.base_trade()
        trade["management"]["tp1_done"] = True
        action = evaluate_management_action(trade, 110.1, datetime.now(UTC))
        self.assertEqual(action["action"], "tp2")

    def test_trailing_action_after_tp2_done(self) -> None:
        trade = self.base_trade()
        trade["management"]["tp1_done"] = True
        trade["management"]["tp2_done"] = True
        action = evaluate_management_action(trade, 112.0, datetime.now(UTC))
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
