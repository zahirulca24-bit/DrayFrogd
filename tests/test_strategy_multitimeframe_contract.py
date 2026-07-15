from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.strategy import evaluate_breakout_strategy, evaluate_pure_smc_strategy
from tests.test_strategy_engine import _build_bullish_pure_smc_series, _build_long_breakout_series, _candle


class StrategyMultitimeframeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_time = datetime(2026, 7, 10, 0, 0, tzinfo=UTC)

    def test_breakout_level_comes_from_setup_timeframe(self) -> None:
        setup = _build_long_breakout_series(
            self.base_time,
            breakout_close=104.0,
            breakout_volume=100.0,
        )
        trigger = _build_long_breakout_series(
            self.base_time,
            breakout_close=101.0,
            breakout_volume=180.0,
        )
        with patch("app.strategy._ema", return_value=[99.0] * len(setup)), patch(
            "app.strategy._rsi", return_value=[60.0] * len(trigger)
        ):
            signal = evaluate_breakout_strategy("BTCUSDT", setup, trigger, self.base_time)

        self.assertEqual(signal["status"], "rejected")
        self.assertEqual(signal["rejection_reason"], "breakout_not_detected")

    def test_breakout_trigger_confirms_setup_level(self) -> None:
        setup = _build_long_breakout_series(
            self.base_time,
            breakout_close=104.0,
            breakout_volume=100.0,
        )
        trigger = _build_long_breakout_series(
            self.base_time,
            breakout_close=105.0,
            breakout_volume=180.0,
        )
        with patch("app.strategy._ema", return_value=[99.0] * len(setup)), patch(
            "app.strategy._rsi", return_value=[60.0] * len(trigger)
        ):
            signal = evaluate_breakout_strategy("BTCUSDT", setup, trigger, self.base_time)

        self.assertEqual(signal["status"], "active")
        self.assertTrue(signal["setup_timeframe_used"])
        self.assertEqual(signal["setup_candle_count"], len(setup))
        self.assertEqual(signal["trigger_candle_count"], len(trigger))

    def test_pure_smc_structure_comes_from_setup_and_mitigation_from_trigger(self) -> None:
        setup = _build_bullish_pure_smc_series(self.base_time, latest_close=10.1)
        trigger = [
            _candle(
                self.base_time + timedelta(minutes=12),
                9.8,
                9.9,
                9.6,
                9.7,
                90.0,
            )
        ]
        signal = evaluate_pure_smc_strategy("BTCUSDT", setup, trigger, self.base_time)

        self.assertEqual(signal["status"], "active")
        self.assertEqual(signal["direction"], "long")
        self.assertTrue(signal["setup_timeframe_used"])
        self.assertEqual(signal["trigger_candle_count"], 1)

    def test_pure_smc_waits_when_trigger_has_not_mitigated_setup_zone(self) -> None:
        setup = _build_bullish_pure_smc_series(self.base_time, latest_close=10.1)
        trigger = [
            _candle(
                self.base_time + timedelta(minutes=12),
                10.0,
                10.2,
                9.9,
                10.1,
                90.0,
            )
        ]
        signal = evaluate_pure_smc_strategy("BTCUSDT", setup, trigger, self.base_time)

        self.assertEqual(signal["status"], "near_setup")
        self.assertEqual(signal["rejection_reason"], "waiting_for_mitigation")
        self.assertTrue(signal["setup_timeframe_used"])


if __name__ == "__main__":
    unittest.main()
