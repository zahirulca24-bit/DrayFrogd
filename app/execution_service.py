from __future__ import annotations

import time
from datetime import UTC, datetime
from math import isfinite
from typing import Any

from app.bot_controls import can_execute, get_execution_mode
from app.execution_core import (
    _add_active_trade_once,
    _build_execution_key,
    _build_order_link_id,
    _emergency_close,
    _place_market_order,
    _recover_order_by_link_id,
    _safe_append_trade_event,
    _safe_log_bot_event,
    _safe_update_trade_entry,
    _utc_now_iso,
    get_active_trades,
)
from app.execution_reservation import reserve_execution_capacity
from app.exchange import BybitClient, ExchangeError
from app.journal import update_trade_entry
from app.position_sizing import calculate_position_size
from app.risk import (
    calculate_authoritative_risk_reward,
    extract_account_equity,
    refresh_risk_state,
    register_active_trade,
    release_active_trade,
    validate_trade,
)
from app.trade_management_profiles import build_profile_management_state, extract_observed_entry_fee


FILL_CONFIRM_ATTEMPTS = 5
FILL_CONFIRM_DELAY_SECONDS = 0.20
PROTECTION_VERIFY_ATTEMPTS = 3
PROTECTION_VERIFY_DELAY_SECONDS = 0.20
RISK_AMOUNT_TOLERANCE = 1.001


def execute_signal(client: BybitClient, signal: dict[str, Any], auto_triggered: bool = False) -> dict[str, Any]:
    """Execute one signal through a single authoritative preflight and fill path."""

    allowed, reason = can_execute()
    if not allowed:
        return {"ok": False, "error": reason}

    original_signal = _normalize_signal(signal)
    if original_signal is None:
        return {"ok": False, "error": "Invalid execution signal payload"}

    ok_wallet, wallet, wallet_error = client.safe_fetch_wallet_balance()
    if not ok_wallet or wallet is None:
        return {"ok": False, "error": wallet_error or "Wallet balance unavailable"}
    account_equity = extract_account_equity(wallet)
    if account_equity is None:
        return {"ok": False, "error": "Fresh account equity is unavailable"}

    ok_symbol, symbol_infos, symbol_error = client.safe_fetch_symbol_info(symbol=original_signal["symbol"])
    if not ok_symbol or not symbol_infos:
        return {"ok": False, "error": symbol_error or "Symbol info unavailable"}
    symbol_info = symbol_infos[0]

    ok_positions, positions, positions_error = client.safe_fetch_positions()
    if not ok_positions:
        return {"ok": False, "error": positions_error or "Position data unavailable"}

    side = "Buy" if original_signal["direction"] == "long" else "Sell"
    quote, quote_error = _fetch_execution_quote(client, original_signal["symbol"], side)
    if quote is None:
        return {"ok": False, "error": quote_error or "Execution quote unavailable"}

    execution_signal = {
        **signal,
        **original_signal,
        "entry": quote["price"],
        "status": "active",
    }
    quote_geometry = calculate_authoritative_risk_reward(
        direction=execution_signal["direction"],
        entry=float(execution_signal["entry"]),
        stop_loss=float(execution_signal["stop_loss"]),
        take_profit=float(execution_signal["take_profit"]),
    )
    if quote_geometry is None:
        return {"ok": False, "error": "Live quote invalidated entry/SL/TP geometry", "pre_order_quote": quote}
    execution_signal["risk_reward"] = quote_geometry["risk_reward"]
    refresh_risk_state(account_equity=account_equity)
    validation = validate_trade(execution_signal, account_equity=account_equity)
    if not validation.get("allowed"):
        return {
            "ok": False,
            "error": validation.get("reason", "Risk validation failed"),
            "pre_order_quote": quote,
        }

    sizing = calculate_position_size(
        signal=execution_signal,
        wallet=wallet,
        symbol_info=symbol_info,
        active_trades=get_active_trades(),
        positions=positions,
        settings={
            "risk_amount": validation.get("risk_amount"),
            "leverage_cap": validation.get("leverage_cap"),
            "exposure_cap": validation.get("exposure_cap"),
        },
        client=client,
    )
    if not sizing.get("allowed"):
        return {
            "ok": False,
            "error": sizing.get("reason", "Unsafe position sizing rejected"),
            "sizing": sizing,
            "pre_order_quote": quote,
        }

    quantity = str(sizing["quantity"])
    stop_loss = client.normalize_price(execution_signal["stop_loss"], symbol_info["tickSize"])
    execution_mode = get_execution_mode()
    execution_key = _build_execution_key(original_signal, execution_mode)
    order_link_id = _build_order_link_id(execution_key)
    selected_leverage = float(sizing.get("selected_leverage") or sizing.get("leverage") or 1.0)

    pending_trade = {
        "execution_key": execution_key,
        "symbol": execution_signal["symbol"],
        "strategy_name": execution_signal.get("strategy_name") or "unknown",
        "strategy": execution_signal.get("strategy_name") or "unknown",
        "direction": execution_signal["direction"],
        "entry": execution_signal["entry"],
        "stop_loss": float(stop_loss),
        "take_profit": execution_signal["take_profit"],
        "quantity": quantity,
        "order_id": None,
        "status": "pending_execution",
        "detected_at": execution_signal.get("detected_at"),
        "opened_at": None,
        "execution_mode": execution_mode,
        "result": None,
        "sl_hit_reason": None,
        "remaining_quantity": quantity,
        "management": {},
        "auto_triggered": auto_triggered,
        "exchange_metadata": {
            "mode": execution_mode,
            "strategy_name": execution_signal.get("strategy_name") or "unknown",
            "strategy": execution_signal.get("strategy_name") or "unknown",
            "trade_type": validation.get("trade_type"),
            "execution_key": execution_key,
            "order_link_id": order_link_id,
            "original_signal_entry": original_signal["entry"],
            "pre_order_quote": quote,
            "position_sizing": sizing,
            "risk_validation": validation,
            "selected_leverage": selected_leverage,
        },
    }

    try:
        reservation = reserve_execution_capacity(
            pending_trade,
            execution_key,
            required_risk=float(validation["risk_amount"]),
            max_active_trades=int(validation["max_active_trades"]),
            max_daily_trades=int(validation.get("max_daily_trades") or 8),
            reentry_cooldown_minutes=int(validation.get("reentry_cooldown_minutes") or 30),
        )
    except Exception as exc:
        _safe_log_bot_event(
            "EXECUTION_RESERVATION_FAILED",
            f"Atomic execution reservation failed for {execution_signal['symbol']}; no order was sent.",
            level="error",
            metadata={"symbol": execution_signal["symbol"], "execution_key": execution_key, "error": str(exc)},
        )
        return {"ok": False, "error": "JOURNAL_RESERVATION_FAILED", "detail": str(exc), "sizing": sizing}

    reserved_trade = reservation.get("trade") or {}
    if not reservation.get("reserved"):
        return {
            "ok": False,
            "error": reservation.get("reason") or "DUPLICATE_EXECUTION",
            "execution_key": execution_key,
            "trade": reserved_trade,
            "sizing": sizing,
        }

    journal_id = str(reserved_trade.get("journal_id") or "")
    pending_trade["journal_id"] = journal_id

    leverage_error = _set_selected_leverage(client, execution_signal["symbol"], selected_leverage)
    if leverage_error:
        return _fail_before_order(
            journal_id=journal_id,
            symbol=execution_signal["symbol"],
            error="LEVERAGE_CONFIGURATION_FAILED",
            detail=leverage_error,
            metadata=pending_trade["exchange_metadata"],
            sizing=sizing,
        )

    order_recovered = False
    try:
        order_result = _place_market_order(
            client,
            symbol=execution_signal["symbol"],
            side=side,
            qty=quantity,
            order_link_id=order_link_id,
        )
    except ExchangeError as exc:
        lookup_ok, recovered_order, lookup_error = _recover_order_by_link_id(
            client,
            symbol=execution_signal["symbol"],
            order_link_id=order_link_id,
        )
        if recovered_order is not None:
            order_result = recovered_order
            order_recovered = True
        elif lookup_ok:
            return _fail_before_order(
                journal_id=journal_id,
                symbol=execution_signal["symbol"],
                error="ORDER_NOT_ACCEPTED",
                detail=str(exc),
                metadata={
                    **pending_trade["exchange_metadata"],
                    "order_error": str(exc),
                    "order_lookup": "not_found",
                },
                sizing=sizing,
            )
        else:
            uncertain_trade = {
                **pending_trade,
                "status": "execution_uncertain",
                "result": "execution_uncertain",
                "close_reason": "ORDER_CONFIRMATION_UNAVAILABLE",
                "exchange_metadata": {
                    **pending_trade["exchange_metadata"],
                    "order_error": str(exc),
                    "order_lookup_error": lookup_error,
                },
            }
            _safe_update_trade_entry(
                journal_id,
                {
                    "status": "execution_uncertain",
                    "result": "execution_uncertain",
                    "close_reason": "ORDER_CONFIRMATION_UNAVAILABLE",
                    "exchange_metadata": uncertain_trade["exchange_metadata"],
                },
            )
            _add_active_trade_once(uncertain_trade)
            register_active_trade(execution_signal["symbol"])
            return {"ok": False, "error": "EXECUTION_UNCERTAIN", "trade": uncertain_trade, "sizing": sizing}

    order_id = str(order_result.get("orderId") or "")
    fill, fill_error = _confirm_fill(
        client,
        symbol=execution_signal["symbol"],
        direction=execution_signal["direction"],
        order_link_id=order_link_id,
        order_id=order_id,
    )
    if fill is None:
        uncertain_trade = {
            **pending_trade,
            "order_id": order_id or None,
            "status": "fill_confirmation_pending",
            "result": "execution_uncertain",
            "close_reason": "FILL_CONFIRMATION_UNAVAILABLE",
            "opened_at": _utc_now_iso(),
            "exchange_metadata": {
                **pending_trade["exchange_metadata"],
                "order_response": order_result,
                "order_recovered_after_error": order_recovered,
                "fill_confirmation_error": fill_error,
            },
        }
        _safe_update_trade_entry(
            journal_id,
            {
                "order_id": order_id or None,
                "status": uncertain_trade["status"],
                "result": uncertain_trade["result"],
                "close_reason": uncertain_trade["close_reason"],
                "opened_at": uncertain_trade["opened_at"],
                "exchange_metadata": uncertain_trade["exchange_metadata"],
            },
        )
        _add_active_trade_once(uncertain_trade)
        register_active_trade(execution_signal["symbol"])
        return {"ok": False, "error": "FILL_CONFIRMATION_UNAVAILABLE", "trade": uncertain_trade, "sizing": sizing}

    actual_entry = float(fill["avg_price"])
    actual_quantity = float(fill["quantity"])
    actual_check = _validate_actual_fill(
        direction=execution_signal["direction"],
        entry=actual_entry,
        stop_loss=float(stop_loss),
        take_profit=float(execution_signal["take_profit"]),
        quantity=actual_quantity,
        validation=validation,
    )

    provisional_trade_for_fee = {
        "exchange_metadata": {
            "fill_confirmation": fill,
        },
    }
    management = build_profile_management_state(
        entry=actual_entry,
        stop_loss=float(stop_loss),
        take_profit=float(execution_signal["take_profit"]),
        quantity=actual_quantity,
        direction=execution_signal["direction"],
        trade_type=str(validation.get("trade_type") or "scalping"),
        observed_entry_fee=extract_observed_entry_fee(provisional_trade_for_fee),
    )
    management["last_state_change"] = _utc_now_iso()
    protected_take_profit = client.normalize_price(management["runner_target"], symbol_info["tickSize"])
    opened_at = fill.get("filled_at") or _utc_now_iso()
    trade = {
        **pending_trade,
        "entry": actual_entry,
        "quantity": actual_quantity,
        "remaining_quantity": actual_quantity,
        "order_id": order_id or fill.get("order_id"),
        "status": "order_filled",
        "opened_at": opened_at,
        "management": management,
        "exchange_metadata": {
            **pending_trade["exchange_metadata"],
            "order_response": order_result,
            "order_recovered_after_error": order_recovered,
            "fill_confirmation": fill,
            "actual_fill_risk": actual_check,
            "management": management,
        },
    }

    persisted_fill, journal_error = _safe_update_trade_entry(
        journal_id,
        {
            "entry_price": actual_entry,
            "quantity": actual_quantity,
            "order_id": trade["order_id"],
            "status": "order_filled",
            "opened_at": opened_at,
            "exchange_metadata": trade["exchange_metadata"],
        },
    )
    if persisted_fill is None:
        return _emergency_close_pending_sync(
            client=client,
            trade=trade,
            error="POST_FILL_JOURNAL_FAILED",
            detail=journal_error or "journal update returned no row",
            sizing=sizing,
        )

    if not actual_check["allowed"]:
        return _emergency_close_pending_sync(
            client=client,
            trade=trade,
            error="ACTUAL_FILL_RISK_VIOLATION",
            detail=actual_check["reason"],
            sizing=sizing,
        )

    protection_error = _attach_and_verify_protection(
        client=client,
        symbol=execution_signal["symbol"],
        direction=execution_signal["direction"],
        take_profit=protected_take_profit,
        stop_loss=stop_loss,
        tick_size=str(symbol_info["tickSize"]),
        journal_id=journal_id,
    )
    if protection_error:
        return _emergency_close_pending_sync(
            client=client,
            trade=trade,
            error="PROTECTION_NOT_VERIFIED",
            detail=protection_error,
            sizing=sizing,
        )

    trade["status"] = "active"
    trade["exchange_metadata"] = {
        **trade["exchange_metadata"],
        "protection_attached": True,
        "protection_verified": True,
        "protection_attached_at": _utc_now_iso(),
        "protection_take_profit": protected_take_profit,
        "protection_stop_loss": stop_loss,
    }
    persisted_active, active_error = _safe_update_trade_entry(
        journal_id,
        {
            "entry_price": actual_entry,
            "quantity": actual_quantity,
            "status": "active",
            "exchange_metadata": trade["exchange_metadata"],
        },
    )
    _add_active_trade_once(trade)
    register_active_trade(execution_signal["symbol"])
    warning = None if persisted_active is not None else f"ACTIVE_STATE_PERSIST_FAILED: {active_error}"
    return {
        "ok": True,
        "trade": trade,
        "sizing": sizing,
        "pre_order_risk": validation,
        "pre_order_quote": quote,
        "actual_fill": fill,
        "selected_leverage": selected_leverage,
        "warning": warning,
    }


def _fetch_execution_quote(client: Any, symbol: str, side: str) -> tuple[dict[str, Any] | None, str | None]:
    method = getattr(client, "safe_fetch_ticker", None)
    if callable(method):
        ok, ticker, error = method(symbol=symbol)
        if not ok or not ticker:
            return None, error or "Ticker unavailable"
    else:
        try:
            payload = client._public_get("/v5/market/tickers", {"category": "linear", "symbol": symbol})
            items = payload.get("list", [])
            ticker = items[0] if items else None
        except Exception as exc:
            return None, str(exc)
        if not ticker:
            return None, "Ticker unavailable"

    price_keys = ("ask1Price", "markPrice", "lastPrice") if side == "Buy" else ("bid1Price", "markPrice", "lastPrice")
    for key in price_keys:
        price = _positive_float(ticker.get(key))
        if price is not None:
            return {"price": price, "source": key, "ticker": ticker}, None
    return None, "Ticker did not provide a usable execution price"


def _set_selected_leverage(client: Any, symbol: str, leverage: float) -> str | None:
    method = getattr(client, "safe_set_leverage", None)
    if not callable(method):
        return "Exchange leverage configuration is unavailable"
    ok, _response, error = method(symbol=symbol, leverage=leverage)
    if ok:
        return None
    normalized = str(error or "Leverage configuration failed")
    if "not modified" in normalized.lower() or "same leverage" in normalized.lower():
        return None
    return normalized


def _confirm_fill(
    client: Any,
    *,
    symbol: str,
    direction: str,
    order_link_id: str,
    order_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    last_error: str | None = None
    expected_side = "buy" if direction == "long" else "sell"

    for attempt in range(1, FILL_CONFIRM_ATTEMPTS + 1):
        method = getattr(client, "safe_fetch_order_by_link_id", None)
        if callable(method):
            ok, order, error = method(symbol=symbol, order_link_id=order_link_id)
            if ok and order:
                status = str(order.get("orderStatus") or "").lower()
                avg_price = _positive_float(order.get("avgPrice"))
                quantity = _positive_float(order.get("cumExecQty") or order.get("qty"))
                if avg_price is not None and quantity is not None and status in {"filled", "partiallyfilled"}:
                    return {
                        "source": "bybit_order",
                        "order_id": str(order.get("orderId") or order_id),
                        "order_link_id": order_link_id,
                        "status": order.get("orderStatus"),
                        "avg_price": avg_price,
                        "quantity": quantity,
                        "filled_at": _timestamp_to_iso(order.get("updatedTime") or order.get("createdTime")),
                        "raw": order,
                    }, None
            elif error:
                last_error = str(error)

        ok_positions, positions, positions_error = client.safe_fetch_positions()
        if ok_positions:
            position = next(
                (
                    item
                    for item in positions
                    if str(item.get("symbol") or "").upper() == symbol
                    and str(item.get("side") or "").lower() == expected_side
                    and (_positive_float(item.get("size")) or 0.0) > 0
                ),
                None,
            )
            if position:
                avg_price = _positive_float(position.get("avgPrice") or position.get("entryPrice"))
                quantity = _positive_float(position.get("size"))
                if avg_price is not None and quantity is not None:
                    return {
                        "source": "bybit_position",
                        "order_id": order_id or None,
                        "order_link_id": order_link_id,
                        "status": "PositionConfirmed",
                        "avg_price": avg_price,
                        "quantity": quantity,
                        "filled_at": _utc_now_iso(),
                        "raw": position,
                    }, None
        elif positions_error:
            last_error = str(positions_error)

        if attempt < FILL_CONFIRM_ATTEMPTS:
            time.sleep(FILL_CONFIRM_DELAY_SECONDS)

    return None, last_error or "Order fill and exchange position could not be confirmed"


def _validate_actual_fill(
    *,
    direction: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    quantity: float,
    validation: dict[str, Any],
) -> dict[str, Any]:
    geometry = calculate_authoritative_risk_reward(
        direction=direction,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )
    if geometry is None:
        return {"allowed": False, "reason": "Actual fill invalidated entry/SL/TP geometry"}

    min_rr = float(validation.get("min_risk_reward") or 0.0)
    if geometry["risk_reward"] + 1e-9 < min_rr:
        return {
            "allowed": False,
            "reason": f"Actual fill reduced RR below {min_rr:.1f}",
            "actual_risk_reward": geometry["risk_reward"],
        }

    actual_risk = geometry["risk_distance"] * quantity
    target_risk = float(validation.get("risk_amount") or 0.0)
    if actual_risk > target_risk * RISK_AMOUNT_TOLERANCE + 1e-9:
        return {
            "allowed": False,
            "reason": f"Actual fill risk {actual_risk:.8f} exceeds target {target_risk:.8f}",
            "actual_risk": actual_risk,
            "target_risk": target_risk,
            "actual_risk_reward": geometry["risk_reward"],
        }
    return {
        "allowed": True,
        "reason": "",
        "actual_risk": actual_risk,
        "target_risk": target_risk,
        "actual_risk_reward": geometry["risk_reward"],
    }


def _attach_and_verify_protection(
    *,
    client: Any,
    symbol: str,
    direction: str,
    take_profit: str,
    stop_loss: str,
    tick_size: str,
    journal_id: str,
) -> str | None:
    last_error: str | None = None
    for attempt in (1, 2):
        try:
            client.set_trading_stop(symbol=symbol, take_profit=take_profit, stop_loss=stop_loss)
        except ExchangeError as exc:
            last_error = str(exc)
            _safe_append_trade_event(
                journal_id,
                "PROTECTION_RETRY" if attempt == 1 else "PROTECTION_FAILED",
                "Protection attach failed.",
                {"symbol": symbol, "attempt": attempt, "error": last_error},
            )
            continue

        verified, verify_error = _verify_protection(
            client,
            symbol=symbol,
            direction=direction,
            take_profit=float(take_profit),
            stop_loss=float(stop_loss),
            tick_size=float(tick_size),
        )
        if verified:
            _safe_append_trade_event(
                journal_id,
                "PROTECTION_VERIFIED",
                "Initial SL/TP protection was attached and verified from the exchange position.",
                {"symbol": symbol, "attempt": attempt, "take_profit": take_profit, "stop_loss": stop_loss},
            )
            return None
        last_error = verify_error or "Protection could not be verified"
        _safe_append_trade_event(
            journal_id,
            "PROTECTION_RETRY" if attempt == 1 else "PROTECTION_FAILED",
            "Protection was submitted but exchange verification failed.",
            {"symbol": symbol, "attempt": attempt, "error": last_error},
        )
    return last_error


def _verify_protection(
    client: Any,
    *,
    symbol: str,
    direction: str,
    take_profit: float,
    stop_loss: float,
    tick_size: float,
) -> tuple[bool, str | None]:
    expected_side = "buy" if direction == "long" else "sell"
    tolerance = max(abs(tick_size), 1e-12)
    last_error: str | None = None
    for attempt in range(1, PROTECTION_VERIFY_ATTEMPTS + 1):
        ok, positions, error = client.safe_fetch_positions()
        if ok:
            position = next(
                (
                    item
                    for item in positions
                    if str(item.get("symbol") or "").upper() == symbol
                    and str(item.get("side") or "").lower() == expected_side
                    and (_positive_float(item.get("size")) or 0.0) > 0
                ),
                None,
            )
            if position:
                actual_sl = _positive_float(position.get("stopLoss"))
                actual_tp = _positive_float(position.get("takeProfit"))
                if (
                    actual_sl is not None
                    and actual_tp is not None
                    and abs(actual_sl - stop_loss) <= tolerance
                    and abs(actual_tp - take_profit) <= tolerance
                ):
                    return True, None
                last_error = f"Exchange protection mismatch: SL={actual_sl}, TP={actual_tp}"
            else:
                last_error = "Exchange position was not found during protection verification"
        else:
            last_error = str(error or "Position fetch failed")
        if attempt < PROTECTION_VERIFY_ATTEMPTS:
            time.sleep(PROTECTION_VERIFY_DELAY_SECONDS)
    return False, last_error


def _fail_before_order(
    *,
    journal_id: str,
    symbol: str,
    error: str,
    detail: str,
    metadata: dict[str, Any],
    sizing: dict[str, Any],
) -> dict[str, Any]:
    closed_at = _utc_now_iso()
    _safe_update_trade_entry(
        journal_id,
        {
            "status": "closed",
            "result": "execution_failed",
            "close_reason": error,
            "closed_at": closed_at,
            "exchange_metadata": {**metadata, "execution_error": detail},
        },
    )
    release_active_trade(symbol)
    return {"ok": False, "error": error, "detail": detail, "sizing": sizing}


def _emergency_close_pending_sync(
    *,
    client: Any,
    trade: dict[str, Any],
    error: str,
    detail: str,
    sizing: dict[str, Any],
) -> dict[str, Any]:
    close_result, close_error = _emergency_close(client, trade)
    metadata = {
        **(trade.get("exchange_metadata") or {}),
        "execution_safety_error": error,
        "execution_safety_detail": detail,
        "emergency_close_response": close_result,
        "emergency_close_error": close_error,
    }
    journal_id = str(trade.get("journal_id") or "")
    if close_error is None:
        unsafe_trade = {
            **trade,
            "status": "close_pending_sync",
            "result": "execution_safety_close",
            "close_reason": error,
            "exchange_metadata": metadata,
        }
        _safe_update_trade_entry(
            journal_id,
            {
                "status": "close_pending_sync",
                "result": unsafe_trade["result"],
                "close_reason": error,
                "exchange_metadata": metadata,
            },
        )
        _add_active_trade_once(unsafe_trade)
        register_active_trade(str(trade.get("symbol") or ""))
        return {"ok": False, "error": error, "detail": detail, "trade": unsafe_trade, "sizing": sizing}

    unsafe_trade = {
        **trade,
        "status": "emergency_close_failed",
        "result": "execution_safety_failure",
        "close_reason": f"{error}_CLOSE_FAILED",
        "exchange_metadata": metadata,
    }
    _safe_update_trade_entry(
        journal_id,
        {
            "status": unsafe_trade["status"],
            "result": unsafe_trade["result"],
            "close_reason": unsafe_trade["close_reason"],
            "exchange_metadata": metadata,
        },
    )
    _add_active_trade_once(unsafe_trade)
    register_active_trade(str(trade.get("symbol") or ""))
    return {
        "ok": False,
        "error": f"{error}_AND_EMERGENCY_CLOSE_FAILED",
        "detail": close_error,
        "trade": unsafe_trade,
        "sizing": sizing,
    }


def _normalize_signal(signal: dict[str, Any]) -> dict[str, Any] | None:
    try:
        direction = str(signal.get("direction") or "").lower().strip()
        if direction not in {"long", "short"}:
            return None
        symbol = str(signal.get("symbol") or "").upper().strip()
        if not symbol:
            return None
        entry = float(signal.get("entry"))
        stop_loss = float(signal.get("stop_loss"))
        take_profit = float(signal.get("take_profit"))
        if not all(isfinite(value) and value > 0 for value in (entry, stop_loss, take_profit)):
            return None
        return {
            "symbol": symbol,
            "strategy_name": str(signal.get("strategy_name") or signal.get("strategy") or "unknown"),
            "trade_type": signal.get("trade_type"),
            "direction": direction,
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_reward": signal.get("risk_reward"),
            "detected_at": signal.get("detected_at"),
            "status": str(signal.get("status") or "active").lower(),
        }
    except (TypeError, ValueError):
        return None


def _timestamp_to_iso(value: Any) -> str:
    try:
        milliseconds = int(value)
    except (TypeError, ValueError):
        return _utc_now_iso()
    if milliseconds <= 0:
        return _utc_now_iso()
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC).isoformat()


def _positive_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(numeric) or numeric <= 0:
        return None
    return numeric
