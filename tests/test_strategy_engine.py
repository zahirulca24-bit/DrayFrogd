import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.signal_pipeline import evaluate_signal_contexts
from app.strategy import (
    STRATEGY_BREAKOUT,
    STRATEGY_EMA_PULLBACK,
    STRATEGY_PURE_SMC,
    _find_confirmed_swings,
    _find_pure_smc_fvg,
    _find_pure_smc_order_block,
    _find_pure_smc_setup,
    _pure_smc_structure_before_index,
    evaluate_breakout_strategy,
    evaluate_pure_smc_strategy,
)


class BreakoutStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_time = datetime(2026, 7, 10, 0, 0, tzinfo=UTC)

    def test_valid_long_breakout(self) -> None:
        candles = _build_long_breakout_series(self.base_time, breakout_close=101.0, breakout_volume=180.0)
        signal = self._run_breakout(candles, ema_value=99.0, rsi_value=60.0)

        self.assertEqual(signal["strategy_name"], STRATEGY_BREAKOUT)
        self.assertEqual(signal["status"], "active")
        self.assertEqual(signal["direction"], "long")

    def test_valid_short_breakout(self) -> None:
        candles = _build_short_breakout_series(self.base_time, breakout_close=98.9, breakout_volume=180.0)
        signal = self._run_breakout(candles, ema_value=101.0, rsi_value=40.0)

        self.assertEqual(signal["strategy_name"], STRATEGY_BREAKOUT)
        self.assertEqual(signal["status"], "active")
        self.assertEqual(signal["direction"], "short")

    def test_wick_only_breakout_is_rejected(self) -> None:
        candles = _build_long_breakout_series(
            self.base_time,
            breakout_close=100.4,
            breakout_high=101.2,
            breakout_volume=180.0,
        )
        signal = self._run_breakout(candles, ema_value=99.0, rsi_value=60.0)

        self.assertEqual(signal["status"], "rejected")
        self.assertEqual(signal["rejection_reason"], "breakout_not_detected")

    def test_low_volume_breakout_is_rejected(self) -> None:
        candles = _build_long_breakout_series(self.base_time, breakout_close=101.0, breakout_volume=150.0)
        signal = self._run_breakout(candles, ema_value=99.0, rsi_value=60.0)

        self.assertEqual(signal["status"], "rejected")
        self.assertEqual(signal["rejection_reason"], "volume_not_confirmed")

    def test_long_rsi_overbought_is_rejected(self) -> None:
        candles = _build_long_breakout_series(self.base_time, breakout_close=101.0, breakout_volume=180.0)
        signal = self._run_breakout(candles, ema_value=99.0, rsi_value=71.0)

        self.assertEqual(signal["status"], "rejected")
        self.assertEqual(signal["rejection_reason"], "rsi_overbought")

    def test_short_rsi_oversold_is_rejected(self) -> None:
        candles = _build_short_breakout_series(self.base_time, breakout_close=98.9, breakout_volume=180.0)
        signal = self._run_breakout(candles, ema_value=101.0, rsi_value=29.0)

        self.assertEqual(signal["status"], "rejected")
        self.assertEqual(signal["rejection_reason"], "rsi_oversold")

    def test_ema200_trend_rejection(self) -> None:
        candles = _build_long_breakout_series(self.base_time, breakout_close=101.0, breakout_volume=180.0)
        signal = self._run_breakout(candles, ema_value=101.5, rsi_value=60.0)

        self.assertEqual(signal["status"], "rejected")
        self.assertEqual(signal["rejection_reason"], "trend_not_confirmed")

    def test_average_volume_excludes_breakout_candle(self) -> None:
        candles = _build_long_breakout_series(self.base_time, breakout_close=101.0, breakout_volume=151.0)
        signal = self._run_breakout(candles, ema_value=99.0, rsi_value=60.0)

        self.assertEqual(signal["status"], "active")
        self.assertEqual(signal["direction"], "long")

    def test_support_and_resistance_exclude_breakout_candle(self) -> None:
        candles = _build_long_breakout_series(
            self.base_time,
            breakout_close=101.0,
            breakout_high=105.0,
            breakout_volume=180.0,
        )
        signal = self._run_breakout(candles, ema_value=99.0, rsi_value=60.0)

        self.assertEqual(signal["status"], "active")
        self.assertEqual(signal["direction"], "long")

    def test_breakout_risk_reward_is_at_least_one_point_five(self) -> None:
        candles = _build_long_breakout_series(self.base_time, breakout_close=101.0, breakout_volume=180.0)
        signal = self._run_breakout(candles, ema_value=99.0, rsi_value=60.0)

        self.assertEqual(signal["status"], "active")
        self.assertGreaterEqual(signal["risk_reward"], 1.5)

    def test_incomplete_candle_is_not_used_when_metadata_exists(self) -> None:
        candles = _build_long_breakout_series(self.base_time, breakout_close=101.0, breakout_volume=180.0)
        incomplete_candle = {
            "timestamp": (self.base_time + timedelta(minutes=len(candles))).isoformat(),
            "open": 100.6,
            "high": 100.7,
            "low": 100.0,
            "close": 100.3,
            "volume": 80.0,
            "confirm": False,
        }
        candles.append(incomplete_candle)

        signal = self._run_breakout(candles, ema_value=99.0, rsi_value=60.0)

        self.assertEqual(signal["status"], "active")
        self.assertEqual(signal["detected_at"], candles[-2]["timestamp"])

    def test_signal_pipeline_returns_all_strategy_results_with_correct_names(self) -> None:
        with patch(
            "app.signal_pipeline.evaluate_registered_strategies",
            return_value=[
                _signal("BTCUSDT", STRATEGY_EMA_PULLBACK, "active"),
                _signal("BTCUSDT", STRATEGY_BREAKOUT, "rejected"),
                _signal("BTCUSDT", STRATEGY_PURE_SMC, "near_setup"),
            ],
        ):
            result = evaluate_signal_contexts([_signal_context(self.base_time)])

        self.assertEqual(len(result["results"]), 3)
        self.assertEqual(
            {item["strategy_name"] for item in result["results"]},
            {STRATEGY_EMA_PULLBACK, STRATEGY_BREAKOUT, STRATEGY_PURE_SMC},
        )
        self.assertTrue(all(item["trade_type"] == "scalping" for item in result["results"]))
        self.assertTrue(all(item["market_rank"] == 1 for item in result["results"]))

    def _run_breakout(self, candles: list[dict[str, float | str]], *, ema_value: float, rsi_value: float) -> dict:
        with patch("app.strategy._ema", return_value=[ema_value] * len(candles)), patch(
            "app.strategy._rsi",
            return_value=[rsi_value] * len(candles),
        ):
            return evaluate_breakout_strategy("BTCUSDT", [], candles, self.base_time)


class PureSmcStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_time = datetime(2026, 7, 10, 0, 0, tzinfo=UTC)

    def test_confirmed_bullish_swing_structure(self) -> None:
        candles = _normalize(_build_bullish_pure_smc_series(self.base_time, latest_close=10.1))
        swings = _find_confirmed_swings(candles)
        structure = _pure_smc_structure_before_index(swings, 10)

        self.assertIsNotNone(structure)
        self.assertEqual(structure["direction"], "bearish")

    def test_confirmed_bearish_swing_structure(self) -> None:
        candles = _normalize(_build_bearish_pure_smc_series(self.base_time, latest_close=10.15))
        swings = _find_confirmed_swings(candles)
        structure = _pure_smc_structure_before_index(swings, 10)

        self.assertIsNotNone(structure)
        self.assertEqual(structure["direction"], "bullish")

    def test_wick_only_structure_break_rejection(self) -> None:
        candles = _build_bullish_pure_smc_series(
            self.base_time,
            break_close=10.1,
            break_high=10.5,
            latest_close=10.1,
        )
        signal = evaluate_pure_smc_strategy("BTCUSDT", [], candles, self.base_time)

        self.assertEqual(signal["status"], "rejected")
        self.assertEqual(signal["rejection_reason"], "choch_not_detected")

    def test_valid_bullish_mss_choch(self) -> None:
        candles = _normalize(_build_bullish_pure_smc_series(self.base_time, latest_close=10.1))
        setup = _find_pure_smc_setup(candles)

        self.assertIsNotNone(setup)
        self.assertEqual(setup["direction"], "long")
        self.assertEqual(setup["break_index"], 10)

    def test_valid_bearish_mss_choch(self) -> None:
        candles = _normalize(_build_bearish_pure_smc_series(self.base_time, latest_close=10.15))
        setup = _find_pure_smc_setup(candles)

        self.assertIsNotNone(setup)
        self.assertEqual(setup["direction"], "short")
        self.assertEqual(setup["break_index"], 10)

    def test_bullish_order_block_detection(self) -> None:
        candles = _normalize(_build_bullish_pure_smc_series(self.base_time, latest_close=10.1))
        order_block = _find_pure_smc_order_block(candles, 10, "long")

        self.assertIsNotNone(order_block)
        self.assertEqual(order_block["low"], 9.6)
        self.assertEqual(order_block["high"], 10.0)

    def test_bearish_order_block_detection(self) -> None:
        candles = _normalize(_build_bearish_pure_smc_series(self.base_time, latest_close=10.15))
        order_block = _find_pure_smc_order_block(candles, 10, "short")

        self.assertIsNotNone(order_block)
        self.assertEqual(order_block["low"], 10.15)
        self.assertEqual(order_block["high"], 10.4)

    def test_bullish_fvg_detection(self) -> None:
        candles = _normalize(_build_bullish_pure_smc_series(self.base_time, latest_close=10.1))
        fvg = _find_pure_smc_fvg(candles, 10, "long")

        self.assertEqual(fvg, (9.4, 9.8))

    def test_bearish_fvg_detection(self) -> None:
        candles = _normalize(_build_bearish_pure_smc_series(self.base_time, latest_close=10.15))
        fvg = _find_pure_smc_fvg(candles, 10, "short")

        self.assertEqual(fvg, (10.1, 10.25))

    def test_invalid_zero_fvg_rejection(self) -> None:
        candles = _build_bullish_pure_smc_series(self.base_time, latest_close=10.1)
        candles[8]["high"] = 9.8
        signal = evaluate_pure_smc_strategy("BTCUSDT", [], candles, self.base_time)

        self.assertEqual(signal["status"], "rejected")
        self.assertEqual(signal["rejection_reason"], "fvg_not_detected")

    def test_ob_fvg_overlap_required(self) -> None:
        candles = _build_bullish_pure_smc_series(self.base_time, latest_close=10.1)
        candles[9]["low"] = 10.05
        candles[9]["high"] = 10.3
        signal = evaluate_pure_smc_strategy("BTCUSDT", [], candles, self.base_time)

        self.assertEqual(signal["status"], "rejected")
        self.assertEqual(signal["rejection_reason"], "aoi_not_confirmed")

    def test_near_setup_before_mitigation(self) -> None:
        signal = evaluate_pure_smc_strategy(
            "BTCUSDT",
            [],
            _build_bullish_pure_smc_series(self.base_time, latest_close=10.1),
            self.base_time,
        )

        self.assertEqual(signal["strategy_name"], STRATEGY_PURE_SMC)
        self.assertEqual(signal["status"], "near_setup")

    def test_active_after_mitigation(self) -> None:
        signal = evaluate_pure_smc_strategy(
            "BTCUSDT",
            [],
            _build_bullish_pure_smc_series(self.base_time, latest_close=9.7),
            self.base_time,
        )

        self.assertEqual(signal["strategy_name"], STRATEGY_PURE_SMC)
        self.assertEqual(signal["status"], "active")
        self.assertEqual(signal["direction"], "long")

    def test_bullish_invalidation(self) -> None:
        signal = evaluate_pure_smc_strategy(
            "BTCUSDT",
            [],
            _build_bullish_pure_smc_series(self.base_time, latest_close=9.4),
            self.base_time,
        )

        self.assertEqual(signal["status"], "rejected")
        self.assertEqual(signal["rejection_reason"], "setup_invalidated")

    def test_bearish_invalidation(self) -> None:
        signal = evaluate_pure_smc_strategy(
            "BTCUSDT",
            [],
            _build_bearish_pure_smc_series(self.base_time, latest_close=10.5),
            self.base_time,
        )

        self.assertEqual(signal["status"], "rejected")
        self.assertEqual(signal["rejection_reason"], "setup_invalidated")

    def test_ten_candle_expiry(self) -> None:
        signal = evaluate_pure_smc_strategy(
            "BTCUSDT",
            [],
            _build_bullish_expired_pure_smc_series(self.base_time),
            self.base_time,
        )

        self.assertEqual(signal["status"], "expired")
        self.assertEqual(signal["rejection_reason"], "signal_expired")

    def test_rr_is_at_least_one_point_five(self) -> None:
        signal = evaluate_pure_smc_strategy(
            "BTCUSDT",
            [],
            _build_bullish_pure_smc_series(self.base_time, latest_close=9.7),
            self.base_time,
        )

        self.assertEqual(signal["status"], "active")
        self.assertGreaterEqual(signal["risk_reward"], 1.5)

    def test_signal_pipeline_keeps_three_strategy_results(self) -> None:
        with patch(
            "app.signal_pipeline.evaluate_registered_strategies",
            return_value=[
                _signal("BTCUSDT", STRATEGY_EMA_PULLBACK, "active"),
                _signal("BTCUSDT", STRATEGY_BREAKOUT, "rejected"),
                _signal("BTCUSDT", STRATEGY_PURE_SMC, "near_setup"),
            ],
        ):
            result = evaluate_signal_contexts([_signal_context(self.base_time)])

        self.assertEqual(len(result["results"]), 3)
        self.assertEqual(
            {item["strategy_name"] for item in result["results"]},
            {STRATEGY_EMA_PULLBACK, STRATEGY_BREAKOUT, STRATEGY_PURE_SMC},
        )

    def test_incomplete_candle_is_not_used_when_metadata_exists(self) -> None:
        candles = _build_bullish_pure_smc_series(self.base_time, latest_close=9.7)
        incomplete_candle = {
            "timestamp": (self.base_time + timedelta(minutes=len(candles))).isoformat(),
            "open": 9.8,
            "high": 9.9,
            "low": 9.3,
            "close": 9.4,
            "volume": 90.0,
            "confirm": False,
        }
        candles.append(incomplete_candle)

        signal = evaluate_pure_smc_strategy("BTCUSDT", [], candles, self.base_time)

        self.assertEqual(signal["status"], "active")
        self.assertEqual(signal["detected_at"], candles[-2]["timestamp"])


def _signal_context(base_time: datetime) -> dict:
    return {
        "symbol": "BTCUSDT",
        "market_rank": 1,
        "trade_type": "scalping",
        "trend": {"state": "UPTREND", "strength": 90.0, "reason": "test_fixture"},
        "market_ranking": {"score": 88.0, "components": {}},
        "scanner_logic": {
            "status": "eligible",
            "direction": "long",
            "reason": "scalping_5m_trend_eligible",
            "confidence_score": 90,
        },
        "setup_candles": [],
        "trigger_candles": [],
        "timeframes": {"trend": "5m", "setup": "5m", "trigger": "1m"},
        "detected_at": base_time.isoformat(),
    }


def _signal(symbol: str, strategy_name: str, status: str) -> dict:
    return {
        "symbol": symbol,
        "strategy_name": strategy_name,
        "strategy": strategy_name,
        "direction": "long" if status in {"active", "near_setup"} else None,
        "entry": 100.0 if status in {"active", "near_setup"} else None,
        "stop_loss": 95.0 if status in {"active", "near_setup"} else None,
        "take_profit": 107.5 if status in {"active", "near_setup"} else None,
        "risk_reward": 1.5 if status in {"active", "near_setup"} else None,
        "detected_at": datetime.now(UTC).isoformat(),
        "status": status,
        "confidence_score": 80 if status == "active" else 70 if status == "near_setup" else 0,
        "rejection_reason": (
            None
            if status == "active"
            else "waiting_for_mitigation"
            if status == "near_setup"
            else "breakout_not_detected"
        ),
    }


def _build_long_breakout_series(
    base_time: datetime,
    *,
    breakout_close: float,
    breakout_volume: float,
    breakout_high: float | None = None,
) -> list[dict[str, float | str]]:
    candles: list[dict[str, float | str]] = []
    for index in range(205):
        open_price = 100.0
        close_price = 100.1
        high = 100.4
        low = 99.8
        candles.append(_candle(base_time + timedelta(minutes=index), open_price, high, low, close_price, 100.0))

    for offset in range(24):
        candles[-25 + offset] = _candle(
            base_time + timedelta(minutes=180 + offset),
            100.0,
            100.5,
            99.7,
            100.2,
            100.0,
        )

    candles[-1] = _candle(
        base_time + timedelta(minutes=204),
        100.4,
        breakout_high if breakout_high is not None else breakout_close + 0.2,
        100.2,
        breakout_close,
        breakout_volume,
    )
    return candles


def _build_short_breakout_series(
    base_time: datetime,
    *,
    breakout_close: float,
    breakout_volume: float,
) -> list[dict[str, float | str]]:
    candles: list[dict[str, float | str]] = []
    for index in range(205):
        open_price = 100.0
        close_price = 99.9
        high = 100.2
        low = 99.6
        candles.append(_candle(base_time + timedelta(minutes=index), open_price, high, low, close_price, 100.0))

    for offset in range(24):
        candles[-25 + offset] = _candle(
            base_time + timedelta(minutes=180 + offset),
            100.0,
            100.3,
            99.5,
            99.8,
            100.0,
        )

    candles[-1] = _candle(
        base_time + timedelta(minutes=204),
        99.6,
        99.7,
        breakout_close - 0.2,
        breakout_close,
        breakout_volume,
    )
    return candles


def _candle(
    timestamp: datetime,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> dict[str, float | str]:
    return {
        "timestamp": timestamp.isoformat(),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _normalize(raw_candles: list[dict[str, float | str]]) -> list:
    from app.strategy import _normalize_candles

    return _normalize_candles(raw_candles)


def _build_bullish_pure_smc_series(
    base_time: datetime,
    *,
    break_close: float = 10.35,
    break_high: float = 10.6,
    latest_close: float = 10.1,
) -> list[dict[str, float | str]]:
    return [
        _candle(base_time + timedelta(minutes=0), 9.8, 9.9, 9.5, 9.7, 100.0),
        _candle(base_time + timedelta(minutes=1), 9.7, 10.2, 9.4, 9.9, 100.0),
        _candle(base_time + timedelta(minutes=2), 9.9, 10.8, 9.8, 10.1, 100.0),
        _candle(base_time + timedelta(minutes=3), 10.0, 10.0, 8.9, 9.2, 100.0),
        _candle(base_time + timedelta(minutes=4), 9.2, 9.9, 9.1, 9.4, 100.0),
        _candle(base_time + timedelta(minutes=5), 9.4, 9.6, 9.0, 9.05, 100.0),
        _candle(base_time + timedelta(minutes=6), 8.9, 10.2, 8.9, 9.8, 100.0),
        _candle(base_time + timedelta(minutes=7), 9.8, 9.8, 8.4, 8.8, 100.0),
        _candle(base_time + timedelta(minutes=8), 8.8, 9.4, 8.9, 9.2, 100.0),
        _candle(base_time + timedelta(minutes=9), 9.9, 10.0, 9.6, 9.7, 100.0),
        _candle(base_time + timedelta(minutes=10), 9.9, break_high, 9.8, break_close, 140.0),
        _candle(
            base_time + timedelta(minutes=11),
            10.0,
            max(10.1, latest_close + 0.2),
            min(9.6, latest_close - 0.1),
            latest_close,
            90.0,
        ),
    ]


def _build_bearish_pure_smc_series(
    base_time: datetime,
    *,
    break_close: float = 10.0,
    latest_close: float = 10.15,
) -> list[dict[str, float | str]]:
    return [
        _candle(base_time + timedelta(minutes=0), 10.0, 10.2, 9.7, 10.1, 100.0),
        _candle(base_time + timedelta(minutes=1), 10.1, 10.4, 9.9, 10.3, 100.0),
        _candle(base_time + timedelta(minutes=2), 10.3, 10.9, 10.0, 10.6, 100.0),
        _candle(base_time + timedelta(minutes=3), 10.6, 10.7, 9.8, 10.0, 100.0),
        _candle(base_time + timedelta(minutes=4), 10.0, 10.5, 10.0, 10.2, 100.0),
        _candle(base_time + timedelta(minutes=5), 10.2, 10.8, 10.2, 10.6, 100.0),
        _candle(base_time + timedelta(minutes=6), 10.6, 11.2, 10.5, 10.9, 100.0),
        _candle(base_time + timedelta(minutes=7), 10.9, 11.0, 10.05, 10.4, 100.0),
        _candle(base_time + timedelta(minutes=8), 10.3, 10.35, 10.25, 10.3, 100.0),
        _candle(base_time + timedelta(minutes=9), 10.2, 10.4, 10.15, 10.35, 100.0),
        _candle(base_time + timedelta(minutes=10), 10.05, 10.1, 9.7, break_close, 140.0),
        _candle(
            base_time + timedelta(minutes=11),
            10.2,
            max(10.3, latest_close + 0.1),
            min(9.9, latest_close - 0.2),
            latest_close,
            90.0,
        ),
    ]


def _build_bullish_expired_pure_smc_series(base_time: datetime) -> list[dict[str, float | str]]:
    candles = _build_bullish_pure_smc_series(base_time, latest_close=10.1)
    for offset in range(12, 21):
        candles.append(_candle(base_time + timedelta(minutes=offset), 10.0, 10.2, 9.85, 10.05, 90.0))
    return candles


if __name__ == "__main__":
    unittest.main()
