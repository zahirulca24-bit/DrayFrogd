from __future__ import annotations

from math import isfinite
from typing import Any

from app.execution import SL_REASON_EXCHANGE_CLOSE, SL_REASON_UNKNOWN, close_trade, get_active_trades, replace_active_trades
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
            close_result = _resolve_close_result(trade, ticker_prices.get(symbol))
            closed_trade = close_trade(journal_id, close_result) if journal_id else None
            if closed_trade is None:
                closed_trade = dict(trade)
                closed_trade.update(close_result)
                closed_trade["status"] = "closed"
            closed_symbols.append(symbol)
            closed_trades.append(closed_trade)
            updates.append({"symbol": symbol, "status": "closed", "reason": close_result.get("close_reason", "Position not found on exchange")})
            _persist_reconciliation_event(journal_id, "RECONCILED_CLOSED", "Exchange no longer reports this position.", close_result)
            continue

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
            updates.append({"symbol": symbol, "status": reconciled["status"], "reason": "Position pending; kept from open order"})
            _persist_reconciliation_event(journal_id, "RECONCILED_PENDING", "Open order exists but position is not open yet.", reconciled)
            continue

        reconciled = dict(trade)
        reconciled["quantity"] = position.get("size", trade.get("quantity"))
        reconciled["remaining_quantity"] = position.get("size", trade.get("remaining_quantity", trade.get("quantity")))
        reconciled["entry"] = _coerce_float(position.get("avgPrice"), trade.get("entry"))
        reconciled["status"] = "active"
        reconciled["mark_price"] = _coerce_float(position.get("markPrice"), ticker_prices.get(symbol))
        reconciled["sl_tp_orders"] = open_orders_by_symbol.get(symbol, [])

        if open_order is not None:
            order_qty = _coerce_float(open_order.get("qty"), None)
            executed_qty = _coerce_float(open_order.get("cumExecQty"), None)
            if order_qty and executed_qty is not None and 0 < executed_qty < order_qty:
                reconciled["status"] = "partial_fill"
                reconciled["filled_quantity"] = executed_qty
            reconciled["order_status"] = open_order.get("orderStatus")
            updates.append({"symbol": symbol, "status": reconciled["status"], "reason": "Updated from open order and position"})
        else:
            updates.append({"symbol": symbol, "status": "active", "reason": "Open order not found; position kept as exchange truth"})

        updated_trades.append(reconciled)
        _persist_reconciliation_event(journal_id, "RECONCILED_ACTIVE", "Local trade synchronized from exchange position and orders.", reconciled)

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


def _resolve_close_result(trade: dict[str, Any], market_price: float | None) -> dict[str, Any]:
    direction = str(trade.get("direction", "")).lower()
    stop_loss = _coerce_float(trade.get("stop_loss"), None)
    take_profit = _coerce_float(trade.get("take_profit"), None)
    result = "unknown"
    sl_hit_reason: str | None = None
    close_reason = "position_not_found_on_exchange"

    if market_price is not None and stop_loss is not None and take_profit is not None:
        if direction == "long":
            if market_price <= stop_loss:
                result = "sl"
                sl_hit_reason = SL_REASON_EXCHANGE_CLOSE
            elif market_price >= take_profit:
                result = "tp"
        elif direction == "short":
            if market_price >= stop_loss:
                result = "sl"
                sl_hit_reason = SL_REASON_EXCHANGE_CLOSE
            elif market_price <= take_profit:
                result = "tp"

    if result == "unknown":
        sl_hit_reason = SL_REASON_UNKNOWN if close_reason else None

    return {
        "result": result,
        "sl_hit_reason": sl_hit_reason if result == "sl" else None,
        "close_reason": close_reason,
        "closed_at": None,
        "exit_price": market_price,
    }


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


def _persist_reconciliation_event(journal_id: str, event_type: str, message: str, payload: dict[str, Any]) -> None:
    if not journal_id:
        return
    status = payload.get("status")
    if status:
        update_trade_entry(journal_id, {"status": status})
    append_trade_event(journal_id, event_type, message, payload)
