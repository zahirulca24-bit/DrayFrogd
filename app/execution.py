"""Public execution API.

The legacy durable state helpers live in execution_core. All new order entry is
routed through execution_service so risk validation, sizing, fill confirmation
and protection verification have a single authoritative path.
"""

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
from app.execution_service import execute_signal

__all__ = [
    "execute_signal",
    "get_active_trades",
    "get_closed_trades",
    "replace_active_trades",
    "update_active_trade",
    "close_trade",
    "add_closed_trades",
]
