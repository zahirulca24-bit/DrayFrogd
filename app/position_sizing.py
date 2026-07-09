from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from app.exchange import BybitClient


SIGNAL_MAX_AGE_MINUTES = 10
DEFAULT_MIN_NOTIONAL = 5.0


def calculate_position_size(
    *,
    signal: dict[str, Any],
    wallet: dict[str, Any],
    symbol_info: dict[str, Any],
    active_trades: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    settings: dict[str, Any],
    client: BybitClient,
) -> dict[str, Any]:
    normalized = _normalize_signal(signal)
    if normalized is None:
        return _reject("Invalid signal values")

    stale_reason = _stale_reason(normalized.get("detected_at"))
    if stale_reason:
        return _reject(stale_reason)

    entry = normalized["entry"]
    stop_loss = normalized["stop_loss"]
    sl_distance = abs(entry - stop_loss)
    if sl_distance <= 0 or not isfinite(sl_distance):
        return _reject("Invalid SL distance")

    equity = _extract_positive(wallet, ["totalEquity", "totalWalletBalance", "totalMarginBalance"])
    if equity is None:
        return _reject("Fresh account equity is unavailable")

    available_balance = _extract_positive(wallet, ["totalAvailableBalance", "totalAvailableBalanceByMp", "totalWalletBalance"])
    if available_balance is None:
        return _reject("Available balance is unavailable")

    risk_per_trade = _positive_float(settings.get("risk_per_trade"))
    leverage_cap = _positive_float(settings.get("leverage_cap"))
    exposure_cap = _positive_float(settings.get("exposure_cap"))
    if risk_per_trade is None:
        return _reject("Risk percent setting is invalid")
    if leverage_cap is None:
        return _reject("Leverage cap setting is invalid")
    if exposure_cap is None:
        return _reject("Exposure cap setting is invalid")

    qty_step = symbol_info.get("qtyStep")
    tick_size = symbol_info.get("tickSize")
    min_order_qty = _positive_float(symbol_info.get("minOrderQty"))
    min_notional = _positive_float(symbol_info.get("minNotionalValue")) or DEFAULT_MIN_NOTIONAL
    if not qty_step:
        return _reject("Symbol qtyStep is unavailable")
    if not tick_size:
        return _reject("Symbol tickSize is unavailable")

    risk_amount = equity * risk_per_trade
    raw_quantity = risk_amount / sl_distance
    normalized_quantity = client.normalize_quantity(raw_quantity, str(qty_step))
    quantity = _positive_float(normalized_quantity)
    if quantity is None:
        return _reject("Calculated quantity is zero after qtyStep normalization")

    if min_order_qty is not None and quantity < min_order_qty:
        normalized_quantity = client.normalize_quantity(min_order_qty, str(qty_step))
        quantity = _positive_float(normalized_quantity)
        if quantity is None:
            return _reject("Minimum order quantity normalizes to zero")

    notional = quantity * entry
    if notional < min_notional:
        min_qty = min_notional / entry
        normalized_quantity = client.normalize_quantity(min_qty, str(qty_step))
        quantity = _positive_float(normalized_quantity)
        if quantity is None:
            return _reject("Minimum notional quantity normalizes to zero")
        notional = quantity * entry
        if notional < min_notional:
            return _reject("Minimum notional cannot be satisfied with symbol precision")

    margin_buffer = available_balance * 0.95
    max_notional_by_margin = margin_buffer * leverage_cap

    if notional > max_notional_by_margin:
        capped_qty = max_notional_by_margin / entry
        normalized_quantity = client.normalize_quantity(capped_qty, str(qty_step))
        quantity = _positive_float(normalized_quantity)

        if quantity is None:
            return _reject("Available balance is too low after margin safety buffer")

        notional = quantity * entry
        required_margin = notional / leverage_cap

        if min_order_qty is not None and quantity < min_order_qty:
            return _reject("Available balance cannot satisfy minimum order quantity")

        if notional < min_notional:
            return _reject("Available balance cannot satisfy minimum notional")
    else:
        required_margin = notional / leverage_cap

    existing_margin = _current_margin(active_trades, positions, leverage_cap)
    max_allowed_margin = equity * exposure_cap
    if existing_margin + required_margin > max_allowed_margin:
        return _reject("Margin exposure cap exceeded")

    actual_risk_amount = quantity * sl_distance
    if actual_risk_amount <= 0 or not isfinite(actual_risk_amount):
        return _reject("Position risk is invalid")
    if actual_risk_amount > risk_amount * 1.001:
        return _reject("Minimum quantity exceeds configured risk percent")

    return {
        "allowed": True,
        "reason": "",
        "quantity": normalized_quantity,
        "quantity_value": quantity,
        "entry": entry,
        "stop_loss": stop_loss,
        "sl_distance": sl_distance,
        "risk_percent": risk_per_trade,
        "risk_amount": actual_risk_amount,
        "target_risk_amount": risk_amount,
        "notional": notional,
        "required_margin": required_margin,
        "equity": equity,
        "available_balance": available_balance,
        "leverage_cap": leverage_cap,
        "exposure_cap": exposure_cap,
        "current_margin_exposure": existing_margin,
        "max_allowed_margin_exposure": max_allowed_margin,
        "current_exposure": existing_margin,
        "max_allowed_exposure": max_allowed_margin,
        "min_notional": min_notional,
        "qty_step": str(qty_step),
        "tick_size": str(tick_size),
    }


def _normalize_signal(signal: dict[str, Any]) -> dict[str, Any] | None:
    try:
        entry = float(signal.get("entry"))
        stop_loss = float(signal.get("stop_loss"))
        take_profit = float(signal.get("take_profit"))
    except (TypeError, ValueError):
        return None

    if not all(isfinite(value) and value > 0 for value in [entry, stop_loss, take_profit]):
        return None
    if entry == stop_loss:
        return None

    return {
        "symbol": str(signal.get("symbol", "")).upper().strip(),
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "detected_at": signal.get("detected_at"),
    }


def _stale_reason(value: Any) -> str:
    if not value:
        return ""

    try:
        detected_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return "Signal timestamp is invalid"

    if detected_at.tzinfo is None:
        detected_at = detected_at.replace(tzinfo=UTC)
    if datetime.now(UTC) - detected_at.astimezone(UTC) > timedelta(minutes=SIGNAL_MAX_AGE_MINUTES):
        return "Signal is stale for position sizing"
    return ""


def _current_margin(
    active_trades: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    fallback_leverage: float,
) -> float:
    margin = 0.0

    for trade in active_trades:
        required_margin = _positive_float(trade.get("required_margin"))
        if required_margin is not None:
            margin += required_margin
            continue

        quantity = _positive_float(trade.get("quantity")) or 0.0
        entry = _positive_float(trade.get("entry")) or 0.0
        leverage = _positive_float(trade.get("leverage")) or fallback_leverage
        if leverage > 0:
            margin += abs(quantity * entry) / leverage

    for position in positions:
        position_margin = (
            _positive_float(position.get("positionIM"))
            or _positive_float(position.get("positionInitialMargin"))
        )
        if position_margin is not None:
            margin += abs(position_margin)
            continue

        position_value = _positive_float(position.get("positionValue"))
        leverage = _positive_float(position.get("leverage")) or fallback_leverage
        if position_value is not None and leverage > 0:
            margin += abs(position_value) / leverage
            continue

        size = _positive_float(position.get("size")) or 0.0
        mark_price = _positive_float(position.get("markPrice")) or 0.0
        if leverage > 0:
            margin += abs(size * mark_price) / leverage

    return margin


def _extract_positive(wallet: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = _positive_float(wallet.get(key))
        if value is not None:
            return value
    return None


def _positive_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(numeric) or numeric <= 0:
        return None
    return numeric


def _reject(reason: str) -> dict[str, Any]:
    return {"allowed": False, "reason": reason, "quantity": None}
