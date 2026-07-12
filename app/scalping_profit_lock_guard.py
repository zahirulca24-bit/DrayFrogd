from __future__ import annotations

from typing import Any

from app.execution_core import get_active_trades
from app.native_profit_orders import (
    _management_state,
    _persist_management_state,
    _positive_float,
    _safe_event,
    _set_and_verify_protection,
    _utc_now_iso,
)
from app.trade_management_profiles import is_scalping_management


def enforce_scalping_tp2_profit_locks(client: Any) -> dict[str, Any]:
    """Keep retrying the Scalping TP2 profit lock until exchange verification passes.

    TP2 fill state and protection state are intentionally separate. A transient
    stop-amendment failure must not become permanent merely because ``tp2_done``
    was already persisted by the native-order reconciler.
    """

    trades = get_active_trades()
    if not trades:
        return {"ok": True, "managed": 0, "actions": [], "errors": []}

    ok_positions, positions, positions_error = client.safe_fetch_positions()
    if not ok_positions:
        return {
            "ok": False,
            "managed": 0,
            "actions": [],
            "errors": [positions_error or "Position data unavailable"],
        }

    positions_by_symbol = {
        str(position.get("symbol") or "").upper(): position
        for position in positions
        if (_positive_float(position.get("size")) or 0.0) > 0
    }

    actions: list[dict[str, Any]] = []
    errors: list[str] = []
    managed = 0

    for trade in trades:
        symbol = str(trade.get("symbol") or "").upper().strip()
        journal_id = str(trade.get("journal_id") or "").strip()
        management = _management_state(trade)
        position = positions_by_symbol.get(symbol)

        if not symbol or not journal_id or position is None:
            continue
        if not management.get("native_tp_enabled") or not is_scalping_management(management):
            continue
        if not _tp2_has_filled(management, position):
            continue

        managed += 1
        position_quantity = _positive_float(position.get("size")) or 0.0
        expected_stop = _positive_float(management.get("tp1"))
        runner_target = _positive_float(management.get("runner_target") or trade.get("take_profit"))
        tick_size = _positive_float(management.get("native_tp_tick_size")) or 1e-8

        if expected_stop is None or runner_target is None:
            error = "Scalping TP2 profit-lock target is unavailable"
            management["profit_lock_verified"] = False
            management["profit_lock_error"] = error
            management["last_state_change"] = _utc_now_iso()
            _persist_management_state(trade, management, position_quantity)
            errors.append(f"{symbol}: {error}")
            actions.append({"symbol": symbol, "action": "SCALPING_TP2_PROFIT_LOCK_BLOCKED"})
            continue

        actual_stop = _positive_float(position.get("stopLoss"))
        tolerance = max(tick_size, 1e-12)
        already_verified = actual_stop is not None and abs(actual_stop - expected_stop) <= tolerance

        if already_verified:
            changed = (
                not bool(management.get("profit_lock_verified"))
                or _positive_float(management.get("profit_lock_stop")) != expected_stop
                or management.get("trailing_stop") is not None
            )
            if changed:
                management["tp1_done"] = True
                management["tp2_done"] = True
                management["profit_lock_verified"] = True
                management["profit_lock_stop"] = expected_stop
                management["profit_lock_error"] = None
                management["trailing_stop"] = None
                management["last_state_change"] = _utc_now_iso()
                _persist_management_state(trade, management, position_quantity)
                _safe_event(
                    journal_id,
                    "SCALPING_TP2_PROFIT_LOCK_CONFIRMED",
                    "Existing Scalping TP2 profit lock was confirmed at the TP1 price.",
                    {"symbol": symbol, "stop_loss": expected_stop, "remaining_quantity": position_quantity},
                )
                actions.append({"symbol": symbol, "action": "SCALPING_TP2_PROFIT_LOCK_CONFIRMED"})
            continue

        retry_count = int(management.get("profit_lock_retry_count") or 0) + 1
        protection = _set_and_verify_protection(
            client,
            trade=trade,
            position=position,
            stop_loss=expected_stop,
            take_profit=runner_target,
            tick_size=tick_size,
        )
        protection_ok = bool(protection.get("ok"))

        management["tp1_done"] = True
        management["tp2_done"] = True
        management["remaining_quantity"] = position_quantity
        management["profit_lock_retry_count"] = retry_count
        management["profit_lock_verified"] = protection_ok
        management["profit_lock_stop"] = expected_stop if protection_ok else None
        management["profit_lock_error"] = None if protection_ok else protection.get("error")
        management["trailing_stop"] = None
        management["last_state_change"] = _utc_now_iso()
        _persist_management_state(trade, management, position_quantity)

        if protection_ok:
            event_type = "SCALPING_TP2_PROFIT_LOCK_REPAIRED"
            message = "Scalping TP2 profit lock was set and verified at the TP1 price."
        else:
            event_type = "SCALPING_TP2_PROFIT_LOCK_RETRY_PENDING"
            message = "Scalping TP2 was filled, but the TP1-price profit lock still requires retry."
            errors.append(f"{symbol}: {protection.get('error') or 'profit-lock verification failed'}")

        _safe_event(
            journal_id,
            event_type,
            message,
            {
                "symbol": symbol,
                "stop_loss": expected_stop,
                "remaining_quantity": position_quantity,
                "retry_count": retry_count,
                "protection": protection,
            },
        )
        actions.append({"symbol": symbol, "action": event_type})

    return {"ok": not errors, "managed": managed, "actions": actions, "errors": errors}


def _tp2_has_filled(management: dict[str, Any], position: dict[str, Any]) -> bool:
    if bool(management.get("tp2_done")):
        return True

    initial_quantity = _positive_float(management.get("initial_quantity"))
    tp1_quantity = _positive_float(management.get("tp1_quantity"))
    tp2_quantity = _positive_float(management.get("tp2_quantity"))
    position_quantity = _positive_float(position.get("size"))
    qty_step = _positive_float(management.get("native_tp_qty_step")) or 1e-12

    if None in (initial_quantity, tp1_quantity, tp2_quantity, position_quantity):
        return False

    tolerance = max(qty_step, float(initial_quantity) * 1e-8, 1e-12)
    expected_after_tp2 = float(initial_quantity) - float(tp1_quantity) - float(tp2_quantity)
    return float(position_quantity) <= expected_after_tp2 + tolerance
