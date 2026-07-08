from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any


MAX_HOLD_SECONDS = 4 * 60 * 60
STAGNANT_SECONDS = 60 * 60


def evaluate_management_action(trade: dict[str, Any], mark_price: float, now: datetime) -> dict[str, str]:
    direction = str(trade.get("direction", "")).lower()
    entry = _to_float(trade.get("entry"), 0.0)
    stop_loss = _to_float(trade.get("stop_loss"), 0.0)
    management = _management_state(trade)
    opened_at = _parse_time(trade.get("opened_at")) or now
    age_seconds = (now - opened_at).total_seconds()

    if age_seconds >= MAX_HOLD_SECONDS:
        return {"action": "max_hold_close"}

    risk = abs(entry - stop_loss)
    if risk <= 0 or direction not in {"long", "short"}:
        return {"action": "hold"}

    progress_r = ((mark_price - entry) / risk) if direction == "long" else ((entry - mark_price) / risk)
    if age_seconds >= STAGNANT_SECONDS and progress_r < 0.25:
        return {"action": "stagnant_close"}

    tp1 = _to_float(management.get("tp1"), entry)
    tp2 = _to_float(management.get("tp2"), entry)
    hit_tp1 = mark_price >= tp1 if direction == "long" else mark_price <= tp1
    hit_tp2 = mark_price >= tp2 if direction == "long" else mark_price <= tp2

    if hit_tp1 and not management.get("tp1_done"):
        return {"action": "tp1"}
    if hit_tp2 and not management.get("tp2_done"):
        return {"action": "tp2"}
    if management.get("tp2_done"):
        return {"action": "trail"}
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
