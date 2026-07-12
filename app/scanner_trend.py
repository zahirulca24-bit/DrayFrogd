from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

TREND_UP = "UPTREND"
TREND_DOWN = "DOWNTREND"
TREND_SIDEWAYS = "SIDEWAYS"
TREND_INSUFFICIENT = "INSUFFICIENT_DATA"

FAST_EMA_PERIOD = 20
SLOW_EMA_PERIOD = 50
MIN_TREND_CANDLES = SLOW_EMA_PERIOD + 5
STRUCTURE_LOOKBACK = 12
SLOPE_LOOKBACK = 5


def analyze_trend(
    candles: list[dict[str, Any]],
    *,
    interval_minutes: int = 60,
    now: datetime | None = None,
) -> dict[str, Any]:
    closed = closed_candles(candles, interval_minutes=interval_minutes, now=now)
    closes = [_number(item.get("close")) for item in closed]
    highs = [_number(item.get("high")) for item in closed]
    lows = [_number(item.get("low")) for item in closed]

    if len(closes) < MIN_TREND_CANDLES or any(value is None for value in closes[-MIN_TREND_CANDLES:]):
        return _trend_result(TREND_INSUFFICIENT, 0.0, len(closed), None, None, None, "not_enough_closed_candles")

    clean_closes = [float(value) for value in closes if value is not None]
    fast = _ema_series(clean_closes, FAST_EMA_PERIOD)
    slow = _ema_series(clean_closes, SLOW_EMA_PERIOD)
    if len(fast) <= SLOPE_LOOKBACK or len(slow) <= SLOPE_LOOKBACK:
        return _trend_result(TREND_INSUFFICIENT, 0.0, len(closed), None, None, None, "ema_unavailable")

    latest_close = clean_closes[-1]
    fast_now = fast[-1]
    slow_now = slow[-1]
    fast_slope = _ratio_change(fast[-1 - SLOPE_LOOKBACK], fast_now)
    slow_slope = _ratio_change(slow[-1 - SLOPE_LOOKBACK], slow_now)

    recent_highs = [float(value) for value in highs[-STRUCTURE_LOOKBACK:] if value is not None]
    recent_lows = [float(value) for value in lows[-STRUCTURE_LOOKBACK:] if value is not None]
    midpoint = max(2, len(recent_highs) // 2)
    prior_high = max(recent_highs[:midpoint], default=latest_close)
    recent_high = max(recent_highs[midpoint:], default=latest_close)
    prior_low = min(recent_lows[:midpoint], default=latest_close)
    recent_low = min(recent_lows[midpoint:], default=latest_close)

    bullish_checks = [
        latest_close > fast_now > slow_now,
        fast_slope > 0,
        slow_slope > 0,
        recent_high > prior_high,
        recent_low > prior_low,
    ]
    bearish_checks = [
        latest_close < fast_now < slow_now,
        fast_slope < 0,
        slow_slope < 0,
        recent_high < prior_high,
        recent_low < prior_low,
    ]
    bullish_score = sum(bullish_checks)
    bearish_score = sum(bearish_checks)
    separation = abs(fast_now - slow_now) / max(abs(latest_close), 1e-12)
    slope_strength = min(abs(fast_slope) + abs(slow_slope), 0.04) / 0.04
    strength = min(
        100.0,
        max(bullish_score, bearish_score) * 16.0
        + min(separation / 0.01, 1.0) * 12.0
        + slope_strength * 8.0,
    )

    if bullish_score >= 4 and bullish_score > bearish_score:
        state = TREND_UP
        reason = "bullish_ema_slope_and_structure"
    elif bearish_score >= 4 and bearish_score > bullish_score:
        state = TREND_DOWN
        reason = "bearish_ema_slope_and_structure"
    else:
        state = TREND_SIDEWAYS
        reason = "trend_confirmation_not_strong_enough"

    return _trend_result(
        state,
        round(strength, 2),
        len(closed),
        round(fast_now, 8),
        round(slow_now, 8),
        round(latest_close, 8),
        reason,
    )


def direction_allowed(trend_state: str, direction: str | None) -> bool:
    normalized = str(direction or "").strip().lower()
    if trend_state == TREND_UP:
        return normalized == "long"
    if trend_state == TREND_DOWN:
        return normalized == "short"
    return False


def closed_candles(
    candles: list[dict[str, Any]],
    *,
    interval_minutes: int,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    reference = _normalize_now(now)
    result: list[dict[str, Any]] = []
    for candle in candles:
        if candle.get("confirm") is False:
            continue
        timestamp = _timestamp(candle.get("timestamp"))
        if timestamp is not None and timestamp + timedelta(minutes=max(1, interval_minutes)) > reference:
            continue
        result.append(candle)
    return result


def score_market_candidate(
    ticker: dict[str, Any],
    *,
    trend_strength: float = 0.0,
    data_completeness: float = 0.0,
) -> dict[str, Any]:
    turnover = max(_number(ticker.get("turnover24h")) or 0.0, 0.0)
    volume = max(_number(ticker.get("volume24h")) or 0.0, 0.0)
    movement = abs(_number(ticker.get("price24hPcnt")) or 0.0)
    if movement > 1:
        movement /= 100.0

    bid = _number(ticker.get("bid1Price"))
    ask = _number(ticker.get("ask1Price"))
    spread_bps = None
    spread_quality = 0.0
    if bid is not None and ask is not None and bid > 0 and ask >= bid:
        midpoint = (bid + ask) / 2.0
        spread_bps = ((ask - bid) / midpoint) * 10_000.0 if midpoint > 0 else None
        if spread_bps is not None:
            spread_quality = max(0.0, min(1.0, 1.0 - (spread_bps / 50.0)))

    turnover_score = min(turnover / 500_000_000.0, 1.0) * 30.0
    volume_score = min(volume / 100_000_000.0, 1.0) * 15.0
    spread_score = spread_quality * 20.0
    momentum_score = min(movement / 0.05, 1.0) * 10.0
    volatility_score = _tradable_volatility_score(movement) * 10.0
    trend_score = max(0.0, min(float(trend_strength), 100.0)) / 100.0 * 10.0
    completeness_score = max(0.0, min(float(data_completeness), 1.0)) * 5.0

    components = {
        "turnover": round(turnover_score, 2),
        "volume": round(volume_score, 2),
        "spread": round(spread_score, 2),
        "momentum": round(momentum_score, 2),
        "volatility": round(volatility_score, 2),
        "trend": round(trend_score, 2),
        "data_completeness": round(completeness_score, 2),
    }
    total = round(min(100.0, sum(components.values())), 2)
    return {
        "score": total,
        "components": components,
        "spread_bps": round(spread_bps, 4) if spread_bps is not None else None,
    }


def _tradable_volatility_score(movement: float) -> float:
    if movement < 0.005:
        return 0.0
    if movement <= 0.08:
        return min(1.0, movement / 0.04)
    if movement >= 0.20:
        return 0.0
    return max(0.0, 1.0 - ((movement - 0.08) / 0.12))


def _trend_result(
    state: str,
    strength: float,
    candle_count: int,
    ema_fast: float | None,
    ema_slow: float | None,
    latest_close: float | None,
    reason: str,
) -> dict[str, Any]:
    return {
        "state": state,
        "strength": strength,
        "candle_count": candle_count,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "latest_close": latest_close,
        "reason": reason,
    }


def _ema_series(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    multiplier = 2.0 / (period + 1.0)
    ema = sum(values[:period]) / period
    result = [ema] * period
    for value in values[period:]:
        ema = ((value - ema) * multiplier) + ema
        result.append(ema)
    return result


def _ratio_change(previous: float, current: float) -> float:
    if previous == 0:
        return 0.0
    return (current - previous) / abs(previous)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _timestamp(value: Any) -> datetime | None:
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
