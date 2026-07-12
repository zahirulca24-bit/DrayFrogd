from __future__ import annotations

from typing import Any

from app.journal import append_trade_event, update_trade_entry
from app.reconciliation_identity import _coerce_float, _utc_now_iso


def _mark_journal_stale(trade: dict[str, Any], error: str) -> dict[str, Any]:
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    previous_reconciliation = metadata.get("reconciliation") if isinstance(metadata.get("reconciliation"), dict) else {}
    return {
        **trade,
        "status": "closed",
        "result": trade.get("result") or "reconciliation_stale",
        "close_reason": trade.get("close_reason") or "EXCHANGE_POSITION_ABSENT",
        "_reconciliation_event_required": previous_reconciliation.get("status") != "journal_stale",
        "close_sync_error": error,
        "exchange_confirmed_active": False,
        "position_synced": False,
        "live_metrics_available": False,
        "close_allowed": False,
        "close_blocked_reason": "No exchange position is confirmed",
        "exchange_metadata": {
            **metadata,
            "reconciliation": {
                **(metadata.get("reconciliation") if isinstance(metadata.get("reconciliation"), dict) else {}),
                "status": "journal_stale",
                "exchange_confirmed_active": False,
                "error": error,
                "last_reconciled_at": _utc_now_iso(),
            },
            "close_sync": {
                **(metadata.get("close_sync") if isinstance(metadata.get("close_sync"), dict) else {}),
                "status": "pending",
                "error": error,
            },
        },
    }


def _persist_active_trade(trade: dict[str, Any], previous: dict[str, Any]) -> None:
    journal_id = str(trade.get("journal_id") or "").strip()
    if not journal_id:
        return
    update_trade_entry(
        journal_id,
        {
            "status": trade.get("status"),
            "entry_price": trade.get("entry"),
            "stop_loss": trade.get("stop_loss"),
            "take_profit": trade.get("take_profit"),
            "quantity": trade.get("quantity"),
            "strategy_name": trade.get("strategy_name") or trade.get("strategy") or "unknown",
            "opened_at": trade.get("opened_at"),
            "exchange_metadata": trade.get("exchange_metadata"),
        },
    )
    previous_metadata = previous.get("exchange_metadata") if isinstance(previous.get("exchange_metadata"), dict) else {}
    previous_reconciliation = previous_metadata.get("reconciliation") if isinstance(previous_metadata.get("reconciliation"), dict) else {}
    previous_size = _coerce_float(previous.get("remaining_quantity") or previous.get("quantity"), None)
    current_size = _coerce_float(trade.get("remaining_quantity") or trade.get("quantity"), None)
    if previous_reconciliation.get("status") != "exchange_confirmed_active" or previous_size != current_size:
        append_trade_event(
            journal_id,
            "RECONCILED_ACTIVE",
            "Trade synchronized from the authoritative Bybit exchange position.",
            {
                "symbol": trade.get("symbol"),
                "direction": trade.get("direction"),
                "quantity": trade.get("quantity"),
                "position_idx": ((trade.get("exchange_metadata") or {}).get("exchange_identity") or {}).get("position_idx"),
            },
        )


def _persist_reconciliation_state(
    journal_id: str,
    trade: dict[str, Any],
    *,
    event_type: str,
    message: str,
) -> None:
    if not journal_id:
        return
    update_trade_entry(
        journal_id,
        {
            "status": trade.get("status"),
            "quantity": trade.get("quantity"),
            "exchange_metadata": trade.get("exchange_metadata"),
        },
    )
    if trade.get("_reconciliation_event_required", True):
        append_trade_event(journal_id, event_type, message, {"symbol": trade.get("symbol"), "status": trade.get("status")})


def _persist_pending_close_sync(journal_id: str, trade: dict[str, Any]) -> None:
    if not journal_id:
        return
    update_trade_entry(
        journal_id,
        {
            "status": "closed",
            "result": trade.get("result") or "reconciliation_stale",
            "close_reason": trade.get("close_reason") or "EXCHANGE_POSITION_ABSENT",
            "exchange_metadata": trade.get("exchange_metadata"),
        },
    )
    if not trade.get("_reconciliation_event_required", True):
        return
    append_trade_event(
        journal_id,
        "JOURNAL_STALE_POSITION_ABSENT",
        "Journal row is not counted as active because no exchange position or open order is confirmed.",
        {"symbol": trade.get("symbol"), "error": trade.get("close_sync_error")},
    )


def _persist_reconciliation_event(
    journal_id: str,
    event_type: str,
    message: str,
    payload: dict[str, Any],
) -> None:
    if not journal_id:
        return
    status = payload.get("status")
    if status:
        update_trade_entry(journal_id, {"status": status})
    append_trade_event(journal_id, event_type, message, payload)
