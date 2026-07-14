from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import app.scanner as scanner
from app.scanner import SCANNER_SYMBOLS, _resolve_scan_universe, run_scan
from app.scanner_trend import TREND_SIDEWAYS, TREND_UP


class FakeScannerClient:
    def __init__(
        self,
        *,
        tickers: list[dict] | None = None,
        market_ok: bool = True,
        reference: datetime | None = None,
        stale: bool = False,
        failed_intervals: set[str] | None = None,
    ) -> None:
        self.tickers = tickers if tickers is not None else [self._ticker("BTCUSDT", 900_000_000)]
        self.market_ok = market_ok
        self.reference = reference or datetime(2026, 7, 12, 8, 0, tzinfo=UTC)
        self.stale = stale
        self.failed_intervals = failed_intervals or set()
        self.calls: list[tuple[str, str, int]] = []

    def safe_fetch_market_tickers(self):
        if not self.market_ok:
            return False, [], "offline"
        return True, list(self.tickers), None

    def safe_fetch_recent_candles(self, symbol: str, interval: str, limit: int):
        self.calls.append((symbol, interval, limit))
        if interval in self.failed_intervals:
            return False, [], f"{interval} unavailable"

        minutes = {"60": 60, "15": 15, "5": 5, "1": 1}[interval]
        last_open = self.reference - timedelta(minutes=minutes)
        if self.stale:
            last_open -= timedelta(days=2)
        first_open = last_open - timedelta(minutes=minutes * (limit - 1))

        candles = []
        for index in range(limit):
            close = 100.0 + (index * 0.2)
            timestamp = first_open + timedelta(minutes=minutes * index)
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
        suppression_patcher = patch(
            "app.scanner.sync_scalping_reentry_cooldowns",
            return_value={"ok": True, "active_symbols": [], "error": None},
        )
        suppression_patcher.start()
        self.addCleanup(suppression_patcher.stop)

    def test_scanner_fetches_separate_scalping_and_intraday_timeframes(self) -> None:
        client = FakeScannerClient()
        with patch(
            "app.scanner.analyze_trend",
            return_value={"state": TREND_UP, "strength": 90.0, "reason": "test"},
        ), patch(
            "app.signal_pipeline.evaluate_registered_strategies",
            return_value=[self._signal("long")],
        ):
            result = run_scan(client, now=client.reference)

        self.assertTrue(result["ok"])
        self.assertEqual([call[1] for call in client.calls], ["60", "15", "5", "1"])
        self.assertEqual(result["timeframes"]["scalping"]["setup"], "5m")
        self.assertEqual(result["timeframes"]["scalping"]["trigger"], "1m")
        self.assertEqual(result["timeframes"]["intraday"]["trend"], "1h")
        self.assertEqual(result["timeframes"]["intraday"]["setup"], "15m")
        self.assertEqual(result["timeframes"]["intraday"]["trigger"], "5m")

    def test_both_profiles_are_evaluated_but_only_one_primary_signal_is_kept_per_symbol(self) -> None:
        client = FakeScannerClient()
        with patch(
            "app.scanner.analyze_trend",
            return_value={"state": TREND_UP, "strength": 90.0, "reason": "test"},
        ), patch(
            "app.signal_pipeline.evaluate_registered_strategies",
            return_value=[self._signal("long")],
        ) as evaluator:
            result = run_scan(client, now=client.reference)

        self.assertEqual(evaluator.call_count, 2)
        self.assertEqual({item["trade_type"] for item in result["results"]}, {"scalping", "intraday"})
        self.assertEqual(result["signals_found"], 1)
        self.assertEqual(len(result["signals"]), 1)
        self.assertEqual(result["signals"][0]["symbol"], "BTCUSDT")
        self.assertTrue(result["signals"][0]["primary_signal"])
        self.assertEqual(result["signals"][0]["confirmation_count"], 0)
        intraday_result = next(item for item in result["results"] if item["trade_type"] == "intraday")
        self.assertEqual(intraday_result["signal_state"], "INVALID")
        self.assertEqual(intraday_result["rejection_reason"], "risk_reward_below_trade_type_minimum")

    def test_sideways_market_never_reaches_strategy_evaluation(self) -> None:
        client = FakeScannerClient()
        with patch(
            "app.scanner.analyze_trend",
            return_value={"state": TREND_SIDEWAYS, "strength": 10.0, "reason": "test"},
        ), patch("app.signal_pipeline.evaluate_registered_strategies") as evaluator:
            result = run_scan(client, now=client.reference)

        evaluator.assert_not_called()
        self.assertEqual(result["ranked_markets"], [])
        self.assertEqual(result["signals_found"], 0)
        self.assertEqual(result["rejected_markets"][0]["reason"], "no_eligible_trade_profile")

    def test_stale_market_never_reaches_strategy_evaluation(self) -> None:
        client = FakeScannerClient(stale=True)
        with patch(
            "app.scanner.analyze_trend",
            return_value={"state": TREND_UP, "strength": 90.0, "reason": "test"},
        ), patch("app.signal_pipeline.evaluate_registered_strategies") as evaluator:
            result = run_scan(client, now=client.reference)

        evaluator.assert_not_called()
        self.assertEqual(result["ranked_markets"], [])
        profiles = result["rejected_markets"][0]["profiles"]
        self.assertEqual(profiles["scalping"]["rejection_reason"], "trend_stale_data")
        self.assertEqual(profiles["intraday"]["rejection_reason"], "trend_stale_data")

    def test_missing_1m_data_blocks_only_scalping_pipeline(self) -> None:
        client = FakeScannerClient(failed_intervals={"1"})
        with patch(
            "app.scanner.analyze_trend",
            return_value={"state": TREND_UP, "strength": 90.0, "reason": "test"},
        ), patch(
            "app.signal_pipeline.evaluate_registered_strategies",
            return_value=[self._signal("long")],
        ) as evaluator:
            result = run_scan(client, now=client.reference)

        self.assertEqual(evaluator.call_count, 1)
        self.assertEqual(result["results"][0]["trade_type"], "intraday")
        self.assertEqual(result["ranked_markets"][0]["eligible_profiles"], ["intraday"])

    def test_market_rank_is_explicit_and_sequential(self) -> None:
        tickers = [
            FakeScannerClient._ticker("BTCUSDT", 900_000_000),
            FakeScannerClient._ticker("ETHUSDT", 800_000_000),
            FakeScannerClient._ticker("SOLUSDT", 700_000_000),
        ]
        client = FakeScannerClient(tickers=tickers)
        with patch(
            "app.scanner.analyze_trend",
            return_value={"state": TREND_UP, "strength": 90.0, "reason": "test"},
        ), patch("app.signal_pipeline.evaluate_registered_strategies", return_value=[]):
            result = run_scan(client, now=client.reference)

        self.assertEqual([item["market_rank"] for item in result["ranked_markets"]], [1, 2, 3])
        self.assertTrue(all(item["market_score"] is not None for item in result["ranked_markets"]))

    def test_universe_is_dynamic_ranked_and_capped_at_thirty(self) -> None:
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

        self.assertEqual(len(universe), 30)
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
            "detected_at": "2026-07-12T08:00:00+00:00",
            "status": "active",
            "confidence_score": 80,
            "rejection_reason": None,
        }


if __name__ == "__main__":
    unittest.main()
