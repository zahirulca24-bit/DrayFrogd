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
    "AVAXUSDT",
    "DOTUSDT",
    "LTCUSDT",
    "BCHUSDT",
    "TRXUSDT",
    "TONUSDT",
    "HBARUSDT",
    "ATOMUSDT",
    "ARBUSDT",
    "OPUSDT",
    "APTUSDT",
    "SUIUSDT",
    "1000PEPEUSDT",
    "WIFUSDT",
    "NEARUSDT",
    "ETCUSDT",
    "FILUSDT",
    "INJUSDT",
    "RUNEUSDT",
    "AAVEUSDT",
    "MATICUSDT",
    "UNIUSDT",
]
SCANNER_SYMBOLS = DEFAULT_SCANNER_SYMBOLS
UNIVERSE_LIMIT = 30
BIAS_CANDLE_LIMIT = 250
TRIGGER_CANDLE_LIMIT = 50

# Liquidity thresholds for symbol selection.
MIN_TURNOVER_24H = 50_000_000.0
MIN_PRICE_MOVEMENT_RATIO = 0.005
MAX_SPREAD_BPS = 50

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
        return list(DEFAULT_SCANNER_SYMBOLS[:UNIVERSE_LIMIT])

    usdt_symbols = [item for item in tickers if str(item.get("symbol", "")).upper().endswith("USDT")]

    liquid_candidates: list[dict[str, Any]] = []
    seen_symbols: set[str] = set()
    for item in usdt_symbols:
        symbol = str(item.get("symbol", "")).upper()
        turnover = _to_float(item.get("turnover24h"))
        price_movement_ratio = _normalize_price_movement_ratio(item.get("price24hPcnt"))

        if not symbol or symbol in seen_symbols:
            continue
        if turnover < MIN_TURNOVER_24H:
            continue
        if price_movement_ratio < MIN_PRICE_MOVEMENT_RATIO:
            continue

        seen_symbols.add(symbol)
        liquid_candidates.append(item)

    top_liquid = sorted(liquid_candidates, key=_liquidity_score, reverse=True)[:UNIVERSE_LIMIT]

    universe: list[str] = []
    for item in top_liquid:
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


def _liquidity_score(item: dict[str, Any]) -> float:
    turnover = _to_float(item.get("turnover24h"))
    price_movement_ratio = _normalize_price_movement_ratio(item.get("price24hPcnt"))
    normalized_turnover = min(turnover / 10_000_000, 100)
    normalized_price_move = price_movement_ratio * 100
    return (normalized_turnover * 0.6) + (normalized_price_move * 0.4)


def _normalize_price_movement_ratio(value: Any) -> float:
    movement = abs(_to_float(value))
    if movement > 1:
        return movement / 100
    return movement


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
