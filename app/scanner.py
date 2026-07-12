from threading import Lock
from typing import Any

from app.exchange import BybitDemoClient
from app.market_quality import MAX_SPREAD_BPS, validate_spread
from app.scanner_trend import (
    TREND_DOWN,
    TREND_INSUFFICIENT,
    TREND_SIDEWAYS,
    TREND_UP,
    analyze_trend,
    closed_candles,
    direction_allowed,
    score_market_candidate,
)
from app.strategy import evaluate_registered_strategies


SCANNER_SYMBOLS: list[str] = []
UNIVERSE_LIMIT = 50
TREND_CANDLE_LIMIT = 250
SETUP_CANDLE_LIMIT = 250
TRIGGER_CANDLE_LIMIT = 100

TREND_INTERVAL = "60"
SETUP_INTERVAL = "15"
TRIGGER_INTERVAL = "5"

# Liquidity and execution-quality thresholds for symbol selection.
MIN_TURNOVER_24H = 50_000_000.0
MIN_PRICE_MOVEMENT_RATIO = 0.005

_signals_lock = Lock()
_latest_signals: list[dict[str, Any]] = []
_latest_scan_results: list[dict[str, Any]] = []
_latest_ranked_markets: list[dict[str, Any]] = []
_latest_universe_metadata: dict[str, dict[str, Any]] = {}


def run_scan(client: BybitDemoClient) -> dict[str, Any]:
    universe = _resolve_scan_universe(client)
    signals: list[dict[str, Any]] = []
    scan_results: list[dict[str, Any]] = []
    ranked_markets: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    with _signals_lock:
        ticker_metadata = {symbol: dict(item) for symbol, item in _latest_universe_metadata.items()}

    for symbol in universe:
        ok_1h, candles_1h, error_1h = client.safe_fetch_recent_candles(
            symbol=symbol,
            interval=TREND_INTERVAL,
            limit=TREND_CANDLE_LIMIT,
        )
        if not ok_1h:
            skipped.append({"symbol": symbol, "reason": error_1h or "Failed to fetch 1h candles"})
            continue

        ok_15m, candles_15m, error_15m = client.safe_fetch_recent_candles(
            symbol=symbol,
            interval=SETUP_INTERVAL,
            limit=SETUP_CANDLE_LIMIT,
        )
        if not ok_15m:
            skipped.append({"symbol": symbol, "reason": error_15m or "Failed to fetch 15m candles"})
            continue

        ok_5m, candles_5m, error_5m = client.safe_fetch_recent_candles(
            symbol=symbol,
            interval=TRIGGER_INTERVAL,
            limit=TRIGGER_CANDLE_LIMIT,
        )
        if not ok_5m:
            skipped.append({"symbol": symbol, "reason": error_5m or "Failed to fetch 5m candles"})
            continue

        closed_1h = closed_candles(candles_1h, interval_minutes=60)
        closed_15m = closed_candles(candles_15m, interval_minutes=15)
        closed_5m = closed_candles(candles_5m, interval_minutes=5)
        trend = analyze_trend(closed_1h, interval_minutes=60)
        completeness = _data_completeness(closed_1h, closed_15m, closed_5m)
        ticker = ticker_metadata.get(symbol, {})
        market_ranking = score_market_candidate(
            ticker,
            trend_strength=float(trend.get("strength") or 0.0),
            data_completeness=completeness,
        )
        market_snapshot = {
            "symbol": symbol,
            "score": market_ranking["score"],
            "score_components": market_ranking["components"],
            "spread_bps": market_ranking["spread_bps"],
            "trend": trend,
            "data_completeness": round(completeness, 4),
        }
        ranked_markets.append(market_snapshot)

        strategy_results = evaluate_registered_strategies(
            symbol=symbol,
            candles_5m=closed_15m,
            candles_1m=closed_5m,
        )
        for result in strategy_results:
            normalized = _normalize_strategy_result(
                symbol=symbol,
                result=result,
                trend=trend,
                market_ranking=market_ranking,
            )
            scan_results.append(normalized)
            if normalized.get("direction") and normalized.get("status") == "active":
                signals.append(normalized)

    signals.sort(key=_signal_sort_key)
    scan_results.sort(key=_result_sort_key)
    ranked_markets.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("symbol") or "")))

    with _signals_lock:
        _latest_signals.clear()
        _latest_signals.extend(signals)
        _latest_scan_results.clear()
        _latest_scan_results.extend(scan_results)
        _latest_ranked_markets.clear()
        _latest_ranked_markets.extend(ranked_markets)

    return {
        "ok": True,
        "symbols_scanned": len(universe),
        "universe": universe,
        "signals_found": len(signals),
        "signals": list(signals),
        "results": list(scan_results),
        "ranked_markets": list(ranked_markets),
        "skipped": skipped,
        "max_spread_bps": MAX_SPREAD_BPS,
        "timeframes": {
            "trend": "1h",
            "setup": "15m",
            "trigger": "5m",
            "open_candle_confirmation": False,
        },
    }


def get_latest_signals() -> list[dict[str, Any]]:
    with _signals_lock:
        return list(_latest_scan_results or _latest_signals)


def get_active_signals() -> list[dict[str, Any]]:
    with _signals_lock:
        return [signal for signal in _latest_signals if signal.get("status") == "active"]


def get_ranked_markets() -> list[dict[str, Any]]:
    with _signals_lock:
        return list(_latest_ranked_markets)


def _normalize_strategy_result(
    *,
    symbol: str,
    result: dict[str, Any],
    trend: dict[str, Any],
    market_ranking: dict[str, Any],
) -> dict[str, Any]:
    original_status = result.get("status")
    direction = result.get("direction")
    normalized = {
        "symbol": symbol,
        "strategy_name": result.get("strategy_name") or result.get("strategy"),
        "strategy": result.get("strategy") or result.get("strategy_name"),
        "trade_type": result.get("trade_type") or "scalping",
        "direction": direction,
        "entry": result.get("entry"),
        "stop_loss": result.get("stop_loss"),
        "take_profit": result.get("take_profit"),
        "risk_reward": result.get("risk_reward"),
        "detected_at": result.get("detected_at"),
        "status": original_status,
        "confidence_score": result.get("confidence_score"),
        "rejection_reason": result.get("rejection_reason"),
        "trend_state": trend.get("state"),
        "trend_strength": trend.get("strength"),
        "trend_reason": trend.get("reason"),
        "trend_aligned": direction_allowed(str(trend.get("state") or ""), direction),
        "market_score": market_ranking.get("score"),
        "market_score_components": market_ranking.get("components"),
        "timeframes": {"trend": "1h", "setup": "15m", "trigger": "5m"},
    }

    if direction and original_status in {"active", "near_setup"} and not normalized["trend_aligned"]:
        normalized["original_status"] = original_status
        normalized["status"] = "blocked"
        normalized["rejection_reason"] = _trend_block_reason(str(trend.get("state") or ""), str(direction))

    return normalized


def _resolve_scan_universe(client: BybitDemoClient) -> list[str]:
    ok, tickers, _ = client.safe_fetch_market_tickers()
    if not ok or not tickers:
        with _signals_lock:
            SCANNER_SYMBOLS.clear()
            _latest_universe_metadata.clear()
        return []

    candidates: list[tuple[float, str, dict[str, Any], dict[str, Any]]] = []
    seen_symbols: set[str] = set()
    for item in tickers:
        symbol = str(item.get("symbol", "")).upper()
        if not symbol or symbol in seen_symbols or not symbol.endswith("USDT"):
            continue

        turnover = _to_float(item.get("turnover24h"))
        movement = _normalize_price_movement_ratio(item.get("price24hPcnt"))
        spread_gate = validate_spread(item)
        if not spread_gate.get("allowed"):
            continue
        if turnover < MIN_TURNOVER_24H:
            continue
        if movement < MIN_PRICE_MOVEMENT_RATIO:
            continue

        seen_symbols.add(symbol)
        ranking = score_market_candidate(item)
        candidates.append((float(ranking["score"]), symbol, item, ranking))

    candidates.sort(key=lambda row: (-row[0], row[1]))
    selected = candidates[:UNIVERSE_LIMIT]
    universe = [symbol for _, symbol, _, _ in selected]
    metadata = {
        symbol: {
            **item,
            "_universe_score": ranking["score"],
            "_universe_score_components": ranking["components"],
        }
        for _, symbol, item, ranking in selected
    }

    with _signals_lock:
        SCANNER_SYMBOLS.clear()
        SCANNER_SYMBOLS.extend(universe)
        _latest_universe_metadata.clear()
        _latest_universe_metadata.update(metadata)

    return universe


def _data_completeness(
    candles_1h: list[dict[str, Any]],
    candles_15m: list[dict[str, Any]],
    candles_5m: list[dict[str, Any]],
) -> float:
    ratios = (
        min(len(candles_1h) / 55.0, 1.0),
        min(len(candles_15m) / 214.0, 1.0),
        min(len(candles_5m) / 40.0, 1.0),
    )
    return sum(ratios) / len(ratios)


def _trend_block_reason(trend_state: str, direction: str) -> str:
    if trend_state == TREND_SIDEWAYS:
        return "trend_sideways"
    if trend_state == TREND_INSUFFICIENT:
        return "trend_insufficient_data"
    if trend_state == TREND_UP and direction.lower() != "long":
        return "trend_conflict_uptrend_long_only"
    if trend_state == TREND_DOWN and direction.lower() != "short":
        return "trend_conflict_downtrend_short_only"
    return "trend_not_aligned"


def _signal_sort_key(item: dict[str, Any]) -> tuple[float, float, str, str]:
    return (
        -float(item.get("market_score") or 0.0),
        -float(item.get("confidence_score") or 0.0),
        str(item.get("symbol") or ""),
        str(item.get("strategy_name") or ""),
    )


def _result_sort_key(item: dict[str, Any]) -> tuple[int, float, float, str, str]:
    priority = {"active": 0, "near_setup": 1, "blocked": 2, "rejected": 3, "expired": 4}
    return (
        priority.get(str(item.get("status") or ""), 9),
        -float(item.get("market_score") or 0.0),
        -float(item.get("confidence_score") or 0.0),
        str(item.get("symbol") or ""),
        str(item.get("strategy_name") or ""),
    )


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
