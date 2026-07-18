from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.database import Base, DATABASE_URL, SessionLocal, check_database_connection, engine
from app.models import BotRuntimeConfig, TradeJournal
from app.trade_state import is_exchange_active_status

BDT = ZoneInfo("Asia/Dhaka")
_INSTALLED = False
_CANONICAL_LEGACY_RISK = 0.01


class ConfigAuthorityState(Base):
    __tablename__ = "config_authority_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="bootstrap", nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


def install() -> None:
    """Install one config/durability/performance authority without changing strategy rules."""

    global _INSTALLED
    if _INSTALLED:
        return

    import app.bot_controls as bot_controls
    import app.metrics as metrics
    import app.readiness as readiness
    import app.strategy_audit as strategy_audit

    original_ensure_runtime_config = bot_controls.ensure_runtime_config
    original_update_bot_config = bot_controls.update_bot_config
    original_get_bot_status = bot_controls.get_bot_status
    original_get_risk_settings = bot_controls.get_risk_settings
    original_can_execute = bot_controls.can_execute
    original_readiness = readiness.get_readiness_status
    original_metrics = metrics.get_metrics
    original_strategy_audit_builder = strategy_audit.build_strategy_audit

    def ensure_runtime_config() -> None:
        original_ensure_runtime_config()
        _normalize_legacy_config_row()
        _ensure_authority_state()

    def update_bot_config(
        execution_mode: str | None = None,
        auto_trading_enabled: bool | None = None,
        risk_per_trade: float | None = None,
        leverage_cap: float | None = None,
        exposure_cap: float | None = None,
        max_open_trades: int | None = None,
        max_daily_trades: int | None = None,
    ) -> dict[str, Any]:
        if risk_per_trade is not None and abs(float(risk_per_trade) - _CANONICAL_LEGACY_RISK) > 1e-12:
            raise ValueError(
                "Risk percentage is read-only compatibility data; authoritative risk is fixed by profile "
                "(20 USDT scalping / 50 USDT intraday)."
            )

        result = original_update_bot_config(
            execution_mode=execution_mode,
            auto_trading_enabled=auto_trading_enabled,
            risk_per_trade=_CANONICAL_LEGACY_RISK if risk_per_trade is not None else None,
            leverage_cap=leverage_cap,
            exposure_cap=exposure_cap,
            max_open_trades=max_open_trades,
            max_daily_trades=max_daily_trades,
        )
        if any(
            value is not None
            for value in (
                execution_mode,
                auto_trading_enabled,
                risk_per_trade,
                leverage_cap,
                exposure_cap,
                max_open_trades,
                max_daily_trades,
            )
        ):
            _bump_authority_state("bot_config_api")
        return normalize_config_payload(result)

    def get_bot_status() -> dict[str, Any]:
        return normalize_config_payload(original_get_bot_status())

    def get_risk_settings() -> dict[str, Any]:
        return normalize_config_payload(original_get_risk_settings())

    def can_execute() -> tuple[bool, str]:
        allowed, reason = original_can_execute()
        if not allowed:
            return allowed, reason
        durability = database_durability_status()
        if not durability["execution_safe"]:
            return False, str(durability["reason"] or "Durable primary storage is not proven")
        return True, ""

    def readiness_with_durability() -> dict[str, Any]:
        payload = dict(original_readiness())
        durability = database_durability_status()
        persistence = dict(payload.get("persistence") or {})
        local = dict(persistence.get("local_journal_storage") or {})
        local.update(
            configured=durability["configured"],
            backend=durability["backend"],
            target="trade_journal / bot_events / risk_runtime_state / bot_runtime_config",
            durability_mode=durability["durability_mode"],
            execution_safe=durability["execution_safe"],
            connection_ok=durability["connection_ok"],
            schema_revision=durability["schema_revision"],
            reason=durability["reason"],
            primary=True,
        )
        persistence["local_journal_storage"] = local
        external = dict(persistence.get("external_audit_sink") or {})
        external["role"] = "secondary_audit_only"
        persistence["external_audit_sink"] = external
        payload["persistence"] = persistence
        checks = dict(payload.get("checks") or {})
        checks["durable_primary_storage"] = bool(durability["execution_safe"])
        payload["checks"] = checks
        errors = dict(payload.get("errors") or {})
        errors["storage"] = None if durability["execution_safe"] else durability["reason"]
        payload["errors"] = errors
        payload["ready_for_execution"] = bool(payload.get("ready_for_execution")) and bool(durability["execution_safe"])
        payload["config_authority"] = config_authority_snapshot()
        return payload

    def metrics_with_truth(*args: Any, **kwargs: Any) -> dict[str, Any]:
        payload = dict(original_metrics(*args, **kwargs))
        wins = int(payload.get("win_trades") or 0)
        losses = int(payload.get("loss_trades") or 0)
        known = wins + losses
        payload.update(
            performance_metric_source="financially_reconciled_terminal_outcomes",
            win_rate_denominator=known,
            win_rate_status="available" if known > 0 else "insufficient_data",
            unknown_outcomes_excluded=True,
            realized_r_status="unavailable_without_exact_realized_r_evidence",
        )
        # Legacy synthetic (wins*2-losses) R is not financially authoritative.
        payload["pnl_r"] = None
        return payload

    def build_strategy_audit_with_truth(*args: Any, **kwargs: Any) -> dict[str, Any]:
        payload = original_strategy_audit_builder(*args, **kwargs)
        if not isinstance(payload, dict):
            return payload
        summary = dict(payload.get("summary") or {})
        wins = int(summary.get("wins") or 0)
        losses = int(summary.get("losses") or 0)
        summary.update(
            win_rate_denominator=wins + losses,
            unknown_outcomes_excluded=True,
            metric_source="bybit_ledger_or_exact_journal_identity",
        )
        payload["summary"] = summary
        strategies = []
        for item in payload.get("strategies") or []:
            row = dict(item)
            row_wins = int(row.get("wins") or 0)
            row_losses = int(row.get("losses") or 0)
            row.update(
                win_rate_denominator=row_wins + row_losses,
                unknown_outcomes_excluded=True,
                metric_source="bybit_ledger_or_exact_journal_identity",
            )
            strategies.append(row)
        payload["strategies"] = strategies
        return payload

    bot_controls.ensure_runtime_config = ensure_runtime_config
    bot_controls.update_bot_config = update_bot_config
    bot_controls.get_bot_status = get_bot_status
    bot_controls.get_risk_settings = get_risk_settings
    bot_controls.can_execute = can_execute
    readiness.get_readiness_status = readiness_with_durability
    metrics.get_metrics = metrics_with_truth
    strategy_audit.build_strategy_audit = build_strategy_audit_with_truth

    _INSTALLED = True


def database_durability_status() -> dict[str, Any]:
    backend = "postgresql" if DATABASE_URL.startswith("postgresql+") else "sqlite"
    environment = str(settings.app_env or "development").strip().lower()
    connection_ok = True
    connection_error: str | None = None
    try:
        check_database_connection()
    except Exception as exc:  # pragma: no cover - runtime infrastructure path
        connection_ok = False
        connection_error = str(exc)

    if backend == "postgresql":
        durability_mode = "managed_postgresql"
        durable = True
    elif environment == "production":
        durability_mode = "ephemeral_or_unverified_sqlite"
        durable = False
    else:
        durability_mode = "local_development_sqlite"
        durable = True

    execution_safe = bool(connection_ok and durable)
    reason = connection_error
    if connection_ok and not durable:
        reason = "Production execution requires PostgreSQL or separately verified persistent primary storage"

    return {
        "configured": bool(DATABASE_URL),
        "backend": backend,
        "environment": environment,
        "durability_mode": durability_mode,
        "connection_ok": connection_ok,
        "execution_safe": execution_safe,
        "schema_revision": "sqlalchemy_metadata_create_all",
        "reason": reason,
    }


def normalize_config_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    authority = config_authority_snapshot()
    try:
        from app.risk import RISK_PROFILES

        profiles = {name: dict(profile) for name, profile in RISK_PROFILES.items()}
    except Exception:
        profiles = {
            "scalping": {"risk_amount": 20.0, "leverage_cap": 20.0, "min_risk_reward": 1.5},
            "intraday": {"risk_amount": 50.0, "leverage_cap": 10.0, "min_risk_reward": 2.0},
        }

    result.update(
        risk_model="profile_fixed_usdt",
        risk_profiles=profiles,
        risk_per_trade=_CANONICAL_LEGACY_RISK,
        risk_per_trade_read_only=True,
        risk_per_trade_authority="profile_fixed_usdt",
        max_daily_trades=0,
        daily_trade_limit_enabled=False,
        config_authority=authority,
        trade_counts=_trade_count_snapshot(),
    )
    return result


def config_authority_snapshot() -> dict[str, Any]:
    row = _ensure_authority_state()
    return {
        "version": int(row.version),
        "source": str(row.source),
        "effective_at": row.effective_at.isoformat() if row.effective_at else None,
        "authority": "backend_bot_runtime_config_v2",
    }


def _ensure_authority_state() -> ConfigAuthorityState:
    ConfigAuthorityState.__table__.create(bind=engine, checkfirst=True)
    db = SessionLocal()
    try:
        row = db.query(ConfigAuthorityState).filter(ConfigAuthorityState.id == 1).first()
        if row is None:
            row = ConfigAuthorityState(id=1, version=1, source="bootstrap", effective_at=datetime.now(UTC))
            db.add(row)
            db.commit()
            db.refresh(row)
        db.expunge(row)
        return row
    finally:
        db.close()


def _bump_authority_state(source: str) -> ConfigAuthorityState:
    ConfigAuthorityState.__table__.create(bind=engine, checkfirst=True)
    db = SessionLocal()
    try:
        row = db.query(ConfigAuthorityState).filter(ConfigAuthorityState.id == 1).first()
        if row is None:
            row = ConfigAuthorityState(id=1, version=1, source=source, effective_at=datetime.now(UTC))
            db.add(row)
        else:
            row.version = int(row.version or 0) + 1
            row.source = source
            row.effective_at = datetime.now(UTC)
        db.commit()
        db.refresh(row)
        db.expunge(row)
        return row
    finally:
        db.close()


def _normalize_legacy_config_row() -> None:
    db = SessionLocal()
    try:
        row = db.query(BotRuntimeConfig).filter(BotRuntimeConfig.id == 1).first()
        if row is not None and abs(float(row.risk_per_trade or 0.0) - _CANONICAL_LEGACY_RISK) > 1e-12:
            row.risk_per_trade = _CANONICAL_LEGACY_RISK
            db.commit()
    finally:
        db.close()


def _trade_count_snapshot(now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    target_day = current.astimezone(BDT).date().isoformat()
    db = SessionLocal()
    try:
        rows = db.query(TradeJournal).all()
    finally:
        db.close()

    day_rows = [row for row in rows if _row_is_on_bdt_day(row, target_day)]
    return {
        "date": target_day,
        "timezone": "Asia/Dhaka",
        "configured_limit": 0,
        "limit_enabled": False,
        "attempted": len(day_rows),
        "orders_accepted": sum(1 for row in day_rows if str(row.order_id or "").strip()),
        "positions_opened": sum(1 for row in day_rows if _timestamp_is_day(row.opened_at, target_day)),
        "active_now": sum(1 for row in rows if is_exchange_active_status(row.status)),
    }


def _row_is_on_bdt_day(row: TradeJournal, target_day: str) -> bool:
    if _timestamp_is_day(row.detected_at, target_day) or _timestamp_is_day(row.opened_at, target_day):
        return True
    created_at = row.created_at
    if created_at is None:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return created_at.astimezone(BDT).date().isoformat() == target_day


def _timestamp_is_day(value: Any, target_day: str) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(BDT).date().isoformat() == target_day
