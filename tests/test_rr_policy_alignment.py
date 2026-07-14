import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from app.risk import get_risk_state, validate_trade
from app.strategy import Candle, _build_ema_active_signal


SAFE_STATE = {
    "circuit_breaker_active": False,
    "circuit_breaker_reason": None,
    "day_start_equity": 1000.0,
    "symbol_cooldowns": {},
    "active_symbols": [],
    "active_trade_count": 0,
    "available_risk": 50.0,
    "live_risk": 0.0,
    "base_risk_pool": 50.0,
    "effective_risk_pool": 50.0,
    "min_risk_reward": 1.5,
}


class RiskRewardPolicyAlignmentTests(unittest.TestCase):
    def test_strategy_generated_one_point_five_r_signal_passes_risk_gate(self) -> None:
        timestamp = datetime(2026, 7, 12, 0, 0, tzinfo=UTC)
        candles = [
            Candle(timestamp=timestamp, open=100.0, high=101.0, low=99.8, close=100.4),
            Candle(timestamp=timestamp, open=100.4, high=101.2, low=100.0, close=100.8),
            Candle(timestamp=timestamp, open=100.8, high=101.8, low=100.7, close=101.6),
        ]

        signal = _build_ema_active_signal(
            "BTCUSDT",
            "long",
            candles,
            pullback_index=1,
            trigger_index=2,
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.risk_reward, 1.5)

        with patch("app.risk.refresh_risk_state", return_value=SAFE_STATE):
            validation = validate_trade({**signal.to_dict(), "trade_type": "scalping"}, account_equity=1000.0)

        self.assertTrue(validation["allowed"])
        self.assertEqual(validation["reason"], "")
        self.assertAlmostEqual(validation["authoritative_risk_reward"], 1.5, places=9)
        self.assertEqual(validation["trade_type"], "scalping")

    def test_signal_below_one_point_five_r_is_rejected(self) -> None:
        signal = {
            "symbol": "ETHUSDT",
            "strategy_name": "breakout",
            "trade_type": "scalping",
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 98.0,
            "take_profit": 102.98,
            "risk_reward": 1.49,
            "status": "active",
        }

        validation = validate_trade(signal, account_equity=1000.0)

        self.assertFalse(validation["allowed"])
        self.assertEqual(validation["reason"], "Risk reward below scalping minimum 1.5")

    def test_risk_state_exposes_aligned_minimum(self) -> None:
        with patch("app.risk.refresh_risk_state", return_value=SAFE_STATE):
            state = get_risk_state()
        self.assertEqual(state["min_risk_reward"], 1.5)


if __name__ == "__main__":
    unittest.main()
