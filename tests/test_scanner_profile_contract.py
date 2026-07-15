from __future__ import annotations

import unittest

from app.engines import INTRADAY_PROFILE, SCALPING_PROFILE
from app.scanner import (
    INTRADAY_SETUP_INTERVAL,
    INTRADAY_TREND_INTERVAL,
    SCALPING_TRIGGER_INTERVAL,
    SHARED_5M_INTERVAL,
    _intraday_timeframes,
    _scalping_timeframes,
)


class ScannerProfileContractTests(unittest.TestCase):
    def test_scanner_intervals_derive_from_canonical_profiles(self) -> None:
        self.assertEqual(INTRADAY_TREND_INTERVAL, INTRADAY_PROFILE.trend_interval)
        self.assertEqual(INTRADAY_SETUP_INTERVAL, INTRADAY_PROFILE.setup_interval)
        self.assertEqual(SHARED_5M_INTERVAL, SCALPING_PROFILE.setup_interval)
        self.assertEqual(SCALPING_TRIGGER_INTERVAL, SCALPING_PROFILE.trigger_interval)
        self.assertEqual(SCALPING_PROFILE.setup_interval, INTRADAY_PROFILE.trigger_interval)

    def test_scanner_timeframe_metadata_uses_canonical_profiles(self) -> None:
        self.assertEqual(_scalping_timeframes(), SCALPING_PROFILE.timeframes())
        self.assertEqual(_intraday_timeframes(), INTRADAY_PROFILE.timeframes())


if __name__ == "__main__":
    unittest.main()
