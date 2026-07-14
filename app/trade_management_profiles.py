from __future__ import annotations

from math import isfinite
from typing import Any


LEGACY_MAX_HOLD_SECONDS = 4 * 60 * 60

TRADE_MANAGEMENT_PROFILES: dict[str, dict[str, Any]] = {
    "scalping": {
        "profile_name": "scalping_v2",
        "tp1_r": 1.5,
        "tp2_r": 2.0,
        "runner_r": 2.5,
        "tp1_fraction": 0.50,
        "tp2_fraction": 0.25,
        "runner_fraction": 0.25,
        "break_even_trigger_r": 1.0,
        "post_tp2_stop_r": 1.5,
        "trailing_enabled": False,
        "max_hold_seconds": 30 * 60,
    },
    "intraday": {
        "profile_name": "intraday_v1",
        "tp1_r": 2.0,
        "tp2_r": 2.5,
        "runner_r": 3.0,
        "tp1_fraction": 0.50,
        "tp2_fraction": 0.25,
        "runner_fraction": 0.25,
        "break_even_trigger_r": 2.0,
        "post_tp2_stop_r": None,
        "trailing_enabled": True,
        "max_hold_seconds": 6 * 60 * 60,
    },
}


def build_profile_management_state(
    *,
    entry: float,
    stop_loss: float,
    take_profit: float,
    quantity: float,
    direction: str,
    trade_type: str,
    observed_entry_fee: float = 0.0,
) -> dict[str, Any]:
    normalized_type = normalize_trade_type(trade_type)
    if normalized_type is None:
        raise ValueError("trade_type must be scalping or intraday")
    profile = TRADE_MANAGEMENT_PROFILES[normalized_type]
    risk = abs(float(entry) - float(stop_loss))
    qty = max(float(quantity), 0.0)
    entry_fee = max(float(observed_entry_fee or 0.0), 0.0)
    estimated_round_trip_fee = entry_fee * 2.0
    fee_buffer_per_unit = estimated_round_trip_fee / qty if qty > 0 and estimated_round_trip_fee > 0 else 0.0
    break_even_price = float(entry) + fee_buffer_per_unit if direction == "long" else float(entry) - fee_buffer_per_unit

    return {
        "profile_name": profile["profile_name"],
        "trade_type": normalized_type,
        "tp1": price_at_r(entry, stop_loss, direction, profile["tp1_r"]),
        "tp2": price_at_r(entry, stop_loss, direction, profile["tp2_r"]),
        "strategy_take_profit": float(take_profit),
        "runner_target": price_at_r(entry, stop_loss, direction, profile["runner_r"]),
        "tp1_r": profile["tp1_r"],
        "tp2_r": profile["tp2_r"],
        "runner_r": profile["runner_r"],
        "tp1_fraction": profile["tp1_fraction"],
        "tp2_fraction": profile["tp2_fraction"],
        "runner_fraction": profile["runner_fraction"],
        "break_even_trigger_r": profile["break_even_trigger_r"],
        "break_even_price": break_even_price,
        "observed_entry_fee": entry_fee,
        "estimated_round_trip_fee": estimated_round_trip_fee,
        "fee_buffer_per_unit": fee_buffer_per_unit,
        "fee_buffer_source": "observed_entry_fee_x2" if entry_fee > 0 else "entry_fee_unavailable",
        "post_tp2_stop_r": profile["post_tp2_stop_r"],
        "trailing_enabled": profile["trailing_enabled"],
        "max_hold_seconds": profile["max_hold_seconds"],
        "initial_quantity": qty,
        "remaining_quantity": qty,
        "tp1_done": False,
        "tp2_done": False,
        "break_even_set": False,
        "trailing_stop": None,
        "profit_lock_stop": None,
        "last_momentum_check": None,
    }


def extract_observed_entry_fee(trade: dict[str, Any]) -> float:
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    fill = metadata.get("fill_confirmation") if isinstance(metadata.get("fill_confirmation"), dict) else {}
    raw = fill.get("raw") if isinstance(fill.get("raw"), dict) else {}

    for key in ("cumExecFee", "execFee", "fee"):
        value = _non_negative_float(raw.get(key))
        if value is not None:
            return value

    details = raw.get("cumFeeDetail") or raw.get("feeDetail")
    if isinstance(details, dict):
        values = [_non_negative_float(value) for value in details.values()]
        return sum(value for value in values if value is not None)
    return 0.0


def normalize_trade_type(value: Any) -> str | None:
    normalized = str(value or "").lower().strip()
    return normalized if normalized in TRADE_MANAGEMENT_PROFILES else None


def trade_type_from_trade(trade: dict[str, Any], management: dict[str, Any] | None = None) -> str | None:
    state = management or _management_state(trade)
    explicit = state.get("trade_type")
    if explicit in TRADE_MANAGEMENT_PROFILES:
        return str(explicit)

    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    validation = metadata.get("risk_validation") if isinstance(metadata.get("risk_validation"), dict) else {}
    candidate = trade.get("trade_type") or metadata.get("trade_type") or validation.get("trade_type")
    return normalize_trade_type(candidate)


def is_profiled_management(management: dict[str, Any]) -> bool:
    return str(management.get("profile_name") or "") in {
        "scalping_v2",
        "intraday_v1",
    }


def is_scalping_management(management: dict[str, Any]) -> bool:
    return str(management.get("profile_name") or "") == "scalping_v2"


def trailing_enabled(management: dict[str, Any]) -> bool:
    if not is_profiled_management(management):
        return True
    return bool(management.get("trailing_enabled"))


def max_hold_seconds(management: dict[str, Any]) -> int:
    value = _positive_float(management.get("max_hold_seconds"))
    return int(value) if value is not None else LEGACY_MAX_HOLD_SECONDS


def break_even_stop(trade: dict[str, Any], management: dict[str, Any], entry: float | None = None) -> float:
    candidate = _positive_float(management.get("break_even_price"))
    if candidate is not None:
        return candidate
    fallback = _positive_float(entry)
    if fallback is not None:
        return fallback
    return _positive_float(trade.get("entry")) or 0.0


def post_tp2_stop(trade: dict[str, Any], management: dict[str, Any], mark_price: float) -> float:
    if is_scalping_management(management):
        tp1 = _positive_float(management.get("tp1"))
        if tp1 is not None:
            return tp1
    return trailing_stop(trade, mark_price)


def trailing_stop(trade: dict[str, Any], mark_price: float, multiple: float = 1.0) -> float:
    entry = _positive_float(trade.get("entry")) or 0.0
    stop_loss = _positive_float(trade.get("stop_loss")) or 0.0
    risk = abs(entry - stop_loss)
    if str(trade.get("direction") or "").lower() == "long":
        return float(mark_price) - risk * float(multiple)
    return float(mark_price) + risk * float(multiple)


def price_at_r(entry: float, stop_loss: float, direction: str, r_multiple: float) -> float:
    risk = abs(float(entry) - float(stop_loss))
    if str(direction or "").lower() == "long":
        return float(entry) + risk * float(r_multiple)
    return float(entry) - risk * float(r_multiple)


def progress_r(*, entry: float, stop_loss: float, direction: str, mark_price: float) -> float:
    risk = abs(float(entry) - float(stop_loss))
    if risk <= 0:
        return 0.0
    if str(direction or "").lower() == "long":
        return (float(mark_price) - float(entry)) / risk
    return (float(entry) - float(mark_price)) / risk


def _management_state(trade: dict[str, Any]) -> dict[str, Any]:
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    management = trade.get("management") or metadata.get("management") or {}
    return dict(management)


def _positive_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) and numeric > 0 else None


def _non_negative_float(value: Any) -> float | None:
    try:
        numeric = abs(float(value))
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None
