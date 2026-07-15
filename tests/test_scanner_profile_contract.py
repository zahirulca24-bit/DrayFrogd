from __future__ import annotations

import unittest

from app.config import settings
from app.engines import INTRADAY_PROFILE, SCALPING_PROFILE
from app.scanner import (
    INTRADAY_SETUP_CANDLE_LIMIT,
    INTRADAY_SETUP_INTERVAL,
    INTRADAY_TREND_CANDLE_LIMIT,
    INTRADAY_TREND_INTERVAL,
    SCALPING_SETUP_CANDLE_LIMIT,
    SCALPING_TRIGGER_CANDLE_LIMIT,
    SCALPING_TRIGGER_INTERVAL,
    SHARED_5M_INTERVAL,
    UNIVERSE_LIMIT,
    _intraday_timeframes,
    _scalping_timeframes,
)
from app.scanner_logic import MIN_TRIGGER_CANDLES, STRUCTURE_SCAN_WINDOW
from app.scanner_trend import MIN_TREND_CANDLES


class ScannerProfileContractTests(unittest.TestCase):
    """Protect canonical profile wiring and production-safe scanner limits."""

    def test_scanner_intervals_derive_from_canonical_profiles(self) -> None:
        self.assertEqual(INTRADAY_TREND_INTERVAL, INTRADAY_PROFILE.trend_interval)
        self.assertEqual(INTRADAY_SETUP_INTERVAL, INTRADAY_PROFILE.setup_interval)
        self.assertEqual(SHARED_5M_INTERVAL, SCALPING_PROFILE.setup_interval)
        self.assertEqual(SCALPING_TRIGGER_INTERVAL, SCALPING_PROFILE.trigger_interval)
        self.assertEqual(SCALPING_PROFILE.setup_interval, INTRADAY_PROFILE.trigger_interval)

    def test_scanner_timeframe_metadata_uses_canonical_profiles(self) -> None:
        self.assertEqual(_scalping_timeframes(), SCALPING_PROFILE.timeframes())
        self.assertEqual(_intraday_timeframes(), INTRADAY_PROFILE.timeframes())

    def test_scanner_preserves_memory_safe_config_limits(self) -> None:
        self.assertEqual(UNIVERSE_LIMIT, max(1, settings.scanner_universe_limit))
        self.assertEqual(
            INTRADAY_TREND_CANDLE_LIMIT,
            max(MIN_TREND_CANDLES, settings.intraday_trend_candle_limit),
        )
        self.assertEqual(
            INTRADAY_SETUP_CANDLE_LIMIT,
            max(STRUCTURE_SCAN_WINDOW, settings.intraday_setup_candle_limit),
        )
        self.assertEqual(
            SCALPING_SETUP_CANDLE_LIMIT,
            max(STRUCTURE_SCAN_WINDOW, settings.scalping_setup_candle_limit),
        )
        self.assertEqual(
            SCALPING_TRIGGER_CANDLE_LIMIT,
            max(MIN_TRIGGER_CANDLES, settings.scalping_trigger_candle_limit),
        )


if __name__ == "__main__":
    unittest.main()
