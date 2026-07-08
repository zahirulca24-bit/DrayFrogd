from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any


EMA_BIAS_PERIOD = 200
EMA_PULLBACK_PERIOD = 20
RSI_PERIOD = 14
EXPIRY_CANDLES = 5
EXPIRY_MINUTES = 15
TRIGGER_WINDOW_CANDLES = 5
SWING_LOOKBACK = 5
STOP_BUFFER_RATIO = 0.001
TARGET_R_MULTIPLE = 2.0
EMA_PULLBACK_TOLERANCE_RATIO = 0.0015


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class StrategySignal:
    symbol: str
    direction: str | None
    entry: float | None
    stop_loss: float | None
    take_profit: float | None
    risk_reward: float | None
    detected_at: str | None
    status: str
    confidence_score: int | None = None
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_ema_pullback_strategy(
    symbol: str,
    candles_5m: list[dict[str, Any] | Candle],
    candles_1m: list[dict[str, Any] | Candle],
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_5m = _normalize_candles(candles_5m)
    normalized_1m = _normalize_candles(candles_1m)
    timeframe_now = _normalize_now(now, normalized_1m)

    if len(normalized_5m) < EMA_BIAS_PERIOD + RSI_PERIOD or len(normalized_1m) < EMA_PULLBACK_PERIOD + 2:
        return _rejected_signal(symbol, "rejected", "missing_data")

    bias = _detect_bias(normalized_5m)
    if bias is None:
        return _rejected_signal(symbol, "rejected", "bias_not_confirmed")

    pullback_index = _find_latest_pullback(normalized_1m, bias)
    if pullback_index is None:
        return _rejected_signal(symbol, "blocked", "pullback_not_detected")

    trigger_index = _find_trigger_index(normalized_1m, bias, pullback_index)
    if trigger_index is None:
        if _pullback_is_expired(normalized_1m, pullback_index, timeframe_now):
            return _rejected_signal(symbol, "blocked", "signal_expired")
        near_signal = _build_near_setup_signal(symbol, bias, normalized_1m, pullback_index)
        if near_signal is None:
            return _rejected_signal(symbol, "rejected", "invalid_trade_levels")
        return _rejected_signal(
            near_signal.symbol,
            "near_setup",
            "waiting_for_trigger",
            direction=near_signal.direction,
            entry=near_signal.entry,
            stop_loss=near_signal.stop_loss,
            take_profit=near_signal.take_profit,
            risk_reward=near_signal.risk_reward,
            detected_at=near_signal.detected_at,
            confidence_score=_signal_confidence(near_signal.risk_reward, "near_setup"),
        )

    signal = _build_signal(symbol, bias, normalized_1m, pullback_index, trigger_index)
    if signal is None:
        return _rejected_signal(symbol, "rejected", "invalid_trade_levels")

    expiry_time = min(
        normalized_1m[trigger_index].timestamp + timedelta(minutes=EXPIRY_MINUTES),
        normalized_1m[min(trigger_index + TRIGGER_WINDOW_CANDLES, len(normalized_1m) - 1)].timestamp,
    )
    status = "expired" if timeframe_now > expiry_time else "active"

    return StrategySignal(
        symbol=signal.symbol,
        direction=signal.direction,
        entry=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        risk_reward=signal.risk_reward,
        detected_at=signal.detected_at,
        status=status,
        confidence_score=_signal_confidence(signal.risk_reward, status),
    ).to_dict()


def _detect_bias(candles: list[Candle]) -> str | None:
    closes = [candle.close for candle in candles]
    ema200 = _ema(closes, EMA_BIAS_PERIOD)
    rsi = _rsi(closes, RSI_PERIOD)
    if ema200 is None or rsi is None or len(ema200) < 2:
        return None

    last_close = closes[-1]
    last_ema = ema200[-1]
    prev_ema = ema200[-2]
    last_rsi = rsi[-1]
    slope = last_ema - prev_ema

    if last_close > last_ema and slope > 0 and last_rsi >= 52:
        return "long"
    if last_close < last_ema and slope < 0 and last_rsi <= 48:
        return "short"
    return None


def _find_latest_pullback(candles: list[Candle], direction: str) -> int | None:
    closes = [candle.close for candle in candles]
    ema20 = _ema(closes, EMA_PULLBACK_PERIOD)
    if ema20 is None:
        return None

    for index in range(len(candles) - 2, EMA_PULLBACK_PERIOD - 2, -1):
        candle = candles[index]
        ema_value = ema20[index]
        if _touches_ema(candle, ema_value):
            return index
    return None


def _find_trigger_index(candles: list[Candle], direction: str, pullback_index: int) -> int | None:
    closes = [candle.close for candle in candles]
    ema20 = _ema(closes, EMA_PULLBACK_PERIOD)
    if ema20 is None:
        return None

    max_index = min(pullback_index + TRIGGER_WINDOW_CANDLES, len(candles) - 1)
    for index in range(pullback_index + 1, max_index + 1):
        previous = candles[index - 1]
        current = candles[index]
        ema_value = ema20[index]

        if direction == "long" and current.close > previous.high and current.close > ema_value:
            return index
        if direction == "short" and current.close < previous.low and current.close < ema_value:
            return index
    return None


def _build_signal(
    symbol: str,
    direction: str,
    candles: list[Candle],
    pullback_index: int,
    trigger_index: int,
) -> StrategySignal | None:
    trigger_candle = candles[trigger_index]
    entry = trigger_candle.close
    stop_loss = _calculate_stop_loss(candles, direction, pullback_index, trigger_index)
    if stop_loss is None:
        return None

    risk = entry - stop_loss if direction == "long" else stop_loss - entry
    if not _is_valid_number(entry, stop_loss, risk) or risk <= 0:
        return None

    take_profit = entry + (risk * TARGET_R_MULTIPLE) if direction == "long" else entry - (risk * TARGET_R_MULTIPLE)
    risk_reward = abs((take_profit - entry) / risk) if risk else 0.0
    if not _is_valid_number(take_profit, risk_reward) or risk_reward < TARGET_R_MULTIPLE:
        return None

    return StrategySignal(
        symbol=symbol,
        direction=direction,
        entry=round(entry, 8),
        stop_loss=round(stop_loss, 8),
        take_profit=round(take_profit, 8),
        risk_reward=round(risk_reward, 4),
        detected_at=trigger_candle.timestamp.isoformat(),
        status="active",
        confidence_score=_signal_confidence(risk_reward, "active"),
    )


def _build_near_setup_signal(
    symbol: str,
    direction: str,
    candles: list[Candle],
    pullback_index: int,
) -> StrategySignal | None:
    latest_index = min(len(candles) - 1, pullback_index + TRIGGER_WINDOW_CANDLES - 1)
    latest_candle = candles[latest_index]
    reference_candle = candles[max(pullback_index, latest_index - 1)]
    trigger_level = reference_candle.high if direction == "long" else reference_candle.low
    entry = trigger_level * (1 + STOP_BUFFER_RATIO) if direction == "long" else trigger_level * (1 - STOP_BUFFER_RATIO)
    stop_loss = _calculate_stop_loss(candles, direction, pullback_index, latest_index)
    if stop_loss is None:
        return None

    risk = entry - stop_loss if direction == "long" else stop_loss - entry
    if not _is_valid_number(entry, stop_loss, risk) or risk <= 0:
        return None

    take_profit = entry + (risk * TARGET_R_MULTIPLE) if direction == "long" else entry - (risk * TARGET_R_MULTIPLE)
    risk_reward = abs((take_profit - entry) / risk) if risk else 0.0
    if not _is_valid_number(take_profit, risk_reward) or risk_reward < TARGET_R_MULTIPLE:
        return None

    return StrategySignal(
        symbol=symbol,
        direction=direction,
        entry=round(entry, 8),
        stop_loss=round(stop_loss, 8),
        take_profit=round(take_profit, 8),
        risk_reward=round(risk_reward, 4),
        detected_at=latest_candle.timestamp.isoformat(),
        status="near_setup",
        confidence_score=_signal_confidence(risk_reward, "near_setup"),
    )


def _calculate_stop_loss(candles: list[Candle], direction: str, pullback_index: int, trigger_index: int) -> float | None:
    start_index = max(0, pullback_index - (SWING_LOOKBACK - 1))
    window = candles[start_index : trigger_index + 1]
    if not window:
        return None

    if direction == "long":
        swing = min(candle.low for candle in window)
        return swing * (1 - STOP_BUFFER_RATIO)

    swing = max(candle.high for candle in window)
    return swing * (1 + STOP_BUFFER_RATIO)


def _pullback_is_expired(candles: list[Candle], pullback_index: int, now: datetime) -> bool:
    pullback_time = candles[pullback_index].timestamp
    candle_expired = len(candles) - 1 >= pullback_index + TRIGGER_WINDOW_CANDLES
    time_expired = now > pullback_time + timedelta(minutes=EXPIRY_MINUTES)
    return candle_expired or time_expired


def _touches_ema(candle: Candle, ema_value: float) -> bool:
    tolerance = ema_value * EMA_PULLBACK_TOLERANCE_RATIO
    return candle.low - tolerance <= ema_value <= candle.high + tolerance


def _normalize_candles(raw_candles: list[dict[str, Any] | Candle]) -> list[Candle]:
    normalized: list[Candle] = []
    for item in raw_candles:
        try:
            candle = item if isinstance(item, Candle) else Candle(
                timestamp=_parse_timestamp(item.get("timestamp")),
                open=float(item.get("open")),
                high=float(item.get("high")),
                low=float(item.get("low")),
                close=float(item.get("close")),
            )
        except (TypeError, ValueError):
            return []
        if not _is_valid_number(candle.open, candle.high, candle.low, candle.close):
            return []
        normalized.append(candle)
    normalized.sort(key=lambda candle: candle.timestamp)
    return normalized


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    raise ValueError("Invalid timestamp value")


def _ema(values: list[float], period: int) -> list[float] | None:
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)
    ema_values: list[float] = []
    seed = sum(values[:period]) / period
    ema_values.extend(values[: period - 1])
    ema_values.append(seed)

    current = seed
    for value in values[period:]:
        current = ((value - current) * multiplier) + current
        ema_values.append(current)

    return ema_values


def _rsi(values: list[float], period: int) -> list[float] | None:
    if len(values) <= period:
        return None

    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, len(values)):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))

    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    rsi_values = [50.0] * period

    for index in range(period, len(gains)):
        average_gain = ((average_gain * (period - 1)) + gains[index]) / period
        average_loss = ((average_loss * (period - 1)) + losses[index]) / period
        if average_loss == 0:
            rsi_values.append(100.0)
            continue
        relative_strength = average_gain / average_loss
        rsi_values.append(100 - (100 / (1 + relative_strength)))

    if average_loss == 0 and len(rsi_values) == period:
        rsi_values.append(100.0)

    while len(rsi_values) < len(values):
        rsi_values.insert(0, 50.0)

    return rsi_values[-len(values) :]


def _is_valid_number(*values: float) -> bool:
    return all(value is not None and isfinite(value) for value in values)


def _resolve_now(candles: list[Candle]) -> datetime:
    if candles:
        return candles[-1].timestamp
    return datetime.now(UTC)


def _normalize_now(now: datetime | None, candles: list[Candle]) -> datetime:
    if now is None:
        return _resolve_now(candles)
    return now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)


def _rejected_signal(
    symbol: str,
    status: str,
    reason: str,
    *,
    direction: str | None = None,
    entry: float | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    risk_reward: float | None = None,
    detected_at: str | None = None,
    confidence_score: int | None = 0,
) -> dict[str, Any]:
    return StrategySignal(
        symbol=symbol,
        direction=direction,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_reward=risk_reward,
        detected_at=detected_at,
        status=status,
        confidence_score=confidence_score,
        rejection_reason=reason,
    ).to_dict()


def _signal_confidence(risk_reward: float | None, status: str) -> int:
    rr = risk_reward or 0.0
    if status == "near_setup":
        return 76 if rr >= 2.0 else 68
    if rr >= 2.5:
        return 90
    if rr >= 2.0:
        return 80
    return 50
