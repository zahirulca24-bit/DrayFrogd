from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from app.scanner import (
    INTRADAY_SETUP_CANDLE_LIMIT,
    MIN_STRATEGY_SETUP_CANDLES,
    SCALPING_SETUP_CANDLE_LIMIT,
)
from app.strategy import EMA_BIAS_PERIOD, RSI_PERIOD, evaluate_ema_pullback_strategy


def candles(count: int, *, minutes: int) -> list[dict]:
    start = datetime(2026, 7, 17, 0, 0, tzinfo=UTC)
    payload: list[dict] = []
    for index in range(count):
        price = 100.0 + (index * 0.05)
        payload.append(
            {
                "timestamp": (start + timedelta(minutes=index * minutes)).isoformat(),
                "open": price - 0.02,
                "high": price + 0.08,
                "low": price - 0.08,
                "close": price,
                "volume": 1000.0 + index,
            }
        )
    return payload


class ScannerDataContractTests(unittest.TestCase):
    def test_production_setup_limits_cover_ema200_and_rsi_warmup_after_open_candle_drop(self) -> None:
        required_closed = EMA_BIAS_PERIOD + RSI_PERIOD
        self.assertEqual(MIN_STRATEGY_SETUP_CANDLES, required_closed + 1)
        self.assertGreaterEqual(SCALPING_SETUP_CANDLE_LIMIT, required_closed + 1)
        self.assertGreaterEqual(INTRADAY_SETUP_CANDLE_LIMIT, required_closed + 1)

    def test_strategy_receiving_required_closed_candles_does_not_report_missing_data(self) -> None:
        result = evaluate_ema_pullback_strategy(
            "BTCUSDT",
            candles(EMA_BIAS_PERIOD + RSI_PERIOD, minutes=5),
            candles(60, minutes=1),
            now=datetime(2026, 7, 17, 4, 0, tzinfo=UTC),
        )
        self.assertNotEqual(result.get("rejection_reason"), "missing_data")


if __name__ == "__main__":
    unittest.main()
