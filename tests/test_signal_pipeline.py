from __future__ import annotations

import unittest
from unittest.mock import patch

from app.signal_pipeline import (
    SIGNAL_ACTIVE,
    SIGNAL_EXPIRED,
    SIGNAL_INVALID,
    SIGNAL_NEAR_SETUP,
    SIGNAL_NO_SETUP,
    evaluate_signal_contexts,
    normalize_strategy_result,
)


class SignalPipelineTests(unittest.TestCase):
    def test_raw_strategy_statuses_map_to_canonical_five_state_contract(self) -> None:
        cases = [
            ("active", None, SIGNAL_ACTIVE),
            ("near_setup", "waiting_for_trigger", SIGNAL_NEAR_SETUP),
            ("expired", "signal_expired", SIGNAL_EXPIRED),
            ("rejected", "breakout_not_detected", SIGNAL_NO_SETUP),
            ("rejected", "invalid_trade_levels", SIGNAL_INVALID),
        ]
        for status, reason, expected in cases:
            with self.subTest(status=status, reason=reason):
                result = normalize_strategy_result(
                    symbol="BTCUSDT",
                    result=self._raw_signal(status=status, reason=reason),
                    trade_type="scalping",
                    market_rank=1,
                    trend=self._trend("UPTREND"),
                    market_ranking={"score": 90.0, "components": {}},
                    scanner_logic={"status": "eligible", "direction": "long"},
                    timeframes={"trend": "5m", "setup": "5m", "trigger": "1m"},
                )
                self.assertEqual(result["signal_state"], expected)

    def test_active_primary_is_selected_once_per_symbol(self) -> None:
        contexts = [
            self._context("BTCUSDT", "scalping", 1),
            self._context("BTCUSDT", "intraday", 1),
        ]
        outputs = [
            [self._raw_signal(strategy="ema_pullback", status="active", confidence=82)],
            [self._raw_signal(strategy="breakout", status="active", confidence=91)],
        ]
        with patch("app.signal_pipeline.evaluate_registered_strategies", side_effect=outputs):
            result = evaluate_signal_contexts(contexts)

        self.assertEqual(result["strategy_checks"], 2)
        self.assertEqual(result["signals_found"], 1)
        self.assertEqual(len(result["primary_signals"]), 1)
        primary = result["signals"][0]
        self.assertEqual(primary["symbol"], "BTCUSDT")
        self.assertEqual(primary["strategy_name"], "breakout")
        self.assertEqual(primary["trade_type"], "scalping")
        self.assertTrue(primary["primary_signal"])
        self.assertEqual(primary["confirmation_count"], 1)
        self.assertEqual(primary["confirmations"][0]["strategy_name"], "ema_pullback")

    def test_active_beats_near_setup_even_when_near_has_higher_confidence(self) -> None:
        context = self._context("BTCUSDT", "scalping", 1)
        with patch(
            "app.signal_pipeline.evaluate_registered_strategies",
            return_value=[
                self._raw_signal(strategy="ema_pullback", status="near_setup", confidence=99),
                self._raw_signal(strategy="breakout", status="active", confidence=70),
            ],
        ):
            result = evaluate_signal_contexts([context])

        self.assertEqual(result["signals_found"], 1)
        self.assertEqual(result["near_setups"], 0)
        self.assertEqual(result["signals"][0]["strategy_name"], "breakout")
        self.assertEqual(result["signals"][0]["signal_state"], SIGNAL_ACTIVE)

    def test_near_setup_is_monitor_only_and_not_executable(self) -> None:
        context = self._context("ETHUSDT", "scalping", 2)
        with patch(
            "app.signal_pipeline.evaluate_registered_strategies",
            return_value=[self._raw_signal(status="near_setup", reason="waiting_for_trigger")],
        ):
            result = evaluate_signal_contexts([context])

        self.assertEqual(result["signals_found"], 0)
        self.assertEqual(result["near_setups"], 1)
        signal = result["monitoring_signals"][0]
        self.assertTrue(signal["monitor_only"])
        self.assertFalse(signal["is_executable"])
        self.assertEqual(signal["signal_state"], SIGNAL_NEAR_SETUP)

    def test_invalid_geometry_can_never_become_active(self) -> None:
        raw = self._raw_signal(status="active")
        raw["stop_loss"] = 101.0
        result = normalize_strategy_result(
            symbol="BTCUSDT",
            result=raw,
            trade_type="scalping",
            market_rank=1,
            trend=self._trend("UPTREND"),
            market_ranking={"score": 90.0, "components": {}},
            scanner_logic={"status": "eligible", "direction": "long"},
        )

        self.assertEqual(result["signal_state"], SIGNAL_INVALID)
        self.assertEqual(result["rejection_reason"], "invalid_trade_geometry")
        self.assertFalse(result["is_executable"])

    def test_opposite_trend_direction_is_invalid(self) -> None:
        result = normalize_strategy_result(
            symbol="BTCUSDT",
            result=self._raw_signal(direction="short", status="active"),
            trade_type="scalping",
            market_rank=1,
            trend=self._trend("UPTREND"),
            market_ranking={"score": 90.0, "components": {}},
            scanner_logic={"status": "eligible", "direction": "long"},
        )

        self.assertEqual(result["signal_state"], SIGNAL_INVALID)
        self.assertEqual(result["rejection_reason"], "trend_conflict_uptrend_long_only")

    def test_missing_trade_type_is_invalid_and_never_defaults_to_scalping(self) -> None:
        result = normalize_strategy_result(
            symbol="BTCUSDT",
            result=self._raw_signal(status="active"),
            market_rank=1,
            trend=self._trend("UPTREND"),
            market_ranking={"score": 90.0, "components": {}},
            scanner_logic={"status": "eligible", "direction": "long"},
        )

        self.assertIsNone(result["trade_type"])
        self.assertEqual(result["signal_state"], SIGNAL_INVALID)
        self.assertFalse(result["is_executable"])

    def test_intraday_requires_two_r_minimum(self) -> None:
        raw = self._raw_signal(status="active")
        raw["risk_reward"] = 1.5
        result = normalize_strategy_result(
            symbol="BTCUSDT",
            result=raw,
            trade_type="intraday",
            market_rank=1,
            trend=self._trend("UPTREND"),
            market_ranking={"score": 90.0, "components": {}},
            scanner_logic={"status": "active", "direction": "long"},
        )

        self.assertEqual(result["signal_state"], SIGNAL_INVALID)
        self.assertEqual(result["rejection_reason"], "risk_reward_below_trade_type_minimum")
        self.assertFalse(result["is_executable"])

    def test_expired_and_no_setup_results_are_not_kept_as_useful_signals(self) -> None:
        context = self._context("SOLUSDT", "scalping", 3)
        with patch(
            "app.signal_pipeline.evaluate_registered_strategies",
            return_value=[
                self._raw_signal(strategy="ema_pullback", status="expired", reason="signal_expired"),
                self._raw_signal(strategy="breakout", status="rejected", reason="breakout_not_detected"),
            ],
        ):
            result = evaluate_signal_contexts([context])

        self.assertEqual(result["signals_found"], 0)
        self.assertEqual(result["near_setups"], 0)
        self.assertEqual(result["useful_signals"], 0)
        self.assertEqual(result["state_counts"][SIGNAL_EXPIRED], 1)
        self.assertEqual(result["state_counts"][SIGNAL_NO_SETUP], 1)

    def test_global_signal_ranking_is_deterministic(self) -> None:
        contexts = [
            self._context("ETHUSDT", "scalping", 2),
            self._context("BTCUSDT", "scalping", 1),
        ]
        outputs = [
            [self._raw_signal(strategy="breakout", status="active", confidence=80)],
            [self._raw_signal(strategy="ema_pullback", status="active", confidence=80)],
        ]
        with patch("app.signal_pipeline.evaluate_registered_strategies", side_effect=outputs):
            result = evaluate_signal_contexts(contexts)

        self.assertEqual([item["symbol"] for item in result["signals"]], ["BTCUSDT", "ETHUSDT"])
        self.assertEqual([item["signal_rank"] for item in result["signals"]], [1, 2])

    @staticmethod
    def _trend(state: str) -> dict:
        return {"state": state, "strength": 90.0, "reason": "test"}

    @staticmethod
    def _context(symbol: str, trade_type: str, market_rank: int) -> dict:
        timeframes = (
            {"trend": "5m", "setup": "5m", "trigger": "1m"}
            if trade_type == "scalping"
            else {"trend": "1h", "setup": "15m", "trigger": "5m"}
        )
        return {
            "symbol": symbol,
            "market_rank": market_rank,
            "trade_type": trade_type,
            "trend": {"state": "UPTREND", "strength": 90.0, "reason": "test"},
            "market_ranking": {"score": 90.0 - market_rank, "components": {}},
            "scanner_logic": {
                "status": "active" if trade_type == "intraday" else "eligible",
                "direction": "long",
                "reason": "test",
            },
            "setup_candles": [],
            "trigger_candles": [],
            "timeframes": timeframes,
        }

    @staticmethod
    def _raw_signal(
        *,
        strategy: str = "ema_pullback",
        direction: str = "long",
        status: str = "active",
        reason: str | None = None,
        confidence: int = 80,
    ) -> dict:
        return {
            "strategy_name": strategy,
            "strategy": strategy,
            "direction": direction,
            "entry": 100.0,
            "stop_loss": 99.0 if direction == "long" else 101.0,
            "take_profit": 102.0 if direction == "long" else 98.0,
            "risk_reward": 2.0,
            "detected_at": "2026-07-12T08:00:00+00:00",
            "status": status,
            "confidence_score": confidence,
            "rejection_reason": reason,
        }


if __name__ == "__main__":
    unittest.main()
