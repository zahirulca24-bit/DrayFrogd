from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Callable


EMA_BIAS_PERIOD = 200
EMA_PULLBACK_PERIOD = 20
RSI_PERIOD = 14
EXPIRY_CANDLES = 5
EXPIRY_MINUTES = 15
TRIGGER_WINDOW_CANDLES = 5
SWING_LOOKBACK = 5
STOP_BUFFER_RATIO = 0.001
TARGET_R_MULTIPLE = 2.0
EMA_TARGET_R_MULTIPLE = 1.5
EMA_PULLBACK_TOLERANCE_RATIO = 0.0015
STRATEGY_EMA_PULLBACK = "ema_pullback"
STRATEGY_BREAKOUT = "breakout"
STRATEGY_PURE_SMC = "pure_smc"
BREAKOUT_LEVEL_LOOKBACK = 24
BREAKOUT_VOLUME_LOOKBACK = 20
BREAKOUT_VOLUME_MULTIPLE = 1.5
BREAKOUT_TARGET_R_MULTIPLE = 1.5
PURE_SMC_TARGET_R_MULTIPLE = 1.5
PURE_SMC_EXPIRY_CANDLES = 10
SWING_CONFIRMATION_CANDLES = 2
STRUCTURE_LOOKBACK = 16
MSS_BODY_MULTIPLE = 1.15
DISPLACEMENT_VOLUME_MULTIPLE = 1.2
SWEEP_LOOKBACK = 18
SWEEP_BODY_MULTIPLE = 1.15
FVG_BUFFER_RATIO = 0.0005


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class StrategySignal:
    symbol: str
    strategy_name: str
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
        payload = asdict(self)
        # Preserve the legacy field name while introducing the shared strategy_name schema.
        payload["strategy"] = self.strategy_name
        return payload


StrategyEvaluator = Callable[[str, list[Candle], list[Candle], datetime | None], dict[str, Any]]


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_name: str
    evaluator: StrategyEvaluator
    enabled: bool = True


def get_strategy_registry() -> dict[str, StrategyDefinition]:
    return {
        STRATEGY_EMA_PULLBACK: StrategyDefinition(
            strategy_name=STRATEGY_EMA_PULLBACK,
            evaluator=evaluate_ema_pullback_strategy,
            enabled=True,
        ),
        STRATEGY_BREAKOUT: StrategyDefinition(
            strategy_name=STRATEGY_BREAKOUT,
            evaluator=evaluate_breakout_strategy,
            enabled=True,
        ),
        STRATEGY_PURE_SMC: StrategyDefinition(
            strategy_name=STRATEGY_PURE_SMC,
            evaluator=evaluate_pure_smc_strategy,
            enabled=True,
        ),
    }


def evaluate_registered_strategies(
    symbol: str,
    candles_5m: list[dict[str, Any] | Candle],
    candles_1m: list[dict[str, Any] | Candle],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for definition in get_strategy_registry().values():
        if not definition.enabled:
            continue
        results.append(definition.evaluator(symbol, candles_5m, candles_1m, now))

    return results


def evaluate_strategy_pipeline(
    symbol: str,
    candles_5m: list[dict[str, Any] | Candle],
    candles_1m: list[dict[str, Any] | Candle],
    now: datetime | None = None,
) -> dict[str, Any]:
    first_near_setup: dict[str, Any] | None = None
    first_result: dict[str, Any] | None = None

    for result in evaluate_registered_strategies(symbol, candles_5m, candles_1m, now):
        if first_result is None:
            first_result = result
        if result.get("status") == "active":
            return result
        if result.get("status") == "near_setup" and first_near_setup is None:
            first_near_setup = result

    return first_near_setup or first_result or _rejected_signal(
        symbol,
        "rejected",
        "no_enabled_strategy",
        strategy_name=STRATEGY_EMA_PULLBACK,
    )


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
        return _rejected_signal(symbol, "rejected", "missing_data", strategy_name=STRATEGY_EMA_PULLBACK)

    bias = _detect_bias(normalized_5m)
    if bias is None:
        return _rejected_signal(symbol, "rejected", "bias_not_confirmed", strategy_name=STRATEGY_EMA_PULLBACK)

    pullback_index = _find_latest_pullback(normalized_1m, bias)
    if pullback_index is None:
        if _has_opposite_structure_pullback(normalized_1m, bias):
            return _rejected_signal(
                symbol,
                "rejected",
                "opposite_pullback_structure",
                strategy_name=STRATEGY_EMA_PULLBACK,
            )
        return _rejected_signal(symbol, "blocked", "pullback_not_detected", strategy_name=STRATEGY_EMA_PULLBACK)

    trigger_index = _find_trigger_index(normalized_1m, bias, pullback_index)
    if trigger_index is None:
        if _pullback_is_expired(normalized_1m, pullback_index, timeframe_now):
            return _rejected_signal(symbol, "blocked", "signal_expired", strategy_name=STRATEGY_EMA_PULLBACK)
        near_signal = _build_ema_near_setup_signal(symbol, bias, normalized_1m, pullback_index)
        if near_signal is None:
            return _rejected_signal(symbol, "rejected", "invalid_trade_levels", strategy_name=STRATEGY_EMA_PULLBACK)
        return _rejected_signal(
            symbol,
            "near_setup",
            "waiting_for_trigger",
            strategy_name=STRATEGY_EMA_PULLBACK,
            direction=near_signal.direction,
            entry=near_signal.entry,
            stop_loss=near_signal.stop_loss,
            take_profit=near_signal.take_profit,
            risk_reward=near_signal.risk_reward,
            detected_at=near_signal.detected_at,
            confidence_score=_signal_confidence(near_signal.risk_reward, "near_setup"),
        )

    signal = _build_ema_active_signal(symbol, bias, normalized_1m, pullback_index, trigger_index)
    if signal is None:
        return _rejected_signal(symbol, "rejected", "invalid_trade_levels", strategy_name=STRATEGY_EMA_PULLBACK)

    expiry_time = min(
        normalized_1m[trigger_index].timestamp + timedelta(minutes=EXPIRY_MINUTES),
        normalized_1m[min(trigger_index + TRIGGER_WINDOW_CANDLES, len(normalized_1m) - 1)].timestamp,
    )
    status = "expired" if timeframe_now > expiry_time else "active"

    return StrategySignal(
        symbol=signal.symbol,
        strategy_name=STRATEGY_EMA_PULLBACK,
        direction=signal.direction,
        entry=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
        risk_reward=signal.risk_reward,
        detected_at=signal.detected_at,
        status=status,
        confidence_score=_signal_confidence(signal.risk_reward, status),
    ).to_dict()


def _find_latest_pullback(candles: list[Candle], direction: str) -> int | None:
    closes = [candle.close for candle in candles]
    ema20 = _ema(closes, EMA_PULLBACK_PERIOD)
    if ema20 is None:
        return None

    for index in range(len(candles) - 2, EMA_PULLBACK_PERIOD - 2, -1):
        candle = candles[index]
        ema_value = ema20[index]
        if _touches_ema(candle, ema_value) and _is_directionally_valid_pullback(candle, ema_value, direction):
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


def _build_ema_active_signal(
    symbol: str,
    direction: str,
    candles: list[Candle],
    pullback_index: int,
    trigger_index: int,
) -> StrategySignal | None:
    trigger_candle = candles[trigger_index]
    entry = trigger_candle.close
    stop_loss = _calculate_ema_stop_loss(candles, direction, pullback_index, trigger_index)
    if stop_loss is None:
        return None

    risk = entry - stop_loss if direction == "long" else stop_loss - entry
    if not _is_valid_number(entry, stop_loss, risk) or risk <= 0:
        return None

    take_profit = entry + (risk * EMA_TARGET_R_MULTIPLE) if direction == "long" else entry - (risk * EMA_TARGET_R_MULTIPLE)
    risk_reward = abs((take_profit - entry) / risk) if risk else 0.0
    if not _is_valid_number(take_profit, risk_reward) or risk_reward < EMA_TARGET_R_MULTIPLE:
        return None

    return StrategySignal(
        symbol=symbol,
        strategy_name=STRATEGY_EMA_PULLBACK,
        direction=direction,
        entry=round(entry, 8),
        stop_loss=round(stop_loss, 8),
        take_profit=round(take_profit, 8),
        risk_reward=round(risk_reward, 4),
        detected_at=trigger_candle.timestamp.isoformat(),
        status="active",
        confidence_score=_signal_confidence(risk_reward, "active"),
    )


def _build_ema_near_setup_signal(
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
    stop_loss = _calculate_ema_stop_loss(candles, direction, pullback_index, latest_index)
    if stop_loss is None:
        return None

    risk = entry - stop_loss if direction == "long" else stop_loss - entry
    if not _is_valid_number(entry, stop_loss, risk) or risk <= 0:
        return None

    take_profit = entry + (risk * EMA_TARGET_R_MULTIPLE) if direction == "long" else entry - (risk * EMA_TARGET_R_MULTIPLE)
    risk_reward = abs((take_profit - entry) / risk) if risk else 0.0
    if not _is_valid_number(take_profit, risk_reward) or risk_reward < EMA_TARGET_R_MULTIPLE:
        return None

    return StrategySignal(
        symbol=symbol,
        strategy_name=STRATEGY_EMA_PULLBACK,
        direction=direction,
        entry=round(entry, 8),
        stop_loss=round(stop_loss, 8),
        take_profit=round(take_profit, 8),
        risk_reward=round(risk_reward, 4),
        detected_at=latest_candle.timestamp.isoformat(),
        status="near_setup",
        confidence_score=_signal_confidence(risk_reward, "near_setup"),
    )


def _calculate_ema_stop_loss(candles: list[Candle], direction: str, pullback_index: int, trigger_index: int) -> float | None:
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


def _is_directionally_valid_pullback(candle: Candle, ema_value: float, direction: str) -> bool:
    if direction == "long":
        return not (candle.close < candle.open and candle.close < ema_value)
    return not (candle.close > candle.open and candle.close > ema_value)


def _has_opposite_structure_pullback(candles: list[Candle], direction: str) -> bool:
    closes = [candle.close for candle in candles]
    ema20 = _ema(closes, EMA_PULLBACK_PERIOD)
    if ema20 is None:
        return False

    for index in range(len(candles) - 2, EMA_PULLBACK_PERIOD - 2, -1):
        candle = candles[index]
        ema_value = ema20[index]
        if _touches_ema(candle, ema_value) and not _is_directionally_valid_pullback(candle, ema_value, direction):
            return True
    return False


def evaluate_breakout_strategy(
    symbol: str,
    candles_5m: list[dict[str, Any] | Candle],
    candles_1m: list[dict[str, Any] | Candle],
    now: datetime | None = None,
) -> dict[str, Any]:
    completed_candles_1m = _normalize_candles(_exclude_incomplete_candles(candles_1m))
    minimum_candles = max(EMA_BIAS_PERIOD, RSI_PERIOD + 1, BREAKOUT_LEVEL_LOOKBACK + 1, BREAKOUT_VOLUME_LOOKBACK + 1)
    if len(completed_candles_1m) < minimum_candles:
        return _rejected_signal(symbol, "rejected", "missing_data", strategy_name=STRATEGY_BREAKOUT)

    latest = completed_candles_1m[-1]
    prior_candles = completed_candles_1m[:-1]
    level_window = prior_candles[-BREAKOUT_LEVEL_LOOKBACK:]
    volume_window = prior_candles[-BREAKOUT_VOLUME_LOOKBACK:]
    if len(level_window) < BREAKOUT_LEVEL_LOOKBACK or len(volume_window) < BREAKOUT_VOLUME_LOOKBACK:
        return _rejected_signal(symbol, "rejected", "missing_data", strategy_name=STRATEGY_BREAKOUT)

    resistance = max(candle.high for candle in level_window)
    support = min(candle.low for candle in level_window)
    long_breakout = latest.close > resistance
    short_breakout = latest.close < support
    if not long_breakout and not short_breakout:
        return _rejected_signal(symbol, "rejected", "breakout_not_detected", strategy_name=STRATEGY_BREAKOUT)

    closes = [candle.close for candle in completed_candles_1m]
    ema200 = _ema(closes, EMA_BIAS_PERIOD)
    rsi_values = _rsi(closes, RSI_PERIOD)
    if ema200 is None or rsi_values is None:
        return _rejected_signal(symbol, "rejected", "missing_data", strategy_name=STRATEGY_BREAKOUT)

    last_ema = ema200[-1]
    last_rsi = rsi_values[-1]
    average_volume = _average_volume(volume_window, BREAKOUT_VOLUME_LOOKBACK)

    if long_breakout:
        if latest.close <= last_ema:
            return _rejected_signal(symbol, "rejected", "trend_not_confirmed", strategy_name=STRATEGY_BREAKOUT)
        if last_rsi > 70:
            return _rejected_signal(symbol, "rejected", "rsi_overbought", strategy_name=STRATEGY_BREAKOUT)
        if average_volume <= 0 or latest.volume <= average_volume * BREAKOUT_VOLUME_MULTIPLE:
            return _rejected_signal(symbol, "rejected", "volume_not_confirmed", strategy_name=STRATEGY_BREAKOUT)
        return _build_breakout_signal(
            symbol=symbol,
            direction="long",
            latest=latest,
            level=resistance,
            reference_window=level_window,
        )

    if latest.close >= last_ema:
        return _rejected_signal(symbol, "rejected", "trend_not_confirmed", strategy_name=STRATEGY_BREAKOUT)
    if last_rsi < 30:
        return _rejected_signal(symbol, "rejected", "rsi_oversold", strategy_name=STRATEGY_BREAKOUT)
    if average_volume <= 0 or latest.volume <= average_volume * BREAKOUT_VOLUME_MULTIPLE:
        return _rejected_signal(symbol, "rejected", "volume_not_confirmed", strategy_name=STRATEGY_BREAKOUT)
    return _build_breakout_signal(
        symbol=symbol,
        direction="short",
        latest=latest,
        level=support,
        reference_window=level_window,
    )


def evaluate_pure_smc_strategy(
    symbol: str,
    candles_5m: list[dict[str, Any] | Candle],
    candles_1m: list[dict[str, Any] | Candle],
    now: datetime | None = None,
) -> dict[str, Any]:
    completed_candles = _normalize_candles(_exclude_incomplete_candles(candles_1m))
    timeframe_now = _normalize_now(now, completed_candles)
    if len(completed_candles) < max(12, (SWING_CONFIRMATION_CANDLES * 2) + 5):
        return _rejected_signal(symbol, "rejected", "missing_data", strategy_name=STRATEGY_PURE_SMC)

    setup = _find_pure_smc_setup(completed_candles)
    if setup is None:
        return _rejected_signal(
            symbol,
            "rejected",
            _last_pure_smc_reason(completed_candles),
            strategy_name=STRATEGY_PURE_SMC,
        )

    direction = str(setup["direction"])
    break_index = int(setup["break_index"])
    break_candle = completed_candles[break_index]
    latest_candle = completed_candles[-1]
    order_block = _find_pure_smc_order_block(completed_candles, break_index, direction)
    if order_block is None:
        return _rejected_signal(symbol, "rejected", "invalid_trade_levels", strategy_name=STRATEGY_PURE_SMC)

    fvg_zone = _find_pure_smc_fvg(completed_candles, break_index, direction)
    if fvg_zone is None:
        return _rejected_signal(symbol, "rejected", "fvg_not_detected", strategy_name=STRATEGY_PURE_SMC)

    mitigation_zone = _intersect_zones(order_block["low"], order_block["high"], fvg_zone[0], fvg_zone[1])
    if mitigation_zone is None:
        return _rejected_signal(symbol, "rejected", "aoi_not_confirmed", strategy_name=STRATEGY_PURE_SMC)

    invalidation_level = float(order_block["invalidation"])
    invalidated = _setup_invalidated(completed_candles[break_index + 1 :], invalidation_level, direction)
    if invalidated:
        return _rejected_signal(symbol, "rejected", "setup_invalidated", strategy_name=STRATEGY_PURE_SMC)

    candles_since_break = len(completed_candles) - break_index - 1
    if candles_since_break >= PURE_SMC_EXPIRY_CANDLES and not _candle_inside_zone(latest_candle, mitigation_zone[0], mitigation_zone[1]):
        return _rejected_signal(
            symbol,
            "expired",
            "signal_expired",
            strategy_name=STRATEGY_PURE_SMC,
            direction=direction,
            detected_at=break_candle.timestamp.isoformat(),
            confidence_score=_pure_smc_confidence(mitigated=False, rr_valid=False),
        )

    entry = round(_midpoint(mitigation_zone[0], mitigation_zone[1]), 8)
    stop_loss = _calculate_pure_smc_stop_loss(order_block, direction)
    take_profit = _calculate_take_profit(entry, stop_loss, direction, PURE_SMC_TARGET_R_MULTIPLE)
    risk_reward = _risk_reward(entry, stop_loss, take_profit)
    if (
        stop_loss is None
        or take_profit is None
        or risk_reward is None
        or risk_reward < PURE_SMC_TARGET_R_MULTIPLE
    ):
        return _rejected_signal(symbol, "rejected", "invalid_trade_levels", strategy_name=STRATEGY_PURE_SMC)

    mitigated = _candle_inside_zone(latest_candle, mitigation_zone[0], mitigation_zone[1])
    status = "active" if mitigated else "near_setup"
    detected_at = latest_candle.timestamp.isoformat() if mitigated else break_candle.timestamp.isoformat()
    return StrategySignal(
        symbol=symbol,
        strategy_name=STRATEGY_PURE_SMC,
        direction=direction,
        entry=entry,
        stop_loss=round(stop_loss, 8),
        take_profit=round(take_profit, 8),
        risk_reward=round(risk_reward, 4),
        detected_at=detected_at,
        status=status,
        confidence_score=_pure_smc_confidence(mitigated=mitigated, rr_valid=True),
        rejection_reason="waiting_for_mitigation" if not mitigated else None,
    ).to_dict()


def _find_pure_smc_setup(candles: list[Candle]) -> dict[str, Any] | None:
    swings = _find_confirmed_swings(candles)
    if len(swings["highs"]) < 2 or len(swings["lows"]) < 2:
        return None

    latest_setup: dict[str, Any] | None = None
    for break_index in range((SWING_CONFIRMATION_CANDLES * 2) + 2, len(candles)):
        trend = _pure_smc_structure_before_index(swings, break_index)
        if trend is None:
            continue

        candle = candles[break_index]
        if trend["direction"] == "bearish" and candle.close > float(trend["reference_level"]):
            latest_setup = {
                "direction": "long",
                "break_index": break_index,
                "reference_level": trend["reference_level"],
                "structure": trend["direction"],
            }
        elif trend["direction"] == "bullish" and candle.close < float(trend["reference_level"]):
            latest_setup = {
                "direction": "short",
                "break_index": break_index,
                "reference_level": trend["reference_level"],
                "structure": trend["direction"],
            }

    return latest_setup


def _last_pure_smc_reason(candles: list[Candle]) -> str:
    swings = _find_confirmed_swings(candles)
    if len(swings["highs"]) < 2 or len(swings["lows"]) < 2:
        return "structure_not_confirmed"

    had_structure = False
    had_same_direction_break = False
    for break_index in range((SWING_CONFIRMATION_CANDLES * 2) + 2, len(candles)):
        trend = _pure_smc_structure_before_index(swings, break_index)
        if trend is None:
            continue
        had_structure = True
        candle = candles[break_index]
        reference_level = float(trend["reference_level"])
        if trend["direction"] == "bullish" and candle.close > reference_level:
            had_same_direction_break = True
        if trend["direction"] == "bearish" and candle.close < reference_level:
            had_same_direction_break = True

    if had_same_direction_break:
        return "choch_not_detected"
    if had_structure:
        return "mss_not_detected"
    return "structure_not_confirmed"


def _find_confirmed_swings(candles: list[Candle]) -> dict[str, list[dict[str, Any]]]:
    swing_highs: list[dict[str, Any]] = []
    swing_lows: list[dict[str, Any]] = []
    for index in range(SWING_CONFIRMATION_CANDLES, len(candles) - SWING_CONFIRMATION_CANDLES):
        candle = candles[index]
        left = candles[index - SWING_CONFIRMATION_CANDLES : index]
        right = candles[index + 1 : index + SWING_CONFIRMATION_CANDLES + 1]
        if all(candle.high > item.high for item in left + right):
            swing_highs.append({"index": index, "price": candle.high, "timestamp": candle.timestamp.isoformat()})
        if all(candle.low < item.low for item in left + right):
            swing_lows.append({"index": index, "price": candle.low, "timestamp": candle.timestamp.isoformat()})
    return {"highs": swing_highs, "lows": swing_lows}


def _pure_smc_structure_before_index(swings: dict[str, list[dict[str, Any]]], break_index: int) -> dict[str, Any] | None:
    eligible_highs = [item for item in swings["highs"] if int(item["index"]) <= break_index - (SWING_CONFIRMATION_CANDLES + 1)]
    eligible_lows = [item for item in swings["lows"] if int(item["index"]) <= break_index - (SWING_CONFIRMATION_CANDLES + 1)]
    if len(eligible_highs) < 2 or len(eligible_lows) < 2:
        return None

    last_high = eligible_highs[-1]
    prev_high = eligible_highs[-2]
    last_low = eligible_lows[-1]
    prev_low = eligible_lows[-2]

    if float(last_high["price"]) < float(prev_high["price"]) and float(last_low["price"]) < float(prev_low["price"]):
        return {"direction": "bearish", "reference_level": float(last_high["price"])}
    if float(last_high["price"]) > float(prev_high["price"]) and float(last_low["price"]) > float(prev_low["price"]):
        return {"direction": "bullish", "reference_level": float(last_low["price"])}
    return None


def _find_pure_smc_order_block(candles: list[Candle], break_index: int, direction: str) -> dict[str, float] | None:
    search_window = candles[:break_index]
    opposite_candle: Candle | None = None
    if direction == "long":
        for candle in reversed(search_window):
            if candle.close < candle.open:
                opposite_candle = candle
                break
    else:
        for candle in reversed(search_window):
            if candle.close > candle.open:
                opposite_candle = candle
                break

    if opposite_candle is None or opposite_candle.high <= opposite_candle.low:
        return None

    return {
        "low": opposite_candle.low,
        "high": opposite_candle.high,
        "invalidation": opposite_candle.low if direction == "long" else opposite_candle.high,
    }


def _find_pure_smc_fvg(candles: list[Candle], break_index: int, direction: str) -> tuple[float, float] | None:
    start_index = max(0, break_index - 2)
    end_index = min(len(candles) - 3, break_index)
    for index in range(end_index, start_index - 1, -1):
        left = candles[index]
        right = candles[index + 2]
        if direction == "long" and left.high < right.low:
            return (left.high, right.low)
        if direction == "short" and left.low > right.high:
            return (right.high, left.low)
    return None


def _intersect_zones(first_low: float, first_high: float, second_low: float, second_high: float) -> tuple[float, float] | None:
    low = max(min(first_low, first_high), min(second_low, second_high))
    high = min(max(first_low, first_high), max(second_low, second_high))
    if high <= low:
        return None
    return (low, high)


def _setup_invalidated(candles: list[Candle], invalidation_level: float, direction: str) -> bool:
    for candle in candles:
        if direction == "long" and candle.close < invalidation_level:
            return True
        if direction == "short" and candle.close > invalidation_level:
            return True
    return False


def _candle_inside_zone(candle: Candle, zone_low: float, zone_high: float) -> bool:
    low = min(zone_low, zone_high)
    high = max(zone_low, zone_high)
    return low <= candle.close <= high


def _calculate_pure_smc_stop_loss(order_block: dict[str, float], direction: str) -> float | None:
    if direction == "long":
        stop_loss = float(order_block["low"]) * (1 - STOP_BUFFER_RATIO)
    else:
        stop_loss = float(order_block["high"]) * (1 + STOP_BUFFER_RATIO)
    return stop_loss if _is_valid_number(stop_loss) else None


def _calculate_take_profit(entry: float, stop_loss: float, direction: str, rr_multiple: float) -> float | None:
    risk = entry - stop_loss if direction == "long" else stop_loss - entry
    if not _is_valid_number(entry, stop_loss, risk) or risk <= 0:
        return None
    return entry + (risk * rr_multiple) if direction == "long" else entry - (risk * rr_multiple)


def _risk_reward(entry: float, stop_loss: float, take_profit: float) -> float | None:
    risk = abs(entry - stop_loss)
    if not _is_valid_number(entry, stop_loss, take_profit, risk) or risk <= 0:
        return None
    return abs(take_profit - entry) / risk


def _pure_smc_confidence(*, mitigated: bool, rr_valid: bool) -> int:
    score = 0
    score += 25  # confirmed structure shift
    score += 20  # valid order block
    score += 15  # valid FVG
    score += 15  # mitigation zone overlap
    score += 15 if mitigated else 5
    score += 10 if rr_valid else 0
    return min(score, 100)


def evaluate_hybrid_strategy(
    symbol: str,
    candles_5m: list[dict[str, Any] | Candle],
    candles_1m: list[dict[str, Any] | Candle],
    now: datetime | None = None,
) -> dict[str, Any]:
    candles_5m = _ensure_candles(candles_5m)
    candles_1m = _ensure_candles(candles_1m)
    if len(candles_1m) < 12:
        return _rejected_signal(symbol, "rejected", "missing_hybrid_data", strategy="Hybrid")

    sweep_index = len(candles_1m) - 3
    displacement_index = len(candles_1m) - 2
    retest_index = len(candles_1m) - 1
    sweep_candle = candles_1m[sweep_index]
    displacement_candle = candles_1m[displacement_index]
    retest_candle = candles_1m[retest_index]
    support, resistance = _retail_levels(candles_1m, sweep_index)

    bullish_sweep = _bullish_sweep(candles_1m, sweep_index, support)
    bearish_sweep = _bearish_sweep(candles_1m, sweep_index, resistance)
    if not bullish_sweep and not bearish_sweep:
        return _rejected_signal(symbol, "blocked", "liquidity_sweep_not_found", strategy="Hybrid")

    direction = "long" if bullish_sweep else "short"
    fvg_zone = _find_fvg_zone(candles_1m, displacement_index, direction)
    if fvg_zone is None:
        return _rejected_signal(symbol, "rejected", "fvg_not_confirmed", strategy="Hybrid")

    zone_low, zone_high = fvg_zone
    invalidation = sweep_candle.low if direction == "long" else sweep_candle.high
    if direction == "long":
        invalidation *= 1 - STOP_BUFFER_RATIO
    else:
        invalidation *= 1 + STOP_BUFFER_RATIO

    if _is_invalidated(retest_candle, invalidation, direction):
        return _rejected_signal(symbol, "blocked", "setup_invalidated", strategy="Hybrid")

    displacement_ok = _rapid_displacement_ok(candles_1m, displacement_index, direction)
    if not displacement_ok:
        return _rejected_signal(symbol, "blocked", "displacement_not_confirmed", strategy="Hybrid")

    if _touches_zone(retest_candle, zone_low, zone_high):
        entry = _midpoint(zone_low, zone_high)
        return _build_signal(
            symbol=symbol,
            strategy="Hybrid",
            direction=direction,
            entry=entry,
            stop_loss=invalidation,
            detected_at=retest_candle.timestamp.isoformat(),
            status="active",
        )

    entry = _midpoint(zone_low, zone_high)
    return _build_signal(
        symbol=symbol,
        strategy="Hybrid",
        direction=direction,
        entry=entry,
        stop_loss=invalidation,
        detected_at=retest_candle.timestamp.isoformat(),
        status="near_setup",
    )


def _breakout_trend_ok(candles_5m: list[Candle], bias: str) -> bool:
    closes = [candle.close for candle in candles_5m]
    ema200 = _ema(closes, EMA_BIAS_PERIOD)
    if ema200 is None or len(ema200) < 2:
        return False
    last_close = closes[-1]
    last_ema = ema200[-1]
    prev_ema = ema200[-2]
    slope = last_ema - prev_ema
    if bias == "long":
        return last_close > last_ema and slope > 0
    return last_close < last_ema and slope < 0


def _build_breakout_signal(
    *,
    symbol: str,
    direction: str,
    latest: Candle,
    level: float,
    reference_window: list[Candle],
) -> dict[str, Any]:
    stop_loss = _calculate_breakout_stop_loss(direction, level, reference_window)
    if stop_loss is None:
        return _rejected_signal(symbol, "rejected", "invalid_trade_levels", strategy_name=STRATEGY_BREAKOUT)

    risk = latest.close - stop_loss if direction == "long" else stop_loss - latest.close
    if not _is_valid_number(latest.close, stop_loss, risk) or risk <= 0:
        return _rejected_signal(symbol, "rejected", "invalid_trade_levels", strategy_name=STRATEGY_BREAKOUT)

    take_profit = latest.close + (risk * BREAKOUT_TARGET_R_MULTIPLE) if direction == "long" else latest.close - (risk * BREAKOUT_TARGET_R_MULTIPLE)
    risk_reward = abs((take_profit - latest.close) / risk) if risk else 0.0
    if not _is_valid_number(take_profit, risk_reward) or risk_reward < BREAKOUT_TARGET_R_MULTIPLE:
        return _rejected_signal(symbol, "rejected", "invalid_trade_levels", strategy_name=STRATEGY_BREAKOUT)

    return StrategySignal(
        symbol=symbol,
        strategy_name=STRATEGY_BREAKOUT,
        direction=direction,
        entry=round(latest.close, 8),
        stop_loss=round(stop_loss, 8),
        take_profit=round(take_profit, 8),
        risk_reward=round(risk_reward, 4),
        detected_at=latest.timestamp.isoformat(),
        status="active",
        confidence_score=_signal_confidence(risk_reward, "active"),
    ).to_dict()


def _calculate_breakout_stop_loss(direction: str, level: float, reference_window: list[Candle]) -> float | None:
    if not reference_window:
        return None

    if direction == "long":
        swing_low = min(candle.low for candle in reference_window)
        return min(level, swing_low) * (1 - STOP_BUFFER_RATIO)

    swing_high = max(candle.high for candle in reference_window)
    return max(level, swing_high) * (1 + STOP_BUFFER_RATIO)


def _bullish_structure_shift(candles: list[Candle], mss_index: int, prior_window: list[Candle]) -> bool:
    if len(prior_window) < 4 or mss_index < 2:
        return False
    prior_high = max(candle.high for candle in prior_window)
    mss_candle = candles[mss_index]
    body = abs(mss_candle.close - mss_candle.open)
    average_body = _average_body(prior_window, min(8, len(prior_window)))
    return (
        mss_candle.close > prior_high
        and mss_candle.close > mss_candle.open
        and body >= max(average_body * MSS_BODY_MULTIPLE, 0.0000001)
    )


def _bearish_structure_shift(candles: list[Candle], mss_index: int, prior_window: list[Candle]) -> bool:
    if len(prior_window) < 4 or mss_index < 2:
        return False
    prior_low = min(candle.low for candle in prior_window)
    mss_candle = candles[mss_index]
    body = abs(mss_candle.close - mss_candle.open)
    average_body = _average_body(prior_window, min(8, len(prior_window)))
    return (
        mss_candle.close < prior_low
        and mss_candle.close < mss_candle.open
        and body >= max(average_body * MSS_BODY_MULTIPLE, 0.0000001)
    )


def _find_order_block(candles: list[Candle], mss_index: int, direction: str) -> Candle | None:
    start = max(0, mss_index - 6)
    search_window = candles[start:mss_index]
    if direction == "long":
        for candle in reversed(search_window):
            if candle.close < candle.open:
                return candle
    else:
        for candle in reversed(search_window):
            if candle.close > candle.open:
                return candle
    return None


def _find_fvg_zone(candles: list[Candle], center_index: int, direction: str) -> tuple[float, float] | None:
    if center_index < 2 or center_index >= len(candles):
        return None
    left = candles[center_index - 2]
    right = candles[center_index]
    if direction == "long" and right.low > left.high:
        return (left.high * (1 + FVG_BUFFER_RATIO), right.low * (1 - FVG_BUFFER_RATIO))
    if direction == "short" and right.high < left.low:
        return (right.high * (1 + FVG_BUFFER_RATIO), left.low * (1 - FVG_BUFFER_RATIO))
    return None


def _ob_invalidation(candle: Candle, direction: str) -> float | None:
    if direction == "long":
        return candle.low * (1 - STOP_BUFFER_RATIO)
    return candle.high * (1 + STOP_BUFFER_RATIO)


def _is_invalidated(candle: Candle, invalidation: float, direction: str) -> bool:
    if direction == "long":
        return candle.low <= invalidation
    return candle.high >= invalidation


def _touches_zone(candle: Candle, zone_low: float, zone_high: float) -> bool:
    low = min(zone_low, zone_high)
    high = max(zone_low, zone_high)
    return candle.low <= high and candle.high >= low


def _bullish_sweep(candles: list[Candle], sweep_index: int, support: float | None) -> bool:
    if support is None or sweep_index < 0:
        return False
    candle = candles[sweep_index]
    return candle.low < support and candle.close > support


def _bearish_sweep(candles: list[Candle], sweep_index: int, resistance: float | None) -> bool:
    if resistance is None or sweep_index < 0:
        return False
    candle = candles[sweep_index]
    return candle.high > resistance and candle.close < resistance


def _rapid_displacement_ok(candles: list[Candle], displacement_index: int, direction: str) -> bool:
    if displacement_index < 2:
        return False
    candle = candles[displacement_index]
    body = abs(candle.close - candle.open)
    average_body = _average_body(candles[max(0, displacement_index - 8) : displacement_index], min(8, displacement_index))
    average_volume = _average_volume(candles[max(0, displacement_index - 8) : displacement_index], min(8, displacement_index))
    if direction == "long":
        return candle.close > candle.open and body >= max(average_body * SWEEP_BODY_MULTIPLE, 0.0000001) and candle.volume >= max(average_volume * DISPLACEMENT_VOLUME_MULTIPLE, 0.0000001)
    return candle.close < candle.open and body >= max(average_body * SWEEP_BODY_MULTIPLE, 0.0000001) and candle.volume >= max(average_volume * DISPLACEMENT_VOLUME_MULTIPLE, 0.0000001)


def _retail_levels(candles: list[Candle], upto_index: int) -> tuple[float | None, float | None]:
    window = candles[max(0, upto_index - SWEEP_LOOKBACK) : upto_index]
    if len(window) < 5:
        return None, None
    return min(candle.low for candle in window), max(candle.high for candle in window)


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


def _build_signal(
    *,
    symbol: str,
    strategy: str,
    direction: str,
    entry: float,
    stop_loss: float,
    detected_at: str,
    status: str,
) -> dict[str, Any]:
    risk = entry - stop_loss if direction == "long" else stop_loss - entry
    if not _is_valid_number(entry, stop_loss, risk) or risk <= 0:
        return _rejected_signal(symbol, "rejected", "invalid_trade_levels", strategy_name=strategy)

    take_profit = entry + (risk * TARGET_R_MULTIPLE) if direction == "long" else entry - (risk * TARGET_R_MULTIPLE)
    risk_reward = abs((take_profit - entry) / risk) if risk else 0.0
    if not _is_valid_number(take_profit, risk_reward) or risk_reward < TARGET_R_MULTIPLE:
        return _rejected_signal(symbol, "rejected", "invalid_trade_levels", strategy_name=strategy)

    signal = StrategySignal(
        symbol=symbol,
        strategy_name=strategy,
        direction=direction,
        entry=round(entry, 8),
        stop_loss=round(stop_loss, 8),
        take_profit=round(take_profit, 8),
        risk_reward=round(risk_reward, 4),
        detected_at=detected_at,
        status=status,
        confidence_score=_signal_confidence(risk_reward, status),
    )
    return signal.to_dict()


def _average_volume(candles: list[Candle], period: int) -> float:
    window = candles[-period:] if len(candles) >= period else candles
    values = [candle.volume for candle in window if candle.volume > 0]
    if not values:
        return 0.0
    return sum(values) / len(values)


def _average_body(candles: list[Candle], period: int) -> float:
    window = candles[-period:] if len(candles) >= period else candles
    values = [abs(candle.close - candle.open) for candle in window]
    if not values:
        return 0.0
    return sum(values) / len(values)


def _latest_rsi(candles: list[Candle]) -> float | None:
    closes = [candle.close for candle in candles]
    values = _rsi(closes, RSI_PERIOD)
    if not values:
        return None
    return values[-1]


def _swing_stop_loss(candles: list[Candle], direction: str, reference_window: list[Candle], latest: Candle) -> float | None:
    if not reference_window:
        return None
    start_index = max(0, len(candles) - max(SWING_LOOKBACK + 1, len(reference_window)))
    window = candles[start_index:-1]
    if not window:
        window = reference_window
    if direction == "long":
        swing = min(candle.low for candle in window)
        return swing * (1 - STOP_BUFFER_RATIO)
    swing = max(candle.high for candle in window)
    return swing * (1 + STOP_BUFFER_RATIO)


def _midpoint(low: float, high: float) -> float:
    return (low + high) / 2


def _exclude_incomplete_candles(raw_candles: list[dict[str, Any] | Candle]) -> list[dict[str, Any] | Candle]:
    if not raw_candles:
        return []
    last_candle = raw_candles[-1]
    if isinstance(last_candle, Candle):
        return list(raw_candles)
    if _candle_is_incomplete(last_candle):
        return list(raw_candles[:-1])
    return list(raw_candles)


def _candle_is_incomplete(candle: dict[str, Any]) -> bool:
    for key in ("confirm", "confirmed", "isClosed", "closed", "is_closed"):
        value = candle.get(key)
        if value is None:
            continue
        return str(value).strip().lower() in {"0", "false", "no"}
    return False


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
                volume=float(item.get("volume") or 0.0),
            )
        except (TypeError, ValueError):
            return []
        if not _is_valid_number(candle.open, candle.high, candle.low, candle.close, candle.volume):
            return []
        normalized.append(candle)
    normalized.sort(key=lambda candle: candle.timestamp)
    return normalized


def _ensure_candles(raw_candles: list[dict[str, Any] | Candle]) -> list[Candle]:
    if not raw_candles:
        return []
    if all(isinstance(item, Candle) for item in raw_candles):
        return list(raw_candles)
    return _normalize_candles(raw_candles)


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


def _normalize_now(now: datetime | None, candles: list[Candle]) -> datetime:
    if now is None:
        if candles:
            return candles[-1].timestamp
        return datetime.now(UTC)
    return now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)


def _rejected_signal(
    symbol: str,
    status: str,
    reason: str,
    *,
    strategy_name: str | None = None,
    strategy: str | None = None,
    direction: str | None = None,
    entry: float | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    risk_reward: float | None = None,
    detected_at: str | None = None,
    confidence_score: int | None = 0,
) -> dict[str, Any]:
    resolved_strategy_name = strategy_name or strategy or STRATEGY_EMA_PULLBACK
    return StrategySignal(
        symbol=symbol,
        strategy_name=resolved_strategy_name,
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
        return 74 if rr >= 2.0 else 66
    if rr >= 2.5:
        return 90
    if rr >= 2.0:
        return 80
    return 50
