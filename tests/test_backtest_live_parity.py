from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.backtest import (
    _evaluate_profiled_signal,
    _profile_config,
    _resolve_backtest_parameters,
    run_strategy_backtest,
)
from app.engines import INTRADAY_PROFILE, SCALPING_PROFILE
from app.schemas import BacktestRequest
from app.scanner_trend import TREND_UP


class FakeBacktestClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self.reference = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)

    def safe_fetch_recent_candles(self, symbol: str, interval: str, limit: int):
        self.calls.append((symbol, interval, limit))
        minutes = {"1": 1, "5": 5, "15": 15, "60": 60}[interval]
        count = max(300, min(limit, 400))
        first = self.reference - timedelta(minutes=minutes * count)
        candles = []
        for index in range(count):
            close = 100.0 + (index * 0.05)
            candles.append(
                {
                    "timestamp": (first + timedelta(minutes=minutes * index)).isoformat(),
                    "open": close - 0.02,
                    "high": close + 0.08,
                    "low": close - 0.08,
                    "close": close,
                    "volume": 1000.0,
                    "confirm": True,
                }
            )
        return True, candles, None


class BacktestLiveParityTests(unittest.TestCase):
    def test_profile_config_derives_scalping_contract(self) -> None:
        profile = _profile_config("scalping")
        self.assertEqual(profile["trend_interval"], SCALPING_PROFILE.trend_interval)
        self.assertEqual(profile["setup_interval"], SCALPING_PROFILE.setup_interval)
        self.assertEqual(profile["trigger_interval"], SCALPING_PROFILE.trigger_interval)
        self.assertEqual(profile["default_risk_amount"], SCALPING_PROFILE.risk_amount)
        self.assertEqual(profile["default_min_risk_reward"], SCALPING_PROFILE.min_risk_reward)
        self.assertEqual(profile["max_hold_candles"], 30)

    def test_profile_config_derives_intraday_contract(self) -> None:
        profile = _profile_config("intraday")
        self.assertEqual(profile["trend_interval"], INTRADAY_PROFILE.trend_interval)
        self.assertEqual(profile["setup_interval"], INTRADAY_PROFILE.setup_interval)
        self.assertEqual(profile["trigger_interval"], INTRADAY_PROFILE.trigger_interval)
        self.assertEqual(profile["default_risk_amount"], INTRADAY_PROFILE.risk_amount)
        self.assertEqual(profile["default_min_risk_reward"], INTRADAY_PROFILE.min_risk_reward)
        self.assertEqual(profile["max_hold_candles"], 72)

    def test_request_defaults_do_not_force_scalping_values_onto_intraday(self) -> None:
        request = BacktestRequest(trade_type="intraday")
        self.assertIsNone(request.risk_amount)
        self.assertIsNone(request.min_risk_reward)
        self.assertIsNone(request.max_hold_candles)

    def test_profile_floor_and_hold_cap_are_enforced(self) -> None:
        resolved = _resolve_backtest_parameters(
            _profile_config("scalping"),
            risk_amount=None,
            min_risk_reward=1.0,
            max_hold_candles=240,
        )
        self.assertEqual(resolved["risk_amount"], 20.0)
        self.assertEqual(resolved["min_risk_reward"], 1.5)
        self.assertEqual(resolved["max_hold_candles"], 30)
        self.assertTrue(resolved["hold_limit_capped_to_profile"])

    def test_intraday_raw_one_point_five_r_is_profiled_to_two_r_before_backtest(self) -> None:
        def evaluator(symbol, setup, trigger, now=None):
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

        with patch("app.backtest._strategy_evaluator", return_value=evaluator):
            signal, results = _evaluate_profiled_signal(
                "ema_pullback",
                "BTCUSDT",
                "intraday",
                [],
                [],
                datetime(2026, 7, 15, 12, 0, tzinfo=UTC),
                trend={"state": TREND_UP, "strength": 90.0, "reason": "test"},
                scanner_logic={"status": "active", "direction": "long", "reason": "test"},
                timeframes=INTRADAY_PROFILE.timeframes(),
            )

        self.assertEqual(len(results), 1)
        self.assertIsNotNone(signal)
        self.assertEqual(signal["signal_state"], "ACTIVE")
        self.assertEqual(signal["risk_reward"], 2.0)
        self.assertEqual(signal["take_profit"], 102.0)
        self.assertTrue(signal["profile_adjusted_target"])

    def test_canonical_trend_gate_rejects_opposite_direction(self) -> None:
        def evaluator(symbol, setup, trigger, now=None):
            return [{
                "symbol": symbol,
                "strategy_name": "breakout",
                "strategy": "breakout",
                "direction": "short",
                "entry": 100.0,
                "stop_loss": 101.0,
                "take_profit": 98.5,
                "risk_reward": 1.5,
                "detected_at": "2026-07-15T12:00:00+00:00",
                "status": "active",
                "confidence_score": 85,
                "rejection_reason": None,
            }]

        with patch("app.backtest._strategy_evaluator", return_value=evaluator):
            signal, results = _evaluate_profiled_signal(
                "breakout",
                "BTCUSDT",
                "scalping",
                [],
                [],
                datetime(2026, 7, 15, 12, 0, tzinfo=UTC),
                trend={"state": TREND_UP, "strength": 90.0, "reason": "test"},
                scanner_logic={"status": "eligible", "direction": "long", "reason": "test"},
                timeframes=SCALPING_PROFILE.timeframes(),
            )

        self.assertIsNone(signal)
        self.assertEqual(results[0]["signal_state"], "INVALID")
        self.assertEqual(results[0]["rejection_reason"], "trend_conflict_uptrend_long_only")

    def test_backtest_fetches_all_live_profile_timeframes(self) -> None:
        client = FakeBacktestClient()
        with patch(
            "app.backtest.analyze_trend",
            return_value={"state": TREND_UP, "strength": 90.0, "reason": "test"},
        ), patch(
            "app.backtest._evaluate_profiled_signal",
            return_value=(None, [{"signal_state": "NO_SETUP", "rejection_reason": "test"}]),
        ):
            result = run_strategy_backtest(client, symbol="BTCUSDT", trade_type="scalping", candle_limit=300)

        self.assertTrue(result["ok"])
        self.assertEqual([call[1] for call in client.calls], ["1", "5", "15"])
        self.assertEqual(result["risk_amount"], 20.0)
        self.assertEqual(result["min_risk_reward"], 1.5)
        self.assertEqual(result["max_hold_candles"], 30)
        self.assertTrue(result["live_pipeline_parity"]["trend_gate"])
        self.assertTrue(result["live_pipeline_parity"]["canonical_signal_gate"])


if __name__ == "__main__":
    unittest.main()
