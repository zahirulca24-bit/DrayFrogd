from __future__ import annotations

import unittest

from app.market_quality import MAX_SPREAD_BPS, calculate_spread_bps, validate_spread


class MarketQualityTests(unittest.TestCase):
    def test_calculates_bid_ask_spread_in_bps(self) -> None:
        spread = calculate_spread_bps({"bid1Price": "99.9", "ask1Price": "100.1"})
        self.assertIsNotNone(spread)
        self.assertAlmostEqual(spread or 0.0, 20.0, places=6)

    def test_rejects_spread_above_existing_fifty_bps_limit(self) -> None:
        result = validate_spread({"bid1Price": "99.7", "ask1Price": "100.3"})
        self.assertFalse(result["allowed"])
        self.assertGreater(result["spread_bps"], MAX_SPREAD_BPS)

    def test_rejects_when_spread_cannot_be_verified(self) -> None:
        result = validate_spread({"lastPrice": "100"})
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "SPREAD_UNAVAILABLE")

    def test_allows_spread_at_or_below_limit(self) -> None:
        result = validate_spread({"bid1Price": "99.8", "ask1Price": "100.2"})
        self.assertTrue(result["allowed"])
        self.assertLessEqual(result["spread_bps"], MAX_SPREAD_BPS)


if __name__ == "__main__":
    unittest.main()
