from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from app.execution import close_trade, get_active_trades, update_active_trade
from app.exchange import BybitClient, ExchangeError
from app.journal import append_trade_event, log_bot_event, update_trade_entry
from app.risk import release_active_trade
from app.trade_management_rules import MAX_HOLD_SECONDS, STAGNANT_SECONDS, evaluate_management_action


TRAILING_R_MULTIPLE = 1.0


def manage_open_trades(client: BybitClient) -> dict[str, Any]:
    local_trades = get_active_trades()
    if not local_trades:
        return {"ok": True, "actions": [], "managed": 0}

    ok_positions, positions, positions_error = client.safe_fetch_positions()
    ok_tickers, tickers, tickers_error = client.safe_fetch_market_tickers()
    ok_orders, open_orders, orders_error = client.safe_fetch_open_orders()
    if not ok_positions or not ok_tickers:
        return {"ok": False, "error": positions_error or tickers_error or "Trade management data unavailable", "actions": []}

    positions_by_symbol = {str(item.get("symbol", "")).upper(): item for item in positions if _position_is_open(item)}
    ticker_prices = _ticker_price_map(tickers)
    open_orders_by_symbol = _open_orders_by_symbol(open_orders if ok_orders else [])
    actions: list[dict[str, Any]] = []

    for trade in local_trades:
        symbol = str(trade.get("symbol", "")).upper()
        journal_id = str(trade.get("journal_id") or "")
        position = positions_by_symbol.get(symbol)
        mark_price = _to_float(ticker_prices.get(symbol), None)

        if position is None:
            actions.append(_record_action(trade, "POSITION_MISSING", "Exchange position is not open; reconciliation should close it.", {}))
            continue

        remaining_qty = _to_float(position.get("size"), _to_float(trade.get("remaining_quantity") or trade.get("quantity"), 0.0))
        entry = _to_float(position.get("avgPrice"), _to_float(trade.get("entry"), 0.0))
        if mark_price is None:
            mark_price = _to_float(position.get("markPrice"), None)
        if remaining_qty <= 0 or entry <= 0 or mark_price is None:
            actions.append(_record_action(trade, "MANAGEMENT_SKIPPED", "Invalid exchange position values.", {"position": position}))
            continue

        management = _management_state(trade)
        management["remaining_quantity"] = remaining_qty
        trade_updates: dict[str, Any] = {
            "remaining_quantity": remaining_qty,
            "quantity": remaining_qty,
            "entry": entry,
            "mark_price": mark_price,
            "sl_tp_orders": open_orders_by_symbol.get(symbol, []),
            "management": management,
        }

        decision = evaluate_management_action(trade, mark_price, datetime.now(UTC))
        if decision["action"] == "hold":
            update_active_trade(journal_id, trade_updates)
            _persist_trade_management(trade, trade_updates)
            continue

        if decision["action"] == "max_hold_close":
            close_result = _close_quantity(client, trade, remaining_qty)
            close_fields = {
                "result": "time_exit",
                "close_reason": "MAX_HOLD_TIME",
                "exit_price": mark_price,
                "closed_at": _utc_now_iso(),
                "exchange_metadata": _merge_metadata(trade, {"management": management, "close_order": close_result}),
            }
            closed = close_trade(journal_id, close_fields)
            release_active_trade(symbol)
            actions.append(_record_action(closed or trade, "MAX_HOLD_TIME", "Maximum holding time reached; position close requested.", close_fields))
            continue

        if decision["action"] == "stagnant_close":
            close_result = _close_quantity(client, trade, remaining_qty)
            close_fields = {
                "result": "stagnant_exit",
                "close_reason": "MOMENTUM_FAILED",
                "exit_price": mark_price,
                "closed_at": _utc_now_iso(),
                "exchange_metadata": _merge_metadata(trade, {"management": management, "close_order": close_result}),
            }
            closed = close_trade(journal_id, close_fields)
            release_active_trade(symbol)
            actions.append(_record_action(closed or trade, "MOMENTUM_FAILED", "Trade momentum failed; early close requested.", close_fields))
            continue

        if decision["action"] == "tp1":
            close_qty = min(remaining_qty, _initial_qty(management) * float(management.get("tp1_fraction", 0.5)))
            close_result = _close_quantity(client, trade, close_qty)
            management["tp1_done"] = True
            management["break_even_set"] = True
            management["remaining_quantity"] = max(remaining_qty - close_qty, 0.0)
            management["last_state_change"] = _utc_now_iso()
            _set_protection(client, trade, stop_loss=entry, take_profit=_runner_target(trade, management))
            trade_updates.update({"remaining_quantity": management["remaining_quantity"], "quantity": management["remaining_quantity"], "management": management})
            update_active_trade(journal_id, trade_updates)
            _persist_trade_management(trade, trade_updates)
            actions.append(_record_action(trade, "TP1_PARTIAL_CLOSE", "TP1 reached; partial close and break-even stop requested.", {"qty": close_qty, "order": close_result}))
            continue

        if decision["action"] == "tp2":
            close_qty = min(remaining_qty, _initial_qty(management) * float(management.get("tp2_fraction", 0.25)))
            close_result = _close_quantity(client, trade, close_qty)
            management["tp2_done"] = True
            management["remaining_quantity"] = max(remaining_qty - close_qty, 0.0)
            management["trailing_stop"] = _trailing_stop(trade, mark_price)
            management["last_state_change"] = _utc_now_iso()
            _set_protection(client, trade, stop_loss=management["trailing_stop"], take_profit=_runner_target(trade, management))
            trade_updates.update({"remaining_quantity": management["remaining_quantity"], "quantity": management["remaining_quantity"], "management": management})
            update_active_trade(journal_id, trade_updates)
            _persist_trade_management(trade, trade_updates)
            actions.append(_record_action(trade, "TP2_PARTIAL_CLOSE", "TP2 reached; second partial close and trailing stop requested.", {"qty": close_qty, "order": close_result}))
            continue

        if decision["action"] == "trail":
            new_stop = _trailing_stop(trade, mark_price)
            if _is_better_stop(trade, new_stop, management.get("trailing_stop")):
                management["trailing_stop"] = new_stop
                management["last_state_change"] = _utc_now_iso()
                _set_protection(client, trade, stop_loss=new_stop, take_profit=_runner_target(trade, management))
                trade_updates["management"] = management
                update_active_trade(journal_id, trade_updates)
                _persist_trade_management(trade, trade_updates)
                actions.append(_record_action(trade, "TRAILING_STOP_UPDATED", "Runner trailing stop updated.", {"stop_loss": new_stop}))

    return {"ok": True, "actions": actions, "managed": len(local_trades), "orders_error": orders_error}


def _close_quantity(client: BybitClient, trade: dict[str, Any], qty: float) -> dict[str, Any]:
    if qty <= 0:
        return {"skipped": True, "reason": "quantity_zero"}
    symbol = str(trade.get("symbol", "")).upper()
    close_side = "Sell" if str(trade.get("direction", "")).lower() == "long" else "Buy"
    try:
        return client.close_position_market(symbol=symbol, side=close_side, qty=_format_qty(qty))
    except ExchangeError as exc:
        log_bot_event(
            "TRADE_MANAGEMENT_CLOSE_FAILED",
            f"Close request failed for {symbol}",
            level="error",
            metadata={"affected_module": "trade_management", "error_code": "PARTIAL_CLOSE_FAILED", "symbol": symbol, "error": str(exc)},
        )
        return {"error": str(exc)}


def _set_protection(client: BybitClient, trade: dict[str, Any], stop_loss: float, take_profit: float) -> dict[str, Any]:
    symbol = str(trade.get("symbol", "")).upper()
    try:
        return client.set_trading_stop(symbol=symbol, take_profit=str(take_profit), stop_loss=str(stop_loss))
    except ExchangeError as exc:
        log_bot_event(
            "TRADE_MANAGEMENT_PROTECTION_FAILED",
            f"Protection update failed for {symbol}",
            level="error",
            metadata={"affected_module": "trade_management", "error_code": "PROTECTION_UPDATE_FAILED", "symbol": symbol, "error": str(exc)},
        )
        return {"error": str(exc)}


def _persist_trade_management(trade: dict[str, Any], updates: dict[str, Any]) -> None:
    journal_id = str(trade.get("journal_id") or "")
    if not journal_id:
        return
    update_trade_entry(
        journal_id,
        {
            "status": updates.get("status", trade.get("status", "active")),
            "exchange_metadata": _merge_metadata(trade, {"management": updates.get("management"), "sl_tp_orders": updates.get("sl_tp_orders")}),
        },
    )


def _record_action(trade: dict[str, Any], event_type: str, message: str, metadata: dict[str, Any]) -> dict[str, Any]:
    journal_id = str(trade.get("journal_id") or "")
    symbol = str(trade.get("symbol", "")).upper()
    payload = {"symbol": symbol, **metadata}
    if journal_id:
        append_trade_event(journal_id, event_type, message, payload)
    return {"event_type": event_type, "symbol": symbol, "message": message, "metadata": payload}


def _management_state(trade: dict[str, Any]) -> dict[str, Any]:
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    management = trade.get("management") or metadata.get("management") or {}
    return dict(management)


def _merge_metadata(trade: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    current = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    return {**current, **updates}


def _runner_target(trade: dict[str, Any], management: dict[str, Any]) -> float:
    return _to_float(management.get("runner_target"), _to_float(trade.get("take_profit"), 0.0))


def _trailing_stop(trade: dict[str, Any], mark_price: float) -> float:
    entry = _to_float(trade.get("entry"), 0.0)
    stop_loss = _to_float(trade.get("stop_loss"), 0.0)
    risk = abs(entry - stop_loss)
    if str(trade.get("direction", "")).lower() == "long":
        return mark_price - risk * TRAILING_R_MULTIPLE
    return mark_price + risk * TRAILING_R_MULTIPLE


def _is_better_stop(trade: dict[str, Any], new_stop: float, old_stop: Any) -> bool:
    old = _to_float(old_stop, None)
    if old is None:
        return True
    if str(trade.get("direction", "")).lower() == "long":
        return new_stop > old
    return new_stop < old


def _initial_qty(management: dict[str, Any]) -> float:
    return _to_float(management.get("initial_quantity"), 0.0)


def _position_is_open(position: dict[str, Any]) -> bool:
    size = _to_float(position.get("size"), 0.0)
    return isfinite(size) and size > 0


def _open_orders_by_symbol(open_orders: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for order in open_orders:
        grouped.setdefault(str(order.get("symbol", "")).upper(), []).append(order)
    return grouped


def _ticker_price_map(tickers: list[dict[str, Any]]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for ticker in tickers:
        price = _to_float(ticker.get("lastPrice"), None)
        if price is not None:
            prices[str(ticker.get("symbol", "")).upper()] = price
    return prices


def _to_float(value: Any, fallback: Any) -> Any:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback
    return numeric if isfinite(numeric) else fallback


def _format_qty(qty: float) -> str:
    return f"{qty:.8f}".rstrip("0").rstrip(".")


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
