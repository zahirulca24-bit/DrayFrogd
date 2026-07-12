from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import app.scanner as scanner
from app.scanner import SCANNER_SYMBOLS, _resolve_scan_universe, run_scan
from app.scanner_trend import TREND_UP


class FakeScannerClient:
    def __init__(self, *, tickers: list[dict] | None = None, market_ok: bool = True) -> None:
        self.tickers = tickers if tickers is not None else [self._ticker("BTCUSDT", 900_000_000)]
        self.market_ok = market_ok
        self.calls: list[tuple[str, str, int]] = []
        self.base_time = datetime(2026, 1, 1, tzinfo=UTC)

    def safe_fetch_market_tickers(self):
        if not self.market_ok:
            return False, [], "offline"
        return True, list(self.tickers), None

    def safe_fetch_recent_candles(self, symbol: str, interval: str, limit: int):
        self.calls.append((symbol, interval, limit))
        minutes = {"60": 60, "15": 15, "5": 5}[interval]
        candles = []
        for index in range(limit):
            close = 100.0 + (index * 0.2)
            timestamp = self.base_time + timedelta(minutes=minutes * index)
            candles.append(
                {
                    "timestamp": timestamp.isoformat(),
                    "open": close - 0.1,
                    "high": close + 0.3,
                    "low": close - 0.3,
                    "close": close,
                    "volume": 1000.0,
                }
            )
        return True, candles, None

    @staticmethod
    def _ticker(symbol: str, turnover: float, *, movement: float = 0.03, spread: float = 0.1) -> dict:
        return {
            "symbol": symbol,
            "turnover24h": str(turnover),
            "volume24h": str(turnover / 10),
            "price24hPcnt": str(movement),
            "bid1Price": str(100.0 - spread),
            "ask1Price": str(100.0 + spread),
        }


class ScannerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        SCANNER_SYMBOLS.clear()
        with scanner._signals_lock:
            scanner._latest_universe_metadata.clear()
            scanner._latest_ranked_markets.clear()
            scanner._latest_signals.clear()
            scanner._latest_scan_results.clear()

    def test_scanner_uses_1h_15m_and_5m_only(self) -> None:
        client = FakeScannerClient()
        with patch(
            "app.scanner.evaluate_registered_strategies",
            return_value=[self._signal("long")],
        ):
            result = run_scan(client)

        self.assertTrue(result["ok"])
        self.assertEqual([call[1] for call in client.calls], ["60", "15", "5"])
        self.assertEqual(result["timeframes"]["trend"], "1h")
        self.assertEqual(result["timeframes"]["setup"], "15m")
        self.assertEqual(result["timeframes"]["trigger"], "5m")

    def test_uptrend_allows_long_signal(self) -> None:
        client = FakeScannerClient()
        with patch(
            "app.scanner.evaluate_registered_strategies",
            return_value=[self._signal("long")],
        ), patch(
            "app.scanner.analyze_trend",
            return_value={"state": TREND_UP, "strength": 90.0, "reason": "test"},
        ):
            result = run_scan(client)

        self.assertEqual(result["signals_found"], 1)
        self.assertEqual(result["signals"][0]["status"], "active")
        self.assertTrue(result["signals"][0]["trend_aligned"])

    def test_uptrend_blocks_short_signal(self) -> None:
        client = FakeScannerClient()
        with patch(
            "app.scanner.evaluate_registered_strategies",
            return_value=[self._signal("short")],
        ), patch(
            "app.scanner.analyze_trend",
            return_value={"state": TREND_UP, "strength": 90.0, "reason": "test"},
        ):
            result = run_scan(client)

        self.assertEqual(result["signals_found"], 0)
        self.assertEqual(result["results"][0]["status"], "blocked")
        self.assertEqual(result["results"][0]["rejection_reason"], "trend_conflict_uptrend_long_only")

    def test_universe_is_dynamic_ranked_and_capped_at_fifty(self) -> None:
        tickers = [
            FakeScannerClient._ticker(f"COIN{index}USDT", 60_000_000 + (index * 10_000_000))
            for index in range(55)
        ]
        tickers.extend(
            [
                FakeScannerClient._ticker("LOWTURNUSDT", 1_000_000),
                FakeScannerClient._ticker("LOWMOVEUSDT", 100_000_000, movement=0.001),
                FakeScannerClient._ticker("NOTUSDC", 500_000_000),
            ]
        )
        universe = _resolve_scan_universe(FakeScannerClient(tickers=tickers))

        self.assertEqual(len(universe), 50)
        self.assertEqual(universe, list(SCANNER_SYMBOLS))
        self.assertNotIn("LOWTURNUSDT", universe)
        self.assertNotIn("LOWMOVEUSDT", universe)
        self.assertNotIn("NOTUSDC", universe)
        self.assertEqual(universe[0], "COIN54USDT")

    def test_market_ticker_failure_does_not_use_hardcoded_fallback(self) -> None:
        universe = _resolve_scan_universe(FakeScannerClient(market_ok=False))
        self.assertEqual(universe, [])
        self.assertEqual(SCANNER_SYMBOLS, [])

    @staticmethod
    def _signal(direction: str) -> dict:
        return {
            "strategy_name": "ema_pullback",
            "strategy": "ema_pullback",
            "direction": direction,
            "entry": 100.0,
            "stop_loss": 99.0 if direction == "long" else 101.0,
            "take_profit": 101.5 if direction == "long" else 98.5,
            "risk_reward": 1.5,
            "detected_at": "2026-01-01T00:00:00+00:00",
            "status": "active",
            "confidence_score": 80,
            "rejection_reason": None,
        }


if __name__ == "__main__":
    unittest.main()
