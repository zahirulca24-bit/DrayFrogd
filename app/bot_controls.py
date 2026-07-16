from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.database import SessionLocal, engine
from app.models import BotRuntimeConfig, RiskRuntimeState
from app.runtime_guard import get_watchdog_execution_block


DEFAULT_RISK_SETTINGS = {
    # Legacy percentage field is retained for API compatibility. The risk engine
    # now uses fixed USDT profiles: 20 USDT scalping and 50 USDT intraday.
    "risk_per_trade": 0.01,
    "leverage_cap": 20.0,
    "exposure_cap": 0.50,
    "max_open_trades": 5,
    # Locked turnover guard. Eight exchange attempts per BDT day prevents
    # fee churn while preserving enough capacity for both trade profiles.
    "max_daily_trades": 8,
}


def ensure_runtime_config() -> None:
    _ensure_runtime_columns()
    db = SessionLocal()
    try:
        row = db.query(BotRuntimeConfig).filter(BotRuntimeConfig.id == 1).first()
        if row is None:
            row = BotRuntimeConfig(
                id=1,
                bot_status="idle",
                emergency_stop=False,
                execution_mode="demo",
                auto_trading_enabled=True,
                **DEFAULT_RISK_SETTINGS,
            )
            db.add(row)
        else:
            # Keep the persisted compatibility fields aligned with the locked
            # authority policy. Profile-specific risk/leverage is returned by
            # app.risk.validate_trade.
            row.leverage_cap = DEFAULT_RISK_SETTINGS["leverage_cap"]
            row.exposure_cap = DEFAULT_RISK_SETTINGS["exposure_cap"]
            row.max_open_trades = DEFAULT_RISK_SETTINGS["max_open_trades"]
            row.max_daily_trades = DEFAULT_RISK_SETTINGS["max_daily_trades"]
        db.commit()
    finally:
        db.close()


def start_bot() -> dict[str, Any]:
    if _risk_circuit_breaker_active():
        return _update_runtime(bot_status="stopped")
    return _update_runtime(bot_status="running")


def stop_bot() -> dict[str, Any]:
    return _update_runtime(bot_status="stopped")


def activate_emergency_stop() -> dict[str, Any]:
    return _update_runtime(bot_status="stopped", emergency_stop=True)


def resume_bot() -> dict[str, Any]:
    return _update_runtime(emergency_stop=False)


def update_bot_config(
    execution_mode: str | None = None,
    auto_trading_enabled: bool | None = None,
    risk_per_trade: float | None = None,
    leverage_cap: float | None = None,
    exposure_cap: float | None = None,
    max_open_trades: int | None = None,
    max_daily_trades: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if execution_mode is not None:
        normalized_mode = execution_mode.lower()
        if normalized_mode not in {"demo", "live"}:
            raise ValueError("Execution mode must be demo or live")
        if normalized_mode == "live" and not is_live_mode_available():
            raise ValueError("Live mode cannot be enabled until real Bybit API keys are configured")
        payload["execution_mode"] = normalized_mode

    if auto_trading_enabled is not None:
        payload["auto_trading_enabled"] = bool(auto_trading_enabled)

    # Compatibility fields may still arrive from the current Control Center,
    # but the locked risk authority values cannot be overridden.
    if risk_per_trade is not None:
        if risk_per_trade <= 0 or risk_per_trade > 0.05:
            raise ValueError("Legacy risk percentage must be greater than 0 and no more than 5%")
        payload["risk_per_trade"] = float(risk_per_trade)

    if leverage_cap is not None and float(leverage_cap) != DEFAULT_RISK_SETTINGS["leverage_cap"]:
        raise ValueError("Global leverage is locked; scalping uses max 20x and intraday uses max 10x")
    if exposure_cap is not None and abs(float(exposure_cap) - 0.50) > 1e-9:
        raise ValueError("Total margin exposure cap is locked at 50%")
    if max_open_trades is not None and int(max_open_trades) != 5:
        raise ValueError("Active trade limit is locked at 5")
    if max_daily_trades is not None and int(max_daily_trades) not in {0, 8}:
        raise ValueError("Daily executable trade count is locked at 8")

    payload.update(
        leverage_cap=DEFAULT_RISK_SETTINGS["leverage_cap"],
        exposure_cap=DEFAULT_RISK_SETTINGS["exposure_cap"],
        max_open_trades=DEFAULT_RISK_SETTINGS["max_open_trades"],
        max_daily_trades=DEFAULT_RISK_SETTINGS["max_daily_trades"],
    )
    return _update_runtime(**payload)


def get_bot_status() -> dict[str, Any]:
    row = _get_runtime_row()
    return _serialize_runtime(row)


def get_risk_settings() -> dict[str, Any]:
    row = _get_runtime_row()
    return {
        "risk_per_trade": row.risk_per_trade,
        "leverage_cap": row.leverage_cap,
        "exposure_cap": row.exposure_cap,
        "max_open_trades": row.max_open_trades,
        "max_daily_trades": row.max_daily_trades,
    }


def can_execute() -> tuple[bool, str]:
    row = _get_runtime_row()
    if row.emergency_stop:
        return False, "Emergency stop is active"
    watchdog_blocked, watchdog_reason = get_watchdog_execution_block()
    if watchdog_blocked:
        return False, f"Runtime watchdog blocked execution: {watchdog_reason or 'critical mismatch'}"
    if _risk_circuit_breaker_active():
        return False, "Daily net realized loss circuit breaker is active"
    if row.bot_status != "running":
        return False, "Bot is not running"
    if not row.auto_trading_enabled:
        return False, "Auto trading is disabled"
    if row.execution_mode == "live" and not is_live_mode_available():
        return False, "Live mode is not unlocked"
    return True, ""


def get_execution_mode() -> str:
    return _get_runtime_row().execution_mode


def is_live_mode_available() -> bool:
    return bool(settings.bybit_live_api_key and settings.bybit_live_api_secret)


def _update_runtime(**updates: Any) -> dict[str, Any]:
    ensure_runtime_config()
    db = SessionLocal()
    try:
        row = db.query(BotRuntimeConfig).filter(BotRuntimeConfig.id == 1).first()
        if row is None:
            row = BotRuntimeConfig(id=1, **DEFAULT_RISK_SETTINGS)
            db.add(row)
            db.flush()

        for key, value in updates.items():
            setattr(row, key, value)
        db.commit()
        db.refresh(row)
        return _serialize_runtime(row)
    finally:
        db.close()


def _get_runtime_row() -> BotRuntimeConfig:
    ensure_runtime_config()
    db = SessionLocal()
    try:
        row = db.query(BotRuntimeConfig).filter(BotRuntimeConfig.id == 1).first()
        if row is None:
            raise RuntimeError("Bot runtime config is unavailable")
        db.expunge(row)
        return row
    finally:
        db.close()


def _serialize_runtime(row: BotRuntimeConfig) -> dict[str, Any]:
    return {
        "status": row.bot_status,
        "emergency_stop": row.emergency_stop,
        "execution_mode": row.execution_mode,
        "auto_trading_enabled": row.auto_trading_enabled,
        "live_mode_available": is_live_mode_available(),
        "risk_model": "dynamic_fixed_usdt",
        "risk_per_trade": row.risk_per_trade,
        "leverage_cap": row.leverage_cap,
        "exposure_cap": row.exposure_cap,
        "max_open_trades": row.max_open_trades,
        "max_active_trades": row.max_open_trades,
        "max_daily_trades": row.max_daily_trades,
        "daily_trade_limit_enabled": True,
    }


def _risk_circuit_breaker_active() -> bool:
    try:
        inspector = inspect(engine)
        if "risk_runtime_state" not in inspector.get_table_names():
            return False
        existing = {column["name"] for column in inspector.get_columns("risk_runtime_state")}
        if "circuit_breaker_active" not in existing:
            return False
        db = SessionLocal()
        try:
            row = db.query(RiskRuntimeState).filter(RiskRuntimeState.id == 1).first()
            return bool(row and row.circuit_breaker_active)
        finally:
            db.close()
    except SQLAlchemyError:
        # Database failures are handled by readiness/watchdog. Do not claim a
        # breaker state that could not be read.
        return False


def _ensure_runtime_columns() -> None:
    inspector = inspect(engine)
    if "bot_runtime_config" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("bot_runtime_config")}
    column_defs = {
        "risk_per_trade": "FLOAT NOT NULL DEFAULT 0.01",
        "leverage_cap": "FLOAT NOT NULL DEFAULT 20.0",
        "exposure_cap": "FLOAT NOT NULL DEFAULT 0.50",
        "max_open_trades": "INTEGER NOT NULL DEFAULT 5",
        "max_daily_trades": "INTEGER NOT NULL DEFAULT 8",
    }
    with engine.begin() as connection:
        for name, definition in column_defs.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE bot_runtime_config ADD COLUMN {name} {definition}"))
