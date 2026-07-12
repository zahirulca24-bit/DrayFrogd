from __future__ import annotations

import hashlib
from typing import Any

from app.execution_core import get_active_trades
from app.native_profit_orders import (
    FAILED_STATUSES,
    FILLED_STATUSES,
    _compact_order_snapshot,
    _management_state,
    _order_snapshot,
    _persist_management_state,
    _positive_float,
    _safe_event,
    _set_and_verify_protection,
    _utc_now_iso,
    install_native_profit_orders,
)
from app.trade_management_profiles import (
    break_even_stop,
    is_scalping_management,
    post_tp2_stop,
    progress_r,
)


def reconcile_native_profit_orders(client: Any) -> dict[str, Any]:
    """Adopt eligible legacy trades and reconcile native TP fills efficiently."""

    trades = get_active_trades()
    if not trades:
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
    native_trades: list[dict[str, Any]] = []

    for trade in trades:
        symbol = str(trade.get("symbol") or "").upper().strip()
        journal_id = str(trade.get("journal_id") or "")
        position = positions_by_symbol.get(symbol)
        management = _management_state(trade)
        if not symbol or not journal_id or position is None:
            continue

        if management.get("native_tp_enabled"):
            native_trades.append(trade)
            continue

        if not _eligible_for_adoption(trade, management, position):
            continue

        metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
        execution_key = str(
            trade.get("execution_key")
            or metadata.get("execution_key")
            or hashlib.sha256(journal_id.encode("utf-8")).hexdigest()
        )
        position_quantity = _positive_float(position.get("size")) or 0.0
        candidate_management = {
            **management,
            "initial_quantity": _positive_float(management.get("initial_quantity")) or position_quantity,
            "remaining_quantity": position_quantity,
        }
        candidate = {
            **trade,
            "execution_key": execution_key,
            "quantity": position_quantity,
            "remaining_quantity": position_quantity,
            "management": candidate_management,
            "exchange_metadata": {
                **metadata,
                "execution_key": execution_key,
                "management": candidate_management,
            },
        }
        adoption = install_native_profit_orders(client, candidate)
        if not adoption.get("ok"):
            errors.append(f"{symbol} native TP adoption: {adoption.get('error') or 'failed'}")
            _safe_event(
                journal_id,
                "NATIVE_TP_ADOPTION_SKIPPED",
                "Existing active trade could not be adopted into native TP management; legacy fallback remains active.",
                {"symbol": symbol, "error": adoption.get("error")},
            )
            continue

        adopted_management = dict(adoption.get("management") or {})
        candidate["management"] = adopted_management
        candidate["exchange_metadata"] = {
            **candidate["exchange_metadata"],
            "management": adopted_management,
            "native_profit_orders": adoption.get("orders") or {},
        }
        _persist_management_state(candidate, adopted_management, position_quantity)
        _safe_event(
            journal_id,
            "NATIVE_TP_ORDERS_ADOPTED",
            "Existing active trade was adopted into exchange-native TP1/TP2 management.",
            {"symbol": symbol, "orders": adoption.get("orders") or {}},
        )
        actions.append({"symbol": symbol, "action": "NATIVE_TP_ORDERS_ADOPTED"})
        native_trades.append(candidate)

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
        entry = _positive_float(position.get("avgPrice") or trade.get("entry")) or 0.0
        original_stop = _positive_float(trade.get("stop_loss")) or entry
        mark_price = _positive_float(position.get("markPrice")) or entry
        direction = str(trade.get("direction") or "").lower()
        tick_size = _positive_float(management.get("native_tp_tick_size")) or 1e-8
        runner_target = _positive_float(management.get("runner_target") or trade.get("take_profit")) or 0.0

        changed = False

        # Scalping has an early 1R protection gate. This runs in the dedicated
        # two-second native watcher rather than the slower scanner loop.
        if is_scalping_management(management) and not bool(management.get("break_even_set")):
            current_r = progress_r(
                entry=entry,
                stop_loss=original_stop,
                direction=direction,
                mark_price=mark_price,
            )
            if current_r + 1e-9 >= float(management.get("break_even_trigger_r") or 1.0):
                target_stop = break_even_stop(trade, management, entry)
                protection = _set_and_verify_protection(
                    client,
                    trade=trade,
                    position=position,
                    stop_loss=target_stop,
                    take_profit=runner_target,
                    tick_size=tick_size,
                )
                if protection.get("ok"):
                    management["break_even_set"] = True
                    management["break_even_stop"] = target_stop
                    management["last_state_change"] = _utc_now_iso()
                    changed = True
                    _safe_event(
                        journal_id,
                        "SCALPING_1R_BREAK_EVEN_SET",
                        "Scalping reached 1R; break-even plus observed-fee buffer was verified.",
                        {"symbol": symbol, "progress_r": current_r, "stop_loss": target_stop, "protection": protection},
                    )
                    actions.append({"symbol": symbol, "action": "SCALPING_1R_BREAK_EVEN_SET"})
                else:
                    management["break_even_error"] = protection.get("error")
                    management["last_state_change"] = _utc_now_iso()
                    changed = True

        tp1_snapshot, tp1_error = _order_snapshot(client, symbol, management.get("tp1_order_link_id"))
        tp2_snapshot, tp2_error = _order_snapshot(client, symbol, management.get("tp2_order_link_id"))
        if tp1_error:
            errors.append(f"{symbol} TP1: {tp1_error}")
        if tp2_error:
            errors.append(f"{symbol} TP2: {tp2_error}")

        changed = _store_snapshot_if_changed(management, "tp1", tp1_snapshot) or changed
        changed = _store_snapshot_if_changed(management, "tp2", tp2_snapshot) or changed

        tp1_status = str((tp1_snapshot or {}).get("orderStatus") or "").lower()
        tp2_status = str((tp2_snapshot or {}).get("orderStatus") or "").lower()
        inferred_tp1 = initial_quantity > 0 and tp1_quantity > 0 and position_quantity <= initial_quantity - tp1_quantity + tolerance
        inferred_tp2 = initial_quantity > 0 and tp1_quantity > 0 and tp2_quantity > 0 and position_quantity <= initial_quantity - tp1_quantity - tp2_quantity + tolerance
        tp1_filled = tp1_status in FILLED_STATUSES or inferred_tp1
        tp2_filled = tp2_status in FILLED_STATUSES or inferred_tp2

        failed_stage = None
        failed_status = ""
        if not management.get("tp1_done") and tp1_status in FAILED_STATUSES:
            failed_stage, failed_status = "tp1", tp1_status
        elif not management.get("tp2_done") and tp2_status in FAILED_STATUSES:
            failed_stage, failed_status = "tp2", tp2_status
        if failed_stage and not management.get("native_tp_degraded"):
            management["native_tp_degraded"] = True
            management["native_tp_degraded_reason"] = f"{failed_stage.upper()} order status {failed_status}"
            management["last_state_change"] = _utc_now_iso()
            changed = True
            _safe_event(
                journal_id,
                "NATIVE_TP_DEGRADED",
                "Native partial take-profit order is unavailable; mark-price fallback is enabled.",
                {"symbol": symbol, "stage": failed_stage, "status": failed_status},
            )
            actions.append({"symbol": symbol, "action": "NATIVE_TP_DEGRADED"})

        if tp1_filled and not bool(management.get("tp1_done")):
            management["tp1_done"] = True
            management["tp1_fill_source"] = "exchange_order" if tp1_status in FILLED_STATUSES else "position_size_reconciliation"
            management["remaining_quantity"] = position_quantity
            management["last_state_change"] = _utc_now_iso()
            target_stop = break_even_stop(trade, management, entry)
            protection = _set_and_verify_protection(
                client,
                trade=trade,
                position=position,
                stop_loss=target_stop,
                take_profit=runner_target,
                tick_size=tick_size,
            )
            management["break_even_set"] = bool(protection.get("ok"))
            management["break_even_stop"] = target_stop if protection.get("ok") else None
            if not protection.get("ok"):
                management["break_even_error"] = protection.get("error")
            changed = True
            event_type = "NATIVE_TP1_FILLED_BREAK_EVEN_SET" if management["break_even_set"] else "NATIVE_TP1_FILLED_BREAK_EVEN_PENDING"
            _safe_event(
                journal_id,
                event_type,
                "TP1 was filled by the exchange; remaining position break-even state was updated.",
                {"symbol": symbol, "remaining_quantity": position_quantity, "stop_loss": target_stop, "protection": protection},
            )
            actions.append({"symbol": symbol, "action": event_type})

        if tp2_filled and not bool(management.get("tp2_done")):
            management["tp1_done"] = True
            management["tp2_done"] = True
            management["tp2_fill_source"] = "exchange_order" if tp2_status in FILLED_STATUSES else "position_size_reconciliation"
            management["remaining_quantity"] = position_quantity
            candidate_stop = post_tp2_stop(trade, management, mark_price)
            protection = _set_and_verify_protection(
                client,
                trade=trade,
                position=position,
                stop_loss=candidate_stop,
                take_profit=runner_target,
                tick_size=tick_size,
            )
            protection_ok = bool(protection.get("ok"))
            management["break_even_set"] = bool(management.get("break_even_set")) or protection_ok
            if is_scalping_management(management):
                management["profit_lock_stop"] = candidate_stop if protection_ok else None
                management["trailing_stop"] = None
                if not protection_ok:
                    management["profit_lock_error"] = protection.get("error")
                event_type = "SCALPING_TP2_PROFIT_LOCK_SET" if protection_ok else "SCALPING_TP2_PROFIT_LOCK_PENDING"
                event_message = "Scalping TP2 was filled; remaining 25% is protected at the TP1 price."
            else:
                management["trailing_stop"] = candidate_stop if protection_ok else None
                if not protection_ok:
                    management["trailing_error"] = protection.get("error")
                event_type = "NATIVE_TP2_FILLED_TRAILING_SET" if protection_ok else "NATIVE_TP2_FILLED_TRAILING_PENDING"
                event_message = "TP2 was filled by the exchange; runner trailing protection state was updated."
            management["last_state_change"] = _utc_now_iso()
            changed = True
            _safe_event(
                journal_id,
                event_type,
                event_message,
                {"symbol": symbol, "remaining_quantity": position_quantity, "stop_loss": candidate_stop, "protection": protection},
            )
            actions.append({"symbol": symbol, "action": event_type})

        if changed:
            _persist_management_state(trade, management, position_quantity)

    return {"ok": not errors, "managed": len(native_trades), "actions": actions, "errors": errors}


def _eligible_for_adoption(trade: dict[str, Any], management: dict[str, Any], position: dict[str, Any]) -> bool:
    if str(trade.get("status") or "active").lower() != "active":
        return False
    if management.get("tp1_done") or management.get("tp2_done"):
        return False
    if not all(_positive_float(management.get(key)) for key in ("tp1", "tp2", "runner_target")):
        return False
    position_quantity = _positive_float(position.get("size"))
    initial_quantity = _positive_float(management.get("initial_quantity"))
    if position_quantity is None:
        return False
    if initial_quantity is None:
        return True
    tolerance = max(initial_quantity * 1e-8, 1e-12)
    return abs(position_quantity - initial_quantity) <= tolerance


def _store_snapshot_if_changed(management: dict[str, Any], prefix: str, snapshot: dict[str, Any] | None) -> bool:
    if not snapshot:
        return False
    compact = _compact_order_snapshot(snapshot)
    status = str(snapshot.get("orderStatus") or "unknown")
    if management.get(f"{prefix}_order_snapshot") == compact and management.get(f"{prefix}_order_status") == status:
        return False
    management[f"{prefix}_order_snapshot"] = compact
    management[f"{prefix}_order_status"] = status
    return True
