"""Public execution API.

The legacy durable state helpers live in execution_core. All new order entry is
routed through execution_service so risk validation, sizing, fill confirmation
and protection verification have a single authoritative path. Exchange-native
partial profit orders are installed before a successful execution is returned.
"""

from typing import Any

from app.execution_core import (
    RESULT_EXECUTION_FAILED,
    RESULT_EXECUTION_UNCERTAIN,
    RESULT_PROTECTION_FAILED,
    SL_REASON_EXCHANGE_CLOSE,
    SL_REASON_FORCED_RISK_CLOSE,
    SL_REASON_UNKNOWN,
    _active_order_ids,
    _active_trades,
    _add_active_trade_once,
    _attach_protection_with_retry,
    _build_execution_key,
    _build_management_state,
    _build_order_link_id,
    _calculate_realized_pnl,
    _closed_trades,
    _emergency_close,
    _execution_lock,
    _handle_post_order_journal_failure,
    _handle_protection_failure,
    _normalize_signal,
    _optional_float,
    _place_market_order,
    _recover_order_by_link_id,
    _safe_append_trade_event,
    _safe_log_bot_event,
    _safe_update_trade_entry,
    _to_float,
    _utc_now_iso,
    add_closed_trades,
    close_trade,
    get_active_trades,
    get_closed_trades,
    replace_active_trades,
    update_active_trade,
)
from app.execution_service import (
    _emergency_close_pending_sync,
    execute_signal as _execute_signal_authoritatively,
)
from app.journal import append_trade_event, update_trade_entry
from app.market_quality import validate_spread
from app.native_profit_orders import (
    _set_and_verify_protection,
    cancel_native_profit_orders,
    install_native_profit_orders,
)
from app.trade_management_profiles import (
    build_profile_management_state,
    extract_observed_entry_fee,
    trade_type_from_trade,
)


def execute_signal(client: Any, signal: dict[str, Any], auto_triggered: bool = False) -> dict[str, Any]:
    spread_gate = _execution_spread_gate(client, str(signal.get("symbol") or "").upper())
    if not spread_gate.get("allowed"):
        return {
            "ok": False,
            "error": "SPREAD_GATE_REJECTED",
            "detail": spread_gate.get("reason"),
            "spread": spread_gate,
        }

    result = _execute_signal_authoritatively(client, signal, auto_triggered)

    if result.get("error") == "FILL_CONFIRMATION_UNAVAILABLE":
        trade = result.get("trade") if isinstance(result.get("trade"), dict) else None
        if not trade:
            return result
        safe_result = _emergency_close_pending_sync(
            client=client,
            trade=trade,
            error="FILL_CONFIRMATION_UNAVAILABLE",
            detail=str(
                (trade.get("exchange_metadata") or {}).get("fill_confirmation_error")
                or "Order fill could not be confirmed; emergency close was required."
            ),
            sizing=result.get("sizing") or {},
        )
        _sync_active_safety_state(safe_result)
        return safe_result

    if not result.get("ok"):
        return result

    trade = result.get("trade") if isinstance(result.get("trade"), dict) else None
    if not trade:
        return {"ok": False, "error": "ACTIVE_TRADE_PAYLOAD_UNAVAILABLE", **result}

    profiled = _apply_management_profile(client, trade, spread_gate)
    if not profiled.get("ok"):
        safe_result = _emergency_close_pending_sync(
            client=client,
            trade=profiled.get("trade") or trade,
            error="MANAGEMENT_PROFILE_INSTALLATION_FAILED",
            detail=str(profiled.get("error") or "Trade management profile could not be installed and verified."),
            sizing=result.get("sizing") or {},
        )
        _sync_active_safety_state(safe_result)
        return safe_result
    trade = profiled["trade"]

    native_setup = install_native_profit_orders(client, trade)
    if not native_setup.get("ok"):
        cancel_native_profit_orders(client, trade)
        safe_result = _emergency_close_pending_sync(
            client=client,
            trade=trade,
            error="NATIVE_TP_INSTALLATION_FAILED",
            detail=str(native_setup.get("error") or "Exchange-native TP1/TP2 orders could not be installed."),
            sizing=result.get("sizing") or {},
        )
        _sync_active_safety_state(safe_result)
        return safe_result

    management = dict(native_setup.get("management") or {})
    orders = dict(native_setup.get("orders") or {})
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    updated_trade = {
        **trade,
        "trade_type": management.get("trade_type"),
        "take_profit": management.get("runner_target"),
        "management": management,
        "exchange_metadata": {
            **metadata,
            "trade_type": management.get("trade_type"),
            "management": management,
            "native_profit_orders": orders,
            "execution_spread": spread_gate,
        },
    }
    journal_id = str(updated_trade.get("journal_id") or "")
    try:
        persisted = update_trade_entry(
            journal_id,
            {
                "status": "active",
                "take_profit": updated_trade.get("take_profit"),
                "exchange_metadata": updated_trade["exchange_metadata"],
            },
        )
    except Exception as exc:
        persisted = None
        persist_error = str(exc)
    else:
        persist_error = "journal entry not found" if persisted is None else ""

    if persisted is None:
        cancel_native_profit_orders(client, updated_trade)
        safe_result = _emergency_close_pending_sync(
            client=client,
            trade=updated_trade,
            error="NATIVE_TP_STATE_PERSIST_FAILED",
            detail=persist_error or "Native TP state could not be persisted.",
            sizing=result.get("sizing") or {},
        )
        _sync_active_safety_state(safe_result)
        return safe_result

    update_active_trade(
        journal_id,
        {
            "trade_type": management.get("trade_type"),
            "take_profit": management.get("runner_target"),
            "management": management,
            "exchange_metadata": updated_trade["exchange_metadata"],
        },
    )
    try:
        append_trade_event(
            journal_id,
            "NATIVE_TP_ORDERS_INSTALLED",
            "Exchange-native TP1 and TP2 reduce-only orders were installed.",
            {
                "symbol": updated_trade.get("symbol"),
                "trade_type": management.get("trade_type"),
                "profile_name": management.get("profile_name"),
                "tp1": orders.get("tp1"),
                "tp2": orders.get("tp2"),
            },
        )
    except Exception:
        pass

    result["trade"] = updated_trade
    result["native_profit_orders"] = orders
    result["management_profile"] = management.get("profile_name")
    result["spread"] = spread_gate
    return result


def _execution_spread_gate(client: Any, symbol: str) -> dict[str, Any]:
    if not symbol:
        return {"allowed": False, "reason": "SPREAD_UNAVAILABLE", "spread_bps": None}

    single_ticker_method = getattr(client, "safe_fetch_ticker", None)
    if callable(single_ticker_method):
        try:
            ok, ticker, error = single_ticker_method(symbol=symbol)
        except Exception as exc:
            return {"allowed": False, "reason": str(exc), "spread_bps": None}
        if ok and ticker:
            return validate_spread(ticker)
        return {"allowed": False, "reason": error or "SPREAD_UNAVAILABLE", "spread_bps": None}

    market_tickers_method = getattr(client, "safe_fetch_market_tickers", None)
    if callable(market_tickers_method):
        try:
            ok, tickers, error = market_tickers_method()
        except Exception as exc:
            return {"allowed": False, "reason": str(exc), "spread_bps": None}
        if not ok:
            return {"allowed": False, "reason": error or "SPREAD_UNAVAILABLE", "spread_bps": None}
        ticker = next(
            (
                item
                for item in tickers
                if str(item.get("symbol") or "").upper() == symbol
            ),
            None,
        )
        if ticker:
            return validate_spread(ticker)
        return {"allowed": False, "reason": "SPREAD_UNAVAILABLE", "spread_bps": None}

    public_get = getattr(client, "_public_get", None)
    if callable(public_get):
        try:
            payload = public_get("/v5/market/tickers", {"category": "linear", "symbol": symbol})
            items = payload.get("list", []) if isinstance(payload, dict) else []
            ticker = items[0] if items else None
        except Exception as exc:
            return {"allowed": False, "reason": str(exc), "spread_bps": None}
        if ticker:
            return validate_spread(ticker)

    return {"allowed": False, "reason": "SPREAD_UNAVAILABLE", "spread_bps": None}


def _apply_management_profile(client: Any, trade: dict[str, Any], spread_gate: dict[str, Any]) -> dict[str, Any]:
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    trade_type = trade_type_from_trade(trade)
    management = build_profile_management_state(
        entry=float(trade.get("entry") or 0.0),
        stop_loss=float(trade.get("stop_loss") or 0.0),
        take_profit=float(trade.get("take_profit") or 0.0),
        quantity=float(trade.get("remaining_quantity") or trade.get("quantity") or 0.0),
        direction=str(trade.get("direction") or ""),
        trade_type=trade_type,
        observed_entry_fee=extract_observed_entry_fee(trade),
    )
    management["last_state_change"] = _utc_now_iso()
    profiled_trade = {
        **trade,
        "trade_type": trade_type,
        "take_profit": management["runner_target"],
        "management": management,
        "exchange_metadata": {
            **metadata,
            "trade_type": trade_type,
            "management": management,
            "execution_spread": spread_gate,
        },
    }

    ok_symbol, symbol_infos, symbol_error = client.safe_fetch_symbol_info(symbol=str(profiled_trade.get("symbol") or ""))
    if not ok_symbol or not symbol_infos:
        return {"ok": False, "error": symbol_error or "Symbol precision unavailable", "trade": profiled_trade}
    ok_positions, positions, positions_error = client.safe_fetch_positions()
    if not ok_positions:
        return {"ok": False, "error": positions_error or "Position unavailable", "trade": profiled_trade}
    direction_side = "buy" if str(profiled_trade.get("direction") or "").lower() == "long" else "sell"
    position = next(
        (
            item
            for item in positions
            if str(item.get("symbol") or "").upper() == str(profiled_trade.get("symbol") or "").upper()
            and str(item.get("side") or "").lower() == direction_side
            and float(item.get("size") or 0.0) > 0
        ),
        None,
    )
    if position is None:
        return {"ok": False, "error": "Position unavailable during profile protection verification", "trade": profiled_trade}

    protection = _set_and_verify_protection(
        client,
        trade=profiled_trade,
        position=position,
        stop_loss=float(profiled_trade.get("stop_loss") or 0.0),
        take_profit=float(management["runner_target"]),
        tick_size=float(symbol_infos[0].get("tickSize") or 1e-8),
    )
    if not protection.get("ok"):
        return {"ok": False, "error": protection.get("error"), "trade": profiled_trade}
    management["profile_protection_verified"] = True
    management["profile_protection"] = protection
    profiled_trade["management"] = management
    profiled_trade["exchange_metadata"]["management"] = management
    return {"ok": True, "trade": profiled_trade}


def _sync_active_safety_state(result: dict[str, Any]) -> None:
    updated_trade = result.get("trade") if isinstance(result.get("trade"), dict) else None
    if not updated_trade or not updated_trade.get("journal_id"):
        return
    update_active_trade(
        str(updated_trade["journal_id"]),
        {
            "status": updated_trade.get("status"),
            "result": updated_trade.get("result"),
            "close_reason": updated_trade.get("close_reason"),
            "exchange_metadata": updated_trade.get("exchange_metadata"),
        },
    )


__all__ = [
    "execute_signal",
    "get_active_trades",
    "get_closed_trades",
    "replace_active_trades",
    "update_active_trade",
    "close_trade",
    "add_closed_trades",
]
