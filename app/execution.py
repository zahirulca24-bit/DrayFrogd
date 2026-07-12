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
from app.native_profit_orders import cancel_native_profit_orders, install_native_profit_orders


def execute_signal(client: Any, signal: dict[str, Any], auto_triggered: bool = False) -> dict[str, Any]:
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
        "management": management,
        "exchange_metadata": {
            **metadata,
            "management": management,
            "native_profit_orders": orders,
        },
    }
    journal_id = str(updated_trade.get("journal_id") or "")
    try:
        persisted = update_trade_entry(
            journal_id,
            {
                "status": "active",
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
                "tp1": orders.get("tp1"),
                "tp2": orders.get("tp2"),
            },
        )
    except Exception:
        pass

    result["trade"] = updated_trade
    result["native_profit_orders"] = orders
    return result


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
