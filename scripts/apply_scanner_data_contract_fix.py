from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected repair anchor not found in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "app/scanner.py",
        "from app.signal_pipeline import evaluate_signal_contexts, normalize_strategy_result\n",
        "from app.signal_pipeline import evaluate_signal_contexts, normalize_strategy_result\nfrom app.strategy import EMA_BIAS_PERIOD, RSI_PERIOD\n",
    )
    replace_once(
        "app/scanner.py",
        """INTRADAY_TREND_CANDLE_LIMIT = max(MIN_TREND_CANDLES, settings.intraday_trend_candle_limit)\nINTRADAY_SETUP_CANDLE_LIMIT = max(STRUCTURE_SCAN_WINDOW, settings.intraday_setup_candle_limit)\nSCALPING_SETUP_CANDLE_LIMIT = max(STRUCTURE_SCAN_WINDOW, settings.scalping_setup_candle_limit)\nSCALPING_TRIGGER_CANDLE_LIMIT = max(MIN_TRIGGER_CANDLES, settings.scalping_trigger_candle_limit)\n""",
        """MIN_STRATEGY_SETUP_CANDLES = EMA_BIAS_PERIOD + RSI_PERIOD + 1\n\nINTRADAY_TREND_CANDLE_LIMIT = max(MIN_TREND_CANDLES, settings.intraday_trend_candle_limit)\nINTRADAY_SETUP_CANDLE_LIMIT = max(\n    STRUCTURE_SCAN_WINDOW,\n    MIN_STRATEGY_SETUP_CANDLES,\n    settings.intraday_setup_candle_limit,\n)\nSCALPING_SETUP_CANDLE_LIMIT = max(\n    STRUCTURE_SCAN_WINDOW,\n    MIN_STRATEGY_SETUP_CANDLES,\n    settings.scalping_setup_candle_limit,\n)\nSCALPING_TRIGGER_CANDLE_LIMIT = max(MIN_TRIGGER_CANDLES, settings.scalping_trigger_candle_limit)\n""",
    )

    replace_once(
        "frontend/src/signalTruth.ts",
        """  return {\n    symbolsScanned: scan ? finiteInteger(scan.symbols_scanned) : null,\n    symbolsRepresented: new Set(results.map((signal) => signal.symbol)).size,\n""",
        """  const representedSymbols = new Set(results.map((signal) => signal.symbol)).size;\n\n  return {\n    symbolsScanned: scan ? finiteInteger(scan.symbols_scanned) : representedSymbols || null,\n    symbolsRepresented: representedSymbols,\n""",
    )

    Path("tests/test_scanner_data_contract.py").write_text(
        '''from __future__ import annotations\n\nimport unittest\nfrom datetime import UTC, datetime, timedelta\n\nfrom app.scanner import (\n    INTRADAY_SETUP_CANDLE_LIMIT,\n    MIN_STRATEGY_SETUP_CANDLES,\n    SCALPING_SETUP_CANDLE_LIMIT,\n)\nfrom app.strategy import EMA_BIAS_PERIOD, RSI_PERIOD, evaluate_ema_pullback_strategy\n\n\ndef candles(count: int, *, minutes: int) -> list[dict]:\n    start = datetime(2026, 7, 17, 0, 0, tzinfo=UTC)\n    payload: list[dict] = []\n    for index in range(count):\n        price = 100.0 + (index * 0.05)\n        payload.append(\n            {\n                "timestamp": (start + timedelta(minutes=index * minutes)).isoformat(),\n                "open": price - 0.02,\n                "high": price + 0.08,\n                "low": price - 0.08,\n                "close": price,\n                "volume": 1000.0 + index,\n            }\n        )\n    return payload\n\n\nclass ScannerDataContractTests(unittest.TestCase):\n    def test_production_setup_limits_cover_ema200_and_rsi_warmup_after_open_candle_drop(self) -> None:\n        required_closed = EMA_BIAS_PERIOD + RSI_PERIOD\n        self.assertEqual(MIN_STRATEGY_SETUP_CANDLES, required_closed + 1)\n        self.assertGreaterEqual(SCALPING_SETUP_CANDLE_LIMIT, required_closed + 1)\n        self.assertGreaterEqual(INTRADAY_SETUP_CANDLE_LIMIT, required_closed + 1)\n\n    def test_strategy_receiving_required_closed_candles_does_not_report_missing_data(self) -> None:\n        result = evaluate_ema_pullback_strategy(\n            "BTCUSDT",\n            candles(EMA_BIAS_PERIOD + RSI_PERIOD, minutes=5),\n            candles(60, minutes=1),\n            now=datetime(2026, 7, 17, 4, 0, tzinfo=UTC),\n        )\n        self.assertNotEqual(result.get("rejection_reason"), "missing_data")\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
