from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from threading import Lock
from typing import Any

from app.bot_controls import get_risk_settings


MIN_RISK_REWARD = 1.5
LOSS_COOLDOWN_MINUTES = 15

_risk_lock = Lock()
_active_symbols: set[str] = set()
_trades_today = 0
_trades_day: str | None = None
_cooldown_until: datetime | None = None


def validate_trade(signal: dict[str, Any]) -> dict[str, Any]:
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
        _reset_daily_state_if_needed(now)

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
    now = datetime.now(UTC)
    settings = get_risk_settings()
    with _risk_lock:
        _reset_daily_state_if_needed(now)
        return {
            "risk_per_trade": settings["risk_per_trade"],
            "leverage_cap": settings["leverage_cap"],
            "exposure_cap": settings["exposure_cap"],
            "max_open_trades": settings["max_open_trades"],
            "max_trades_per_day": settings["max_daily_trades"],
            "min_risk_reward": MIN_RISK_REWARD,
            "active_symbols": sorted(_active_symbols),
            "trades_today": _trades_today,
            "cooldown_until": _cooldown_until.isoformat() if _cooldown_until else None,
        }


def register_active_trade(symbol: str) -> None:
    normalized_symbol = symbol.upper().strip()
    if not normalized_symbol:
        return

    now = datetime.now(UTC)
    with _risk_lock:
        _reset_daily_state_if_needed(now)
        _active_symbols.add(normalized_symbol)
        globals()["_trades_today"] = _trades_today + 1


def release_active_trade(symbol: str) -> None:
    normalized_symbol = symbol.upper().strip()
    if not normalized_symbol:
        return

    with _risk_lock:
        _active_symbols.discard(normalized_symbol)


def start_loss_cooldown(now: datetime | None = None) -> None:
    current = now.astimezone(UTC) if now and now.tzinfo else now.replace(tzinfo=UTC) if now else datetime.now(UTC)
    with _risk_lock:
        globals()["_cooldown_until"] = current + timedelta(minutes=LOSS_COOLDOWN_MINUTES)


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
    if stop_loss < entry < take_profit:
        return True
    if take_profit < entry < stop_loss:
        return True
    return False


def _reset_daily_state_if_needed(now: datetime) -> None:
    global _trades_day, _trades_today

    current_day = now.date().isoformat()
    if _trades_day != current_day:
        _trades_day = current_day
        _trades_today = 0
