from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.database import SessionLocal
from app.models import TradeJournal
from app.risk import LOSS_COOLDOWN_MINUTES, start_loss_cooldown


def sync_loss_cooldowns(now: datetime | None = None) -> dict[str, Any]:
    """Restore 30-minute symbol cooldowns from exact negative realized PnL.

    The journal is authoritative. Re-running this function is idempotent because
    each expiry is calculated from the original close timestamp rather than the
    current worker time, so repeated worker cycles never extend a cooldown.
    """

    current = _as_utc(now)
    cutoff = current - timedelta(minutes=LOSS_COOLDOWN_MINUTES)
    applied: list[dict[str, str]] = []

    db = SessionLocal()
    try:
        rows = (
            db.query(TradeJournal)
            .filter(TradeJournal.status == "closed")
            .filter(TradeJournal.realized_pnl < 0)
            .all()
        )
        for row in rows:
            closed_at = _parse_time(row.closed_at)
            if closed_at is None or closed_at <= cutoff or closed_at > current + timedelta(minutes=1):
                continue
            symbol = str(row.symbol or "").upper().strip()
            if not symbol:
                continue
            start_loss_cooldown(symbol=symbol, now=closed_at)
            applied.append(
                {
                    "symbol": symbol,
                    "closed_at": closed_at.isoformat(),
                    "cooldown_until": (closed_at + timedelta(minutes=LOSS_COOLDOWN_MINUTES)).isoformat(),
                }
            )
    finally:
        db.close()

    return {"ok": True, "applied": applied, "applied_count": len(applied)}


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
