from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any

SWING_CONFIRMATION = 2
MIN_SETUP_CANDLES = 24
MIN_TRIGGER_CANDLES = 16
STRUCTURE_SCAN_WINDOW = 80
ORDER_BLOCK_LOOKBACK = 10
SWEEP_LOOKBACK = 10
DISPLACEMENT_BODY_MULTIPLE = 1.5
DISPLACEMENT_VOLUME_MULTIPLE = 1.2
STOP_BUFFER_RATIO = 0.001
TARGET_R_MULTIPLE = 1.5

STATUS_ACTIVE = "active"
STATUS_NEAR_SETUP = "near_setup"
STATUS_BLOCKED = "blocked"
STATUS_REJECTED = "rejected"


@dataclass(frozen=True)
class StructureCandle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class PriceZone:
    low: float
    high: float

    def to_dict(self) -> dict[str, float]:
        return {"low": round(min(self.low, self.high), 8), "high": round(max(self.low, self.high), 8)}


@dataclass(frozen=True)
class StructureEvent:
    direction: str
    event_type: str
    index: int
    reference_high: float
    reference_low: float
    prior_structure: str



def evaluate_multitimeframe_logic(
    symbol: str,
    candles_15m: list[dict[str, Any]],
    candles_5m: list[dict[str, Any]],
    *,
    trend_state: str | None = None,
) -> dict[str, Any]:
    setup = analyze_15m_setup(candles_15m, trend_state=trend_state)
    confirmation = confirm_5m_entry(candles_5m, setup)

    direction = setup.get("direction") or confirmation.get("direction")
    status = confirmation.get("status") if setup.get("qualified") else setup.get("status")
    reason = confirmation.get("reason") if setup.get("qualified") else setup.get("reason")

    return {
        "symbol": symbol,
        "status": status,
        "direction": direction,
        "reason": reason,
        "setup_15m": setup,
        "confirmation_5m": confirmation,
        "entry": confirmation.get("entry"),
        "stop_loss": confirmation.get("stop_loss"),
        "take_profit": confirmation.get("take_profit"),
        "risk_reward": confirmation.get("risk_reward"),
        "detected_at": confirmation.get("detected_at") or setup.get("detected_at"),
        "confidence_score": _combined_confidence(setup, confirmation),
    }



def analyze_15m_setup(
    candles: list[dict[str, Any]],
    *,
    trend_state: str | None = None,
) -> dict[str, Any]:
    normalized = _normalize_candles(candles)
    if len(normalized) < MIN_SETUP_CANDLES:
        return _setup_result(
            status=STATUS_REJECTED,
            reason="missing_15m_data",
            candle_count=len(normalized),
        )

    event = _latest_structure_event(normalized)
    if event is None:
        return _setup_result(
            status=STATUS_BLOCKED,
            reason="15m_structure_event_not_found",
            candle_count=len(normalized),
        )

    if not _trend_direction_allowed(trend_state, event.direction):
        return _setup_result(
            status=STATUS_BLOCKED,
            reason="15m_structure_conflicts_with_1h_trend",
            candle_count=len(normalized),
            direction=event.direction,
            structure_event=event,
        )

    order_block = _find_order_block(normalized, event.index, event.direction)
    fvg = _find_fvg(normalized, event.index, event.direction)
    sweep = _find_liquidity_sweep(normalized, event)
    dealing_range = PriceZone(event.reference_low, event.reference_high)
    range_midpoint = (dealing_range.low + dealing_range.high) / 2.0

    candidate_zone = _intersect_zones(order_block, fvg) or fvg or order_block
    candidate_price = _zone_midpoint(candidate_zone) if candidate_zone else normalized[event.index].close
    location = _premium_discount_location(candidate_price, range_midpoint)
    correct_location = (
        (event.direction == "long" and location == "discount")
        or (event.direction == "short" and location == "premium")
    )

    checks = {
        "structure_event": True,
        "liquidity_sweep": sweep is not None,
        "fvg": fvg is not None,
        "order_block": order_block is not None,
        "premium_discount": correct_location,
    }
    score = sum(20 for passed in checks.values() if passed)
    qualified = all(checks.values())
    status = STATUS_NEAR_SETUP if qualified else STATUS_BLOCKED
    reason = "15m_setup_qualified_waiting_for_5m" if qualified else _first_failed_setup_reason(checks)
    event_candle = normalized[event.index]

    invalidation = None
    if order_block:
        invalidation = order_block.low if event.direction == "long" else order_block.high

    return _setup_result(
        status=status,
        reason=reason,
        candle_count=len(normalized),
        direction=event.direction,
        structure_event=event,
        liquidity_sweep=sweep,
        fvg=fvg,
        order_block=order_block,
        dealing_range=dealing_range,
        range_midpoint=range_midpoint,
        location=location,
        checks=checks,
        score=score,
        qualified=qualified,
        invalidation=invalidation,
        detected_at=event_candle.timestamp.isoformat(),
    )



def confirm_5m_entry(candles: list[dict[str, Any]], setup: dict[str, Any]) -> dict[str, Any]:
    direction = str(setup.get("direction") or "")
    if not setup.get("qualified") or direction not in {"long", "short"}:
        return _confirmation_result(
            status=STATUS_BLOCKED,
            reason="15m_setup_not_qualified",
            direction=direction or None,
        )

    normalized = _normalize_candles(candles)
    if len(normalized) < MIN_TRIGGER_CANDLES:
        return _confirmation_result(
            status=STATUS_REJECTED,
            reason="missing_5m_data",
            direction=direction,
            candle_count=len(normalized),
        )

    event = _latest_structure_event(normalized)
    choch_confirmed = bool(event and event.direction == direction and event.event_type == "CHOCH")
    if event is None:
        return _confirmation_result(
            status=STATUS_NEAR_SETUP,
            reason="waiting_for_5m_choch",
            direction=direction,
            candle_count=len(normalized),
        )

    displacement = _displacement_confirmed(normalized, event.index, direction)
    local_fvg = _find_fvg(normalized, event.index, direction)
    local_order_block = _find_order_block(normalized, event.index, direction)
    fvg_retest = _zone_retested(normalized, event.index, local_fvg, direction)
    ob_reaction = _order_block_reaction(normalized, event.index, local_order_block, direction)

    checks = {
        "choch": choch_confirmed,
        "displacement": displacement,
        "fvg_retest": fvg_retest,
        "order_block_reaction": ob_reaction,
    }
    trigger_confirmed = choch_confirmed and displacement and (fvg_retest or ob_reaction)
    score = 0
    score += 35 if choch_confirmed else 0
    score += 30 if displacement else 0
    score += 20 if fvg_retest else 0
    score += 15 if ob_reaction else 0

    if not trigger_confirmed:
        return _confirmation_result(
            status=STATUS_NEAR_SETUP,
            reason=_first_failed_trigger_reason(checks),
            direction=direction,
            candle_count=len(normalized),
            structure_event=event,
            displacement=displacement,
            fvg=local_fvg,
            order_block=local_order_block,
            fvg_retest=fvg_retest,
            ob_reaction=ob_reaction,
            checks=checks,
            score=score,
        )

    trigger_candle = normalized[-1]
    entry = trigger_candle.close
    stop_loss = _entry_stop_loss(
        direction=direction,
        setup_invalidation=_optional_float(setup.get("invalidation")),
        local_order_block=local_order_block,
        recent_candles=normalized[max(0, event.index - 4) :],
    )
    if stop_loss is None:
        return _confirmation_result(
            status=STATUS_REJECTED,
            reason="invalid_5m_trade_levels",
            direction=direction,
            candle_count=len(normalized),
            checks=checks,
            score=score,
        )

    risk = entry - stop_loss if direction == "long" else stop_loss - entry
    if risk <= 0:
        return _confirmation_result(
            status=STATUS_REJECTED,
            reason="invalid_5m_trade_geometry",
            direction=direction,
            candle_count=len(normalized),
            checks=checks,
            score=score,
        )

    take_profit = entry + (risk * TARGET_R_MULTIPLE) if direction == "long" else entry - (risk * TARGET_R_MULTIPLE)
    return _confirmation_result(
        status=STATUS_ACTIVE,
        reason="5m_entry_confirmed",
        direction=direction,
        candle_count=len(normalized),
        structure_event=event,
        displacement=displacement,
        fvg=local_fvg,
        order_block=local_order_block,
        fvg_retest=fvg_retest,
        ob_reaction=ob_reaction,
        checks=checks,
        score=score,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_reward=TARGET_R_MULTIPLE,
        detected_at=trigger_candle.timestamp.isoformat(),
    )



def _latest_structure_event(candles: list[StructureCandle]) -> StructureEvent | None:
    scan_start = max((SWING_CONFIRMATION * 2) + 4, len(candles) - STRUCTURE_SCAN_WINDOW)
    latest: StructureEvent | None = None
    swings = _confirmed_swings(candles)

    for index in range(scan_start, len(candles)):
        eligible_highs = [item for item in swings["highs"] if item["index"] <= index - SWING_CONFIRMATION - 1]
        eligible_lows = [item for item in swings["lows"] if item["index"] <= index - SWING_CONFIRMATION - 1]
        if len(eligible_highs) < 2 or len(eligible_lows) < 2:
            continue

        last_high, previous_high = eligible_highs[-1], eligible_highs[-2]
        last_low, previous_low = eligible_lows[-1], eligible_lows[-2]
        prior_structure = _structure_label(previous_high, last_high, previous_low, last_low)
        candle = candles[index]
        reference_high = float(last_high["price"])
        reference_low = float(last_low["price"])

        if candle.close > reference_high:
            latest = StructureEvent(
                direction="long",
                event_type="CHOCH" if prior_structure == "bearish" else "BOS",
                index=index,
                reference_high=reference_high,
                reference_low=reference_low,
                prior_structure=prior_structure,
            )
        elif candle.close < reference_low:
            latest = StructureEvent(
                direction="short",
                event_type="CHOCH" if prior_structure == "bullish" else "BOS",
                index=index,
                reference_high=reference_high,
                reference_low=reference_low,
                prior_structure=prior_structure,
            )

    return latest



def _confirmed_swings(candles: list[StructureCandle]) -> dict[str, list[dict[str, Any]]]:
    highs: list[dict[str, Any]] = []
    lows: list[dict[str, Any]] = []
    for index in range(SWING_CONFIRMATION, len(candles) - SWING_CONFIRMATION):
        candle = candles[index]
        neighbours = candles[index - SWING_CONFIRMATION : index] + candles[index + 1 : index + SWING_CONFIRMATION + 1]
        if all(candle.high > item.high for item in neighbours):
            highs.append({"index": index, "price": candle.high})
        if all(candle.low < item.low for item in neighbours):
            lows.append({"index": index, "price": candle.low})
    return {"highs": highs, "lows": lows}



def _structure_label(
    previous_high: dict[str, Any],
    last_high: dict[str, Any],
    previous_low: dict[str, Any],
    last_low: dict[str, Any],
) -> str:
    higher_high = float(last_high["price"]) > float(previous_high["price"])
    higher_low = float(last_low["price"]) > float(previous_low["price"])
    lower_high = float(last_high["price"]) < float(previous_high["price"])
    lower_low = float(last_low["price"]) < float(previous_low["price"])
    if higher_high and higher_low:
        return "bullish"
    if lower_high and lower_low:
        return "bearish"
    return "range"



def _find_liquidity_sweep(candles: list[StructureCandle], event: StructureEvent) -> dict[str, Any] | None:
    start = max(0, event.index - SWEEP_LOOKBACK)
    for index in range(event.index - 1, start - 1, -1):
        candle = candles[index]
        if event.direction == "long" and candle.low < event.reference_low and candle.close > event.reference_low:
            return {
                "side": "sell_side",
                "index": index,
                "level": round(event.reference_low, 8),
                "timestamp": candle.timestamp.isoformat(),
            }
        if event.direction == "short" and candle.high > event.reference_high and candle.close < event.reference_high:
            return {
                "side": "buy_side",
                "index": index,
                "level": round(event.reference_high, 8),
                "timestamp": candle.timestamp.isoformat(),
            }
    return None



def _find_order_block(candles: list[StructureCandle], event_index: int, direction: str) -> PriceZone | None:
    start = max(0, event_index - ORDER_BLOCK_LOOKBACK)
    for candle in reversed(candles[start:event_index]):
        if direction == "long" and candle.close < candle.open:
            return PriceZone(candle.low, candle.high)
        if direction == "short" and candle.close > candle.open:
            return PriceZone(candle.low, candle.high)
    return None



def _find_fvg(candles: list[StructureCandle], event_index: int, direction: str) -> PriceZone | None:
    center_start = max(1, event_index - 2)
    center_end = min(len(candles) - 2, event_index + 2)
    for center in range(center_end, center_start - 1, -1):
        left = candles[center - 1]
        right = candles[center + 1]
        if direction == "long" and left.high < right.low:
            return PriceZone(left.high, right.low)
        if direction == "short" and left.low > right.high:
            return PriceZone(right.high, left.low)
    return None



def _displacement_confirmed(candles: list[StructureCandle], event_index: int, direction: str) -> bool:
    if event_index < 5 or event_index >= len(candles):
        return False
    event_candle = candles[event_index]
    reference = candles[max(0, event_index - 10) : event_index]
    if not reference:
        return False

    body = abs(event_candle.close - event_candle.open)
    average_body = sum(abs(item.close - item.open) for item in reference) / len(reference)
    body_ok = body >= max(average_body * DISPLACEMENT_BODY_MULTIPLE, 1e-12)
    direction_ok = (
        event_candle.close > event_candle.open if direction == "long" else event_candle.close < event_candle.open
    )

    positive_volumes = [item.volume for item in reference if item.volume > 0]
    if positive_volumes and event_candle.volume > 0:
        average_volume = sum(positive_volumes) / len(positive_volumes)
        volume_ok = event_candle.volume >= average_volume * DISPLACEMENT_VOLUME_MULTIPLE
    else:
        volume_ok = True
    return body_ok and direction_ok and volume_ok



def _zone_retested(
    candles: list[StructureCandle],
    event_index: int,
    zone: PriceZone | None,
    direction: str,
) -> bool:
    if zone is None or event_index >= len(candles) - 1:
        return False
    for candle in candles[event_index + 1 :]:
        if _touches_zone(candle, zone) and _directional_rejection(candle, direction):
            return True
    return False



def _order_block_reaction(
    candles: list[StructureCandle],
    event_index: int,
    zone: PriceZone | None,
    direction: str,
) -> bool:
    if zone is None or event_index >= len(candles) - 1:
        return False
    return any(
        _touches_zone(candle, zone) and _directional_rejection(candle, direction)
        for candle in candles[event_index + 1 :]
    )



def _directional_rejection(candle: StructureCandle, direction: str) -> bool:
    if direction == "long":
        return candle.close > candle.open and candle.close >= (candle.low + candle.high) / 2.0
    return candle.close < candle.open and candle.close <= (candle.low + candle.high) / 2.0



def _touches_zone(candle: StructureCandle, zone: PriceZone) -> bool:
    low = min(zone.low, zone.high)
    high = max(zone.low, zone.high)
    return candle.low <= high and candle.high >= low



def _entry_stop_loss(
    *,
    direction: str,
    setup_invalidation: float | None,
    local_order_block: PriceZone | None,
    recent_candles: list[StructureCandle],
) -> float | None:
    candidates: list[float] = []
    if setup_invalidation is not None:
        candidates.append(setup_invalidation)
    if local_order_block is not None:
        candidates.append(local_order_block.low if direction == "long" else local_order_block.high)
    if recent_candles:
        candidates.append(
            min(item.low for item in recent_candles)
            if direction == "long"
            else max(item.high for item in recent_candles)
        )
    if not candidates:
        return None
    raw = min(candidates) if direction == "long" else max(candidates)
    return raw * (1 - STOP_BUFFER_RATIO) if direction == "long" else raw * (1 + STOP_BUFFER_RATIO)



def _setup_result(
    *,
    status: str,
    reason: str,
    candle_count: int,
    direction: str | None = None,
    structure_event: StructureEvent | None = None,
    liquidity_sweep: dict[str, Any] | None = None,
    fvg: PriceZone | None = None,
    order_block: PriceZone | None = None,
    dealing_range: PriceZone | None = None,
    range_midpoint: float | None = None,
    location: str | None = None,
    checks: dict[str, bool] | None = None,
    score: int = 0,
    qualified: bool = False,
    invalidation: float | None = None,
    detected_at: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "direction": direction,
        "candle_count": candle_count,
        "structure_event": asdict(structure_event) if structure_event else None,
        "liquidity_sweep": liquidity_sweep,
        "fvg": fvg.to_dict() if fvg else None,
        "order_block": order_block.to_dict() if order_block else None,
        "dealing_range": dealing_range.to_dict() if dealing_range else None,
        "range_midpoint": round(range_midpoint, 8) if range_midpoint is not None else None,
        "location": location,
        "checks": checks or {},
        "score": score,
        "qualified": qualified,
        "invalidation": round(invalidation, 8) if invalidation is not None else None,
        "detected_at": detected_at,
    }



def _confirmation_result(
    *,
    status: str,
    reason: str,
    direction: str | None,
    candle_count: int = 0,
    structure_event: StructureEvent | None = None,
    displacement: bool = False,
    fvg: PriceZone | None = None,
    order_block: PriceZone | None = None,
    fvg_retest: bool = False,
    ob_reaction: bool = False,
    checks: dict[str, bool] | None = None,
    score: int = 0,
    entry: float | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    risk_reward: float | None = None,
    detected_at: str | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "direction": direction,
        "candle_count": candle_count,
        "structure_event": asdict(structure_event) if structure_event else None,
        "displacement": displacement,
        "fvg": fvg.to_dict() if fvg else None,
        "order_block": order_block.to_dict() if order_block else None,
        "fvg_retest": fvg_retest,
        "order_block_reaction": ob_reaction,
        "checks": checks or {},
        "score": score,
        "entry": round(entry, 8) if entry is not None else None,
        "stop_loss": round(stop_loss, 8) if stop_loss is not None else None,
        "take_profit": round(take_profit, 8) if take_profit is not None else None,
        "risk_reward": round(risk_reward, 4) if risk_reward is not None else None,
        "detected_at": detected_at,
    }



def _first_failed_setup_reason(checks: dict[str, bool]) -> str:
    mapping = {
        "liquidity_sweep": "15m_liquidity_sweep_not_found",
        "fvg": "15m_fvg_not_found",
        "order_block": "15m_order_block_not_found",
        "premium_discount": "15m_premium_discount_invalid",
    }
    for name in ("liquidity_sweep", "fvg", "order_block", "premium_discount"):
        if not checks.get(name):
            return mapping[name]
    return "15m_setup_not_qualified"



def _first_failed_trigger_reason(checks: dict[str, bool]) -> str:
    if not checks.get("choch"):
        return "waiting_for_5m_choch"
    if not checks.get("displacement"):
        return "waiting_for_5m_displacement"
    if not checks.get("fvg_retest") and not checks.get("order_block_reaction"):
        return "waiting_for_5m_retest_or_ob_reaction"
    return "5m_trigger_not_confirmed"



def _combined_confidence(setup: dict[str, Any], confirmation: dict[str, Any]) -> int:
    setup_score = int(setup.get("score") or 0)
    confirmation_score = int(confirmation.get("score") or 0)
    return min(100, round((setup_score * 0.55) + (confirmation_score * 0.45)))



def _trend_direction_allowed(trend_state: str | None, direction: str) -> bool:
    normalized = str(trend_state or "").upper()
    if normalized == "UPTREND":
        return direction == "long"
    if normalized == "DOWNTREND":
        return direction == "short"
    return normalized not in {"SIDEWAYS", "INSUFFICIENT_DATA"}



def _intersect_zones(first: PriceZone | None, second: PriceZone | None) -> PriceZone | None:
    if first is None or second is None:
        return None
    low = max(min(first.low, first.high), min(second.low, second.high))
    high = min(max(first.low, first.high), max(second.low, second.high))
    return PriceZone(low, high) if high > low else None



def _zone_midpoint(zone: PriceZone) -> float:
    return (min(zone.low, zone.high) + max(zone.low, zone.high)) / 2.0



def _premium_discount_location(price: float, midpoint: float) -> str:
    if price < midpoint:
        return "discount"
    if price > midpoint:
        return "premium"
    return "equilibrium"



def _normalize_candles(candles: list[dict[str, Any]]) -> list[StructureCandle]:
    normalized: list[StructureCandle] = []
    seen: set[datetime] = set()
    for item in candles:
        timestamp = _parse_timestamp(item.get("timestamp"))
        open_price = _number(item.get("open"))
        high = _number(item.get("high"))
        low = _number(item.get("low"))
        close = _number(item.get("close"))
        volume = _number(item.get("volume")) or 0.0
        if timestamp is None or None in {open_price, high, low, close}:
            continue
        if timestamp in seen or high < low or min(open_price, high, low, close) <= 0:
            continue
        seen.add(timestamp)
        normalized.append(
            StructureCandle(
                timestamp=timestamp,
                open=float(open_price),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=max(float(volume), 0.0),
            )
        )
    normalized.sort(key=lambda candle: candle.timestamp)
    return normalized



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



def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None



def _optional_float(value: Any) -> float | None:
    return _number(value)
