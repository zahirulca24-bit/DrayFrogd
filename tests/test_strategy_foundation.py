import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from app.scanner import run_scan
from app.strategy import (
    STRATEGY_EMA_PULLBACK,
    Candle,
    StrategySignal,
    _build_ema_active_signal,
    evaluate_ema_pullback_strategy,
)


class FakeScannerClient:
    def safe_fetch_recent_candles(self, symbol: str, interval: str, limit: int):
        candle = {
            "timestamp": datetime.now(UTC).isoformat(),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000.0,
        }
        return True, [candle] * limit, None

    def safe_fetch_market_tickers(self):
        return False, [], "offline"


class StrategyFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_time = datetime(2026, 7, 10, 0, 0, tzinfo=UTC)
        self.candles_5m = [
            {
                "timestamp": (self.base_time).isoformat(),
                "open": 100.0,
                "high": 100.5,
                "low": 99.5,
                "close": 100.2,
            }
        ] * 260
        self.candles_1m = [
            {
                "timestamp": (self.base_time).isoformat(),
                "open": 100.0,
                "high": 100.5,
                "low": 99.5,
                "close": 100.2,
            }
        ] * 40

    def test_ema_signal_includes_common_schema_fields(self) -> None:
        fake_signal = StrategySignal(
            symbol="BTCUSDT",
            strategy_name=STRATEGY_EMA_PULLBACK,
            direction="long",
            entry=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            risk_reward=2.0,
            detected_at=self.base_time.isoformat(),
            status="active",
            confidence_score=80,
            rejection_reason=None,
        )
        with (
            patch("app.strategy._detect_bias", return_value="long"),
            patch("app.strategy._find_latest_pullback", return_value=20),
            patch("app.strategy._find_trigger_index", return_value=21),
            patch("app.strategy._build_ema_active_signal", return_value=fake_signal),
        ):
            signal = evaluate_ema_pullback_strategy("BTCUSDT", self.candles_5m, self.candles_1m, self.base_time)

        self.assertEqual(signal["strategy_name"], STRATEGY_EMA_PULLBACK)
        self.assertEqual(signal["strategy"], STRATEGY_EMA_PULLBACK)
        for field in [
            "symbol",
            "direction",
            "entry",
            "stop_loss",
            "take_profit",
            "risk_reward",
            "confidence_score",
            "detected_at",
            "status",
            "rejection_reason",
        ]:
            self.assertIn(field, signal)

    def test_scanner_preserves_strategy_name(self) -> None:
        with patch("app.scanner._resolve_scan_universe", return_value=["BTCUSDT"]), patch(
            "app.scanner.evaluate_registered_strategies",
            return_value=[
                {
                    "strategy_name": STRATEGY_EMA_PULLBACK,
                    "strategy": STRATEGY_EMA_PULLBACK,
                    "symbol": "BTCUSDT",
                    "direction": "long",
                    "entry": 100.0,
                    "stop_loss": 95.0,
                    "take_profit": 110.0,
                    "risk_reward": 2.0,
                    "confidence_score": 80,
                    "detected_at": self.base_time.isoformat(),
                    "status": "active",
                    "rejection_reason": None,
                }
            ],
        ), patch(
            "app.scanner.analyze_trend",
            return_value={"state": "UPTREND", "strength": 90.0, "reason": "test_fixture"},
        ):
            result = run_scan(FakeScannerClient())

        self.assertTrue(result["ok"])
        self.assertEqual(result["signals"][0]["strategy_name"], STRATEGY_EMA_PULLBACK)
        self.assertEqual(result["results"][0]["strategy_name"], STRATEGY_EMA_PULLBACK)

    def test_direction_aware_long_pullback_is_allowed(self) -> None:
        candles_1m = self._build_ema_pullback_candles(
            touch_open=100.3,
            touch_high=100.5,
            touch_low=99.8,
            touch_close=100.1,
            trigger_open=100.2,
            trigger_high=101.0,
            trigger_low=100.1,
            trigger_close=100.8,
        )

        with patch("app.strategy._detect_bias", return_value="long"), patch("app.strategy._ema", return_value=[100.0] * len(candles_1m)):
            signal = evaluate_ema_pullback_strategy("BTCUSDT", self.candles_5m, candles_1m, self.base_time)

        self.assertEqual(signal["status"], "active")
        self.assertEqual(signal["direction"], "long")
        self.assertEqual(signal["strategy_name"], STRATEGY_EMA_PULLBACK)

    def test_direction_aware_short_pullback_is_allowed(self) -> None:
        candles_1m = self._build_ema_pullback_candles(
            touch_open=99.7,
            touch_high=100.2,
            touch_low=99.5,
            touch_close=99.9,
            trigger_open=99.8,
            trigger_high=99.9,
            trigger_low=99.0,
            trigger_close=99.2,
        )

        with patch("app.strategy._detect_bias", return_value="short"), patch("app.strategy._ema", return_value=[100.0] * len(candles_1m)):
            signal = evaluate_ema_pullback_strategy("BTCUSDT", self.candles_5m, candles_1m, self.base_time)

        self.assertEqual(signal["status"], "active")
        self.assertEqual(signal["direction"], "short")
        self.assertEqual(signal["strategy_name"], STRATEGY_EMA_PULLBACK)

    def test_invalid_opposite_structure_pullback_is_rejected(self) -> None:
        candles_1m = self._build_ema_pullback_candles(
            touch_open=100.4,
            touch_high=100.5,
            touch_low=99.7,
            touch_close=99.8,
            trigger_open=99.9,
            trigger_high=100.0,
            trigger_low=99.7,
            trigger_close=99.95,
        )

        with patch("app.strategy._detect_bias", return_value="long"), patch("app.strategy._ema", return_value=[100.0] * len(candles_1m)):
            signal = evaluate_ema_pullback_strategy("BTCUSDT", self.candles_5m, candles_1m, self.base_time)

        self.assertEqual(signal["status"], "rejected")
        self.assertEqual(signal["rejection_reason"], "opposite_pullback_structure")
        self.assertEqual(signal["strategy_name"], STRATEGY_EMA_PULLBACK)

    def test_ema_signal_risk_reward_is_one_point_five(self) -> None:
        candles = [
            Candle(timestamp=self.base_time, open=100.0, high=101.0, low=99.8, close=100.4),
            Candle(timestamp=self.base_time, open=100.4, high=101.2, low=100.0, close=100.8),
            Candle(timestamp=self.base_time, open=100.8, high=101.8, low=100.7, close=101.6),
        ]

        signal = _build_ema_active_signal("BTCUSDT", "long", candles, pullback_index=1, trigger_index=2)

        self.assertIsNotNone(signal)
        self.assertEqual(signal.risk_reward, 1.5)

    def _build_ema_pullback_candles(
        self,
        *,
        touch_open: float,
        touch_high: float,
        touch_low: float,
        touch_close: float,
        trigger_open: float,
        trigger_high: float,
        trigger_low: float,
        trigger_close: float,
    ) -> list[dict[str, float | str]]:
        candles: list[dict[str, float | str]] = []
        for index in range(38):
            candles.append(
                {
                    "timestamp": self.base_time.isoformat(),
                    "open": 101.0,
                    "high": 101.3,
                    "low": 100.9,
                    "close": 101.1,
                    "volume": 1000.0,
                }
            )
        candles.append(
            {
                "timestamp": self.base_time.isoformat(),
                "open": touch_open,
                "high": touch_high,
                "low": touch_low,
                "close": touch_close,
                "volume": 1000.0,
            }
        )
        candles.append(
            {
                "timestamp": self.base_time.isoformat(),
                "open": trigger_open,
                "high": trigger_high,
                "low": trigger_low,
                "close": trigger_close,
                "volume": 1000.0,
            }
        )
        return candles


if __name__ == "__main__":
    unittest.main()
