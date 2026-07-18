from __future__ import annotations

from math import isfinite
from typing import Any

from app.trade_state import is_exchange_active_status, normalize_status

AUTHORITATIVE_CLOSE_SOURCES = {
    "bybit_position_closed_pnl",
    "bybit_account_transaction_log",
}

REJECTED_RESULTS = {
    "execution_failed",
    "order_rejected",
}

REJECTED_CLOSE_REASONS = {
    "order_not_accepted",
}

PENDING_FINANCIAL_STATUSES = {
    "close_requested",
    "close_uncertain",
    "close_pending_sync",
    "reconciliation_pending",
    "execution_uncertain",
}


def annotate_trade_truth(trade: dict[str, Any]) -> dict[str, Any]:
    """Attach the single counting/performance decision used by every surface."""

    decision = performance_decision(trade)
    status = normalize_status(trade.get("status"))
    counts_as_trade = is_exchange_active_status(status) or decision["eligible"]
    if is_exchange_active_status(status):
        count_reason = "exchange_active"
    elif decision["eligible"]:
        count_reason = "financially_reconciled_closed"
    else:
        count_reason = decision["reason"]

    return {
        **trade,
        "counts_as_trade": counts_as_trade,
        "trade_count_reason": count_reason,
        "performance_eligible": decision["eligible"],
        "performance_exclusion_reason": None if decision["eligible"] else decision["reason"],
        "financial_reconciliation_status": (
            "reconciled"
            if decision["eligible"]
            else "pending"
            if status in PENDING_FINANCIAL_STATUSES
            else "excluded"
        ),
        "financial_truth_source": decision.get("source"),
    }


def performance_decision(trade: dict[str, Any]) -> dict[str, Any]:
    status = normalize_status(trade.get("status"))
    if status != "closed":
        return _decision(False, "not_financially_closed")

    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    close_sync = metadata.get("close_sync") if isinstance(metadata.get("close_sync"), dict) else {}
    source = str(close_sync.get("source") or "").strip().lower()

    result = str(trade.get("result") or "").strip().lower()
    close_reason = str(trade.get("close_reason") or "").strip().lower()
    if (result in REJECTED_RESULTS or close_reason in REJECTED_CLOSE_REASONS) and source not in AUTHORITATIVE_CLOSE_SOURCES:
        return _decision(False, "order_rejected_or_not_accepted", source)

    missing_fields = [
        field
        for field in ("exit_price", "realized_pnl", "fees")
        if _number(trade.get(field)) is None
    ]
    if missing_fields:
        return _decision(False, f"missing_{'_'.join(missing_fields)}", source)

    if source not in AUTHORITATIVE_CLOSE_SOURCES:
        return _decision(False, "authoritative_close_source_missing", source)

    records = close_sync.get("records") if isinstance(close_sync.get("records"), list) else []
    record_keys = close_sync.get("record_keys") if isinstance(close_sync.get("record_keys"), list) else []
    if not records and not record_keys:
        return _decision(False, "authoritative_close_records_missing", source)

    if not _has_close_identity(close_sync, records):
        return _decision(False, "authoritative_close_identity_missing", source)

    return _decision(True, "financially_reconciled", source)


def filter_performance_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [annotated for trade in trades if (annotated := annotate_trade_truth(trade))["performance_eligible"]]


def _has_close_identity(close_sync: dict[str, Any], records: list[Any]) -> bool:
    for key in (
        "close_order_ids",
        "matched_close_order_ids",
        "matched_close_order_link_ids",
        "close_exec_ids",
    ):
        values = close_sync.get(key)
        if isinstance(values, (list, tuple, set)) and any(str(value or "").strip() for value in values):
            return True

    for record in records:
        if not isinstance(record, dict):
            continue
        for key in (
            "orderId",
            "order_id",
            "orderLinkId",
            "order_link_id",
            "execId",
            "exec_id",
            "transactionId",
            "transaction_id",
            "id",
        ):
            if str(record.get(key) or "").strip():
                return True
    return False


def _decision(eligible: bool, reason: str, source: str | None = None) -> dict[str, Any]:
    return {
        "eligible": eligible,
        "reason": reason,
        "source": source or None,
    }


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None
