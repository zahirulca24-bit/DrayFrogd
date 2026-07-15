from __future__ import annotations

import unittest
from unittest.mock import patch

from app.engines import (
    INTRADAY_PROFILE,
    SCALPING_PROFILE,
    build_engine_context,
    evaluate_engine_strategies,
)
from app.signal_pipeline import SIGNAL_ACTIVE, evaluate_signal_contexts


class EngineSeparationTests(unittest.TestCase):
    def test_profiles_have_independent_timeframes_and_risk_contracts(self) -> None:
        self.assertEqual(SCALPING_PROFILE.timeframes(), {
            "trend": "15m",
            "setup": "5m",
            "trigger": "1m",
            "open_candle_confirmation": False,
        })
        self.assertEqual(INTRADAY_PROFILE.timeframes(), {
            "trend": "1h",
            "setup": "15m",
            "trigger": "5m",
            "open_candle_confirmation": False,
        })
        self.assertEqual(SCALPING_PROFILE.risk_amount, 20.0)
        self.assertEqual(INTRADAY_PROFILE.risk_amount, 50.0)
        self.assertEqual(SCALPING_PROFILE.min_risk_reward, 1.5)
        self.assertEqual(INTRADAY_PROFILE.min_risk_reward, 2.0)

    def test_context_builder_preserves_explicit_engine_identity(self) -> None:
        scalping = build_engine_context(
            "scalping",
            symbol="BTCUSDT",
            trend={"state": "UPTREND"},
            scanner_logic={"status": "eligible", "direction": "long"},
            setup_candles=[],
            trigger_candles=[],
        )
        intraday = build_engine_context(
            "intraday",
            symbol="BTCUSDT",
            trend={"state": "UPTREND"},
            scanner_logic={"status": "active", "direction": "long"},
            setup_candles=[],
            trigger_candles=[],
        )

        self.assertEqual(scalping["trade_type"], "scalping")
        self.assertEqual(scalping["engine_profile"], "scalping")
        self.assertEqual(intraday["trade_type"], "intraday")
        self.assertEqual(intraday["engine_profile"], "intraday")
        self.assertNotEqual(scalping["timeframes"], intraday["timeframes"])

    def test_scalping_keeps_valid_one_point_five_r_target(self) -> None:
        result = evaluate_engine_strategies(
            "scalping",
            symbol="BTCUSDT",
            setup_candles=[],
            trigger_candles=[],
            evaluator=self._one_point_five_r_evaluator,
        )[0]

        self.assertEqual(result["engine_profile"], "scalping")
        self.assertAlmostEqual(result["take_profit"], 101.5)
        self.assertAlmostEqual(result["risk_reward"], 1.5)
        self.assertFalse(result["profile_adjusted_target"])

    def test_intraday_raises_valid_one_point_five_r_target_to_two_r(self) -> None:
        result = evaluate_engine_strategies(
            "intraday",
            symbol="BTCUSDT",
            setup_candles=[],
            trigger_candles=[],
            evaluator=self._one_point_five_r_evaluator,
        )[0]

        self.assertEqual(result["engine_profile"], "intraday")
        self.assertAlmostEqual(result["raw_take_profit"], 101.5)
        self.assertAlmostEqual(result["take_profit"], 102.0)
        self.assertAlmostEqual(result["risk_reward"], 2.0)
        self.assertTrue(result["profile_adjusted_target"])

    def test_intraday_profiled_signal_survives_two_r_signal_gate(self) -> None:
        context = {
            "symbol": "BTCUSDT",
            "market_rank": 1,
            "trade_type": "intraday",
            "trend": {"state": "UPTREND", "strength": 90.0, "reason": "test"},
            "market_ranking": {"score": 90.0, "components": {}},
            "scanner_logic": {"status": "active", "direction": "long", "reason": "test"},
            "setup_candles": [],
            "trigger_candles": [],
            "timeframes": INTRADAY_PROFILE.timeframes(),
        }
        with patch("app.signal_pipeline.evaluate_registered_strategies", self._one_point_five_r_evaluator):
            output = evaluate_signal_contexts([context])

        self.assertEqual(output["signals_found"], 1)
        signal = output["signals"][0]
        self.assertEqual(signal["signal_state"], SIGNAL_ACTIVE)
        self.assertEqual(signal["trade_type"], "intraday")
        self.assertEqual(signal["engine_profile"], "intraday")
        self.assertAlmostEqual(signal["risk_reward"], 2.0)
        self.assertAlmostEqual(signal["take_profit"], 102.0)
        self.assertTrue(signal["profile_adjusted_target"])

    @staticmethod
    def _one_point_five_r_evaluator(symbol, candles_5m, candles_1m, now=None):
        return [{
            "symbol": symbol,
            "strategy_name": "ema_pullback",
            "strategy": "ema_pullback",
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 99.0,
            "take_profit": 101.5,
            "risk_reward": 1.5,
            "detected_at": "2026-07-15T12:00:00+00:00",
            "status": "active",
            "confidence_score": 85,
            "rejection_reason": None,
        }]


if __name__ == "__main__":
    unittest.main()
