from threading import Lock
from typing import Any

from app.exchange import BybitDemoClient
from app.strategy import evaluate_ema_pullback_strategy


DEFAULT_SCANNER_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "BNBUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "LINKUSDT",
]
SCANNER_SYMBOLS = DEFAULT_SCANNER_SYMBOLS
UNIVERSE_LIMIT = 20
BIAS_CANDLE_LIMIT = 250
TRIGGER_CANDLE_LIMIT = 50

_signals_lock = Lock()
_latest_signals: list[dict[str, Any]] = []
_latest_scan_results: list[dict[str, Any]] = []


def run_scan(client: BybitDemoClient) -> dict[str, Any]:
    universe = _resolve_scan_universe(client)
    signals: list[dict[str, Any]] = []
    scan_results: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for symbol in universe:
        ok_5m, candles_5m, error_5m = client.safe_fetch_recent_candles(symbol=symbol, interval="5", limit=BIAS_CANDLE_LIMIT)
        if not ok_5m:
            skipped.append({"symbol": symbol, "reason": error_5m or "Failed to fetch 5m candles"})
            continue

        ok_1m, candles_1m, error_1m = client.safe_fetch_recent_candles(symbol=symbol, interval="1", limit=TRIGGER_CANDLE_LIMIT)
        if not ok_1m:
            skipped.append({"symbol": symbol, "reason": error_1m or "Failed to fetch 1m candles"})
            continue

        signal = evaluate_ema_pullback_strategy(symbol=symbol, candles_5m=candles_5m, candles_1m=candles_1m)
        normalized = {
            "symbol": symbol,
            "direction": signal.get("direction"),
            "entry": signal.get("entry"),
            "stop_loss": signal.get("stop_loss"),
            "take_profit": signal.get("take_profit"),
            "risk_reward": signal.get("risk_reward"),
            "detected_at": signal.get("detected_at"),
            "status": signal.get("status"),
            "confidence_score": signal.get("confidence_score"),
            "rejection_reason": signal.get("rejection_reason"),
        }
        scan_results.append(normalized)
        if normalized.get("direction") and normalized.get("status") == "active":
            signals.append(normalized)

    with _signals_lock:
        _latest_signals.clear()
        _latest_signals.extend(signals)
        _latest_scan_results.clear()
        _latest_scan_results.extend(scan_results)

    return {
        "ok": True,
        "symbols_scanned": len(universe),
        "universe": universe,
        "signals_found": len(signals),
        "signals": list(signals),
        "results": list(scan_results),
        "skipped": skipped,
    }


def get_latest_signals() -> list[dict[str, Any]]:
    with _signals_lock:
        return list(_latest_scan_results or _latest_signals)


def get_active_signals() -> list[dict[str, Any]]:
    with _signals_lock:
        return [signal for signal in _latest_signals if signal.get("status") == "active"]


def _resolve_scan_universe(client: BybitDemoClient) -> list[str]:
    ok, tickers, _ = client.safe_fetch_market_tickers()
    if not ok or not tickers:
        return list(DEFAULT_SCANNER_SYMBOLS)

    normalized = [item for item in tickers if str(item.get("symbol", "")).upper().endswith("USDT")]
    top_liquid = sorted(normalized, key=lambda item: _to_float(item.get("turnover24h")), reverse=True)[:10]
    top_gainers = sorted(normalized, key=lambda item: _to_float(item.get("price24hPcnt")), reverse=True)[:10]

    universe: list[str] = []
    for item in [*top_liquid, *top_gainers]:
        symbol = str(item.get("symbol", "")).upper()
        if symbol and symbol not in universe:
            universe.append(symbol)

    if len(universe) < UNIVERSE_LIMIT:
        for symbol in DEFAULT_SCANNER_SYMBOLS:
            if symbol not in universe:
                universe.append(symbol)
            if len(universe) >= UNIVERSE_LIMIT:
                break

    return universe[:UNIVERSE_LIMIT]


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
