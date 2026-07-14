from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.journal import (
    _build_trade_payload,
    _ensure_trade_journal_columns,
    reserve_trade_execution,
    serialize_trade_entry,
)
from app.models import RiskRuntimeState, TradeJournal
from app.trade_state import CAPACITY_BLOCKING_STATUSES


def reserve_execution_capacity(
    trade: dict[str, Any],
    execution_key: str,
    *,
    required_risk: float | None = None,
    max_active_trades: int | None = None,
    max_daily_trades: int | None = None,
    reentry_cooldown_minutes: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Atomically reserve both the execution key and portfolio risk capacity.

    PostgreSQL locks the single risk-runtime row while active-trade count,
    symbol exclusivity and available risk are checked and updated. This prevents
    two different signals from passing the same stale portfolio-capacity view.
    Legacy callers without a risk guard retain the existing reservation path.
    """

    if required_risk is None or max_active_trades is None:
        return reserve_trade_execution(trade, execution_key)

    normalized_key = str(execution_key or "").strip().lower()
    symbol = str(trade.get("symbol") or "").upper().strip()
    risk_amount = float(required_risk)
    active_limit = int(max_active_trades)
    daily_limit = int(max_daily_trades if max_daily_trades is not None else 8)
    cooldown_minutes = int(reentry_cooldown_minutes if reentry_cooldown_minutes is not None else 30)
    current = now.astimezone(UTC) if now and now.tzinfo else (now.replace(tzinfo=UTC) if now else datetime.now(UTC))
    if not normalized_key:
        raise ValueError("execution_key is required")
    if not symbol:
        raise ValueError("symbol is required")
    if risk_amount <= 0:
        raise ValueError("required_risk must be positive")
    if active_limit <= 0:
        raise ValueError("max_active_trades must be positive")
    if daily_limit <= 0:
        raise ValueError("max_daily_trades must be positive")
    if cooldown_minutes < 0:
        raise ValueError("reentry_cooldown_minutes cannot be negative")

    _ensure_trade_journal_columns()
    journal_id = str(trade.get("journal_id") or f"exec-{normalized_key[:48]}")
    pending_trade = {
        **trade,
        "journal_id": journal_id,
        "execution_key": normalized_key,
        "status": "pending_execution",
        "order_id": None,
        "opened_at": None,
        "closed_at": None,
    }
    payload = _build_trade_payload(pending_trade, journal_id=journal_id, default_opened_at=False)

    db = SessionLocal()
    try:
        existing = (
            db.query(TradeJournal)
            .filter(or_(TradeJournal.execution_key == normalized_key, TradeJournal.journal_id == journal_id))
            .first()
        )
        if existing is not None:
            return {"reserved": False, "reason": "DUPLICATE_EXECUTION", "trade": serialize_trade_entry(existing)}

        state = (
            db.query(RiskRuntimeState)
            .filter(RiskRuntimeState.id == 1)
            .with_for_update()
            .first()
        )
        if state is None:
            return {"reserved": False, "reason": "RISK_STATE_UNAVAILABLE", "trade": None}
        if bool(state.circuit_breaker_active):
            return {
                "reserved": False,
                "reason": state.circuit_breaker_reason or "DAILY_NET_LOSS_CIRCUIT_BREAKER",
                "trade": None,
            }
        trades_today = int(state.trades_today or 0)
        if trades_today >= daily_limit:
            return {
                "reserved": False,
                "reason": "DAILY_TRADE_LIMIT_REACHED",
                "trades_today": trades_today,
                "max_daily_trades": daily_limit,
                "trade": None,
            }
        recent_close = (
            db.query(TradeJournal)
            .filter(
                TradeJournal.symbol == symbol,
                TradeJournal.status == "closed",
                TradeJournal.opened_at.isnot(None),
                TradeJournal.closed_at.isnot(None),
                or_(TradeJournal.result.is_(None), TradeJournal.result != "execution_failed"),
            )
            .order_by(TradeJournal.id.desc())
            .first()
        )
        cooldown_until = _cooldown_until(recent_close, cooldown_minutes)
        if cooldown_until is not None and current < cooldown_until:
            return {
                "reserved": False,
                "reason": "SYMBOL_REENTRY_COOLDOWN",
                "cooldown_until": cooldown_until.isoformat(),
                "trade": None,
            }

        open_rows = db.query(TradeJournal).filter(TradeJournal.status.in_(sorted(CAPACITY_BLOCKING_STATUSES))).all()
        if any(str(row.symbol or "").upper() == symbol for row in open_rows):
            return {"reserved": False, "reason": "SYMBOL_ALREADY_ACTIVE", "trade": None}
        if len(open_rows) >= active_limit:
            return {"reserved": False, "reason": "ACTIVE_TRADE_LIMIT_REACHED", "trade": None}

        available_risk = float(state.available_risk or 0.0)
        if risk_amount > available_risk + 1e-9:
            return {
                "reserved": False,
                "reason": "DYNAMIC_RISK_CAPACITY_EXCEEDED",
                "required_risk": risk_amount,
                "available_risk": available_risk,
                "trade": None,
            }

        metadata = dict(trade.get("exchange_metadata") or {})
        metadata["risk_reservation"] = {
            "required_risk": risk_amount,
            "available_risk_before": available_risk,
            "available_risk_after": max(available_risk - risk_amount, 0.0),
            "active_trades_before": len(open_rows),
            "active_trades_after": len(open_rows) + 1,
            "trades_today_before": trades_today,
            "trades_today_after": trades_today + 1,
            "max_daily_trades": daily_limit,
            "reentry_cooldown_minutes": cooldown_minutes,
        }
        pending_trade["exchange_metadata"] = metadata
        payload = _build_trade_payload(pending_trade, journal_id=journal_id, default_opened_at=False)

        active_symbols = _decode_symbols(state.active_symbols)
        if symbol not in active_symbols:
            active_symbols.append(symbol)
        state.active_symbols = json.dumps(sorted(active_symbols), separators=(",", ":"))
        state.active_trade_count = len(open_rows) + 1
        state.trades_today = trades_today + 1
        state.live_risk = float(state.live_risk or 0.0) + risk_amount
        state.available_risk = max(available_risk - risk_amount, 0.0)

        row = TradeJournal(**payload)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = (
                db.query(TradeJournal)
                .filter(or_(TradeJournal.execution_key == normalized_key, TradeJournal.journal_id == journal_id))
                .first()
            )
            if existing is None:
                raise
            return {"reserved": False, "reason": "DUPLICATE_EXECUTION", "trade": serialize_trade_entry(existing)}

        db.refresh(row)
        return {"reserved": True, "reason": "", "trade": serialize_trade_entry(row)}
    finally:
        db.close()


def _cooldown_until(row: TradeJournal | None, cooldown_minutes: int) -> datetime | None:
    if row is None or cooldown_minutes <= 0:
        return None
    parsed = _parse_timestamp(row.closed_at)
    return parsed + timedelta(minutes=cooldown_minutes) if parsed is not None else None


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _decode_symbols(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    result: list[str] = []
    for item in parsed:
        symbol = str(item or "").upper().strip()
        if symbol and symbol not in result:
            result.append(symbol)
    return result
