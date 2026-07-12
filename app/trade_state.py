from __future__ import annotations

from typing import Any

# Rows in these states represent an exchange-confirmed open position or an
# execution that must remain reserved until the exchange outcome is known.
CAPACITY_BLOCKING_STATUSES = {
    "pending_execution",
    "order_submitted",
    "fill_confirmation_pending",
    "order_filled",
    "protection_pending",
    "active",
    "partial_fill",
    "close_requested",
    "close_uncertain",
    "execution_uncertain",
    "emergency_close_failed",
}

# Only these states may be counted as an operator-visible active position.
EXCHANGE_ACTIVE_STATUSES = {
    "active",
    "partial_fill",
    "close_requested",
    "close_uncertain",
}

NON_ACTIVE_RECONCILIATION_STATUSES = {
    "journal_stale",
    "reconciliation_pending",
    "close_pending_sync",
    "closed",
}


def normalize_status(value: Any) -> str:
    return str(value or "").strip().lower()


def is_capacity_blocking_status(value: Any) -> bool:
    return normalize_status(value) in CAPACITY_BLOCKING_STATUSES


def is_exchange_active_status(value: Any) -> bool:
    return normalize_status(value) in EXCHANGE_ACTIVE_STATUSES


def exchange_confirmed(trade: dict[str, Any]) -> bool:
    if trade.get("exchange_confirmed_active") is True:
        return True
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    reconciliation = metadata.get("reconciliation") if isinstance(metadata.get("reconciliation"), dict) else {}
    return reconciliation.get("exchange_confirmed_active") is True
