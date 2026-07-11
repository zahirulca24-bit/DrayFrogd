from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from math import isfinite
from typing import Any, Callable

from app.close_fill_sync import fetch_exact_close_result
from app.exchange import BybitClient, ExchangeError
from app.execution import close_trade, get_active_trades, update_active_trade
from app.journal import (
    append_trade_event,
    create_trade_entry,
    get_open_trade_history,
    log_bot_event,
    update_trade_entry,
)
from app.risk import release_active_trade


CLOSE_WORKFLOW_STATUSES = {
    "close_requested",
    "close_uncertain",
    "close_pending_sync",
}
UNSAFE_CLOSE_STATUSES = {
    "pending_execution",
    "order_submitted",
    "execution_uncertain",
    "emergency_close_failed",
    "protection_pending",
    *CLOSE_WORKFLOW_STATUSES,
}


def enrich_active_trades(
    trades: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    execution_mode: str,
    *,
    journal_factory: Callable[[dict[str, Any]], dict[str, Any]] = create_trade_entry,
) -> list[dict[str, Any]]:
    """Merge authoritative Bybit position metrics into local open trades."""
    merged = [dict(trade) for trade in trades]
    trades_by_symbol = {str(trade.get("symbol", "")).upper(): trade for trade in merged}
    open_positions = [position for position in positions if _position_is_open(position)]
    open_symbols = {str(position.get("symbol", "")).upper() for position in open_positions}

    for trade in merged:
        symbol = str(trade.get("symbol", "")).upper()
        if symbol not in open_symbols:
            trade.update(
                {
                    "position_synced": False,
                    "live_metrics_available": False,
                    "close_allowed": False,
                    "close_blocked_reason": "Exchange position is not currently confirmed",
                }
            )

    for position in open_positions:
        symbol = str(position.get("symbol", "")).upper()
        if not symbol:
            continue

        snapshot = _position_snapshot(position)
        existing = trades_by_symbol.get(symbol)
        if existing is None:
            trade = {
                "symbol": symbol,
                "strategy_name": "unknown",
                "strategy": "unknown",
                "direction": snapshot["direction"],
                "entry": snapshot["entry"],
                "stop_loss": snapshot["stop_loss"] or snapshot["entry"],
                "take_profit": snapshot["take_profit"] or snapshot["entry"],
                "quantity": snapshot["size"],
                "remaining_quantity": snapshot["size"],
                "status": "active",
                "opened_at": _utc_now_iso(),
                "execution_mode": execution_mode,
                "order_id": None,
                "journal_id": f"exchange-{execution_mode}-{symbol}",
                "exchange_metadata": {
                    "source": "exchange_position_only",
                    "position_snapshot": position,
                },
            }
            journal = journal_factory(trade)
            trade["journal_id"] = journal["journal_id"]
            merged.append(trade)
            trades_by_symbol[symbol] = trade
            existing = trade

        status = str(existing.get("status") or "active").lower()
        close_allowed, blocked_reason = _close_permission(existing, snapshot)
        metadata = existing.get("exchange_metadata") if isinstance(existing.get("exchange_metadata"), dict) else {}
        existing.update(
            {
                "quantity": snapshot["size"],
                "remaining_quantity": snapshot["size"],
                "entry": snapshot["entry"] or _number(existing.get("entry")) or 0.0,
                "direction": snapshot["direction"],
                "status": status if status in CLOSE_WORKFLOW_STATUSES else "active",
                "mark_price": snapshot["mark_price"],
                "leverage": snapshot["leverage"],
                "position_value": snapshot["position_value"],
                "position_margin": snapshot["position_margin"],
                "unrealized_pnl": snapshot["unrealized_pnl"],
                "pnl_percent": snapshot["pnl_percent"],
                "liquidation_price": snapshot["liquidation_price"],
                "position_synced": True,
                "live_metrics_available": snapshot["live_metrics_available"],
                "close_allowed": close_allowed,
                "close_blocked_reason": blocked_reason,
                "exchange_metadata": {
                    **metadata,
                    "position_snapshot": position,
                    "live_metrics_source": "bybit_position",
                },
            }
        )
        if not _positive(existing.get("stop_loss")) and snapshot["stop_loss"]:
            existing["stop_loss"] = snapshot["stop_loss"]
        if not _positive(existing.get("take_profit")) and snapshot["take_profit"]:
            existing["take_profit"] = snapshot["take_profit"]

    return merged


def request_market_close(client: BybitClient, journal_id: str) -> dict[str, Any]:
    """Persist a close command before sending a reduce-only market order."""
    normalized_id = str(journal_id or "").strip()
    if not normalized_id:
        return {"ok": False, "error": "INVALID_JOURNAL_ID"}

    trade = _find_open_trade(normalized_id)
    if trade is None:
        return {"ok": False, "error": "TRADE_NOT_FOUND"}

    current_status = str(trade.get("status") or "").lower()
    if current_status in CLOSE_WORKFLOW_STATUSES:
        return {
            "ok": True,
            "duplicate": True,
            "status": current_status,
            "trade": trade,
            "message": "A close request is already being processed",
        }
    if current_status in UNSAFE_CLOSE_STATUSES:
        return {
            "ok": False,
            "error": "CLOSE_NOT_ALLOWED",
            "detail": f"Trade status {current_status or 'unknown'} is not safe for manual close",
        }

    ok_positions, positions, positions_error = client.safe_fetch_positions()
    if not ok_positions:
        return {
            "ok": False,
            "error": "POSITION_SYNC_FAILED",
            "detail": positions_error or "Exchange position data unavailable",
        }

    symbol = str(trade.get("symbol") or "").upper()
    position = next(
        (
            item
            for item in positions
            if str(item.get("symbol") or "").upper() == symbol and _position_is_open(item)
        ),
        None,
    )
    if position is None:
        return _sync_already_closed_position(client, trade)

    size = _number(position.get("size"))
    side = str(position.get("side") or "").lower()
    if size is None or size <= 0 or side not in {"buy", "sell"}:
        return {
            "ok": False,
            "error": "INVALID_EXCHANGE_POSITION",
            "detail": "Exchange position size or side is invalid",
        }

    close_side = "Sell" if side == "buy" else "Buy"
    close_request_id = _close_request_id(trade, size)
    requested_at = _utc_now_iso()
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    close_metadata = {
        **metadata,
        "manual_close": {
            "request_id": close_request_id,
            "requested_at": requested_at,
            "requested_size": size,
            "requested_side": close_side,
            "source": "active_trades_ui",
        },
    }

    try:
        persisted = update_trade_entry(
            normalized_id,
            {
                "status": "close_requested",
                "close_reason": "MANUAL_MARKET_CLOSE",
                "exchange_metadata": close_metadata,
            },
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": "CLOSE_RESERVATION_FAILED",
            "detail": str(exc),
        }
    if persisted is None:
        return {
            "ok": False,
            "error": "CLOSE_RESERVATION_FAILED",
            "detail": "Trade journal row was not found",
        }

    update_active_trade(
        normalized_id,
        {
            "status": "close_requested",
            "close_reason": "MANUAL_MARKET_CLOSE",
            "exchange_metadata": close_metadata,
        },
    )

    try:
        order = _submit_reduce_only_close(
            client,
            symbol=symbol,
            side=close_side,
            qty=_format_qty(size),
            order_link_id=close_request_id,
        )
    except ExchangeError as exc:
        return _handle_close_submission_error(
            client,
            trade={**trade, "status": "close_requested", "exchange_metadata": close_metadata},
            order_link_id=close_request_id,
            error=str(exc),
        )

    completed_metadata = {
        **close_metadata,
        "manual_close": {
            **close_metadata["manual_close"],
            "order_response": order,
            "submitted_at": _utc_now_iso(),
        },
    }
    update_active_trade(normalized_id, {"status": "close_requested", "exchange_metadata": completed_metadata})
    update_trade_entry(
        normalized_id,
        {
            "status": "close_requested",
            "close_reason": "MANUAL_MARKET_CLOSE",
            "exchange_metadata": completed_metadata,
        },
    )
    _safe_event(
        normalized_id,
        "MANUAL_MARKET_CLOSE_REQUESTED",
        "Reduce-only market close was submitted; exact close fill synchronization is pending.",
        {
            "symbol": symbol,
            "request_id": close_request_id,
            "quantity": size,
            "order": order,
        },
    )
    return {
        "ok": True,
        "duplicate": False,
        "status": "close_requested",
        "request_id": close_request_id,
        "order": order,
        "message": "Close submitted; waiting for exact Bybit fill and fee synchronization",
    }


def _sync_already_closed_position(client: BybitClient, trade: dict[str, Any]) -> dict[str, Any]:
    journal_id = str(trade.get("journal_id") or "")
    symbol = str(trade.get("symbol") or "").upper()
    exact_close, error = fetch_exact_close_result(client, trade)
    if exact_close is None:
        metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
        pending_metadata = {
            **metadata,
            "close_sync": {
                "status": "pending",
                "reason": error or "Exact Bybit close record is unavailable",
                "requested_at": _utc_now_iso(),
            },
        }
        update_active_trade(
            journal_id,
            {
                "status": "close_pending_sync",
                "close_reason": "POSITION_ABSENT_PENDING_EXACT_SYNC",
                "exchange_metadata": pending_metadata,
            },
        )
        update_trade_entry(
            journal_id,
            {
                "status": "close_pending_sync",
                "close_reason": "POSITION_ABSENT_PENDING_EXACT_SYNC",
                "exchange_metadata": pending_metadata,
            },
        )
        return {
            "ok": True,
            "duplicate": False,
            "status": "close_pending_sync",
            "message": "Position is already absent; exact close fill synchronization is pending",
            "detail": error,
        }

    closed = close_trade(journal_id, exact_close)
    release_active_trade(symbol)
    _safe_event(
        journal_id,
        "MANUAL_CLOSE_ALREADY_COMPLETED",
        "Position was already absent; exact Bybit close data was synchronized.",
        exact_close,
    )
    return {
        "ok": True,
        "duplicate": False,
        "status": "closed",
        "trade": closed or {**trade, **exact_close, "status": "closed"},
        "message": "Position was already closed and exact exchange data was synchronized",
    }


def _handle_close_submission_error(
    client: BybitClient,
    *,
    trade: dict[str, Any],
    order_link_id: str,
    error: str,
) -> dict[str, Any]:
    journal_id = str(trade.get("journal_id") or "")
    symbol = str(trade.get("symbol") or "").upper()
    lookup = getattr(client, "safe_fetch_order_by_link_id", None)
    lookup_ok = False
    recovered_order: dict[str, Any] | None = None
    lookup_error: str | None = "Order lookup is unavailable"
    if callable(lookup):
        try:
            lookup_ok, recovered_order, lookup_error = lookup(
                symbol=symbol,
                order_link_id=order_link_id,
            )
        except Exception as exc:
            lookup_error = str(exc)

    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    if recovered_order is not None:
        recovered_metadata = {
            **metadata,
            "manual_close": {
                **(metadata.get("manual_close") or {}),
                "submission_error": error,
                "recovered_order": recovered_order,
                "recovered_at": _utc_now_iso(),
            },
        }
        update_active_trade(journal_id, {"status": "close_requested", "exchange_metadata": recovered_metadata})
        update_trade_entry(journal_id, {"status": "close_requested", "exchange_metadata": recovered_metadata})
        return {
            "ok": True,
            "duplicate": False,
            "status": "close_requested",
            "request_id": order_link_id,
            "order": recovered_order,
            "message": "Close order was recovered after an ambiguous exchange response",
        }

    if lookup_ok:
        restored_metadata = {
            **metadata,
            "manual_close": {
                **(metadata.get("manual_close") or {}),
                "submission_error": error,
                "lookup": "not_found",
                "failed_at": _utc_now_iso(),
            },
        }
        update_active_trade(journal_id, {"status": "active", "exchange_metadata": restored_metadata})
        update_trade_entry(
            journal_id,
            {
                "status": "active",
                "close_reason": None,
                "exchange_metadata": restored_metadata,
            },
        )
        return {
            "ok": False,
            "error": "CLOSE_ORDER_REJECTED",
            "detail": error,
        }

    uncertain_metadata = {
        **metadata,
        "manual_close": {
            **(metadata.get("manual_close") or {}),
            "submission_error": error,
            "lookup_error": lookup_error,
            "uncertain_at": _utc_now_iso(),
        },
    }
    update_active_trade(journal_id, {"status": "close_uncertain", "exchange_metadata": uncertain_metadata})
    update_trade_entry(
        journal_id,
        {
            "status": "close_uncertain",
            "close_reason": "MANUAL_CLOSE_CONFIRMATION_UNAVAILABLE",
            "exchange_metadata": uncertain_metadata,
        },
    )
    _safe_log(
        "MANUAL_CLOSE_UNCERTAIN",
        f"Manual close confirmation is unavailable for {symbol}; duplicate close is blocked.",
        level="error",
        metadata={
            "journal_id": journal_id,
            "symbol": symbol,
            "request_id": order_link_id,
            "submission_error": error,
            "lookup_error": lookup_error,
        },
    )
    return {
        "ok": False,
        "error": "CLOSE_CONFIRMATION_UNAVAILABLE",
        "detail": lookup_error or error,
        "status": "close_uncertain",
    }


def _submit_reduce_only_close(
    client: BybitClient,
    *,
    symbol: str,
    side: str,
    qty: str,
    order_link_id: str,
) -> dict[str, Any]:
    private_post = getattr(client, "_private_post", None)
    if callable(private_post):
        return private_post(
            "/v5/order/create",
            {
                "category": "linear",
                "symbol": symbol,
                "side": side,
                "orderType": "Market",
                "qty": qty,
                "reduceOnly": True,
                "positionIdx": 0,
                "orderLinkId": order_link_id,
            },
        )

    close_method = getattr(client, "close_position_market")
    try:
        return close_method(
            symbol=symbol,
            side=side,
            qty=qty,
            order_link_id=order_link_id,
        )
    except TypeError as exc:
        if "order_link_id" not in str(exc):
            raise
        return close_method(symbol=symbol, side=side, qty=qty)


def _position_snapshot(position: dict[str, Any]) -> dict[str, Any]:
    size = _number(position.get("size")) or 0.0
    entry = _number(position.get("avgPrice")) or 0.0
    mark_price = _number(position.get("markPrice"))
    leverage = _number(position.get("leverage"))
    position_value = _number(position.get("positionValue"))
    if position_value is None and mark_price is not None:
        position_value = abs(mark_price * size)

    position_margin = _first_number(
        position.get("positionIM"),
        position.get("positionBalance"),
    )
    if position_margin is None and position_value is not None and leverage and leverage > 0:
        position_margin = position_value / leverage

    unrealized_pnl = _number(position.get("unrealisedPnl"))
    pnl_percent = None
    if unrealized_pnl is not None and position_margin is not None and position_margin > 0:
        pnl_percent = unrealized_pnl / position_margin * 100

    live_metrics_available = all(
        value is not None
        for value in (mark_price, leverage, position_value, position_margin, unrealized_pnl, pnl_percent)
    )
    return {
        "size": size,
        "direction": "short" if str(position.get("side") or "").lower() == "sell" else "long",
        "entry": entry,
        "mark_price": mark_price,
        "stop_loss": _number(position.get("stopLoss")),
        "take_profit": _number(position.get("takeProfit")),
        "leverage": leverage,
        "position_value": position_value,
        "position_margin": position_margin,
        "unrealized_pnl": unrealized_pnl,
        "pnl_percent": pnl_percent,
        "liquidation_price": _number(position.get("liqPrice")),
        "live_metrics_available": live_metrics_available,
    }


def _close_permission(trade: dict[str, Any], snapshot: dict[str, Any]) -> tuple[bool, str | None]:
    status = str(trade.get("status") or "active").lower()
    if status in UNSAFE_CLOSE_STATUSES:
        return False, f"Trade status is {status}"
    if not str(trade.get("journal_id") or "").strip():
        return False, "Trade journal identity is unavailable"
    if not snapshot.get("size") or snapshot.get("size") <= 0:
        return False, "Exchange position size is unavailable"
    if snapshot.get("direction") not in {"long", "short"}:
        return False, "Exchange position side is unavailable"
    return True, None


def _find_open_trade(journal_id: str) -> dict[str, Any] | None:
    trade = next(
        (item for item in get_active_trades() if str(item.get("journal_id") or "") == journal_id),
        None,
    )
    if trade is not None:
        return dict(trade)
    trade = next(
        (item for item in get_open_trade_history() if str(item.get("journal_id") or "") == journal_id),
        None,
    )
    return dict(trade) if trade is not None else None


def _close_request_id(trade: dict[str, Any], size: float) -> str:
    raw = "|".join(
        [
            "manual-close",
            str(trade.get("journal_id") or ""),
            str(trade.get("symbol") or "").upper(),
            format(size, ".12g"),
            str(trade.get("opened_at") or trade.get("detected_at") or ""),
        ]
    )
    return f"df-close-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def _position_is_open(position: dict[str, Any]) -> bool:
    size = _number(position.get("size"))
    return size is not None and size > 0


def _positive(value: Any) -> bool:
    numeric = _number(value)
    return numeric is not None and numeric > 0


def _first_number(*values: Any) -> float | None:
    for value in values:
        numeric = _number(value)
        if numeric is not None:
            return numeric
    return None


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None


def _format_qty(qty: float) -> str:
    return f"{qty:.8f}".rstrip("0").rstrip(".")


def _safe_event(journal_id: str, event_type: str, message: str, metadata: dict[str, Any]) -> None:
    try:
        append_trade_event(journal_id, event_type, message, metadata)
    except Exception:
        return


def _safe_log(event_type: str, message: str, *, level: str, metadata: dict[str, Any]) -> None:
    try:
        log_bot_event(event_type, message, level=level, metadata=metadata)
    except Exception:
        return


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
