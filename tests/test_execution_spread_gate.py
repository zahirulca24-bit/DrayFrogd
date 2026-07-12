from __future__ import annotations

import unittest

from app.execution import _execution_spread_gate


class MarketTickerClient:
    def __init__(self, ticker: dict) -> None:
        self.ticker = ticker

    def safe_fetch_market_tickers(self):
        return True, [self.ticker], None


class ExecutionSpreadGateTests(unittest.TestCase):
    def test_uses_existing_bybit_market_tickers_method(self) -> None:
        client = MarketTickerClient(
            {
                "symbol": "BTCUSDT",
                "bid1Price": "99.9",
                "ask1Price": "100.1",
            }
        )
        result = _execution_spread_gate(client, "BTCUSDT")
        self.assertTrue(result["allowed"])
        self.assertAlmostEqual(result["spread_bps"], 20.0, places=6)

    def test_rejects_high_spread_from_market_ticker_list(self) -> None:
        client = MarketTickerClient(
            {
                "symbol": "ALTUSDT",
                "bid1Price": "99.5",
                "ask1Price": "100.5",
            }
        )
        result = _execution_spread_gate(client, "ALTUSDT")
        self.assertFalse(result["allowed"])
        self.assertIn("exceeds maximum", result["reason"])

    def test_rejects_when_requested_symbol_is_missing(self) -> None:
        client = MarketTickerClient(
            {
                "symbol": "ETHUSDT",
                "bid1Price": "99.9",
                "ask1Price": "100.1",
            }
        )
        result = _execution_spread_gate(client, "BTCUSDT")
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "SPREAD_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
