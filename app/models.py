from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    token_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class BotRuntimeConfig(Base):
    __tablename__ = "bot_runtime_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    bot_status: Mapped[str] = mapped_column(String(32), default="idle", nullable=False)
    emergency_stop: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(16), default="demo", nullable=False)
    auto_trading_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    risk_per_trade: Mapped[float] = mapped_column(Float, default=0.01, nullable=False)
    leverage_cap: Mapped[float] = mapped_column(Float, default=20.0, nullable=False)
    exposure_cap: Mapped[float] = mapped_column(Float, default=0.50, nullable=False)
    max_open_trades: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    max_daily_trades: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class RiskRuntimeState(Base):
    __tablename__ = "risk_runtime_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    trades_day: Mapped[str | None] = mapped_column(String(10), nullable=True)
    trades_today: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_symbols: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    active_trade_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    symbol_cooldowns: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    day_start_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl_today: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    live_risk: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    base_risk_pool: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    effective_risk_pool: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    available_risk: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    circuit_breaker_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    circuit_breaker_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class WatchdogRuntimeState(Base):
    __tablename__ = "watchdog_runtime_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    action_mode: Mapped[str] = mapped_column(String(24), default="safe_stop", nullable=False)
    mismatch_tolerance_cycles: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    exposure_tolerance_ratio: Mapped[float] = mapped_column(Float, default=0.01, nullable=False)
    pnl_tolerance: Mapped[float] = mapped_column(Float, default=0.10, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="UNINITIALIZED", nullable=False)
    execution_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reasons_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    consecutive_mismatch_cycles: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_snapshot_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class TradeJournal(Base):
    __tablename__ = "trade_journal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    journal_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    execution_key: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    take_profit: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    strategy_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sl_hit_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    fees: Mapped[float | None] = mapped_column(Float, nullable=True)
    order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detected_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    opened_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    closed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exchange_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class BotEvent(Base):
    __tablename__ = "bot_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    event_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
