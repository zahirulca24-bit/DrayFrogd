from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any

from app.trade_management_profiles import (
    is_profiled_management,
    is_scalping_management,
    max_hold_seconds,
    progress_r,
    trailing_enabled,
)


STAGNANT_SECONDS = 60 * 60


def evaluate_management_action(trade: dict[str, Any], mark_price: float, now: datetime) -> dict[str, str]:
    direction = str(trade.get("direction", "")).lower()
    entry = _to_float(trade.get("entry"), 0.0)
    stop_loss = _to_float(trade.get("stop_loss"), 0.0)
    management = _management_state(trade)
    opened_at = _parse_time(trade.get("opened_at") or trade.get("detected_at")) or now
    age_seconds = (now - opened_at).total_seconds()

    if age_seconds >= max_hold_seconds(management):
        return {"action": "max_hold_close"}

    risk = abs(entry - stop_loss)
    if risk <= 0 or direction not in {"long", "short"}:
        return {"action": "hold"}

    current_progress_r = progress_r(
        entry=entry,
        stop_loss=stop_loss,
        direction=direction,
        mark_price=mark_price,
    )
    if age_seconds >= STAGNANT_SECONDS and current_progress_r < 0.25:
        return {"action": "stagnant_close"}

    tp1_done = bool(management.get("tp1_done"))
    tp2_done = bool(management.get("tp2_done"))
    break_even_set = bool(management.get("break_even_set"))
    trailing_stop = _to_float(management.get("trailing_stop"), None)
    profit_lock_stop = _to_float(management.get("profit_lock_stop"), None)

    # Scalping protects the trade at 1R before TP1. Intraday keeps the existing
    # TP1-fill -> break-even sequence.
    if (
        is_scalping_management(management)
        and not break_even_set
        and current_progress_r + 1e-9 >= float(management.get("break_even_trigger_r") or 1.0)
    ):
        return {"action": "retry_break_even"}

    # Protection retries must run before advancing to the next profit stage.
    if tp1_done and not break_even_set:
        return {"action": "retry_break_even"}
    if tp2_done and trailing_enabled(management) and trailing_stop is None:
        return {"action": "retry_trailing"}
    if tp2_done and is_scalping_management(management) and profit_lock_stop is None:
        return {"action": "retry_profit_lock"}

    native_tp_active = bool(management.get("native_tp_enabled")) and not bool(management.get("native_tp_degraded"))
    if native_tp_active:
        # Exchange-native reduce-only orders own TP1/TP2. Mark-price polling must
        # never submit a duplicate partial market close while those orders are
        # live. The watcher persists fills as tp1_done/tp2_done.
        if tp2_done and trailing_enabled(management):
            return {"action": "trail"}
        return {"action": "hold"}

    tp1 = _to_float(management.get("tp1"), entry)
    tp2 = _to_float(management.get("tp2"), entry)
    hit_tp1 = mark_price >= tp1 if direction == "long" else mark_price <= tp1
    hit_tp2 = mark_price >= tp2 if direction == "long" else mark_price <= tp2

    # Legacy/degraded trades retain mark-price fallback. TP1 must be confirmed
    # before TP2 so a price gap executes one stage per management cycle.
    if hit_tp1 and not tp1_done:
        return {"action": "tp1"}
    if hit_tp2 and tp1_done and not tp2_done:
        return {"action": "tp2"}
    if tp2_done and trailing_enabled(management):
        return {"action": "trail"}
    if tp2_done and is_profiled_management(management):
        return {"action": "hold"}
    return {"action": "hold"}


def _management_state(trade: dict[str, Any]) -> dict[str, Any]:
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    management = trade.get("management") or metadata.get("management") or {}
    return dict(management)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _to_float(value: Any, fallback: Any) -> Any:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback
    return numeric if isfinite(numeric) else fallback
