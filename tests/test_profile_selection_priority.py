from __future__ import annotations

import unittest
from unittest.mock import patch

from app.signal_pipeline import SIGNAL_ACTIVE, SIGNAL_INVALID, SIGNAL_NEAR_SETUP, evaluate_signal_contexts


class ProfileSelectionPriorityTests(unittest.TestCase):
    def test_active_intraday_beats_higher_score_active_scalping_on_same_symbol(self) -> None:
        contexts = [self._context("BTCUSDT", "scalping"), self._context("BTCUSDT", "intraday")]
        outputs = [
            [self._signal("long", "active", confidence=70)],
            [self._signal("long", "active", confidence=99)],
        ]
        with patch("app.signal_pipeline.evaluate_registered_strategies", side_effect=outputs):
            result = evaluate_signal_contexts(contexts)

        self.assertEqual(result["signals_found"], 1)
        self.assertEqual(result["signals"][0]["trade_type"], "intraday")
        self.assertEqual(result["signals"][0]["signal_state"], SIGNAL_ACTIVE)
        self.assertEqual(result["signals"][0]["confirmation_count"], 1)

    def test_active_scalping_beats_near_setup_intraday(self) -> None:
        contexts = [self._context("ETHUSDT", "scalping"), self._context("ETHUSDT", "intraday")]
        outputs = [
            [self._signal("long", "near_setup", confidence=99)],
            [self._signal("long", "active", confidence=70)],
        ]
        with patch("app.signal_pipeline.evaluate_registered_strategies", side_effect=outputs):
            result = evaluate_signal_contexts(contexts)

        self.assertEqual(result["signals_found"], 1)
        self.assertEqual(result["signals"][0]["trade_type"], "scalping")
        self.assertEqual(result["signals"][0]["signal_state"], SIGNAL_ACTIVE)
        intraday = next(item for item in result["results"] if item["trade_type"] == "intraday")
        self.assertEqual(intraday["signal_state"], SIGNAL_NEAR_SETUP)

    def test_opposite_active_profile_directions_block_execution(self) -> None:
        scalping = self._context("SOLUSDT", "scalping")
        scalping["trend"] = {"state": "DOWNTREND", "strength": 90.0, "reason": "test"}
        scalping["scanner_logic"]["direction"] = "short"
        intraday = self._context("SOLUSDT", "intraday")
        contexts = [scalping, intraday]
        outputs = [
            [self._signal("long", "active", confidence=90)],
            [self._signal("short", "active", confidence=90)],
        ]
        with patch("app.signal_pipeline.evaluate_registered_strategies", side_effect=outputs):
            result = evaluate_signal_contexts(contexts)

        self.assertEqual(result["signals_found"], 0)
        self.assertEqual(result["primary_signals"], [])
        conflicted = [item for item in result["results"] if item["rejection_reason"] == "profile_direction_conflict"]
        self.assertEqual(len(conflicted), 2)
        self.assertTrue(all(item["signal_state"] == SIGNAL_INVALID for item in conflicted))
        self.assertTrue(all(not item["is_executable"] for item in conflicted))

    @staticmethod
    def _context(symbol: str, trade_type: str) -> dict:
        return {
            "symbol": symbol,
            "market_rank": 1,
            "trade_type": trade_type,
            "trend": {"state": "UPTREND", "strength": 90.0, "reason": "test"},
            "market_ranking": {"score": 90.0, "components": {}},
            "scanner_logic": {
                "status": "active" if trade_type == "intraday" else "eligible",
                "direction": "long",
                "reason": "test",
            },
            "setup_candles": [],
            "trigger_candles": [],
            "timeframes": (
                {"trend": "15m", "setup": "5m", "trigger": "1m"}
                if trade_type == "scalping"
                else {"trend": "1h", "setup": "15m", "trigger": "5m"}
            ),
        }

    @staticmethod
    def _signal(direction: str, status: str, *, confidence: int) -> dict:
        return {
            "strategy_name": "ema_pullback",
            "strategy": "ema_pullback",
            "direction": direction,
            "entry": 100.0,
            "stop_loss": 99.0 if direction == "long" else 101.0,
            "take_profit": 102.0 if direction == "long" else 98.0,
            "risk_reward": 2.0,
            "detected_at": "2026-07-15T00:00:00+00:00",
            "status": status,
            "confidence_score": confidence,
            "rejection_reason": "waiting_for_trigger" if status == "near_setup" else None,
        }


if __name__ == "__main__":
    unittest.main()
