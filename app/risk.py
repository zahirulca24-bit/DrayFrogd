from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from math import isfinite
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError

from app.bot_controls import get_risk_settings
from app.database import SessionLocal, engine
from app.models import RiskRuntimeState, TradeJournal


MIN_RISK_REWARD = 1.5
LOSS_COOLDOWN_MINUTES = 15
BDT = ZoneInfo("Asia/Dhaka")

_risk_lock = Lock()
_active_symbols: set[str] = set()
_trades_today = 0
_trades_day: str | None = None
_cooldown_until: datetime | None = None
_state_loaded = False


def validate_trade(signal: dict[str, Any]) -> dict[str, Any]:
    _ensure_state_loaded()
    normalized = _normalize_signal(signal)
    if normalized is None:
        return {"allowed": False, "reason": "Invalid signal payload"}

    symbol = normalized["symbol"]
    entry = normalized["entry"]
    stop_loss = normalized["stop_loss"]
    take_profit = normalized["take_profit"]
    risk_reward = normalized["risk_reward"]
    status = normalized["status"]

    if status != "active":
        return {"allowed": False, "reason": "Signal is not active"}
    if not symbol:
        return {"allowed": False, "reason": "Invalid signal payload"}
    if not _is_valid_trade_levels(entry, stop_loss, take_profit):
        return {"allowed": False, "reason": "Invalid entry/stop_loss/take_profit values"}
    if risk_reward < MIN_RISK_REWARD:
        return {"allowed": False, "reason": f"Risk reward below minimum {MIN_RISK_REWARD:.1f}"}

    settings = get_risk_settings()
    now = datetime.now(UTC)
    with _risk_lock:
        day_changed = _reset_daily_state_if_needed(now)
        cooldown_changed = _expire_cooldown_if_needed(now)
        if day_changed or cooldown_changed:
            _persist_state_locked()

        if _cooldown_until and now < _cooldown_until:
            return {"allowed": False, "reason": "Cooldown active after loss"}
        if symbol in _active_symbols:
            return {"allowed": False, "reason": "Symbol already active"}
        if len(_active_symbols) >= settings["max_open_trades"]:
            return {"allowed": False, "reason": "Max open trades exceeded"}
        if _trades_today >= settings["max_daily_trades"]:
            return {"allowed": False, "reason": "Max trades per day exceeded"}

    return {
        "allowed": True,
        "reason": "",
        "risk_per_trade": settings["risk_per_trade"],
        "leverage_cap": settings["leverage_cap"],
        "exposure_cap": settings["exposure_cap"],
    }


def get_risk_state() -> dict[str, Any]:
    _ensure_state_loaded()
    now = datetime.now(UTC)
    settings = get_risk_settings()
    with _risk_lock:
        day_changed = _reset_daily_state_if_needed(now)
        cooldown_changed = _expire_cooldown_if_needed(now)
        if day_changed or cooldown_changed:
            _persist_state_locked()
        return {
            "risk_per_trade": settings["risk_per_trade"],
            "leverage_cap": settings["leverage_cap"],
            "exposure_cap": settings["exposure_cap"],
            "max_open_trades": settings["max_open_trades"],
            "max_trades_per_day": settings["max_daily_trades"],
            "min_risk_reward": MIN_RISK_REWARD,
            "active_symbols": sorted(_active_symbols),
            "trades_today": _trades_today,
            "trades_day": _trades_day,
            "reset_timezone": "Asia/Dhaka",
            "cooldown_until": _cooldown_until.isoformat() if _cooldown_until else None,
        }


def register_active_trade(symbol: str) -> None:
    global _trades_today

    _ensure_state_loaded()
    normalized_symbol = symbol.upper().strip()
    if not normalized_symbol:
        return

    now = datetime.now(UTC)
    with _risk_lock:
        _reset_daily_state_if_needed(now)
        _expire_cooldown_if_needed(now)
        if normalized_symbol not in _active_symbols:
            _active_symbols.add(normalized_symbol)
            _trades_today += 1
        _persist_state_locked()


def release_active_trade(symbol: str) -> None:
    _ensure_state_loaded()
    normalized_symbol = symbol.upper().strip()
    if not normalized_symbol:
        return

    with _risk_lock:
        _active_symbols.discard(normalized_symbol)
        _persist_state_locked()


def start_loss_cooldown(now: datetime | None = None) -> None:
    global _cooldown_until

    _ensure_state_loaded()
    current = _as_utc(now)
    with _risk_lock:
        _cooldown_until = current + timedelta(minutes=LOSS_COOLDOWN_MINUTES)
        _persist_state_locked()


def restore_risk_state(now: datetime | None = None) -> dict[str, Any]:
    global _active_symbols, _trades_today, _trades_day, _cooldown_until, _state_loaded

    current = _as_utc(now)
    current_day = _bdt_day(current)
    stored_symbols: set[str] = set()
    stored_count = 0
    stored_day: str | None = None
    stored_cooldown: datetime | None = None
    journal_symbols: set[str] | None = None
    journal_count: int | None = None

    try:
        RiskRuntimeState.__table__.create(bind=engine, checkfirst=True)
        db = SessionLocal()
        try:
            row = db.query(RiskRuntimeState).filter(RiskRuntimeState.id == 1).first()
            if row is not None:
                stored_symbols = _decode_symbols(row.active_symbols)
                stored_day = row.trades_day
                stored_count = int(row.trades_today or 0) if stored_day == current_day else 0
                stored_cooldown = _as_utc(row.cooldown_until) if row.cooldown_until else None

            try:
                journal_rows = db.query(TradeJournal).all()
                journal_symbols = {
                    str(item.symbol or "").upper().strip()
                    for item in journal_rows
                    if str(item.status or "").lower() != "closed" and str(item.symbol or "").strip()
                }
                journal_count = sum(1 for item in journal_rows if _timestamp_is_on_bdt_day(item.opened_at, current_day))
            except SQLAlchemyError:
                db.rollback()
        finally:
            db.close()
    except SQLAlchemyError:
        pass

    restored_symbols = journal_symbols if journal_symbols is not None else stored_symbols
    restored_count = max(journal_count or 0, stored_count) if journal_count is not None else stored_count
    if stored_cooldown and stored_cooldown <= current:
        stored_cooldown = None

    with _risk_lock:
        _active_symbols = set(restored_symbols)
        _trades_today = restored_count
        _trades_day = current_day
        _cooldown_until = stored_cooldown
        _state_loaded = True
        _persist_state_locked()
        return {
            "active_symbols": sorted(_active_symbols),
            "trades_today": _trades_today,
            "trades_day": _trades_day,
            "cooldown_until": _cooldown_until.isoformat() if _cooldown_until else None,
        }


def _ensure_state_loaded() -> None:
    with _risk_lock:
        loaded = _state_loaded
    if not loaded:
        restore_risk_state()


def _persist_state_locked() -> None:
    try:
        RiskRuntimeState.__table__.create(bind=engine, checkfirst=True)
        db = SessionLocal()
        try:
            row = db.query(RiskRuntimeState).filter(RiskRuntimeState.id == 1).first()
            if row is None:
                row = RiskRuntimeState(id=1)
                db.add(row)
            row.trades_day = _trades_day
            row.trades_today = _trades_today
            row.active_symbols = json.dumps(sorted(_active_symbols), separators=(",", ":"))
            row.cooldown_until = _cooldown_until
            db.commit()
        except SQLAlchemyError:
            db.rollback()
        finally:
            db.close()
    except SQLAlchemyError:
        return


def _normalize_signal(signal: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return {
            "symbol": str(signal.get("symbol", "")).upper(),
            "entry": float(signal.get("entry")),
            "stop_loss": float(signal.get("stop_loss")),
            "take_profit": float(signal.get("take_profit")),
            "risk_reward": float(signal.get("risk_reward")),
            "status": str(signal.get("status", "")),
        }
    except (TypeError, ValueError):
        return None


def _is_valid_trade_levels(entry: float, stop_loss: float, take_profit: float) -> bool:
    if not all(isfinite(value) for value in [entry, stop_loss, take_profit]):
        return False
    if entry <= 0 or stop_loss <= 0 or take_profit <= 0:
        return False
    if entry == stop_loss or entry == take_profit:
        return False
    return stop_loss < entry < take_profit or take_profit < entry < stop_loss


def _reset_daily_state_if_needed(now: datetime) -> bool:
    global _trades_day, _trades_today

    current_day = _bdt_day(now)
    if _trades_day == current_day:
        return False
    _trades_day = current_day
    _trades_today = 0
    return True


def _expire_cooldown_if_needed(now: datetime) -> bool:
    global _cooldown_until

    if _cooldown_until and _cooldown_until <= _as_utc(now):
        _cooldown_until = None
        return True
    return False


def _bdt_day(value: datetime) -> str:
    return _as_utc(value).astimezone(BDT).date().isoformat()


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _timestamp_is_on_bdt_day(value: str | None, expected_day: str) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return _bdt_day(parsed) == expected_day


def _decode_symbols(value: str | None) -> set[str]:
    if not value:
        return set()
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return set()
    if not isinstance(parsed, list):
        return set()
    return {str(symbol).upper().strip() for symbol in parsed if str(symbol).strip()}
