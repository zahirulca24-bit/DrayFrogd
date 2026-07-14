from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from math import isfinite
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.bot_controls import stop_bot
from app.database import SessionLocal, engine
from app.journal import log_bot_event
from app.models import RiskRuntimeState, TradeJournal
from app.trade_state import CAPACITY_BLOCKING_STATUSES


BDT = ZoneInfo("Asia/Dhaka")
ACTIVE_TRADE_LIMIT = 5
DAILY_EXECUTED_TRADE_LIMIT = 8
BASE_RISK_POOL_RATIO = 0.05
DAILY_NET_LOSS_LIMIT_RATIO = 0.05
CAPITAL_EXPOSURE_CAP = 0.50
LOSS_COOLDOWN_MINUTES = 30
RR_MISMATCH_TOLERANCE = 0.02

RISK_PROFILES: dict[str, dict[str, float]] = {
    "scalping": {
        "risk_amount": 20.0,
        "leverage_cap": 20.0,
        "min_risk_reward": 1.5,
    },
    "intraday": {
        "risk_amount": 50.0,
        "leverage_cap": 10.0,
        "min_risk_reward": 2.0,
    },
}

_risk_lock = Lock()


def validate_trade(signal: dict[str, Any], account_equity: float | None = None) -> dict[str, Any]:
    normalized = _normalize_signal(signal)
    if normalized is None:
        return _reject("Invalid signal payload")

    if normalized["status"] != "active":
        return _reject("Signal is not active")
    if not normalized["symbol"]:
        return _reject("Invalid signal payload")
    if normalized["trade_type"] is None:
        return _reject("trade_type must be scalping or intraday")

    geometry = calculate_authoritative_risk_reward(
        direction=normalized["direction"],
        entry=normalized["entry"],
        stop_loss=normalized["stop_loss"],
        take_profit=normalized["take_profit"],
    )
    if geometry is None:
        return _reject("Invalid direction or entry/stop_loss/take_profit geometry")

    calculated_rr = geometry["risk_reward"]
    supplied_rr = normalized["supplied_risk_reward"]
    if supplied_rr is not None and abs(supplied_rr - calculated_rr) > RR_MISMATCH_TOLERANCE:
        return _reject(
            f"Signal risk_reward mismatch: supplied {supplied_rr:.4f}, authoritative {calculated_rr:.4f}"
        )

    profile = RISK_PROFILES[normalized["trade_type"]]
    if calculated_rr + 1e-9 < profile["min_risk_reward"]:
        return _reject(
            f"Risk reward below {normalized['trade_type']} minimum {profile['min_risk_reward']:.1f}"
        )

    state = refresh_risk_state(account_equity=account_equity)
    if state["circuit_breaker_active"]:
        return _reject(state["circuit_breaker_reason"] or "Daily net realized loss circuit breaker is active")
    if state["day_start_equity"] is None or state["day_start_equity"] <= 0:
        return _reject("Day-start account equity is unavailable")

    symbol = normalized["symbol"]
    cooldown_until = state["symbol_cooldowns"].get(symbol) or state["symbol_cooldowns"].get("*")
    if cooldown_until:
        return _reject(f"{symbol} cooldown active until {cooldown_until}")
    if symbol in state["active_symbols"]:
        return _reject("Symbol already has an active trade")
    if state["active_trade_count"] >= ACTIVE_TRADE_LIMIT:
        return _reject("Active trade limit reached")
    daily_limit = int(state.get("max_trades_per_day") or DAILY_EXECUTED_TRADE_LIMIT)
    if int(state.get("trades_today") or 0) >= daily_limit:
        return _reject("DAILY_TRADE_LIMIT_REACHED")

    new_trade_risk = profile["risk_amount"]
    if new_trade_risk > state["available_risk"] + 1e-9:
        return _reject(
            f"Dynamic risk capacity exceeded: required {new_trade_risk:.2f} USDT, "
            f"available {state['available_risk']:.2f} USDT"
        )

    return {
        "allowed": True,
        "reason": "",
        "trade_type": normalized["trade_type"],
        "risk_amount": new_trade_risk,
        "risk_per_trade": new_trade_risk / state["day_start_equity"],
        "leverage_cap": profile["leverage_cap"],
        "exposure_cap": CAPITAL_EXPOSURE_CAP,
        "min_risk_reward": profile["min_risk_reward"],
        "authoritative_risk_reward": calculated_rr,
        "live_risk": state["live_risk"],
        "base_risk_pool": state["base_risk_pool"],
        "effective_risk_pool": state["effective_risk_pool"],
        "available_risk": state["available_risk"],
        "active_trade_count": state["active_trade_count"],
        "max_active_trades": ACTIVE_TRADE_LIMIT,
        "trades_today": int(state.get("trades_today") or 0),
        "max_daily_trades": daily_limit,
        "reentry_cooldown_minutes": LOSS_COOLDOWN_MINUTES,
    }


def calculate_authoritative_risk_reward(
    *,
    direction: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
) -> dict[str, float] | None:
    values = [entry, stop_loss, take_profit]
    if not all(isfinite(value) and value > 0 for value in values):
        return None

    normalized_direction = str(direction or "").lower().strip()
    if normalized_direction == "long":
        if not stop_loss < entry < take_profit:
            return None
        risk_distance = entry - stop_loss
        reward_distance = take_profit - entry
    elif normalized_direction == "short":
        if not take_profit < entry < stop_loss:
            return None
        risk_distance = stop_loss - entry
        reward_distance = entry - take_profit
    else:
        return None

    if risk_distance <= 0 or reward_distance <= 0:
        return None
    return {
        "risk_distance": risk_distance,
        "reward_distance": reward_distance,
        "risk_reward": reward_distance / risk_distance,
    }


def calculate_trade_live_risk(
    *,
    direction: str,
    entry: float,
    current_stop_loss: float,
    remaining_quantity: float,
) -> float:
    if not all(isfinite(value) for value in [entry, current_stop_loss, remaining_quantity]):
        return 0.0
    if entry <= 0 or current_stop_loss <= 0 or remaining_quantity <= 0:
        return 0.0

    normalized_direction = str(direction or "").lower().strip()
    if normalized_direction == "long":
        risk_distance = max(entry - current_stop_loss, 0.0)
    elif normalized_direction == "short":
        risk_distance = max(current_stop_loss - entry, 0.0)
    else:
        return 0.0
    return risk_distance * remaining_quantity


def calculate_risk_capacity(
    *,
    day_start_equity: float,
    realized_pnl_today: float,
    live_risk: float,
) -> dict[str, float]:
    equity = max(float(day_start_equity or 0.0), 0.0)
    realized = float(realized_pnl_today or 0.0)
    current_live_risk = max(float(live_risk or 0.0), 0.0)
    base_pool = equity * BASE_RISK_POOL_RATIO
    effective_pool = max(base_pool + realized, 0.0)
    available = max(effective_pool - current_live_risk, 0.0)
    return {
        "base_risk_pool": base_pool,
        "effective_risk_pool": effective_pool,
        "available_risk": available,
    }


def refresh_risk_state(
    account_equity: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _as_utc(now)
    current_day = _bdt_day(current)
    observed_equity = _positive_float(account_equity)
    _ensure_risk_runtime_columns()

    breaker_activated = False
    snapshot: dict[str, Any]

    with _risk_lock:
        db = SessionLocal()
        try:
            row = db.query(RiskRuntimeState).filter(RiskRuntimeState.id == 1).first()
            if row is None:
                row = RiskRuntimeState(id=1)
                db.add(row)
                db.flush()

            day_changed = row.trades_day != current_day
            previous_breaker = bool(row.circuit_breaker_active) and not day_changed
            if day_changed:
                row.trades_day = current_day
                row.trades_today = 0
                row.day_start_equity = observed_equity
                row.realized_pnl_today = 0.0
                row.live_risk = 0.0
                row.base_risk_pool = 0.0
                row.effective_risk_pool = 0.0
                row.available_risk = 0.0
                row.circuit_breaker_active = False
                row.circuit_breaker_reason = None
            elif row.day_start_equity is None and observed_equity is not None:
                row.day_start_equity = observed_equity

            cooldowns = _decode_cooldowns(row.symbol_cooldowns)
            cooldowns = {
                symbol: expiry
                for symbol, expiry in cooldowns.items()
                if expiry > current
            }

            journal_rows = db.query(TradeJournal).all()
            active_rows = [item for item in journal_rows if str(item.status or "").lower() != "closed"]
            active_symbols = sorted(
                {
                    str(item.symbol or "").upper().strip()
                    for item in active_rows
                    if str(item.symbol or "").strip()
                }
            )
            active_trade_count = len(active_rows)
            trades_today = sum(
                1
                for item in journal_rows
                if _journal_row_consumes_daily_slot(item, current_day)
            )
            realized_pnl_today = sum(
                _realized_pnl_for_day(item, current_day)
                for item in journal_rows
            )
            live_risk = sum(_journal_row_live_risk(item) for item in active_rows)

            day_start_equity = _positive_float(row.day_start_equity)
            capacity = calculate_risk_capacity(
                day_start_equity=day_start_equity or 0.0,
                realized_pnl_today=realized_pnl_today,
                live_risk=live_risk,
            )
            loss_limit = (day_start_equity or 0.0) * DAILY_NET_LOSS_LIMIT_RATIO
            realized_threshold_hit = bool(
                day_start_equity
                and realized_pnl_today <= -(loss_limit) + 1e-9
            )
            equity_drawdown_today = (
                observed_equity - day_start_equity
                if observed_equity is not None and day_start_equity
                else None
            )
            equity_threshold_hit = bool(
                day_start_equity
                and equity_drawdown_today is not None
                and equity_drawdown_today <= -(loss_limit) + 1e-9
            )
            threshold_hit = realized_threshold_hit or equity_threshold_hit
            circuit_breaker_active = previous_breaker or threshold_hit
            if equity_threshold_hit:
                circuit_reason = (
                    f"Daily account equity drawdown limit reached: {equity_drawdown_today:.2f} USDT "
                    f"<= -{loss_limit:.2f} USDT"
                )
            elif realized_threshold_hit:
                circuit_reason = (
                    f"Daily net realized loss limit reached: {realized_pnl_today:.2f} USDT "
                    f"<= -{loss_limit:.2f} USDT"
                )
            elif circuit_breaker_active:
                circuit_reason = row.circuit_breaker_reason or "Daily loss circuit breaker is active"
            else:
                circuit_reason = None

            row.trades_day = current_day
            row.trades_today = trades_today
            row.active_symbols = json.dumps(active_symbols, separators=(",", ":"))
            row.active_trade_count = active_trade_count
            row.symbol_cooldowns = _encode_cooldowns(cooldowns)
            row.cooldown_until = max(cooldowns.values()) if cooldowns else None
            row.realized_pnl_today = realized_pnl_today
            row.live_risk = live_risk
            row.base_risk_pool = capacity["base_risk_pool"]
            row.effective_risk_pool = capacity["effective_risk_pool"]
            row.available_risk = capacity["available_risk"]
            row.circuit_breaker_active = circuit_breaker_active
            row.circuit_breaker_reason = circuit_reason
            db.commit()

            breaker_activated = circuit_breaker_active and not previous_breaker
            snapshot = {
                "risk_model": "dynamic_fixed_usdt",
                "risk_profiles": {
                    name: dict(profile)
                    for name, profile in RISK_PROFILES.items()
                },
                "risk_per_trade": RISK_PROFILES["scalping"]["risk_amount"] / (day_start_equity or 1.0),
                "leverage_cap": RISK_PROFILES["scalping"]["leverage_cap"],
                "exposure_cap": CAPITAL_EXPOSURE_CAP,
                "max_open_trades": ACTIVE_TRADE_LIMIT,
                "max_active_trades": ACTIVE_TRADE_LIMIT,
                "max_trades_per_day": DAILY_EXECUTED_TRADE_LIMIT,
                "daily_trade_limit_enabled": True,
                "min_risk_reward": RISK_PROFILES["scalping"]["min_risk_reward"],
                "active_symbols": active_symbols,
                "active_trade_count": active_trade_count,
                "trades_today": trades_today,
                "trades_day": current_day,
                "reset_timezone": "Asia/Dhaka",
                "cooldown_minutes": LOSS_COOLDOWN_MINUTES,
                "cooldown_until": row.cooldown_until.isoformat() if row.cooldown_until else None,
                "symbol_cooldowns": {
                    symbol: expiry.isoformat()
                    for symbol, expiry in cooldowns.items()
                },
                "day_start_equity": day_start_equity,
                "current_account_equity": observed_equity,
                "equity_drawdown_today": equity_drawdown_today,
                "realized_pnl_today": realized_pnl_today,
                "daily_net_loss_limit_ratio": DAILY_NET_LOSS_LIMIT_RATIO,
                "daily_net_loss_limit_amount": loss_limit,
                "live_risk": live_risk,
                "base_risk_pool": capacity["base_risk_pool"],
                "effective_risk_pool": capacity["effective_risk_pool"],
                "available_risk": capacity["available_risk"],
                "profit_recycling": "full_net_realized_pnl",
                "circuit_breaker_active": circuit_breaker_active,
                "circuit_breaker_reason": circuit_reason,
            }
        finally:
            db.close()

    if snapshot["circuit_breaker_active"]:
        stop_bot()
    if breaker_activated:
        try:
            log_bot_event(
                "DAILY_NET_LOSS_CIRCUIT_BREAKER",
                snapshot["circuit_breaker_reason"] or "Daily net realized loss circuit breaker activated",
                level="error",
                metadata={
                    "affected_module": "risk",
                    "error_code": "DAILY_NET_LOSS_LIMIT_REACHED",
                    "trades_day": snapshot["trades_day"],
                    "day_start_equity": snapshot["day_start_equity"],
                    "current_account_equity": snapshot.get("current_account_equity"),
                    "equity_drawdown_today": snapshot.get("equity_drawdown_today"),
                    "realized_pnl_today": snapshot["realized_pnl_today"],
                    "loss_limit": snapshot["daily_net_loss_limit_amount"],
                },
            )
        except Exception:
            pass
    return snapshot


def get_risk_state() -> dict[str, Any]:
    return refresh_risk_state()


def restore_risk_state(
    now: datetime | None = None,
    account_equity: float | None = None,
) -> dict[str, Any]:
    return refresh_risk_state(account_equity=account_equity, now=now)


def register_active_trade(symbol: str) -> None:
    # The journal is authoritative. A refresh after reservation/order activation
    # immediately derives the active count and live risk from persisted records.
    refresh_risk_state()


def release_active_trade(symbol: str) -> None:
    refresh_risk_state()


def start_loss_cooldown(
    symbol: str | None = None,
    now: datetime | None = None,
    duration_minutes: int = LOSS_COOLDOWN_MINUTES,
) -> None:
    normalized_symbol = str(symbol or "*").upper().strip() or "*"
    current = _as_utc(now)
    duration = max(int(duration_minutes), 1)
    expiry = current + timedelta(minutes=duration)
    _ensure_risk_runtime_columns()

    with _risk_lock:
        db = SessionLocal()
        try:
            row = db.query(RiskRuntimeState).filter(RiskRuntimeState.id == 1).first()
            if row is None:
                row = RiskRuntimeState(id=1, trades_day=_bdt_day(current))
                db.add(row)
                db.flush()
            cooldowns = _decode_cooldowns(row.symbol_cooldowns)
            existing_expiry = cooldowns.get(normalized_symbol)
            if existing_expiry is None or expiry > existing_expiry:
                cooldowns[normalized_symbol] = expiry
            row.symbol_cooldowns = _encode_cooldowns(cooldowns)
            row.cooldown_until = max(cooldowns.values())
            db.commit()
        finally:
            db.close()


def extract_account_equity(wallet: dict[str, Any] | None) -> float | None:
    if not isinstance(wallet, dict):
        return None
    for key in ("totalEquity", "totalWalletBalance", "totalMarginBalance"):
        value = _positive_float(wallet.get(key))
        if value is not None:
            return value
    return None


def resolve_trade_type(signal: dict[str, Any]) -> str | None:
    explicit = str(signal.get("trade_type") or "").lower().strip()
    if explicit in RISK_PROFILES:
        return explicit
    return None


def _normalize_signal(signal: dict[str, Any]) -> dict[str, Any] | None:
    try:
        direction = str(signal.get("direction", "")).lower().strip()
        supplied_rr_raw = signal.get("risk_reward")
        supplied_rr = float(supplied_rr_raw) if supplied_rr_raw is not None else None
        return {
            "symbol": str(signal.get("symbol", "")).upper().strip(),
            "strategy_name": str(signal.get("strategy_name") or signal.get("strategy") or "unknown").lower().strip(),
            "trade_type": resolve_trade_type(signal),
            "direction": direction,
            "entry": float(signal.get("entry")),
            "stop_loss": float(signal.get("stop_loss")),
            "take_profit": float(signal.get("take_profit")),
            "supplied_risk_reward": supplied_rr,
            "status": str(signal.get("status", "")).lower().strip(),
        }
    except (TypeError, ValueError):
        return None


def _journal_row_live_risk(row: TradeJournal) -> float:
    metadata = _metadata(row.exchange_metadata)
    management = metadata.get("management") if isinstance(metadata.get("management"), dict) else {}
    entry = _number(row.entry_price)
    quantity = _number(management.get("remaining_quantity"))
    if quantity is None:
        quantity = _number(row.quantity)
    current_stop = _number(management.get("trailing_stop"))
    if current_stop is None and bool(management.get("break_even_set")):
        current_stop = entry
    if current_stop is None:
        current_stop = _number(row.stop_loss)
    if entry is None or current_stop is None or quantity is None:
        return 0.0
    return calculate_trade_live_risk(
        direction=row.direction,
        entry=entry,
        current_stop_loss=current_stop,
        remaining_quantity=quantity,
    )


def _journal_row_consumes_daily_slot(row: TradeJournal, expected_day: str) -> bool:
    status = str(row.status or "").lower()
    result = str(row.result or "").lower()
    if status == "closed" and result == "execution_failed":
        return False
    if row.opened_at and _timestamp_is_on_bdt_day(row.opened_at, expected_day):
        return True
    return bool(
        status in CAPACITY_BLOCKING_STATUSES
        and _timestamp_is_on_bdt_day(row.detected_at, expected_day)
    )


def _realized_pnl_for_day(row: TradeJournal, expected_day: str) -> float:
    metadata = _metadata(row.exchange_metadata)
    status = str(row.status or "").lower()

    if status == "closed":
        close_sync = metadata.get("close_sync") if isinstance(metadata.get("close_sync"), dict) else {}
        records = close_sync.get("records") if isinstance(close_sync.get("records"), list) else []
        record_values = [
            _number(record.get("closedPnl"))
            for record in records
            if isinstance(record, dict) and _record_is_on_bdt_day(record, expected_day)
        ]
        exact_values = [value for value in record_values if value is not None]
        if exact_values:
            return sum(exact_values)
        if _timestamp_is_on_bdt_day(row.closed_at or row.updated_at, expected_day):
            return _number(row.realized_pnl) or 0.0
        return 0.0

    progress = metadata.get("risk_realized_progress") if isinstance(metadata.get("risk_realized_progress"), dict) else {}
    pnl_by_day = progress.get("pnl_by_bdt_day") if isinstance(progress.get("pnl_by_bdt_day"), dict) else {}
    return _number(pnl_by_day.get(expected_day)) or 0.0


def _record_is_on_bdt_day(record: dict[str, Any], expected_day: str) -> bool:
    for key in ("updatedTime", "createdTime"):
        try:
            timestamp_ms = int(record.get(key))
        except (TypeError, ValueError):
            continue
        if timestamp_ms > 0:
            value = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
            return _bdt_day(value) == expected_day
    return False


def _ensure_risk_runtime_columns() -> None:
    RiskRuntimeState.__table__.create(bind=engine, checkfirst=True)
    inspector = inspect(engine)
    if "risk_runtime_state" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("risk_runtime_state")}
    column_defs = {
        "active_trade_count": "INTEGER NOT NULL DEFAULT 0",
        "symbol_cooldowns": "TEXT NOT NULL DEFAULT '{}'",
        "day_start_equity": "FLOAT NULL",
        "realized_pnl_today": "FLOAT NOT NULL DEFAULT 0",
        "live_risk": "FLOAT NOT NULL DEFAULT 0",
        "base_risk_pool": "FLOAT NOT NULL DEFAULT 0",
        "effective_risk_pool": "FLOAT NOT NULL DEFAULT 0",
        "available_risk": "FLOAT NOT NULL DEFAULT 0",
        "circuit_breaker_active": "BOOLEAN NOT NULL DEFAULT FALSE",
        "circuit_breaker_reason": "VARCHAR(255) NULL",
    }
    with engine.begin() as connection:
        for name, definition in column_defs.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE risk_runtime_state ADD COLUMN {name} {definition}"))


def _decode_cooldowns(value: str | None) -> dict[str, datetime]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    result: dict[str, datetime] = {}
    for symbol, raw_expiry in parsed.items():
        try:
            expiry = datetime.fromisoformat(str(raw_expiry).replace("Z", "+00:00"))
        except ValueError:
            continue
        result[str(symbol).upper().strip()] = _as_utc(expiry)
    return result


def _encode_cooldowns(cooldowns: dict[str, datetime]) -> str:
    return json.dumps(
        {symbol: _as_utc(expiry).isoformat() for symbol, expiry in cooldowns.items()},
        separators=(",", ":"),
        sort_keys=True,
    )


def _metadata(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _timestamp_is_on_bdt_day(value: Any, expected_day: str) -> bool:
    if not value:
        return False
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return False
    return _bdt_day(parsed) == expected_day


def _bdt_day(value: datetime) -> str:
    return _as_utc(value).astimezone(BDT).date().isoformat()


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _positive_float(value: Any) -> float | None:
    numeric = _number(value)
    return numeric if numeric is not None and numeric > 0 else None


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None


def _reject(reason: str) -> dict[str, Any]:
    return {"allowed": False, "reason": reason}
