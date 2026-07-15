from __future__ import annotations

from typing import Any

from app.engines import INTRADAY_PROFILE as INTRADAY_ENGINE_PROFILE
from app.execution_core import get_active_trades
from app.native_profit_orders import (
    FILLED_STATUSES,
    _management_state,
    _persist_management_state,
    _positive_float,
    _safe_event,
    _set_and_verify_protection,
    _utc_now_iso,
)
from app.trade_management_profiles import break_even_stop, post_tp2_stop


INTRADAY_PROFILE = INTRADAY_ENGINE_PROFILE.profile_name


def enforce_intraday_protection(client: Any) -> dict[str, Any]:
    """Continuously verify Intraday TP1 break-even and TP2 trailing protection.

    TP fill state and protection state are deliberately independent. A transient
    exchange amendment or verification failure must therefore be retried on every
    fast monitor cycle even after ``tp1_done``/``tp2_done`` has been persisted.
    Unknown or conflicting profiles are never treated as Intraday.
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
        str(item.get("symbol") or "").upper(): item
        for item in positions
        if (_positive_float(item.get("size")) or 0.0) > 0
    }
    actions: list[dict[str, Any]] = []
    errors: list[str] = []
    managed = 0

    for trade in trades:
        management = _management_state(trade)
        if not _is_authoritative_intraday(trade, management):
            continue

        symbol = str(trade.get("symbol") or "").upper().strip()
        journal_id = str(trade.get("journal_id") or "").strip()
        position = positions_by_symbol.get(symbol)
        if not symbol or not journal_id or position is None:
            continue

        managed += 1
        initial_quantity = _positive_float(management.get("initial_quantity"))
        position_quantity = _positive_float(position.get("size"))
        entry = _positive_float(position.get("avgPrice") or trade.get("entry"))
        mark_price = _positive_float(position.get("markPrice"))
        runner_target = _positive_float(management.get("runner_target") or trade.get("take_profit"))
        tick_size = _positive_float(management.get("native_tp_tick_size")) or 1e-8
        direction = str(trade.get("direction") or "").lower().strip()
        if (
            initial_quantity is None
            or position_quantity is None
            or entry is None
            or mark_price is None
            or runner_target is None
            or direction not in {"long", "short"}
        ):
            errors.append(f"{symbol}: Intraday protection prerequisites unavailable")
            continue

        tp1_quantity = _positive_float(management.get("tp1_quantity")) or (
            initial_quantity * float(management.get("tp1_fraction") or 0.50)
        )
        tp2_quantity = _positive_float(management.get("tp2_quantity")) or (
            initial_quantity * float(management.get("tp2_fraction") or 0.25)
        )
        tolerance = max(tick_size, initial_quantity * 1e-8, 1e-12)
        tp1_status = str(management.get("tp1_order_status") or "").lower()
        tp2_status = str(management.get("tp2_order_status") or "").lower()
        inferred_tp1 = position_quantity <= initial_quantity - tp1_quantity + tolerance
        inferred_tp2 = position_quantity <= initial_quantity - tp1_quantity - tp2_quantity + tolerance
        tp1_filled = bool(management.get("tp1_done")) or tp1_status in FILLED_STATUSES or inferred_tp1
        tp2_filled = bool(management.get("tp2_done")) or tp2_status in FILLED_STATUSES or inferred_tp2

        changed = False
        if tp1_filled and not bool(management.get("tp1_done")):
            management["tp1_done"] = True
            management["tp1_fill_source"] = "position_size_reconciliation" if inferred_tp1 else "exchange_order"
            changed = True
        if tp2_filled and not bool(management.get("tp2_done")):
            management["tp1_done"] = True
            management["tp2_done"] = True
            management["tp2_fill_source"] = "position_size_reconciliation" if inferred_tp2 else "exchange_order"
            changed = True

        management["remaining_quantity"] = position_quantity
        actual_stop = _positive_float(position.get("stopLoss"))
        break_even_target = break_even_stop(trade, management, entry)

        if tp2_filled:
            candidate_stop = post_tp2_stop(
                {**trade, "entry": entry},
                management,
                mark_price,
            )
            candidate_stop = _clamp_to_break_even(candidate_stop, break_even_target, direction)
            candidate_stop = _never_worsen_stop(candidate_stop, actual_stop, direction)
            needs_amendment = _needs_better_stop(actual_stop, candidate_stop, direction, tick_size)
            previously_verified = bool(management.get("trailing_verified"))

            if needs_amendment:
                protection = _set_and_verify_protection(
                    client,
                    trade=trade,
                    position=position,
                    stop_loss=candidate_stop,
                    take_profit=runner_target,
                    tick_size=tick_size,
                )
                if protection.get("ok"):
                    verified_stop = _positive_float(protection.get("stop_loss")) or candidate_stop
                    management["break_even_set"] = True
                    management["break_even_stop"] = break_even_target
                    management["trailing_stop"] = verified_stop
                    management["trailing_verified"] = True
                    management["trailing_error"] = None
                    management["trailing_verified_at"] = _utc_now_iso()
                    actions.append({"symbol": symbol, "action": "INTRADAY_TP2_TRAILING_VERIFIED"})
                    if not previously_verified:
                        _safe_event(
                            journal_id,
                            "INTRADAY_TP2_TRAILING_VERIFIED",
                            "Intraday TP2 runner trailing protection was verified on the exchange.",
                            {"symbol": symbol, "stop_loss": verified_stop, "remaining_quantity": position_quantity},
                        )
                else:
                    error = str(protection.get("error") or "Trailing protection verification failed")
                    prior_error = str(management.get("trailing_error") or "")
                    retry_count = int(management.get("trailing_retry_count") or 0) + 1
                    management["trailing_verified"] = False
                    management["trailing_stop"] = None
                    management["trailing_error"] = error
                    management["trailing_retry_count"] = retry_count
                    errors.append(f"{symbol}: {error}")
                    actions.append({"symbol": symbol, "action": "INTRADAY_TP2_TRAILING_RETRY_PENDING"})
                    if retry_count == 1 or error != prior_error:
                        _safe_event(
                            journal_id,
                            "INTRADAY_TP2_TRAILING_RETRY_PENDING",
                            "Intraday TP2 trailing protection is pending and will retry on the next fast cycle.",
                            {"symbol": symbol, "error": error, "retry_count": retry_count},
                        )
                changed = True
            else:
                management["break_even_set"] = True
                management["break_even_stop"] = break_even_target
                management["trailing_stop"] = actual_stop
                management["trailing_verified"] = True
                management["trailing_error"] = None
                if not previously_verified:
                    management["trailing_verified_at"] = _utc_now_iso()
                    actions.append({"symbol": symbol, "action": "INTRADAY_TP2_TRAILING_CONFIRMED_EXISTING"})
                    _safe_event(
                        journal_id,
                        "INTRADAY_TP2_TRAILING_CONFIRMED_EXISTING",
                        "Existing exchange stop already satisfied Intraday TP2 trailing protection.",
                        {"symbol": symbol, "stop_loss": actual_stop, "remaining_quantity": position_quantity},
                    )
                changed = changed or not previously_verified

        elif tp1_filled:
            needs_amendment = _needs_better_stop(actual_stop, break_even_target, direction, tick_size)
            previously_verified = bool(management.get("break_even_verified"))

            if needs_amendment:
                protection = _set_and_verify_protection(
                    client,
                    trade=trade,
                    position=position,
                    stop_loss=break_even_target,
                    take_profit=runner_target,
                    tick_size=tick_size,
                )
                if protection.get("ok"):
                    verified_stop = _positive_float(protection.get("stop_loss")) or break_even_target
                    management["break_even_set"] = True
                    management["break_even_stop"] = verified_stop
                    management["break_even_verified"] = True
                    management["break_even_error"] = None
                    management["break_even_verified_at"] = _utc_now_iso()
                    actions.append({"symbol": symbol, "action": "INTRADAY_TP1_BREAK_EVEN_VERIFIED"})
                    if not previously_verified:
                        _safe_event(
                            journal_id,
                            "INTRADAY_TP1_BREAK_EVEN_VERIFIED",
                            "Intraday TP1 break-even protection was verified on the exchange.",
                            {"symbol": symbol, "stop_loss": verified_stop, "remaining_quantity": position_quantity},
                        )
                else:
                    error = str(protection.get("error") or "Break-even protection verification failed")
                    prior_error = str(management.get("break_even_error") or "")
                    retry_count = int(management.get("break_even_retry_count") or 0) + 1
                    management["break_even_set"] = False
                    management["break_even_verified"] = False
                    management["break_even_error"] = error
                    management["break_even_retry_count"] = retry_count
                    errors.append(f"{symbol}: {error}")
                    actions.append({"symbol": symbol, "action": "INTRADAY_TP1_BREAK_EVEN_RETRY_PENDING"})
                    if retry_count == 1 or error != prior_error:
                        _safe_event(
                            journal_id,
                            "INTRADAY_TP1_BREAK_EVEN_RETRY_PENDING",
                            "Intraday TP1 break-even protection is pending and will retry on the next fast cycle.",
                            {"symbol": symbol, "error": error, "retry_count": retry_count},
                        )
                changed = True
            else:
                management["break_even_set"] = True
                management["break_even_stop"] = actual_stop
                management["break_even_verified"] = True
                management["break_even_error"] = None
                if not previously_verified:
                    management["break_even_verified_at"] = _utc_now_iso()
                    actions.append({"symbol": symbol, "action": "INTRADAY_TP1_BREAK_EVEN_CONFIRMED_EXISTING"})
                    _safe_event(
                        journal_id,
                        "INTRADAY_TP1_BREAK_EVEN_CONFIRMED_EXISTING",
                        "Existing exchange stop already satisfied Intraday TP1 break-even protection.",
                        {"symbol": symbol, "stop_loss": actual_stop, "remaining_quantity": position_quantity},
                    )
                changed = changed or not previously_verified

        if changed:
            management["last_state_change"] = _utc_now_iso()
            _persist_management_state(trade, management, position_quantity)

    return {"ok": not errors, "managed": managed, "actions": actions, "errors": errors}


def _is_authoritative_intraday(trade: dict[str, Any], management: dict[str, Any]) -> bool:
    profile = str(management.get("profile_name") or "").lower().strip()
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    validation = metadata.get("risk_validation") if isinstance(metadata.get("risk_validation"), dict) else {}
    candidates = {
        str(value).lower().strip()
        for value in (
            management.get("trade_type"),
            trade.get("trade_type"),
            metadata.get("trade_type"),
            validation.get("trade_type"),
        )
        if value is not None and str(value).strip()
    }
    if profile and profile != INTRADAY_PROFILE:
        return False
    if any(candidate != "intraday" for candidate in candidates):
        return False
    return profile == INTRADAY_PROFILE or candidates == {"intraday"}


def _needs_better_stop(actual: float | None, target: float, direction: str, tick_size: float) -> bool:
    tolerance = max(abs(tick_size), 1e-12)
    if actual is None:
        return True
    if direction == "long":
        return actual < target - tolerance
    return actual > target + tolerance


def _clamp_to_break_even(candidate: float, break_even: float, direction: str) -> float:
    return max(candidate, break_even) if direction == "long" else min(candidate, break_even)


def _never_worsen_stop(candidate: float, actual: float | None, direction: str) -> float:
    if actual is None:
        return candidate
    return max(candidate, actual) if direction == "long" else min(candidate, actual)
