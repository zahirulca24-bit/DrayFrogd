from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.database import SessionLocal
from app.models import TradeJournal
from app.risk import start_loss_cooldown


SCALPING_REENTRY_COOLDOWN_MINUTES = 60


def sync_scalping_reentry_cooldowns(now: datetime | None = None) -> dict[str, Any]:
    """Rebuild persistent 60-minute Scalping symbol cooldowns from closed Journal rows.

    The Journal is read first and its session is closed before RiskRuntimeState is
    updated. Re-running is idempotent because every expiry is anchored to the
    authoritative close timestamp and the risk layer never shortens a longer
    existing cooldown.
    """

    current = _as_utc(now)
    cutoff = current - timedelta(minutes=SCALPING_REENTRY_COOLDOWN_MINUTES)
    active: dict[str, datetime] = {}
    applied: list[dict[str, str]] = []
    rows: list[Any] = []
    db = None

    try:
        db = SessionLocal()
        rows = db.query(TradeJournal).filter(TradeJournal.status == "closed").all()
    except Exception as exc:
        return _failure(str(exc))
    finally:
        if db is not None:
            db.close()

    try:
        for row in rows:
            closed_at = _parse_time(row.closed_at)
            if closed_at is None or closed_at <= cutoff or closed_at > current + timedelta(minutes=1):
                continue
            if not _is_scalping_trade(row):
                continue

            symbol = str(row.symbol or "").upper().strip()
            if not symbol:
                continue
            expiry = closed_at + timedelta(minutes=SCALPING_REENTRY_COOLDOWN_MINUTES)
            previous = active.get(symbol)
            if previous is None or expiry > previous:
                active[symbol] = expiry

        for symbol, expiry in sorted(active.items()):
            closed_at = expiry - timedelta(minutes=SCALPING_REENTRY_COOLDOWN_MINUTES)
            start_loss_cooldown(
                symbol=symbol,
                now=closed_at,
                duration_minutes=SCALPING_REENTRY_COOLDOWN_MINUTES,
            )
            applied.append(
                {
                    "symbol": symbol,
                    "closed_at": closed_at.isoformat(),
                    "cooldown_until": expiry.isoformat(),
                }
            )
    except Exception as exc:
        return _failure(str(exc))

    return {
        "ok": True,
        "active_symbols": sorted(active),
        "suppressions": {symbol: expiry.isoformat() for symbol, expiry in sorted(active.items())},
        "applied": applied,
        "applied_count": len(applied),
        "error": None,
    }


def _failure(error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "active_symbols": [],
        "suppressions": {},
        "applied": [],
        "applied_count": 0,
        "error": error,
    }


def _is_scalping_trade(row: Any) -> bool:
    metadata = _metadata(getattr(row, "exchange_metadata", None))
    management = metadata.get("management") if isinstance(metadata.get("management"), dict) else {}
    validation = metadata.get("risk_validation") if isinstance(metadata.get("risk_validation"), dict) else {}
    candidates = (
        getattr(row, "trade_type", None),
        metadata.get("trade_type"),
        management.get("trade_type"),
        validation.get("trade_type"),
    )
    if any(str(value or "").lower().strip() == "scalping" for value in candidates):
        return True
    return str(management.get("profile_name") or "").lower().strip().startswith("scalping_")


def _metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


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
