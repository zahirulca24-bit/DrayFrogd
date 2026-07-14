from __future__ import annotations

import unittest

from app.scanner import _intraday_timeframes, _scalping_timeframes


class ProfileTimeframeContractTests(unittest.TestCase):
    def test_scalping_uses_15m_trend_5m_setup_and_1m_trigger(self) -> None:
        self.assertEqual(
            _scalping_timeframes(),
            {
                "trend": "15m",
                "setup": "5m",
                "trigger": "1m",
                "open_candle_confirmation": False,
            },
        )

    def test_intraday_timeframes_remain_unchanged(self) -> None:
        self.assertEqual(
            _intraday_timeframes(),
            {
                "trend": "1h",
                "setup": "15m",
                "trigger": "5m",
                "open_candle_confirmation": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
