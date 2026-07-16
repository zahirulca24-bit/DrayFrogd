from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

from app.config import settings
from app.engines import INTRADAY_PROFILE, SCALPING_PROFILE, build_engine_context
from app.exchange import BybitDemoClient
from app.market_quality import MAX_SPREAD_BPS, validate_spread
from app.scanner_logic import MIN_TRIGGER_CANDLES, STRUCTURE_SCAN_WINDOW, evaluate_multitimeframe_logic
from app.scanner_trend import (
    MIN_TREND_CANDLES,
    TREND_DOWN,
    TREND_INSUFFICIENT,
    TREND_SIDEWAYS,
    TREND_UP,
    analyze_trend,
    closed_candles,
    score_market_candidate,
)
from app.scalping_cooldown import sync_scalping_reentry_cooldowns
from app.signal_pipeline import evaluate_signal_contexts, normalize_strategy_result
from app.strategy import EMA_BIAS_PERIOD, RSI_PERIOD


SCANNER_SYMBOLS: list[str] = []
UNIVERSE_LIMIT = max(1, settings.scanner_universe_limit)

MIN_STRATEGY_SETUP_CANDLES = EMA_BIAS_PERIOD + RSI_PERIOD + 1

INTRADAY_TREND_CANDLE_LIMIT = max(MIN_TREND_CANDLES, settings.intraday_trend_candle_limit)
INTRADAY_SETUP_CANDLE_LIMIT = max(
    STRUCTURE_SCAN_WINDOW,
    MIN_STRATEGY_SETUP_CANDLES,
    settings.intraday_setup_candle_limit,
)
SCALPING_SETUP_CANDLE_LIMIT = max(
    STRUCTURE_SCAN_WINDOW,
    MIN_STRATEGY_SETUP_CANDLES,
    settings.scalping_setup_candle_limit,
)
SCALPING_TRIGGER_CANDLE_LIMIT = max(MIN_TRIGGER_CANDLES, settings.scalping_trigger_candle_limit)

INTRADAY_TREND_INTERVAL = INTRADAY_PROFILE.trend_interval
INTRADAY_SETUP_INTERVAL = INTRADAY_PROFILE.setup_interval
SHARED_5M_INTERVAL = SCALPING_PROFILE.setup_interval
SCALPING_TRIGGER_INTERVAL = SCALPING_PROFILE.trigger_interval

TREND_CANDLE_LIMIT = INTRADAY_TREND_CANDLE_LIMIT
SETUP_CANDLE_LIMIT = INTRADAY_SETUP_CANDLE_LIMIT
TRIGGER_CANDLE_LIMIT = SCALPING_SETUP_CANDLE_LIMIT
TREND_INTERVAL = INTRADAY_TREND_INTERVAL
SETUP_INTERVAL = INTRADAY_SETUP_INTERVAL
TRIGGER_INTERVAL = SHARED_5M_INTERVAL

STALE_INTERVAL_MULTIPLIER = 2
STALE_DATA = "STALE_DATA"
MIN_TURNOVER_24H = 50_000_000.0
MIN_PRICE_MOVEMENT_RATIO = 0.005

_signals_lock = Lock()
_latest_signals: list[dict[str, Any]] = []
_latest_scan_results: list[dict[str, Any]] = []
_latest_ranked_markets: list[dict[str, Any]] = []
_latest_universe_metadata: dict[str, dict[str, Any]] = {}
_normalize_strategy_result = normalize_strategy_result


def run_scan(client: BybitDemoClient, now: datetime | None = None) -> dict[str, Any]:
    reference = _normalize_now(now)
    universe = _resolve_scan_universe(client)
    ranked_markets: list[dict[str, Any]] = []
    rejected_markets: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    pending_contexts: dict[str, list[dict[str, Any]]] = {}

    with _signals_lock:
        ticker_metadata = {symbol: dict(item) for symbol, item in _latest_universe_metadata.items()}

    for symbol in universe:
        fetched = _fetch_profile_candles(client, symbol, skipped)
        closed_1h = closed_candles(fetched.get(INTRADAY_PROFILE.trend_label, []), interval_minutes=INTRADAY_PROFILE.trend_minutes, now=reference)
        closed_15m = closed_candles(fetched.get(INTRADAY_PROFILE.setup_label, []), interval_minutes=INTRADAY_PROFILE.setup_minutes, now=reference)
        closed_5m = closed_candles(fetched.get(SCALPING_PROFILE.setup_label, []), interval_minutes=SCALPING_PROFILE.setup_minutes, now=reference)
        closed_1m = closed_candles(fetched.get(SCALPING_PROFILE.trigger_label, []), interval_minutes=SCALPING_PROFILE.trigger_minutes, now=reference)

        scalping_trend = _profile_trend(closed_15m, interval_minutes=SCALPING_PROFILE.trend_minutes, now=reference)
        intraday_trend = _profile_trend(closed_1h, interval_minutes=INTRADAY_PROFILE.trend_minutes, now=reference)

        scalping_reason = _profile_rejection_reason(
            scalping_trend,
            setup_candles=closed_5m,
            setup_interval_minutes=SCALPING_PROFILE.setup_minutes,
            trigger_candles=closed_1m,
            trigger_interval_minutes=SCALPING_PROFILE.trigger_minutes,
            now=reference,
        )
        intraday_reason = _profile_rejection_reason(
            intraday_trend,
            setup_candles=closed_15m,
            setup_interval_minutes=INTRADAY_PROFILE.setup_minutes,
            trigger_candles=closed_5m,
            trigger_interval_minutes=INTRADAY_PROFILE.trigger_minutes,
            now=reference,
        )

        scalping_eligible = scalping_reason is None
        intraday_eligible = intraday_reason is None
        intraday_logic = (
            evaluate_multitimeframe_logic(symbol, closed_15m, closed_5m, trend_state=str(intraday_trend.get("state") or ""))
            if intraday_eligible
            else {
                "status": "blocked",
                "direction": None,
                "reason": intraday_reason,
                "confidence_score": 0,
                "setup_15m": {},
                "confirmation_5m": {},
            }
        )

        profile_metadata = {
            "scalping": {
                "eligible": scalping_eligible,
                "approved_direction": _approved_direction(scalping_trend),
                "rejection_reason": scalping_reason,
                "trend": scalping_trend,
                "timeframes": _scalping_timeframes(),
                "risk_contract": SCALPING_PROFILE.risk_contract(),
            },
            "intraday": {
                "eligible": intraday_eligible,
                "approved_direction": _approved_direction(intraday_trend),
                "rejection_reason": intraday_reason,
                "trend": intraday_trend,
                "scanner_logic": intraday_logic,
                "timeframes": _intraday_timeframes(),
                "risk_contract": INTRADAY_PROFILE.risk_contract(),
            },
        }

        if not scalping_eligible and not intraday_eligible:
            rejected_markets.append({"symbol": symbol, "profiles": profile_metadata, "reason": "no_eligible_trade_profile"})
            continue

        completeness = _data_completeness(closed_1h, closed_15m, closed_5m, closed_1m)
        ticker = ticker_metadata.get(symbol, {})
        strongest_trend = max(
            float(scalping_trend.get("strength") or 0.0) if scalping_eligible else 0.0,
            float(intraday_trend.get("strength") or 0.0) if intraday_eligible else 0.0,
        )
        market_ranking = score_market_candidate(ticker, trend_strength=strongest_trend, data_completeness=completeness)
        market_snapshot = {
            "symbol": symbol,
            "market_rank": None,
            "score": market_ranking["score"],
            "market_score": market_ranking["score"],
            "score_components": market_ranking["components"],
            "spread_bps": market_ranking["spread_bps"],
            "eligible_profiles": [profile for profile, eligible in (("scalping", scalping_eligible), ("intraday", intraday_eligible)) if eligible],
            "profiles": profile_metadata,
            "data_completeness": round(completeness, 4),
        }
        ranked_markets.append(market_snapshot)

        contexts: list[dict[str, Any]] = []
        if scalping_eligible:
            contexts.append(
                build_engine_context(
                    "scalping",
                    symbol=symbol,
                    trend=scalping_trend,
                    scanner_logic={
                        "status": "eligible",
                        "direction": _approved_direction(scalping_trend),
                        "reason": f"scalping_{SCALPING_PROFILE.trend_label}_trend_eligible",
                        "confidence_score": scalping_trend.get("strength"),
                    },
                    setup_candles=closed_5m,
                    trigger_candles=closed_1m,
                )
            )
        if intraday_eligible:
            contexts.append(
                build_engine_context(
                    "intraday",
                    symbol=symbol,
                    trend=intraday_trend,
                    scanner_logic=intraday_logic,
                    setup_candles=closed_15m,
                    trigger_candles=closed_5m,
                )
            )
        pending_contexts[symbol] = contexts

    ranked_markets.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("symbol") or "")))
    ranked_markets = ranked_markets[:UNIVERSE_LIMIT]

    strategy_contexts: list[dict[str, Any]] = []
    for market_rank, market in enumerate(ranked_markets, start=1):
        market["market_rank"] = market_rank
        symbol = str(market.get("symbol") or "")
        market_ranking = {
            "score": market.get("score"),
            "components": market.get("score_components"),
            "spread_bps": market.get("spread_bps"),
        }
        for context in pending_contexts.get(symbol, []):
            strategy_contexts.append({**context, "market_rank": market_rank, "market_ranking": market_ranking})

    pipeline = evaluate_signal_contexts(strategy_contexts)
    raw_signals = list(pipeline.get("signals") or [])
    raw_scan_results = list(pipeline.get("results") or [])
    suppression = sync_scalping_reentry_cooldowns(now=reference)
    suppressed_symbols = set(suppression.get("active_symbols") or [])
    signals, scan_results, suppressed_rows = _apply_scalping_suppression(
        raw_signals,
        raw_scan_results,
        suppressed_symbols=suppressed_symbols,
        fail_closed=not bool(suppression.get("ok", False)),
    )

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
        "ranked_symbols": len(ranked_markets),
        "signals_found": len(signals),
        "strategy_checks": len(scan_results),
        "signals": signals,
        "results": scan_results,
        "scalping_signal_suppression": {
            "ok": bool(suppression.get("ok", False)),
            "active_symbols": sorted(suppressed_symbols),
            "suppressed_rows": len(suppressed_rows),
            "error": suppression.get("error"),
        },
        "ranked_markets": ranked_markets,
        "rejected_markets": rejected_markets,
        "skipped": skipped,
        "max_spread_bps": MAX_SPREAD_BPS,
        "timeframes": {
            "scalping": _scalping_timeframes(),
            "intraday": _intraday_timeframes(),
            "open_candle_confirmation": False,
        },
    }


def _apply_scalping_suppression(
    signals: list[dict[str, Any]],
    scan_results: list[dict[str, Any]],
    *,
    suppressed_symbols: set[str],
    fail_closed: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    normalized_symbols = {str(symbol or "").upper().strip() for symbol in suppressed_symbols if str(symbol or "").strip()}

    def is_suppressed(item: dict[str, Any]) -> bool:
        if str(item.get("trade_type") or "").lower().strip() != "scalping":
            return False
        if fail_closed:
            return True
        return str(item.get("symbol") or "").upper().strip() in normalized_symbols

    suppressed_rows = [item for item in scan_results if is_suppressed(item)]
    visible_signals = [item for item in signals if not is_suppressed(item)]
    visible_results = [item for item in scan_results if not is_suppressed(item)]
    return visible_signals, visible_results, suppressed_rows


def get_latest_signals() -> list[dict[str, Any]]:
    with _signals_lock:
        return list(_latest_scan_results or _latest_signals)


def get_active_signals() -> list[dict[str, Any]]:
    with _signals_lock:
        return [signal for signal in _latest_signals if signal.get("status") == "active"]


def get_ranked_markets() -> list[dict[str, Any]]:
    with _signals_lock:
        return list(_latest_ranked_markets)


def _fetch_profile_candles(client: BybitDemoClient, symbol: str, skipped: list[dict[str, str]]) -> dict[str, list[dict[str, Any]]]:
    specs = (
        (INTRADAY_PROFILE.trend_label, INTRADAY_TREND_INTERVAL, INTRADAY_TREND_CANDLE_LIMIT),
        (INTRADAY_PROFILE.setup_label, INTRADAY_SETUP_INTERVAL, INTRADAY_SETUP_CANDLE_LIMIT),
        (SCALPING_PROFILE.setup_label, SHARED_5M_INTERVAL, SCALPING_SETUP_CANDLE_LIMIT),
        (SCALPING_PROFILE.trigger_label, SCALPING_TRIGGER_INTERVAL, SCALPING_TRIGGER_CANDLE_LIMIT),
    )
    fetched: dict[str, list[dict[str, Any]]] = {}
    for label, interval, limit in specs:
        ok, candles, error = client.safe_fetch_recent_candles(symbol=symbol, interval=interval, limit=limit)
        if ok:
            fetched[label] = list(candles or [])
        else:
            fetched[label] = []
            skipped.append({"symbol": symbol, "profile_data": label, "reason": error or f"Failed to fetch {label} candles"})
    return fetched


def _profile_trend(candles: list[dict[str, Any]], *, interval_minutes: int, now: datetime) -> dict[str, Any]:
    trend = analyze_trend(candles, interval_minutes=interval_minutes, now=now)
    if trend.get("state") in {TREND_UP, TREND_DOWN} and not _candles_are_fresh(candles, interval_minutes, now):
        return {**trend, "state": STALE_DATA, "strength": 0.0, "reason": f"stale_{interval_minutes}m_trend_candles"}
    return trend


def _profile_rejection_reason(
    trend: dict[str, Any],
    *,
    setup_candles: list[dict[str, Any]],
    setup_interval_minutes: int,
    trigger_candles: list[dict[str, Any]],
    trigger_interval_minutes: int,
    now: datetime,
) -> str | None:
    state = str(trend.get("state") or "")
    if state == TREND_SIDEWAYS:
        return "trend_sideways"
    if state == TREND_INSUFFICIENT:
        return "trend_insufficient_data"
    if state == STALE_DATA:
        return "trend_stale_data"
    if state not in {TREND_UP, TREND_DOWN}:
        return "trend_not_eligible"
    if not _candles_are_fresh(setup_candles, setup_interval_minutes, now):
        return "setup_data_missing_or_stale"
    if not _candles_are_fresh(trigger_candles, trigger_interval_minutes, now):
        return "trigger_data_missing_or_stale"
    return None


def _candles_are_fresh(candles: list[dict[str, Any]], interval_minutes: int, now: datetime) -> bool:
    if not candles:
        return False
    timestamp = _parse_timestamp(candles[-1].get("timestamp"))
    if timestamp is None:
        return False
    closed_at = timestamp + timedelta(minutes=max(1, interval_minutes))
    if closed_at > now:
        return False
    maximum_age = timedelta(minutes=max(1, interval_minutes) * STALE_INTERVAL_MULTIPLIER)
    return now - closed_at <= maximum_age


def _approved_direction(trend: dict[str, Any]) -> str | None:
    state = str(trend.get("state") or "")
    if state == TREND_UP:
        return "long"
    if state == TREND_DOWN:
        return "short"
    return None


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
        if not spread_gate.get("allowed") or turnover < MIN_TURNOVER_24H or movement < MIN_PRICE_MOVEMENT_RATIO:
            continue
        seen_symbols.add(symbol)
        ranking = score_market_candidate(item)
        candidates.append((float(ranking["score"]), symbol, item, ranking))

    candidates.sort(key=lambda row: (-row[0], row[1]))
    selected = candidates[:UNIVERSE_LIMIT]
    universe = [symbol for _, symbol, _, _ in selected]
    metadata = {
        symbol: {**item, "_universe_score": ranking["score"], "_universe_score_components": ranking["components"]}
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
    candles_1m: list[dict[str, Any]],
) -> float:
    ratios = (
        min(len(candles_1h) / max(1, INTRADAY_TREND_CANDLE_LIMIT), 1.0),
        min(len(candles_15m) / max(1, INTRADAY_SETUP_CANDLE_LIMIT), 1.0),
        min(len(candles_5m) / max(1, SCALPING_SETUP_CANDLE_LIMIT), 1.0),
        min(len(candles_1m) / max(1, SCALPING_TRIGGER_CANDLE_LIMIT), 1.0),
    )
    return sum(ratios) / len(ratios)


def _scalping_timeframes() -> dict[str, Any]:
    return SCALPING_PROFILE.timeframes()


def _intraday_timeframes() -> dict[str, Any]:
    return INTRADAY_PROFILE.timeframes()


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalize_now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        return current.replace(tzinfo=UTC)
    return current.astimezone(UTC)


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
