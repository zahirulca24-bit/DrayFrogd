from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from app.scanner_trend import (
    TREND_DOWN,
    TREND_INSUFFICIENT,
    TREND_SIDEWAYS,
    TREND_UP,
    analyze_trend,
    closed_candles,
    direction_allowed,
    score_market_candidate,
)


class ScannerTrendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_time = datetime(2026, 1, 1, tzinfo=UTC)
        self.now = self.base_time + timedelta(hours=100)

    def test_detects_uptrend_from_ema_slope_and_structure(self) -> None:
        result = analyze_trend(self._series(direction=1), now=self.now)
        self.assertEqual(result["state"], TREND_UP)
        self.assertGreater(result["strength"], 0)

    def test_detects_downtrend_from_ema_slope_and_structure(self) -> None:
        result = analyze_trend(self._series(direction=-1), now=self.now)
        self.assertEqual(result["state"], TREND_DOWN)
        self.assertGreater(result["strength"], 0)

    def test_detects_sideways_when_confirmation_is_weak(self) -> None:
        result = analyze_trend(self._series(direction=0), now=self.now)
        self.assertEqual(result["state"], TREND_SIDEWAYS)

    def test_returns_insufficient_data_below_minimum(self) -> None:
        result = analyze_trend(self._series(direction=1, count=20), now=self.now)
        self.assertEqual(result["state"], TREND_INSUFFICIENT)

    def test_excludes_currently_open_and_unconfirmed_candles(self) -> None:
        candles = self._series(direction=1, count=60)
        candles.append(self._candle(self.now - timedelta(minutes=30), 200.0))
        candles.append({**self._candle(self.base_time, 201.0), "confirm": False})
        closed = closed_candles(candles, interval_minutes=60, now=self.now)
        self.assertEqual(len(closed), 60)

    def test_direction_guard_allows_only_trend_aligned_side(self) -> None:
        self.assertTrue(direction_allowed(TREND_UP, "long"))
        self.assertFalse(direction_allowed(TREND_UP, "short"))
        self.assertTrue(direction_allowed(TREND_DOWN, "short"))
        self.assertFalse(direction_allowed(TREND_SIDEWAYS, "long"))
        self.assertFalse(direction_allowed(TREND_INSUFFICIENT, "short"))

    def test_market_score_is_deterministic_and_bounded(self) -> None:
        ticker = {
            "symbol": "BTCUSDT",
            "turnover24h": "800000000",
            "volume24h": "120000000",
            "price24hPcnt": "0.04",
            "bid1Price": "99.9",
            "ask1Price": "100.1",
        }
        first = score_market_candidate(ticker, trend_strength=80, data_completeness=1)
        second = score_market_candidate(ticker, trend_strength=80, data_completeness=1)
        self.assertEqual(first, second)
        self.assertGreaterEqual(first["score"], 0)
        self.assertLessEqual(first["score"], 100)

    def _series(self, *, direction: int, count: int = 80) -> list[dict[str, float | str]]:
        candles: list[dict[str, float | str]] = []
        for index in range(count):
            close = 100.0 + (direction * index * 0.5)
            candles.append(self._candle(self.base_time + timedelta(hours=index), close))
        return candles

    @staticmethod
    def _candle(timestamp: datetime, close: float) -> dict[str, float | str]:
        return {
            "timestamp": timestamp.isoformat(),
            "open": close - 0.1,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": 1000.0,
        }


if __name__ == "__main__":
    unittest.main()
