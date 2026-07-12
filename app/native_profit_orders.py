from __future__ import annotations

import json
from datetime import UTC, datetime
from math import isfinite
from typing import Any

from app.execution_core import get_active_trades, update_active_trade
from app.exchange import ExchangeError
from app.journal import append_trade_event, log_bot_event, update_trade_entry


TP1_FRACTION = 0.50
TP2_FRACTION = 0.25
ORDER_LINK_PREFIX = "df"
FILLED_STATUSES = {"filled"}
FAILED_STATUSES = {"cancelled", "rejected", "deactivated"}


def install_native_profit_orders(client: Any, trade: dict[str, Any]) -> dict[str, Any]:
    """Install exchange-native reduce-only TP1 and TP2 limit orders.

    Profit is booked by the exchange when price touches the target, so a fast
    candle wick cannot be missed by the slower strategy-management loop.
    """

    symbol = str(trade.get("symbol") or "").upper().strip()
    direction = str(trade.get("direction") or "").lower().strip()
    execution_key = str(trade.get("execution_key") or "").strip()
    management = _management_state(trade)
    initial_quantity = _positive_float(management.get("initial_quantity") or trade.get("quantity"))
    if not symbol or direction not in {"long", "short"} or not execution_key or initial_quantity is None:
        return {"ok": False, "error": "Native TP prerequisites are unavailable"}

    if management.get("native_tp_enabled") and management.get("tp1_order_link_id") and management.get("tp2_order_link_id"):
        return {"ok": True, "management": management, "orders": management.get("native_orders") or {}}

    ok_symbol, symbol_infos, symbol_error = client.safe_fetch_symbol_info(symbol=symbol)
    if not ok_symbol or not symbol_infos:
        return {"ok": False, "error": symbol_error or "Symbol precision is unavailable for native TP orders"}
    symbol_info = symbol_infos[0]
    qty_step = str(symbol_info.get("qtyStep") or "")
    tick_size = str(symbol_info.get("tickSize") or "")
    min_notional = _positive_float(symbol_info.get("minNotionalValue")) or 0.0
    if not qty_step or not tick_size:
        return {"ok": False, "error": "Symbol TP precision is unavailable"}

    tp1_price = _positive_float(management.get("tp1"))
    tp2_price = _positive_float(management.get("tp2"))
    if tp1_price is None or tp2_price is None:
        return {"ok": False, "error": "TP1/TP2 targets are unavailable"}

    tp1_quantity = _normalized_positive_quantity(client, initial_quantity * TP1_FRACTION, qty_step)
    tp2_quantity = _normalized_positive_quantity(client, initial_quantity * TP2_FRACTION, qty_step)
    if tp1_quantity is None or tp2_quantity is None:
        return {"ok": False, "error": "TP1/TP2 quantity is zero after exchange precision"}
    if tp1_quantity + tp2_quantity >= initial_quantity - 1e-12:
        return {"ok": False, "error": "TP1/TP2 precision leaves no runner quantity"}
    if min_notional > 0 and (tp1_quantity * tp1_price < min_notional or tp2_quantity * tp2_price < min_notional):
        return {"ok": False, "error": "Native partial TP is below exchange minimum notional"}

    normalized_tp1_price = client.normalize_price(tp1_price, tick_size)
    normalized_tp2_price = client.normalize_price(tp2_price, tick_size)
    normalized_tp1_quantity = client.normalize_quantity(tp1_quantity, qty_step)
    normalized_tp2_quantity = client.normalize_quantity(tp2_quantity, qty_step)
    close_side = "Sell" if direction == "long" else "Buy"
    tp1_link = _profit_order_link_id(execution_key, "t1")
    tp2_link = _profit_order_link_id(execution_key, "t2")

    placed: list[dict[str, Any]] = []
    try:
        tp1_order = _place_reduce_only_limit(
            client,
            symbol=symbol,
            side=close_side,
            qty=normalized_tp1_quantity,
            price=normalized_tp1_price,
            order_link_id=tp1_link,
        )
        placed.append({"order_link_id": tp1_link, "order_id": tp1_order.get("orderId")})
        tp2_order = _place_reduce_only_limit(
            client,
            symbol=symbol,
            side=close_side,
            qty=normalized_tp2_quantity,
            price=normalized_tp2_price,
            order_link_id=tp2_link,
        )
        placed.append({"order_link_id": tp2_link, "order_id": tp2_order.get("orderId")})
    except ExchangeError as exc:
        for order in placed:
            _cancel_order_best_effort(
                client,
                symbol=symbol,
                order_id=order.get("order_id"),
                order_link_id=order.get("order_link_id"),
            )
        return {"ok": False, "error": str(exc)}

    orders = {
        "tp1": {
            "order_id": str(tp1_order.get("orderId") or "") or None,
            "order_link_id": tp1_link,
            "price": float(normalized_tp1_price),
            "quantity": float(normalized_tp1_quantity),
            "status": "submitted",
        },
        "tp2": {
            "order_id": str(tp2_order.get("orderId") or "") or None,
            "order_link_id": tp2_link,
            "price": float(normalized_tp2_price),
            "quantity": float(normalized_tp2_quantity),
            "status": "submitted",
        },
    }
    updated_management = {
        **management,
        "native_tp_enabled": True,
        "native_tp_degraded": False,
        "native_tp_installed_at": _utc_now_iso(),
        "native_tp_qty_step": qty_step,
        "native_tp_tick_size": tick_size,
        "tp1_order_id": orders["tp1"]["order_id"],
        "tp1_order_link_id": tp1_link,
        "tp1_order_status": "submitted",
        "tp1_quantity": orders["tp1"]["quantity"],
        "tp2_order_id": orders["tp2"]["order_id"],
        "tp2_order_link_id": tp2_link,
        "tp2_order_status": "submitted",
        "tp2_quantity": orders["tp2"]["quantity"],
        "native_orders": orders,
    }
    return {"ok": True, "management": updated_management, "orders": orders}


def cancel_native_profit_orders(client: Any, trade: dict[str, Any]) -> None:
    management = _management_state(trade)
    symbol = str(trade.get("symbol") or "").upper().strip()
    if not symbol:
        return
    for prefix in ("tp1", "tp2"):
        _cancel_order_best_effort(
            client,
            symbol=symbol,
            order_id=management.get(f"{prefix}_order_id"),
            order_link_id=management.get(f"{prefix}_order_link_id"),
        )


def reconcile_native_profit_orders(client: Any) -> dict[str, Any]:
    """Reconcile native TP fills and advance BE/trailing protection.

    The order status is authoritative. Position-size inference is used only as a
    restart-safe fallback when the exchange order history is delayed.
    """

    trades = get_active_trades()
    native_trades = [trade for trade in trades if _management_state(trade).get("native_tp_enabled")]
    if not native_trades:
        return {"ok": True, "managed": 0, "actions": [], "errors": []}

    ok_positions, positions, positions_error = client.safe_fetch_positions()
    if not ok_positions:
        return {"ok": False, "managed": 0, "actions": [], "errors": [positions_error or "Position data unavailable"]}
    positions_by_symbol = {
        str(item.get("symbol") or "").upper(): item
        for item in positions
        if (_positive_float(item.get("size")) or 0.0) > 0
    }

    actions: list[dict[str, Any]] = []
    errors: list[str] = []
    for trade in native_trades:
        symbol = str(trade.get("symbol") or "").upper().strip()
        journal_id = str(trade.get("journal_id") or "")
        management = _management_state(trade)
        position = positions_by_symbol.get(symbol)
        if not symbol or not journal_id or position is None:
            continue

        initial_quantity = _positive_float(management.get("initial_quantity")) or 0.0
        tp1_quantity = _positive_float(management.get("tp1_quantity")) or 0.0
        tp2_quantity = _positive_float(management.get("tp2_quantity")) or 0.0
        position_quantity = _positive_float(position.get("size")) or 0.0
        qty_step = _positive_float(management.get("native_tp_qty_step")) or 1e-12
        tolerance = max(qty_step, initial_quantity * 1e-8, 1e-12)

        tp1_snapshot, tp1_error = _order_snapshot(client, symbol, management.get("tp1_order_link_id"))
        tp2_snapshot, tp2_error = _order_snapshot(client, symbol, management.get("tp2_order_link_id"))
        if tp1_error:
            errors.append(f"{symbol} TP1: {tp1_error}")
        if tp2_error:
            errors.append(f"{symbol} TP2: {tp2_error}")

        changed = False
        if tp1_snapshot:
            management["tp1_order_status"] = str(tp1_snapshot.get("orderStatus") or "unknown")
            management["tp1_order_snapshot"] = _compact_order_snapshot(tp1_snapshot)
            changed = True
        if tp2_snapshot:
            management["tp2_order_status"] = str(tp2_snapshot.get("orderStatus") or "unknown")
            management["tp2_order_snapshot"] = _compact_order_snapshot(tp2_snapshot)
            changed = True

        tp1_status = str((tp1_snapshot or {}).get("orderStatus") or "").lower()
        tp2_status = str((tp2_snapshot or {}).get("orderStatus") or "").lower()
        inferred_tp1 = initial_quantity > 0 and tp1_quantity > 0 and position_quantity <= initial_quantity - tp1_quantity + tolerance
        inferred_tp2 = initial_quantity > 0 and tp1_quantity > 0 and tp2_quantity > 0 and position_quantity <= initial_quantity - tp1_quantity - tp2_quantity + tolerance
        tp1_filled = tp1_status in FILLED_STATUSES or inferred_tp1
        tp2_filled = tp2_status in FILLED_STATUSES or inferred_tp2

        failed_stage = None
        if not management.get("tp1_done") and tp1_status in FAILED_STATUSES:
            failed_stage = "tp1"
        elif not management.get("tp2_done") and tp2_status in FAILED_STATUSES:
            failed_stage = "tp2"
        if failed_stage:
            management["native_tp_degraded"] = True
            management["native_tp_degraded_reason"] = f"{failed_stage.upper()} order status {tp1_status if failed_stage == 'tp1' else tp2_status}"
            management["last_state_change"] = _utc_now_iso()
            changed = True
            _safe_event(
                journal_id,
                "NATIVE_TP_DEGRADED",
                "Native partial take-profit order is unavailable; mark-price fallback is enabled.",
                {"symbol": symbol, "stage": failed_stage, "status": tp1_status if failed_stage == "tp1" else tp2_status},
            )

        if tp1_filled and not bool(management.get("tp1_done")):
            management["tp1_done"] = True
            management["tp1_fill_source"] = "exchange_order" if tp1_status in FILLED_STATUSES else "position_size_reconciliation"
            management["remaining_quantity"] = position_quantity
            management["last_state_change"] = _utc_now_iso()
            protection = _set_and_verify_protection(
                client,
                trade=trade,
                position=position,
                stop_loss=_positive_float(position.get("avgPrice") or trade.get("entry")) or 0.0,
                take_profit=_positive_float(management.get("runner_target") or trade.get("take_profit")) or 0.0,
                tick_size=_positive_float(management.get("native_tp_tick_size")) or 1e-8,
            )
            management["break_even_set"] = protection.get("ok", False)
            if not protection.get("ok"):
                management["break_even_error"] = protection.get("error")
            changed = True
            event_type = "NATIVE_TP1_FILLED_BREAK_EVEN_SET" if management["break_even_set"] else "NATIVE_TP1_FILLED_BREAK_EVEN_PENDING"
            _safe_event(
                journal_id,
                event_type,
                "TP1 was filled by the exchange; remaining position break-even state was updated.",
                {"symbol": symbol, "remaining_quantity": position_quantity, "protection": protection},
            )
            actions.append({"symbol": symbol, "action": event_type})

        if tp2_filled and not bool(management.get("tp2_done")):
            # A gap can fill both native orders before the watcher runs.
            management["tp1_done"] = True
            management["tp2_done"] = True
            management["tp2_fill_source"] = "exchange_order" if tp2_status in FILLED_STATUSES else "position_size_reconciliation"
            management["remaining_quantity"] = position_quantity
            entry = _positive_float(position.get("avgPrice") or trade.get("entry")) or 0.0
            stop_loss = _positive_float(trade.get("stop_loss")) or entry
            mark_price = _positive_float(position.get("markPrice")) or entry
            risk = abs(entry - stop_loss)
            direction = str(trade.get("direction") or "").lower()
            candidate_stop = max(entry, mark_price - risk) if direction == "long" else min(entry, mark_price + risk)
            protection = _set_and_verify_protection(
                client,
                trade=trade,
                position=position,
                stop_loss=candidate_stop,
                take_profit=_positive_float(management.get("runner_target") or trade.get("take_profit")) or 0.0,
                tick_size=_positive_float(management.get("native_tp_tick_size")) or 1e-8,
            )
            management["break_even_set"] = True
            management["trailing_stop"] = candidate_stop if protection.get("ok") else None
            if not protection.get("ok"):
                management["trailing_error"] = protection.get("error")
            management["last_state_change"] = _utc_now_iso()
            changed = True
            event_type = "NATIVE_TP2_FILLED_TRAILING_SET" if management["trailing_stop"] is not None else "NATIVE_TP2_FILLED_TRAILING_PENDING"
            _safe_event(
                journal_id,
                event_type,
                "TP2 was filled by the exchange; runner trailing protection state was updated.",
                {"symbol": symbol, "remaining_quantity": position_quantity, "stop_loss": candidate_stop, "protection": protection},
            )
            actions.append({"symbol": symbol, "action": event_type})

        if changed:
            _persist_management_state(trade, management, position_quantity)

    return {"ok": not errors, "managed": len(native_trades), "actions": actions, "errors": errors}


def _place_reduce_only_limit(
    client: Any,
    *,
    symbol: str,
    side: str,
    qty: str,
    price: str,
    order_link_id: str,
) -> dict[str, Any]:
    method = getattr(client, "place_reduce_only_limit_order", None)
    if callable(method):
        result = method(symbol=symbol, side=side, qty=qty, price=price, order_link_id=order_link_id)
        return result if isinstance(result, dict) else {}
    private_post = getattr(client, "_private_post", None)
    if not callable(private_post):
        raise ExchangeError("Exchange-native reduce-only limit orders are unavailable")
    return private_post(
        "/v5/order/create",
        {
            "category": "linear",
            "symbol": symbol,
            "side": side,
            "orderType": "Limit",
            "qty": qty,
            "price": price,
            "timeInForce": "GTC",
            "reduceOnly": True,
            "positionIdx": 0,
            "orderLinkId": order_link_id,
        },
    )


def _cancel_order_best_effort(
    client: Any,
    *,
    symbol: str,
    order_id: Any = None,
    order_link_id: Any = None,
) -> None:
    try:
        method = getattr(client, "cancel_order", None)
        if callable(method):
            method(symbol=symbol, order_id=order_id, order_link_id=order_link_id)
            return
        private_post = getattr(client, "_private_post", None)
        if callable(private_post):
            payload: dict[str, Any] = {"category": "linear", "symbol": symbol}
            if order_id:
                payload["orderId"] = str(order_id)
            elif order_link_id:
                payload["orderLinkId"] = str(order_link_id)
            else:
                return
            private_post("/v5/order/cancel", payload)
    except Exception:
        return


def _order_snapshot(client: Any, symbol: str, order_link_id: Any) -> tuple[dict[str, Any] | None, str | None]:
    link = str(order_link_id or "").strip()
    if not link:
        return None, "order link id unavailable"
    method = getattr(client, "safe_fetch_order_by_link_id", None)
    if not callable(method):
        return None, "order lookup unavailable"
    try:
        ok, order, error = method(symbol=symbol, order_link_id=link)
    except Exception as exc:
        return None, str(exc)
    if not ok:
        return None, str(error or "order lookup failed")
    return order, None


def _set_and_verify_protection(
    client: Any,
    *,
    trade: dict[str, Any],
    position: dict[str, Any],
    stop_loss: float,
    take_profit: float,
    tick_size: float,
) -> dict[str, Any]:
    symbol = str(trade.get("symbol") or "").upper()
    try:
        normalized_stop = client.normalize_price(stop_loss, str(tick_size))
        normalized_tp = client.normalize_price(take_profit, str(tick_size))
        response = client.set_trading_stop(symbol=symbol, take_profit=normalized_tp, stop_loss=normalized_stop)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    ok_positions, positions, error = client.safe_fetch_positions()
    if not ok_positions:
        return {"ok": False, "error": error or "Protection verification position fetch failed", "response": response}
    expected_side = "buy" if str(trade.get("direction") or "").lower() == "long" else "sell"
    current = next(
        (
            item
            for item in positions
            if str(item.get("symbol") or "").upper() == symbol
            and str(item.get("side") or "").lower() == expected_side
            and (_positive_float(item.get("size")) or 0.0) > 0
        ),
        None,
    )
    if current is None:
        return {"ok": False, "error": "Position unavailable during protection verification", "response": response}
    actual_sl = _positive_float(current.get("stopLoss"))
    actual_tp = _positive_float(current.get("takeProfit"))
    tolerance = max(abs(tick_size), 1e-12)
    if actual_sl is None or actual_tp is None or abs(actual_sl - float(normalized_stop)) > tolerance or abs(actual_tp - float(normalized_tp)) > tolerance:
        return {
            "ok": False,
            "error": f"Protection mismatch: SL={actual_sl}, TP={actual_tp}",
            "response": response,
        }
    return {"ok": True, "stop_loss": float(normalized_stop), "take_profit": float(normalized_tp), "response": response}


def _persist_management_state(trade: dict[str, Any], management: dict[str, Any], remaining_quantity: float) -> None:
    journal_id = str(trade.get("journal_id") or "")
    if not journal_id:
        return
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    updated_metadata = {
        **metadata,
        "management": management,
        "native_profit_orders": management.get("native_orders") or metadata.get("native_profit_orders"),
    }
    updates = {
        "remaining_quantity": remaining_quantity,
        "quantity": remaining_quantity,
        "management": management,
        "exchange_metadata": updated_metadata,
    }
    update_active_trade(journal_id, updates)
    update_trade_entry(
        journal_id,
        {
            "quantity": remaining_quantity,
            "exchange_metadata": updated_metadata,
        },
    )


def _management_state(trade: dict[str, Any]) -> dict[str, Any]:
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    management = trade.get("management") or metadata.get("management") or {}
    return dict(management)


def _normalized_positive_quantity(client: Any, value: float, qty_step: str) -> float | None:
    try:
        return _positive_float(client.normalize_quantity(value, qty_step))
    except Exception:
        return None


def _profit_order_link_id(execution_key: str, stage: str) -> str:
    # Bybit accepts orderLinkId up to 36 characters.
    return f"{ORDER_LINK_PREFIX}-{stage}-{execution_key[:29]}"


def _compact_order_snapshot(order: dict[str, Any]) -> dict[str, Any]:
    return {
        key: order.get(key)
        for key in ("orderId", "orderLinkId", "orderStatus", "qty", "cumExecQty", "leavesQty", "avgPrice", "price", "updatedTime")
        if key in order
    }


def _safe_event(journal_id: str, event_type: str, message: str, metadata: dict[str, Any]) -> None:
    try:
        append_trade_event(journal_id, event_type, message, metadata)
    except Exception:
        return


def _positive_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) and numeric > 0 else None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
