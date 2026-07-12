from __future__ import annotations

import hashlib
from typing import Any

from app.journal import create_trade_entry, get_open_trade_history, get_trade_by_execution_key
from app.reconciliation_identity import (
    _coerce_float, _identity_payload, _metadata_identity, _position_identity,
    _position_snapshot, _timestamp_ms_to_iso, _trade_identity, _trade_timestamp, _utc_now_iso,
)

CLOSE_WORKFLOW_STATUSES = {"close_requested", "close_uncertain"}


def _safe_open_trade_history() -> list[dict[str, Any]]:
    try:
        return get_open_trade_history(limit=500)
    except Exception:
        return []


def _dedupe_candidates(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    anonymous = 0
    for trade in trades:
        key = _candidate_id(trade)
        if not key:
            anonymous += 1
            key = f"anonymous:{anonymous}:{id(trade)}"
        current = deduped.get(key)
        if current is None or _trade_timestamp(trade) >= _trade_timestamp(current):
            deduped[key] = dict(trade)
    return list(deduped.values())


def _candidate_id(trade: dict[str, Any]) -> str:
    journal_id = str(trade.get("journal_id") or "").strip()
    if journal_id:
        return f"journal:{journal_id}"
    execution_key = str(trade.get("execution_key") or "").strip()
    if execution_key:
        return f"execution:{execution_key}"
    return ""


def _match_candidate(
    candidates: list[dict[str, Any]],
    identity: tuple[str, str, str, int],
) -> dict[str, Any] | None:
    exact = [trade for trade in candidates if _metadata_identity(trade) == identity]
    if exact:
        return max(exact, key=_trade_timestamp)

    compatible = [trade for trade in candidates if _trade_identity(trade, identity[0]) == identity]
    if compatible:
        return max(compatible, key=_trade_timestamp)

    legacy = [
        trade
        for trade in candidates
        if str(trade.get("execution_mode") or identity[0]).lower() == identity[0]
        and str(trade.get("symbol") or "").upper() == identity[1]
        and str(trade.get("direction") or "").lower() == identity[2]
    ]
    return max(legacy, key=_trade_timestamp) if len(legacy) == 1 else None


def _recover_exchange_position(position: dict[str, Any], mode: str) -> dict[str, Any]:
    identity = _position_identity(position, mode)
    created_ms = str(position.get("createdTime") or position.get("updatedTime") or "")
    seed = "|".join([*map(str, identity), created_ms, str(position.get("avgPrice") or "")])
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    execution_key = f"recovered-{digest[:48]}"
    existing = get_trade_by_execution_key(execution_key)
    if existing is not None:
        return existing

    snapshot = _position_snapshot(position)
    opened_at = _timestamp_ms_to_iso(position.get("createdTime") or position.get("updatedTime"))
    trade = {
        "journal_id": f"exchange-{digest[:32]}",
        "execution_key": execution_key,
        "symbol": identity[1],
        "strategy_name": "unknown",
        "strategy": "unknown",
        "direction": identity[2],
        "entry": snapshot["entry"],
        "stop_loss": snapshot["stop_loss"] or snapshot["entry"],
        "take_profit": snapshot["take_profit"] or snapshot["entry"],
        "quantity": snapshot["size"],
        "remaining_quantity": snapshot["size"],
        "status": "active",
        "opened_at": opened_at,
        "execution_mode": mode,
        "order_id": None,
        "exchange_metadata": {
            "source": "exchange_position_recovery",
            "needs_attention": True,
            "exchange_identity": _identity_payload(identity),
            "position_snapshot": position,
            "reconciliation": {
                "status": "exchange_unmatched_recovered",
                "exchange_confirmed_active": True,
                "recovered_at": _utc_now_iso(),
            },
        },
    }
    return create_trade_entry(trade)


def _merge_position(
    trade: dict[str, Any],
    position: dict[str, Any],
    orders: list[dict[str, Any]],
    ticker_price: float | None,
    identity: tuple[str, str, str, int],
    *,
    recovered: bool,
) -> dict[str, Any]:
    snapshot = _position_snapshot(position)
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    status = str(trade.get("status") or "active").lower()
    visible_status = status if status in CLOSE_WORKFLOW_STATUSES else "active"
    mark_price = snapshot["mark_price"] or ticker_price

    result = {
        **trade,
        "symbol": identity[1],
        "direction": identity[2],
        "execution_mode": identity[0],
        "quantity": snapshot["size"],
        "remaining_quantity": snapshot["size"],
        "entry": snapshot["entry"] or _coerce_float(trade.get("entry"), 0.0),
        "status": visible_status,
        "mark_price": mark_price,
        "leverage": snapshot["leverage"],
        "position_value": snapshot["position_value"],
        "position_margin": snapshot["position_margin"],
        "unrealized_pnl": snapshot["unrealized_pnl"],
        "pnl_percent": snapshot["pnl_percent"],
        "liquidation_price": snapshot["liquidation_price"],
        "sl_tp_orders": list(orders),
        "position_synced": True,
        "exchange_confirmed_active": True,
        "live_metrics_available": snapshot["live_metrics_available"],
        "close_allowed": True,
        "close_blocked_reason": None,
        "exchange_metadata": {
            **metadata,
            "exchange_identity": _identity_payload(identity),
            "position_snapshot": position,
            "live_metrics_source": "bybit_position",
            "reconciliation": {
                **(metadata.get("reconciliation") if isinstance(metadata.get("reconciliation"), dict) else {}),
                "status": "exchange_confirmed_active",
                "exchange_confirmed_active": True,
                "recovered": recovered,
                "last_reconciled_at": _utc_now_iso(),
            },
        },
    }
    if snapshot["stop_loss"]:
        result["stop_loss"] = snapshot["stop_loss"]
    if snapshot["take_profit"]:
        result["take_profit"] = snapshot["take_profit"]
    return result


def _pending_order_trade(trade: dict[str, Any], open_order: dict[str, Any]) -> dict[str, Any]:
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    previous_reconciliation = metadata.get("reconciliation") if isinstance(metadata.get("reconciliation"), dict) else {}
    order_qty = _coerce_float(open_order.get("qty"), None)
    executed_qty = _coerce_float(open_order.get("cumExecQty"), None)
    status = "partial_fill" if order_qty and executed_qty is not None and 0 < executed_qty < order_qty else "reconciliation_pending"
    return {
        **trade,
        "status": status,
        "exchange_confirmed_active": False,
        "position_synced": False,
        "live_metrics_available": False,
        "close_allowed": False,
        "close_blocked_reason": "Open order exists, but no exchange position is confirmed",
        "order_status": open_order.get("orderStatus"),
        "filled_quantity": executed_qty,
        "_reconciliation_event_required": previous_reconciliation.get("status") != "pending_order",
        "exchange_metadata": {
            **metadata,
            "reconciliation": {
                **(metadata.get("reconciliation") if isinstance(metadata.get("reconciliation"), dict) else {}),
                "status": "pending_order",
                "exchange_confirmed_active": False,
                "last_reconciled_at": _utc_now_iso(),
            },
        },
    }
