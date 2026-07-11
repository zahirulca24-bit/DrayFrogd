import unittest
from datetime import UTC, datetime
from unittest.mock import patch

import app.risk as risk
from app.strategy import Candle, _build_ema_active_signal


RISK_SETTINGS = {
    "risk_per_trade": 0.01,
    "leverage_cap": 5.0,
    "exposure_cap": 0.30,
    "max_open_trades": 3,
    "max_daily_trades": 8,
}


class RiskRewardPolicyAlignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        with risk._risk_lock:
            risk._active_symbols.clear()
            risk._trades_today = 0
            risk._trades_day = None
            risk._cooldown_until = None
            risk._state_loaded = True

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

        with patch("app.risk.get_risk_settings", return_value=RISK_SETTINGS), patch("app.risk._persist_state_locked"):
            validation = risk.validate_trade(signal.to_dict())

        self.assertTrue(validation["allowed"])
        self.assertEqual(validation["reason"], "")

    def test_signal_below_one_point_five_r_is_rejected(self) -> None:
        signal = {
            "symbol": "ETHUSDT",
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 98.0,
            "take_profit": 102.98,
            "risk_reward": 1.49,
            "status": "active",
        }

        validation = risk.validate_trade(signal)

        self.assertFalse(validation["allowed"])
        self.assertEqual(validation["reason"], "Risk reward below minimum 1.5")

    def test_risk_state_exposes_aligned_minimum(self) -> None:
        with patch("app.risk.get_risk_settings", return_value=RISK_SETTINGS), patch("app.risk._persist_state_locked"):
            state = risk.get_risk_state()

        self.assertEqual(state["min_risk_reward"], 1.5)


if __name__ == "__main__":
    unittest.main()
