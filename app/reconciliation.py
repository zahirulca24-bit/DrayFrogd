from __future__ import annotations

from math import isfinite
from typing import Any

from app.close_fill_sync import fetch_exact_close_result
from app.execution import close_trade, get_active_trades, replace_active_trades
from app.exchange import BybitClient
from app.journal import append_trade_event, update_trade_entry
from app.risk import release_active_trade


def reconcile_state(client: BybitClient) -> dict[str, Any]:
    local_trades = get_active_trades()

    ok_orders, open_orders, orders_error = client.safe_fetch_open_orders()
    ok_positions, positions, positions_error = client.safe_fetch_positions()
    ok_tickers, tickers, _ = client.safe_fetch_market_tickers()
    if not ok_orders or not ok_positions:
        return {
            "ok": False,
            "error": orders_error or positions_error or "Reconciliation failed",
            "trades": local_trades,
        }

    open_orders_by_id = {
        str(order.get("orderId")): order
        for order in open_orders
        if order.get("orderId")
    }
    open_orders_by_symbol = _orders_by_symbol(open_orders)
    positions_by_symbol = {
        str(position.get("symbol")): position
        for position in positions
        if _position_is_open(position)
    }
    ticker_prices = _ticker_price_map(tickers if ok_tickers else [])

    updated_trades: list[dict[str, Any]] = []
    closed_trades: list[dict[str, Any]] = []
    closed_symbols: list[str] = []
    updates: list[dict[str, Any]] = []

    for trade in local_trades:
        symbol = str(trade.get("symbol", "")).upper()
        journal_id = str(trade.get("journal_id", "")).strip()
        order_id = str(trade.get("order_id", "")).strip()
        open_order = open_orders_by_id.get(order_id) if order_id else None
        position = positions_by_symbol.get(symbol)

        if position is None and open_order is None:
            ok_recheck, positions_recheck, recheck_error = client.safe_fetch_positions()
            position_recheck = None
            if ok_recheck:
                position_recheck = next(
                    (
                        item
                        for item in positions_recheck
                        if str(item.get("symbol", "")).upper() == symbol and _position_is_open(item)
                    ),
                    None,
                )

            if position_recheck is None:
                exact_close, close_sync_error = fetch_exact_close_result(client, trade)
                if exact_close is None:
                    pending_trade = _mark_close_pending_sync(
                        trade,
                        error=close_sync_error or recheck_error or "exact close data is unavailable",
                    )
                    updated_trades.append(pending_trade)
                    updates.append(
                        {
                            "symbol": symbol,
                            "status": "close_pending_sync",
                            "reason": pending_trade["close_sync_error"],
                        }
                    )
                    _persist_pending_close_sync(journal_id, pending_trade)
                    continue

                closed_trade = close_trade(journal_id, exact_close) if journal_id else None
                if closed_trade is None:
                    closed_trade = dict(trade)
                    closed_trade.update(exact_close)
                    closed_trade["status"] = "closed"
                closed_symbols.append(symbol)
                closed_trades.append(closed_trade)
                updates.append(
                    {
                        "symbol": symbol,
                        "status": "closed",
                        "reason": "Exact Bybit closed PnL synchronized",
                    }
                )
                _persist_reconciliation_event(
                    journal_id,
                    "RECONCILED_CLOSED_EXACT",
                    "Exchange position is absent and exact Bybit close fill/PnL/fees were synchronized.",
                    exact_close,
                )
                continue

            position = position_recheck

        if position is None and open_order is not None:
            reconciled = dict(trade)
            order_qty = _coerce_float(open_order.get("qty"), None)
            executed_qty = _coerce_float(open_order.get("cumExecQty"), None)
            reconciled["order_status"] = open_order.get("orderStatus")
            if order_qty and executed_qty is not None and 0 < executed_qty < order_qty:
                reconciled["status"] = "partial_fill"
                reconciled["filled_quantity"] = executed_qty
            else:
                reconciled["status"] = "pending"
            updated_trades.append(reconciled)
            updates.append(
                {
                    "symbol": symbol,
                    "status": reconciled["status"],
                    "reason": "Position pending; kept from open order",
                }
            )
            _persist_reconciliation_event(
                journal_id,
                "RECONCILED_PENDING",
                "Open order exists but position is not open yet.",
                reconciled,
            )
            continue

        reconciled = dict(trade)
        reconciled["quantity"] = position.get("size", trade.get("quantity"))
        reconciled["remaining_quantity"] = position.get(
            "size",
            trade.get("remaining_quantity", trade.get("quantity")),
        )
        reconciled["entry"] = _coerce_float(position.get("avgPrice"), trade.get("entry"))
        reconciled["status"] = "active"
        reconciled["mark_price"] = _coerce_float(position.get("markPrice"), ticker_prices.get(symbol))
        reconciled["sl_tp_orders"] = open_orders_by_symbol.get(symbol, [])
        reconciled.pop("close_sync_error", None)

        if open_order is not None:
            order_qty = _coerce_float(open_order.get("qty"), None)
            executed_qty = _coerce_float(open_order.get("cumExecQty"), None)
            if order_qty and executed_qty is not None and 0 < executed_qty < order_qty:
                reconciled["status"] = "partial_fill"
                reconciled["filled_quantity"] = executed_qty
            reconciled["order_status"] = open_order.get("orderStatus")
            updates.append(
                {
                    "symbol": symbol,
                    "status": reconciled["status"],
                    "reason": "Updated from open order and position",
                }
            )
        else:
            updates.append(
                {
                    "symbol": symbol,
                    "status": "active",
                    "reason": "Open order not found; position kept as exchange truth",
                }
            )

        updated_trades.append(reconciled)
        _persist_reconciliation_event(
            journal_id,
            "RECONCILED_ACTIVE",
            "Local trade synchronized from exchange position and orders.",
            reconciled,
        )

    replace_active_trades(updated_trades)

    for symbol in closed_symbols:
        release_active_trade(symbol)

    return {
        "ok": True,
        "trades": updated_trades,
        "closed_trades": closed_trades,
        "closed": closed_symbols,
        "updates": updates,
    }


def _mark_close_pending_sync(trade: dict[str, Any], error: str) -> dict[str, Any]:
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    pending = dict(trade)
    pending["status"] = "close_pending_sync"
    pending["close_sync_error"] = error
    pending["exchange_metadata"] = {
        **metadata,
        "close_sync": {
            **(metadata.get("close_sync") if isinstance(metadata.get("close_sync"), dict) else {}),
            "status": "pending",
            "error": error,
        },
    }
    return pending


def _persist_pending_close_sync(journal_id: str, trade: dict[str, Any]) -> None:
    if not journal_id:
        return
    update_trade_entry(
        journal_id,
        {
            "status": "close_pending_sync",
            "exchange_metadata": trade.get("exchange_metadata"),
        },
    )
    append_trade_event(
        journal_id,
        "CLOSE_SYNC_PENDING",
        "Exchange position is absent, but exact Bybit close fill/PnL/fees are not available yet.",
        {
            "symbol": trade.get("symbol"),
            "error": trade.get("close_sync_error"),
        },
    )


def _position_is_open(position: dict[str, Any]) -> bool:
    try:
        size = float(position.get("size", 0))
    except (TypeError, ValueError):
        return False
    return isfinite(size) and size > 0


def _coerce_float(value: Any, fallback: Any) -> float | Any:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback
    return numeric if isfinite(numeric) else fallback


def _ticker_price_map(tickers: list[dict[str, Any]]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for ticker in tickers:
        symbol = str(ticker.get("symbol", "")).upper()
        try:
            prices[symbol] = float(ticker.get("lastPrice"))
        except (TypeError, ValueError):
            continue
    return prices


def _orders_by_symbol(open_orders: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in open_orders:
        grouped.setdefault(str(order.get("symbol", "")).upper(), []).append(order)
    return grouped


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
