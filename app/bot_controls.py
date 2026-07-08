from typing import Any

from sqlalchemy import inspect, text

from app.config import settings
from app.database import SessionLocal, engine
from app.models import BotRuntimeConfig


DEFAULT_RISK_SETTINGS = {
    "risk_per_trade": 0.01,
    "leverage_cap": 5.0,
    "exposure_cap": 0.30,
    "max_open_trades": 3,
    "max_daily_trades": 8,
}


def ensure_runtime_config() -> None:
    _ensure_runtime_columns()
    db = SessionLocal()
    try:
        row = db.query(BotRuntimeConfig).filter(BotRuntimeConfig.id == 1).first()
        if row is None:
            db.add(
                BotRuntimeConfig(
                    id=1,
                    bot_status="idle",
                    emergency_stop=False,
                    execution_mode="demo",
                    auto_trading_enabled=True,
                    **DEFAULT_RISK_SETTINGS,
                )
            )
            db.commit()
    finally:
        db.close()


def start_bot() -> dict[str, Any]:
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

    if risk_per_trade is not None:
        if risk_per_trade <= 0 or risk_per_trade > 0.05:
            raise ValueError("Risk per trade must be greater than 0 and no more than 5%")
        payload["risk_per_trade"] = float(risk_per_trade)

    if leverage_cap is not None:
        if leverage_cap <= 0 or leverage_cap > 50:
            raise ValueError("Leverage cap must be greater than 0 and no more than 50")
        payload["leverage_cap"] = float(leverage_cap)

    if exposure_cap is not None:
        if exposure_cap <= 0 or exposure_cap > 1:
            raise ValueError("Exposure cap must be greater than 0 and no more than 100%")
        payload["exposure_cap"] = float(exposure_cap)

    if max_open_trades is not None:
        if max_open_trades < 1 or max_open_trades > 25:
            raise ValueError("Max open trades must be between 1 and 25")
        payload["max_open_trades"] = int(max_open_trades)

    if max_daily_trades is not None:
        if max_daily_trades < 1 or max_daily_trades > 100:
            raise ValueError("Max daily trades must be between 1 and 100")
        payload["max_daily_trades"] = int(max_daily_trades)

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
    db = SessionLocal()
    try:
        row = db.query(BotRuntimeConfig).filter(BotRuntimeConfig.id == 1).first()
        if row is None:
            row = BotRuntimeConfig(id=1)
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
        "risk_per_trade": row.risk_per_trade,
        "leverage_cap": row.leverage_cap,
        "exposure_cap": row.exposure_cap,
        "max_open_trades": row.max_open_trades,
        "max_daily_trades": row.max_daily_trades,
    }


def _ensure_runtime_columns() -> None:
    inspector = inspect(engine)
    if "bot_runtime_config" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("bot_runtime_config")}
    column_defs = {
        "risk_per_trade": "FLOAT NOT NULL DEFAULT 0.01",
        "leverage_cap": "FLOAT NOT NULL DEFAULT 5.0",
        "exposure_cap": "FLOAT NOT NULL DEFAULT 0.30",
        "max_open_trades": "INTEGER NOT NULL DEFAULT 3",
        "max_daily_trades": "INTEGER NOT NULL DEFAULT 8",
    }
    with engine.begin() as connection:
        for name, definition in column_defs.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE bot_runtime_config ADD COLUMN {name} {definition}"))
