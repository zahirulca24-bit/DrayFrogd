from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from app.config import settings as app_settings
from app.engines.profiles import get_engine_profile
from app.exchange import BybitClient
from app.trading_costs import calculate_cost_adjusted_geometry


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
    if not _valid_signal_geometry(normalized):
        return _reject("Invalid SL/TP geometry for direction")

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

    supplied_fixed_risk = _positive_float(settings.get("risk_amount"))
    fixed_risk_mode = supplied_fixed_risk is not None
    target_risk_amount = supplied_fixed_risk
    legacy_risk_percent = _positive_float(settings.get("risk_per_trade"))
    if target_risk_amount is None and legacy_risk_percent is not None:
        target_risk_amount = equity * legacy_risk_percent
    if target_risk_amount is None:
        return _reject("Fixed USDT risk amount is unavailable")

    leverage_cap = _positive_float(settings.get("leverage_cap"))
    exposure_cap = _positive_float(settings.get("exposure_cap"))
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

    fee_bps = _non_negative_float(settings.get("fee_bps"))
    if fee_bps is None:
        fee_bps = _non_negative_float(settings.get("fee_bps_per_side"))
    if fee_bps is None:
        fee_bps = max(float(app_settings.execution_taker_fee_bps), 0.0)

    slippage_bps = _non_negative_float(settings.get("slippage_bps"))
    if slippage_bps is None:
        slippage_bps = max(float(app_settings.execution_slippage_bps), 0.0)

    min_net_risk_reward = _non_negative_float(settings.get("min_risk_reward"))
    if min_net_risk_reward is None:
        min_net_risk_reward = _non_negative_float(signal.get("engine_min_risk_reward"))
    if min_net_risk_reward is None:
        try:
            min_net_risk_reward = get_engine_profile(signal.get("trade_type")).min_risk_reward
        except ValueError:
            min_net_risk_reward = 0.0

    unit_economics = calculate_cost_adjusted_geometry(
        direction=normalized["direction"],
        entry=entry,
        stop_loss=stop_loss,
        take_profit=normalized["take_profit"],
        quantity=1.0,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )
    if unit_economics is None:
        return _reject("Invalid entry/SL/TP geometry")
    if unit_economics["net_reward"] <= 0:
        return _reject("Estimated fees and slippage eliminate the trade reward")
    if unit_economics["net_risk_reward"] + 1e-9 < min_net_risk_reward:
        return _reject(
            f"Net risk reward {unit_economics['net_risk_reward']:.4f} is below "
            f"minimum {min_net_risk_reward:.4f} after fees and slippage"
        )

    risk_per_unit_with_fees = unit_economics["net_risk"]
    raw_quantity = target_risk_amount / risk_per_unit_with_fees
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

    economics = calculate_cost_adjusted_geometry(
        direction=normalized["direction"],
        entry=entry,
        stop_loss=stop_loss,
        take_profit=normalized["take_profit"],
        quantity=quantity,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )
    if economics is None:
        return _reject("Position economics are invalid")

    price_risk_amount = economics["gross_risk"]
    estimated_open_fee = economics["estimated_entry_fee"]
    estimated_stop_fee = economics["estimated_stop_exit_fee"]
    estimated_round_trip_fees = estimated_open_fee + estimated_stop_fee
    actual_risk_amount = economics["net_risk"]
    if price_risk_amount <= 0 or actual_risk_amount <= 0 or not isfinite(actual_risk_amount):
        return _reject("Position risk is invalid")
    if actual_risk_amount > target_risk_amount * 1.001:
        return _reject("Minimum quantity exceeds configured fee-inclusive USDT risk")
    if economics["net_risk_reward"] + 1e-9 < min_net_risk_reward:
        return _reject(
            f"Net risk reward {economics['net_risk_reward']:.4f} is below "
            f"minimum {min_net_risk_reward:.4f} after quantity normalization"
        )

    existing_margin = _current_margin(active_trades, positions, leverage_cap)
    max_allowed_margin = equity * exposure_cap
    remaining_exposure_margin = max_allowed_margin - existing_margin
    margin_buffer = available_balance * 0.95

    if not fixed_risk_mode:
        # Preserve the previous API behavior for legacy percentage sizing.
        selected_leverage = leverage_cap
        minimum_required_leverage = selected_leverage
        required_margin = notional / selected_leverage
        if required_margin > margin_buffer + 1e-9:
            return _reject("Required margin exceeds available balance")
        if existing_margin + required_margin > max_allowed_margin + 1e-9:
            return _reject("Exposure cap exceeded")
    else:
        if remaining_exposure_margin <= 0:
            return _reject("Capital exposure cap exceeded")

        usable_margin = min(remaining_exposure_margin, margin_buffer)
        if usable_margin <= 0:
            return _reject("Required margin exceeds available balance")

        # The 50% portfolio exposure limit is a hard ceiling, not a target. The
        # previous fixed-risk implementation lowered leverage until one trade
        # used almost the full remaining exposure budget. Fixed-risk trades now
        # use the approved profile leverage cap (20x scalping / 10x intraday).
        # The minimum below is only an admission check.
        minimum_required_leverage = max(notional / usable_margin, 1.0)
        if minimum_required_leverage > leverage_cap + 1e-9:
            return _reject(
                f"Required leverage {minimum_required_leverage:.2f}x exceeds {leverage_cap:.2f}x profile cap"
            )

        selected_leverage = leverage_cap
        required_margin = notional / selected_leverage
        if required_margin > margin_buffer + 1e-9:
            return _reject("Required margin exceeds available balance")
        if existing_margin + required_margin > max_allowed_margin + 1e-9:
            return _reject("Capital exposure cap exceeded")

    portfolio_margin_after = existing_margin + required_margin
    remaining_margin_after = max(max_allowed_margin - portfolio_margin_after, 0.0)

    return {
        "allowed": True,
        "reason": "",
        "quantity": normalized_quantity,
        "quantity_value": quantity,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": normalized["take_profit"],
        "direction": normalized["direction"],
        "sl_distance": sl_distance,
        "risk_percent": actual_risk_amount / equity,
        "risk_amount": actual_risk_amount,
        "price_risk_amount": price_risk_amount,
        "gross_price_risk_amount": price_risk_amount,
        "fee_inclusive_risk_amount": actual_risk_amount,
        "estimated_open_fee": estimated_open_fee,
        "estimated_entry_fee": estimated_open_fee,
        "estimated_stop_fee": estimated_stop_fee,
        "estimated_stop_exit_fee": estimated_stop_fee,
        "estimated_round_trip_fees": estimated_round_trip_fees,
        "estimated_stop_costs": economics["estimated_stop_costs"],
        "estimated_net_reward": economics["net_reward"],
        "gross_risk_reward": economics["gross_risk_reward"],
        "net_risk_reward": economics["net_risk_reward"],
        "fee_bps_per_side": fee_bps,
        "fee_bps": fee_bps,
        "slippage_bps": slippage_bps,
        "min_net_risk_reward": min_net_risk_reward,
        "risk_per_unit_with_fees": risk_per_unit_with_fees,
        "target_risk_amount": target_risk_amount,
        "risk_mode": "fixed_usdt" if fixed_risk_mode else "legacy_percent",
        "notional": notional,
        "required_margin": required_margin,
        "equity": equity,
        "available_balance": available_balance,
        "leverage": selected_leverage,
        "selected_leverage": selected_leverage,
        "minimum_required_leverage": minimum_required_leverage,
        "leverage_cap": leverage_cap,
        "exposure_cap": exposure_cap,
        "current_margin_exposure": existing_margin,
        "portfolio_margin_after": portfolio_margin_after,
        "portfolio_margin_utilization": portfolio_margin_after / equity,
        "trade_margin_utilization": required_margin / equity,
        "max_allowed_margin_exposure": max_allowed_margin,
        "remaining_margin_capacity": remaining_margin_after,
        "current_exposure": existing_margin,
        "max_allowed_exposure": max_allowed_margin,
        "min_notional": min_notional,
        "qty_step": str(qty_step),
        "tick_size": str(tick_size),
    }


def _normalize_signal(signal: dict[str, Any]) -> dict[str, Any] | None:
    try:
        direction = str(signal.get("direction", "")).lower().strip()
        entry = float(signal.get("entry"))
        stop_loss = float(signal.get("stop_loss"))
        take_profit = float(signal.get("take_profit"))
    except (TypeError, ValueError):
        return None

    if direction not in {"long", "short"}:
        return None
    if not all(isfinite(value) and value > 0 for value in [entry, stop_loss, take_profit]):
        return None
    if entry == stop_loss:
        return None

    return {
        "symbol": str(signal.get("symbol", "")).upper().strip(),
        "direction": direction,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "detected_at": signal.get("detected_at"),
    }


def _valid_signal_geometry(signal: dict[str, Any]) -> bool:
    direction = str(signal.get("direction", "")).lower().strip()
    entry = float(signal["entry"])
    stop_loss = float(signal["stop_loss"])
    take_profit = float(signal["take_profit"])
    if direction == "long":
        return stop_loss < entry < take_profit
    if direction == "short":
        return take_profit < entry < stop_loss
    return False


def _stale_reason(value: Any) -> str:
    if not value:
        return "Signal timestamp is required for safe position sizing"

    try:
        detected_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return "Signal timestamp is invalid"

    if detected_at.tzinfo is None:
        detected_at = detected_at.replace(tzinfo=UTC)
    age = datetime.now(UTC) - detected_at.astimezone(UTC)
    if age < timedelta(minutes=-1):
        return "Signal timestamp is in the future"
    if age > timedelta(minutes=SIGNAL_MAX_AGE_MINUTES):
        return "Signal is stale for position sizing"
    return ""


def _current_margin(
    active_trades: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    fallback_leverage: float,
) -> float:
    authoritative_positions = _normalize_open_positions(positions)
    if authoritative_positions:
        return _positions_margin(authoritative_positions, fallback_leverage)
    return _active_trades_margin(active_trades, fallback_leverage)


def _active_trades_margin(active_trades: list[dict[str, Any]], fallback_leverage: float) -> float:
    margin = 0.0
    for trade in active_trades:
        if str(trade.get("status", "active")).lower() == "closed":
            continue
        required_margin = _positive_float(trade.get("required_margin"))
        if required_margin is not None:
            margin += required_margin
            continue

        metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
        sizing = metadata.get("position_sizing") if isinstance(metadata.get("position_sizing"), dict) else {}
        persisted_margin = _positive_float(sizing.get("required_margin"))
        if persisted_margin is not None:
            margin += persisted_margin
            continue

        quantity = _positive_float(trade.get("quantity")) or 0.0
        entry = _positive_float(trade.get("entry")) or 0.0
        leverage = _positive_float(trade.get("leverage")) or _positive_float(sizing.get("selected_leverage")) or fallback_leverage
        if leverage > 0:
            margin += abs(quantity * entry) / leverage
    return margin


def _positions_margin(positions: list[dict[str, Any]], fallback_leverage: float) -> float:
    margin = 0.0
    for position in positions:
        position_margin = _positive_float(position.get("positionIM")) or _positive_float(position.get("positionInitialMargin"))
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


def _normalize_open_positions(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    for position in positions:
        size = _positive_float(position.get("size"))
        if size is None or size <= 0:
            continue

        symbol = str(position.get("symbol", "")).upper().strip()
        if not symbol:
            continue

        side = str(position.get("side", "")).lower().strip()
        position_idx = str(position.get("positionIdx", "")).strip()
        key = (symbol, side, position_idx)
        if key in seen_keys:
            continue

        seen_keys.add(key)
        normalized.append(position)
    return normalized


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


def _non_negative_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(numeric) or numeric < 0:
        return None
    return numeric


def _reject(reason: str) -> dict[str, Any]:
    return {"allowed": False, "reason": reason, "quantity": None}
