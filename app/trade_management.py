from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any

from app.execution import close_trade, get_active_trades, update_active_trade
from app.exchange import BybitClient, ExchangeError
from app.journal import append_trade_event, log_bot_event, update_trade_entry
from app.risk import release_active_trade
from app.trade_management_rules import evaluate_management_action


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
            ok_recheck, positions_recheck, recheck_error = client.safe_fetch_positions()
            if not ok_recheck:
                actions.append(_record_action(trade, "POSITION_RECHECK_FAILED", "Exchange position recheck failed; local trade remains open.", {"error": recheck_error}))
                continue

            position = next(
                (item for item in positions_recheck if str(item.get("symbol", "")).upper() == symbol and _position_is_open(item)),
                None,
            )
            if position is None:
                close_fields = {
                    "result": "exchange_closed",
                    "close_reason": "POSITION_MISSING_VERIFIED",
                    "exit_price": mark_price,
                    "closed_at": _utc_now_iso(),
                    "exchange_metadata": _merge_metadata(trade, {"management": _management_state(trade), "reconciliation": "position_missing_verified_twice"}),
                }
                closed = close_trade(journal_id, close_fields)
                release_active_trade(symbol)
                actions.append(_record_action(closed or trade, "POSITION_MISSING_RECONCILED", "Exchange position verified missing twice; local trade closed and risk slot released.", close_fields))
                continue
            mark_price = _to_float(position.get("markPrice"), mark_price)

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

        decision = evaluate_management_action({**trade, "entry": entry, "management": management}, mark_price, datetime.now(UTC))
        action = decision["action"]

        if action == "hold":
            _save_trade_state(trade, journal_id, trade_updates)
            continue

        if action in {"max_hold_close", "stagnant_close"}:
            close_result = _close_quantity(client, trade, remaining_qty)
            if close_result.get("error"):
                event_type = "MAX_HOLD_CLOSE_FAILED" if action == "max_hold_close" else "STAGNANT_CLOSE_FAILED"
                actions.append(_record_action(trade, event_type, f"Close failed; will retry: {close_result.get('error')}", close_result))
                continue
            close_reason = "MAX_HOLD_TIME" if action == "max_hold_close" else "MOMENTUM_FAILED"
            result = "time_exit" if action == "max_hold_close" else "stagnant_exit"
            close_fields = {
                "result": result,
                "close_reason": close_reason,
                "exit_price": mark_price,
                "closed_at": _utc_now_iso(),
                "exchange_metadata": _merge_metadata(trade, {"management": management, "close_order": close_result}),
            }
            closed = close_trade(journal_id, close_fields)
            release_active_trade(symbol)
            actions.append(_record_action(closed or trade, close_reason, "Position close confirmed.", close_fields))
            continue

        if action == "retry_break_even":
            protection = _set_protection(client, trade, stop_loss=entry, take_profit=_runner_target(trade, management))
            if protection.get("error"):
                actions.append(_record_action(trade, "BREAK_EVEN_RETRY_FAILED", "Break-even stop retry failed; will retry next cycle.", protection))
                continue
            management["break_even_set"] = True
            management["last_state_change"] = _utc_now_iso()
            trade_updates["management"] = management
            _save_trade_state(trade, journal_id, trade_updates)
            actions.append(_record_action(trade, "BREAK_EVEN_CONFIRMED", "Break-even stop confirmed on exchange.", protection))
            continue

        if action == "retry_trailing":
            candidate_stop = _trailing_stop({**trade, "entry": entry}, mark_price)
            protection = _set_protection(client, trade, stop_loss=candidate_stop, take_profit=_runner_target(trade, management))
            if protection.get("error"):
                actions.append(_record_action(trade, "TRAILING_SETUP_RETRY_FAILED", "Trailing stop retry failed; will retry next cycle.", protection))
                continue
            management["trailing_stop"] = candidate_stop
            management["last_state_change"] = _utc_now_iso()
            trade_updates["management"] = management
            _save_trade_state(trade, journal_id, trade_updates)
            actions.append(_record_action(trade, "TRAILING_SETUP_CONFIRMED", "Trailing stop confirmed on exchange.", {"stop_loss": candidate_stop, **protection}))
            continue

        if action == "tp1":
            close_qty = min(remaining_qty, _initial_qty(management) * float(management.get("tp1_fraction", 0.5)))
            close_result = _close_quantity(client, trade, close_qty)
            if close_result.get("error"):
                actions.append(_record_action(trade, "TP1_CLOSE_FAILED", "TP1 partial close failed; will retry.", close_result))
                continue

            management["tp1_done"] = True
            management["remaining_quantity"] = max(remaining_qty - close_qty, 0.0)
            protection = _set_protection(client, trade, stop_loss=entry, take_profit=_runner_target(trade, management))
            management["break_even_set"] = not bool(protection.get("error"))
            management["last_state_change"] = _utc_now_iso()
            trade_updates.update({"remaining_quantity": management["remaining_quantity"], "quantity": management["remaining_quantity"], "management": management})
            _save_trade_state(trade, journal_id, trade_updates)
            event_type = "TP1_PARTIAL_CLOSE" if management["break_even_set"] else "TP1_PARTIAL_CLOSE_BREAK_EVEN_PENDING"
            actions.append(_record_action(trade, event_type, "TP1 partial close confirmed; break-even protection state recorded.", {"qty": close_qty, "order": close_result, "protection": protection}))
            continue

        if action == "tp2":
            close_qty = min(remaining_qty, _initial_qty(management) * float(management.get("tp2_fraction", 0.25)))
            close_result = _close_quantity(client, trade, close_qty)
            if close_result.get("error"):
                actions.append(_record_action(trade, "TP2_CLOSE_FAILED", "TP2 partial close failed; will retry.", close_result))
                continue

            management["tp2_done"] = True
            management["remaining_quantity"] = max(remaining_qty - close_qty, 0.0)
            candidate_stop = _trailing_stop({**trade, "entry": entry}, mark_price)
            protection = _set_protection(client, trade, stop_loss=candidate_stop, take_profit=_runner_target(trade, management))
            management["trailing_stop"] = None if protection.get("error") else candidate_stop
            management["last_state_change"] = _utc_now_iso()
            trade_updates.update({"remaining_quantity": management["remaining_quantity"], "quantity": management["remaining_quantity"], "management": management})
            _save_trade_state(trade, journal_id, trade_updates)
            event_type = "TP2_PARTIAL_CLOSE" if management["trailing_stop"] is not None else "TP2_PARTIAL_CLOSE_TRAILING_PENDING"
            actions.append(_record_action(trade, event_type, "TP2 partial close confirmed; trailing protection state recorded.", {"qty": close_qty, "order": close_result, "protection": protection}))
            continue

        if action == "trail":
            new_stop = _trailing_stop({**trade, "entry": entry}, mark_price)
            if _is_better_stop(trade, new_stop, management.get("trailing_stop")):
                protection = _set_protection(client, trade, stop_loss=new_stop, take_profit=_runner_target(trade, management))
                if protection.get("error"):
                    actions.append(_record_action(trade, "TRAILING_STOP_UPDATE_FAILED", "Trailing stop update failed; will retry.", protection))
                else:
                    management["trailing_stop"] = new_stop
                    management["last_state_change"] = _utc_now_iso()
                    trade_updates["management"] = management
                    _save_trade_state(trade, journal_id, trade_updates)
                    actions.append(_record_action(trade, "TRAILING_STOP_UPDATED", "Runner trailing stop updated.", {"stop_loss": new_stop, "protection": protection}))

    return {"ok": True, "actions": actions, "managed": len(local_trades), "orders_error": orders_error}


def _save_trade_state(trade: dict[str, Any], journal_id: str, updates: dict[str, Any]) -> None:
    update_active_trade(journal_id, updates)
    _persist_trade_management(trade, updates)


def _close_quantity(client: BybitClient, trade: dict[str, Any], qty: float) -> dict[str, Any]:
    if qty <= 0:
        return {"error": "quantity_zero"}
    symbol = str(trade.get("symbol", "")).upper()
    close_side = "Sell" if str(trade.get("direction", "")).lower() == "long" else "Buy"
    try:
        return client.close_position_market(symbol=symbol, side=close_side, qty=_format_qty(qty))
    except ExchangeError as exc:
        error_msg = str(exc)
        log_bot_event("TRADE_MANAGEMENT_CLOSE_FAILED", f"Close request failed for {symbol}", level="error", metadata={"affected_module": "trade_management", "error_code": "PARTIAL_CLOSE_FAILED", "symbol": symbol, "error": error_msg})
        return {"error": error_msg}


def _set_protection(client: BybitClient, trade: dict[str, Any], stop_loss: float, take_profit: float) -> dict[str, Any]:
    symbol = str(trade.get("symbol", "")).upper()
    try:
        result = client.set_trading_stop(symbol=symbol, take_profit=str(take_profit), stop_loss=str(stop_loss))
        return result if isinstance(result, dict) else {"ok": True}
    except ExchangeError as exc:
        error_msg = str(exc)
        log_bot_event("TRADE_MANAGEMENT_PROTECTION_FAILED", f"Protection update failed for {symbol}", level="error", metadata={"affected_module": "trade_management", "error_code": "PROTECTION_UPDATE_FAILED", "symbol": symbol, "error": error_msg})
        return {"error": error_msg}


def _persist_trade_management(trade: dict[str, Any], updates: dict[str, Any]) -> None:
    journal_id = str(trade.get("journal_id") or "")
    if not journal_id:
        return
    update_trade_entry(journal_id, {"status": updates.get("status", trade.get("status", "active")), "exchange_metadata": _merge_metadata(trade, {"management": updates.get("management"), "sl_tp_orders": updates.get("sl_tp_orders")})})


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
