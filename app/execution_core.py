from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from math import isfinite
from threading import Lock
from typing import Any

from app.bot_controls import can_execute, get_execution_mode
from app.exchange import BybitClient, ExchangeError
from app.journal import (
    append_trade_event,
    log_bot_event,
    reserve_trade_execution,
    update_trade_entry,
)
from app.position_sizing import calculate_position_size
from app.risk import register_active_trade, start_loss_cooldown, validate_trade


SL_REASON_UNKNOWN = "unknown"
SL_REASON_EXCHANGE_CLOSE = "exchange_close"
SL_REASON_FORCED_RISK_CLOSE = "forced_risk_close"
RESULT_PROTECTION_FAILED = "protection_failed"
RESULT_EXECUTION_FAILED = "execution_failed"
RESULT_EXECUTION_UNCERTAIN = "execution_uncertain"

_execution_lock = Lock()
_active_trades: list[dict[str, Any]] = []
_closed_trades: list[dict[str, Any]] = []
_active_order_ids: list[str] = []


def execute_signal(client: BybitClient, signal: dict[str, Any], auto_triggered: bool = False) -> dict[str, Any]:
    allowed, reason = can_execute()
    if not allowed:
        return {"ok": False, "error": reason}

    validation = validate_trade(signal)
    if not validation.get("allowed"):
        return {"ok": False, "error": validation.get("reason", "Risk validation failed")}

    normalized_signal = _normalize_signal(signal)
    if normalized_signal is None:
        return {"ok": False, "error": "Invalid execution signal payload"}

    ok_symbol, symbol_infos, symbol_error = client.safe_fetch_symbol_info(symbol=normalized_signal["symbol"])
    if not ok_symbol or not symbol_infos:
        return {"ok": False, "error": symbol_error or "Symbol info unavailable"}

    ok_wallet, wallet, wallet_error = client.safe_fetch_wallet_balance()
    if not ok_wallet or wallet is None:
        return {"ok": False, "error": wallet_error or "Wallet balance unavailable"}

    ok_positions, positions, positions_error = client.safe_fetch_positions()
    if not ok_positions:
        return {"ok": False, "error": positions_error or "Position data unavailable"}

    symbol_info = symbol_infos[0]
    sizing = calculate_position_size(
        signal=normalized_signal,
        wallet=wallet,
        symbol_info=symbol_info,
        active_trades=get_active_trades(),
        positions=positions,
        settings={
            "risk_per_trade": float(validation.get("risk_per_trade", 0.01)),
            "leverage_cap": validation.get("leverage_cap"),
            "exposure_cap": validation.get("exposure_cap"),
        },
        client=client,
    )
    if not sizing.get("allowed"):
        return {"ok": False, "error": sizing.get("reason", "Unsafe position sizing rejected"), "sizing": sizing}

    quantity = str(sizing["quantity"])
    stop_loss = client.normalize_price(normalized_signal["stop_loss"], symbol_info["tickSize"])
    side = "Buy" if normalized_signal["direction"] == "long" else "Sell"
    execution_mode = get_execution_mode()
    management = _build_management_state(
        entry=normalized_signal["entry"],
        stop_loss=float(stop_loss),
        take_profit=normalized_signal["take_profit"],
        quantity=quantity,
        direction=normalized_signal["direction"],
    )
    protected_take_profit = client.normalize_price(management["runner_target"], symbol_info["tickSize"])
    execution_key = _build_execution_key(normalized_signal, execution_mode)
    order_link_id = _build_order_link_id(execution_key)

    pending_trade = {
        "execution_key": execution_key,
        "symbol": normalized_signal["symbol"],
        "strategy_name": normalized_signal.get("strategy_name") or "unknown",
        "strategy": normalized_signal.get("strategy_name") or "unknown",
        "direction": normalized_signal["direction"],
        "entry": normalized_signal["entry"],
        "stop_loss": float(stop_loss),
        "take_profit": normalized_signal["take_profit"],
        "quantity": quantity,
        "order_id": None,
        "status": "pending_execution",
        "detected_at": normalized_signal.get("detected_at"),
        "opened_at": None,
        "execution_mode": execution_mode,
        "result": None,
        "sl_hit_reason": None,
        "remaining_quantity": quantity,
        "management": management,
        "auto_triggered": auto_triggered,
        "exchange_metadata": {
            "mode": execution_mode,
            "strategy_name": normalized_signal.get("strategy_name") or "unknown",
            "strategy": normalized_signal.get("strategy_name") or "unknown",
            "execution_key": execution_key,
            "order_link_id": order_link_id,
            "position_sizing": sizing,
            "management": management,
        },
    }

    try:
        reservation = reserve_trade_execution(pending_trade, execution_key)
    except Exception as exc:
        _safe_log_bot_event(
            "EXECUTION_RESERVATION_FAILED",
            f"Execution reservation failed for {normalized_signal['symbol']}; no order was sent.",
            level="error",
            metadata={"symbol": normalized_signal["symbol"], "execution_key": execution_key, "error": str(exc)},
        )
        return {"ok": False, "error": "JOURNAL_RESERVATION_FAILED", "detail": str(exc), "sizing": sizing}

    reserved_trade = reservation.get("trade") or {}
    if not reservation.get("reserved"):
        return {
            "ok": False,
            "error": "DUPLICATE_EXECUTION",
            "execution_key": execution_key,
            "trade": reserved_trade,
            "sizing": sizing,
        }

    journal_id = str(reserved_trade.get("journal_id") or pending_trade.get("journal_id") or "")
    pending_trade["journal_id"] = journal_id

    order_recovered = False
    try:
        order_result = _place_market_order(
            client,
            symbol=normalized_signal["symbol"],
            side=side,
            qty=quantity,
            order_link_id=order_link_id,
        )
    except ExchangeError as exc:
        lookup_ok, recovered_order, lookup_error = _recover_order_by_link_id(
            client,
            symbol=normalized_signal["symbol"],
            order_link_id=order_link_id,
        )
        if recovered_order is not None:
            order_result = recovered_order
            order_recovered = True
        elif lookup_ok:
            failed_trade = {
                **pending_trade,
                "status": "closed",
                "result": RESULT_EXECUTION_FAILED,
                "close_reason": "ORDER_NOT_ACCEPTED",
                "closed_at": _utc_now_iso(),
                "exchange_metadata": {
                    **pending_trade["exchange_metadata"],
                    "order_error": str(exc),
                    "order_lookup": "not_found",
                },
            }
            _safe_update_trade_entry(
                journal_id,
                {
                    "status": "closed",
                    "result": RESULT_EXECUTION_FAILED,
                    "close_reason": "ORDER_NOT_ACCEPTED",
                    "closed_at": failed_trade["closed_at"],
                    "exchange_metadata": failed_trade["exchange_metadata"],
                },
            )
            _safe_append_trade_event(
                journal_id,
                "ORDER_REJECTED",
                "Exchange order was not accepted and deterministic lookup found no order.",
                {"symbol": normalized_signal["symbol"], "error": str(exc), "order_link_id": order_link_id},
            )
            with _execution_lock:
                _closed_trades.append(failed_trade)
            return {"ok": False, "error": str(exc), "trade": failed_trade, "sizing": sizing}
        else:
            uncertain_trade = {
                **pending_trade,
                "status": "execution_uncertain",
                "result": RESULT_EXECUTION_UNCERTAIN,
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
                    "result": RESULT_EXECUTION_UNCERTAIN,
                    "close_reason": "ORDER_CONFIRMATION_UNAVAILABLE",
                    "exchange_metadata": uncertain_trade["exchange_metadata"],
                },
            )
            _add_active_trade_once(uncertain_trade)
            register_active_trade(normalized_signal["symbol"])
            _safe_log_bot_event(
                "EXECUTION_UNCERTAIN",
                f"Order result is uncertain for {normalized_signal['symbol']}; duplicate retry is blocked.",
                level="error",
                metadata={
                    "symbol": normalized_signal["symbol"],
                    "journal_id": journal_id,
                    "execution_key": execution_key,
                    "order_link_id": order_link_id,
                    "order_error": str(exc),
                    "lookup_error": lookup_error,
                },
            )
            return {"ok": False, "error": "EXECUTION_UNCERTAIN", "trade": uncertain_trade, "sizing": sizing}

    order_id = str(order_result.get("orderId") or "")
    opened_at = _utc_now_iso()
    trade = {
        **pending_trade,
        "order_id": order_id,
        "status": "order_submitted",
        "opened_at": opened_at,
        "exchange_metadata": {
            **pending_trade["exchange_metadata"],
            "order_response": order_result,
            "order_recovered_after_error": order_recovered,
        },
    }

    persisted_order, journal_error = _safe_update_trade_entry(
        journal_id,
        {
            "order_id": order_id,
            "status": "order_submitted",
            "opened_at": opened_at,
            "exchange_metadata": trade["exchange_metadata"],
        },
    )
    if persisted_order is None:
        return _handle_post_order_journal_failure(
            client=client,
            trade=trade,
            protected_take_profit=protected_take_profit,
            stop_loss=stop_loss,
            journal_error=journal_error or "journal update returned no row",
            sizing=sizing,
        )

    protection_error = _attach_protection_with_retry(
        client=client,
        symbol=normalized_signal["symbol"],
        take_profit=protected_take_profit,
        stop_loss=stop_loss,
        journal_id=journal_id,
    )
    if protection_error:
        return _handle_protection_failure(
            client=client,
            trade=trade,
            protection_error=protection_error,
            sizing=sizing,
        )

    trade["status"] = "active"
    trade["exchange_metadata"] = {
        **trade["exchange_metadata"],
        "protection_attached": True,
        "protection_attached_at": _utc_now_iso(),
    }
    persisted_active, active_update_error = _safe_update_trade_entry(
        journal_id,
        {"status": "active", "exchange_metadata": trade["exchange_metadata"]},
    )

    _add_active_trade_once(trade)
    register_active_trade(normalized_signal["symbol"])
    warning = None if persisted_active is not None else f"ACTIVE_STATE_PERSIST_FAILED: {active_update_error}"
    if warning:
        _safe_log_bot_event(
            "ACTIVE_STATE_PERSIST_FAILED",
            f"Protected position is active but final journal state update failed for {normalized_signal['symbol']}.",
            level="error",
            metadata={"symbol": normalized_signal["symbol"], "journal_id": journal_id, "error": active_update_error},
        )
    return {"ok": True, "trade": trade, "sizing": sizing, "warning": warning}


def get_active_trades() -> list[dict[str, Any]]:
    with _execution_lock:
        return [dict(trade) for trade in _active_trades]


def get_closed_trades() -> list[dict[str, Any]]:
    with _execution_lock:
        return [dict(trade) for trade in _closed_trades]


def replace_active_trades(trades: list[dict[str, Any]]) -> None:
    with _execution_lock:
        _active_trades.clear()
        _active_trades.extend(dict(trade) for trade in trades)
        _active_order_ids.clear()
        _active_order_ids.extend(str(trade.get("order_id")) for trade in trades if trade.get("order_id"))


def update_active_trade(journal_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    with _execution_lock:
        trade = next((item for item in _active_trades if item.get("journal_id") == journal_id), None)
        if trade is None:
            return None
        trade.update(updates)
        return dict(trade)


def close_trade(journal_id: str, close_fields: dict[str, Any]) -> dict[str, Any] | None:
    with _execution_lock:
        trade = next((item for item in _active_trades if item.get("journal_id") == journal_id), None)
        if trade is None:
            return None

        exit_price = _optional_float(close_fields.get("exit_price"))
        fees = _optional_float(close_fields.get("fees"))
        realized_pnl = _optional_float(close_fields.get("realized_pnl"))
        if realized_pnl is None and exit_price is not None:
            realized_pnl = _calculate_realized_pnl(trade, exit_price=exit_price, fees=fees or 0.0)

        closed_trade = dict(trade)
        closed_trade.update(close_fields)
        closed_trade.update(
            {
                "status": "closed",
                "closed_at": close_fields.get("closed_at") or _utc_now_iso(),
                "exit_price": exit_price,
                "realized_pnl": realized_pnl,
                "fees": fees,
            }
        )
        _active_trades[:] = [item for item in _active_trades if item.get("journal_id") != journal_id]
        _closed_trades.append(closed_trade)
        if closed_trade.get("order_id"):
            _active_order_ids[:] = [item for item in _active_order_ids if item != closed_trade.get("order_id")]

    update_trade_entry(
        journal_id,
        {
            "status": "closed",
            "result": closed_trade.get("result"),
            "sl_hit_reason": closed_trade.get("sl_hit_reason"),
            "close_reason": closed_trade.get("close_reason"),
            "exit_price": closed_trade.get("exit_price"),
            "realized_pnl": closed_trade.get("realized_pnl"),
            "fees": closed_trade.get("fees"),
            "closed_at": closed_trade.get("closed_at"),
            "exchange_metadata": closed_trade.get("exchange_metadata"),
        },
    )
    if closed_trade.get("result") == "sl":
        start_loss_cooldown()
    return closed_trade


def add_closed_trades(trades: list[dict[str, Any]]) -> None:
    if not trades:
        return
    with _execution_lock:
        for trade in trades:
            _closed_trades.append(dict(trade))


def _handle_post_order_journal_failure(
    *,
    client: BybitClient,
    trade: dict[str, Any],
    protected_take_profit: str,
    stop_loss: str,
    journal_error: str,
    sizing: dict[str, Any],
) -> dict[str, Any]:
    journal_id = str(trade.get("journal_id") or "")
    symbol = str(trade.get("symbol") or "")
    protection_error = _attach_protection_with_retry(
        client=client,
        symbol=symbol,
        take_profit=protected_take_profit,
        stop_loss=stop_loss,
        journal_id=journal_id,
    )
    close_result, close_error = _emergency_close(client, trade)
    metadata = {
        **(trade.get("exchange_metadata") or {}),
        "post_order_journal_error": journal_error,
        "emergency_protection_error": protection_error,
        "emergency_close_response": close_result,
        "emergency_close_error": close_error,
    }

    if close_error is None:
        closed_trade = {
            **trade,
            "status": "closed",
            "result": "journal_failure_emergency_close",
            "close_reason": "POST_ORDER_JOURNAL_FAILED",
            "closed_at": _utc_now_iso(),
            "exchange_metadata": metadata,
        }
        _safe_update_trade_entry(
            journal_id,
            {
                "status": "closed",
                "result": closed_trade["result"],
                "close_reason": closed_trade["close_reason"],
                "closed_at": closed_trade["closed_at"],
                "exchange_metadata": metadata,
            },
        )
        with _execution_lock:
            _closed_trades.append(closed_trade)
        _safe_log_bot_event(
            "POST_ORDER_JOURNAL_FAILED",
            f"Order was emergency-closed because durable post-order journaling failed for {symbol}.",
            level="error",
            metadata={"symbol": symbol, "journal_id": journal_id, "error": journal_error},
        )
        return {"ok": False, "error": "POST_ORDER_JOURNAL_FAILED", "trade": closed_trade, "sizing": sizing}

    unsafe_trade = {
        **trade,
        "status": "emergency_close_failed",
        "result": "journal_failure",
        "close_reason": "POST_ORDER_JOURNAL_FAILED_CLOSE_FAILED",
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
    register_active_trade(symbol)
    _safe_log_bot_event(
        "POST_ORDER_JOURNAL_AND_CLOSE_FAILED",
        f"Critical: order exists and emergency close failed for {symbol}.",
        level="error",
        metadata={"symbol": symbol, "journal_id": journal_id, "journal_error": journal_error, "close_error": close_error},
    )
    return {"ok": False, "error": "POST_ORDER_JOURNAL_AND_CLOSE_FAILED", "trade": unsafe_trade, "sizing": sizing}


def _handle_protection_failure(
    *,
    client: BybitClient,
    trade: dict[str, Any],
    protection_error: str,
    sizing: dict[str, Any],
) -> dict[str, Any]:
    journal_id = str(trade.get("journal_id") or "")
    symbol = str(trade.get("symbol") or "")
    close_result, close_error = _emergency_close(client, trade)
    metadata = {
        **(trade.get("exchange_metadata") or {}),
        "protection_error": protection_error,
        "emergency_close_response": close_result,
        "emergency_close_error": close_error,
    }

    if close_error is None:
        closed_trade = {
            **trade,
            "status": "closed",
            "result": RESULT_PROTECTION_FAILED,
            "close_reason": "PROTECTION_FAILED",
            "realized_pnl": None,
            "fees": None,
            "closed_at": _utc_now_iso(),
            "exchange_metadata": metadata,
        }
        _safe_update_trade_entry(
            journal_id,
            {
                "status": "closed",
                "result": RESULT_PROTECTION_FAILED,
                "close_reason": "PROTECTION_FAILED",
                "realized_pnl": None,
                "fees": None,
                "closed_at": closed_trade["closed_at"],
                "exchange_metadata": metadata,
            },
        )
        _safe_append_trade_event(
            journal_id,
            "PROTECTION_FAILED",
            "Protection failed twice; emergency close was confirmed.",
            {"symbol": symbol, "error": protection_error},
        )
        with _execution_lock:
            _closed_trades.append(closed_trade)
        return {"ok": False, "error": "PROTECTION_FAILED", "trade": closed_trade, "sizing": sizing}

    unsafe_trade = {
        **trade,
        "status": "emergency_close_failed",
        "result": RESULT_PROTECTION_FAILED,
        "close_reason": "PROTECTION_FAILED_CLOSE_FAILED",
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
    register_active_trade(symbol)
    _safe_log_bot_event(
        "PROTECTION_AND_EMERGENCY_CLOSE_FAILED",
        f"Critical: protection and emergency close both failed for {symbol}.",
        level="error",
        metadata={"symbol": symbol, "journal_id": journal_id, "protection_error": protection_error, "close_error": close_error},
    )
    return {"ok": False, "error": "PROTECTION_AND_EMERGENCY_CLOSE_FAILED", "trade": unsafe_trade, "sizing": sizing}


def _normalize_signal(signal: dict[str, Any]) -> dict[str, Any] | None:
    try:
        direction = str(signal.get("direction", "")).lower()
        if direction not in {"long", "short"}:
            return None
        return {
            "symbol": str(signal.get("symbol", "")).upper(),
            "strategy_name": str(signal.get("strategy_name") or signal.get("strategy") or "unknown"),
            "direction": direction,
            "entry": float(signal.get("entry")),
            "stop_loss": float(signal.get("stop_loss")),
            "take_profit": float(signal.get("take_profit")),
            "detected_at": signal.get("detected_at"),
        }
    except (TypeError, ValueError):
        return None


def _build_execution_key(signal: dict[str, Any], execution_mode: str) -> str:
    canonical = {
        "mode": str(execution_mode).lower(),
        "symbol": str(signal.get("symbol", "")).upper(),
        "strategy": str(signal.get("strategy_name") or "unknown").lower(),
        "direction": str(signal.get("direction", "")).lower(),
        "entry": format(float(signal.get("entry", 0)), ".12g"),
        "stop_loss": format(float(signal.get("stop_loss", 0)), ".12g"),
        "take_profit": format(float(signal.get("take_profit", 0)), ".12g"),
        "detected_at": str(signal.get("detected_at") or ""),
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _build_order_link_id(execution_key: str) -> str:
    return f"df-{execution_key[:32]}"


def _place_market_order(client: BybitClient, *, symbol: str, side: str, qty: str, order_link_id: str) -> dict[str, Any]:
    try:
        return client.place_market_order(symbol=symbol, side=side, qty=qty, order_link_id=order_link_id)
    except TypeError as exc:
        if "order_link_id" not in str(exc):
            raise
        return client.place_market_order(symbol=symbol, side=side, qty=qty)


def _recover_order_by_link_id(
    client: BybitClient,
    *,
    symbol: str,
    order_link_id: str,
) -> tuple[bool, dict[str, Any] | None, str | None]:
    method = getattr(client, "safe_fetch_order_by_link_id", None)
    if not callable(method):
        return False, None, "order lookup is unavailable"
    try:
        return method(symbol=symbol, order_link_id=order_link_id)
    except Exception as exc:
        return False, None, str(exc)


def _emergency_close(client: BybitClient, trade: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    close_side = "Sell" if str(trade.get("direction", "")).lower() == "long" else "Buy"
    try:
        result = client.close_position_market(
            symbol=str(trade.get("symbol") or ""),
            side=close_side,
            qty=str(trade.get("quantity") or trade.get("remaining_quantity") or "0"),
        )
        return result if isinstance(result, dict) else {}, None
    except ExchangeError as exc:
        return {}, str(exc)


def _attach_protection_with_retry(*, client: BybitClient, symbol: str, take_profit: str, stop_loss: str, journal_id: str) -> str | None:
    last_error: str | None = None
    for attempt in (1, 2):
        try:
            client.set_trading_stop(symbol=symbol, take_profit=take_profit, stop_loss=stop_loss)
            _safe_append_trade_event(
                journal_id,
                "PROTECTION_ATTACHED",
                "Initial SL/TP protection attached.",
                {"symbol": symbol, "attempt": attempt, "take_profit": take_profit, "stop_loss": stop_loss},
            )
            return None
        except ExchangeError as exc:
            last_error = str(exc)
            _safe_append_trade_event(
                journal_id,
                "PROTECTION_RETRY" if attempt == 1 else "PROTECTION_FAILED",
                "Protection attach failed.",
                {"symbol": symbol, "attempt": attempt, "error": last_error},
            )
    return last_error


def _safe_update_trade_entry(journal_id: str, updates: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = update_trade_entry(journal_id, updates)
        if payload is None:
            return None, "journal entry not found"
        return payload, None
    except Exception as exc:
        return None, str(exc)


def _safe_append_trade_event(journal_id: str, event_type: str, message: str, metadata: dict[str, Any]) -> None:
    try:
        append_trade_event(journal_id, event_type, message, metadata)
    except Exception:
        return


def _safe_log_bot_event(event_type: str, message: str, *, level: str, metadata: dict[str, Any]) -> None:
    try:
        log_bot_event(event_type, message, level=level, metadata=metadata)
    except Exception:
        return


def _add_active_trade_once(trade: dict[str, Any]) -> None:
    journal_id = str(trade.get("journal_id") or "")
    execution_key = str(trade.get("execution_key") or "")
    order_id = str(trade.get("order_id") or "")
    with _execution_lock:
        duplicate = any(
            (journal_id and str(item.get("journal_id") or "") == journal_id)
            or (execution_key and str(item.get("execution_key") or "") == execution_key)
            or (order_id and str(item.get("order_id") or "") == order_id)
            for item in _active_trades
        )
        if not duplicate:
            _active_trades.append(dict(trade))
        if order_id and order_id not in _active_order_ids:
            _active_order_ids.append(order_id)


def _build_management_state(entry: float, stop_loss: float, take_profit: float, quantity: str, direction: str) -> dict[str, Any]:
    risk = abs(entry - stop_loss)
    qty_value = _to_float(quantity, 0.0)

    if direction == "long":
        tp1 = entry + risk * 2.0
        tp2 = entry + risk * 2.5
        runner_target = entry + risk * 3.0
    else:
        tp1 = entry - risk * 2.0
        tp2 = entry - risk * 2.5
        runner_target = entry - risk * 3.0

    return {
        "tp1": tp1,
        "tp2": tp2,
        "strategy_take_profit": take_profit,
        "runner_target": runner_target,
        "tp1_fraction": 0.5,
        "tp2_fraction": 0.25,
        "runner_fraction": 0.25,
        "initial_quantity": qty_value,
        "remaining_quantity": qty_value,
        "tp1_done": False,
        "tp2_done": False,
        "break_even_set": False,
        "trailing_stop": None,
        "last_momentum_check": None,
        "last_state_change": _utc_now_iso(),
    }


def _calculate_realized_pnl(trade: dict[str, Any], *, exit_price: float, fees: float = 0.0) -> float | None:
    entry = _optional_float(trade.get("entry"))
    quantity = _optional_float(trade.get("remaining_quantity") or trade.get("quantity"))
    direction = str(trade.get("direction", "")).lower()
    if entry is None or quantity is None or quantity <= 0 or direction not in {"long", "short"}:
        return None

    gross = (exit_price - entry) * quantity if direction == "long" else (entry - exit_price) * quantity
    net = gross - max(fees, 0.0)
    return round(net, 8)


def _optional_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None


def _to_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
