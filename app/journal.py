from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import desc, inspect, or_, text
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import SessionLocal, engine
from app.models import BotEvent, TradeJournal


def create_trade_entry(trade: dict[str, Any]) -> dict[str, Any]:
    _ensure_trade_journal_columns()
    journal_id = str(trade.get("journal_id") or _make_journal_id())
    payload = _build_trade_payload(trade, journal_id=journal_id, default_opened_at=True)

    db = SessionLocal()
    try:
        row = db.query(TradeJournal).filter(TradeJournal.journal_id == journal_id).first()
        if row is None:
            row = TradeJournal(**payload)
            db.add(row)
        else:
            for key, value in payload.items():
                setattr(row, key, value)
        db.commit()
    finally:
        db.close()

    _send_supabase("trade_journal", payload, upsert=True)
    return payload


def reserve_trade_execution(trade: dict[str, Any], execution_key: str) -> dict[str, Any]:
    """Atomically reserve one execution key before any exchange order is sent."""
    _ensure_trade_journal_columns()
    normalized_key = str(execution_key or "").strip().lower()
    if not normalized_key:
        raise ValueError("execution_key is required")

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
            return {"reserved": False, "trade": serialize_trade_entry(existing)}

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
            return {"reserved": False, "trade": serialize_trade_entry(existing)}
    finally:
        db.close()

    _send_supabase("trade_journal", payload, upsert=True)
    return {"reserved": True, "trade": payload}


def get_trade_by_execution_key(execution_key: str) -> dict[str, Any] | None:
    _ensure_trade_journal_columns()
    normalized_key = str(execution_key or "").strip().lower()
    if not normalized_key:
        return None

    db = SessionLocal()
    try:
        row = db.query(TradeJournal).filter(TradeJournal.execution_key == normalized_key).first()
        return serialize_trade_entry(row) if row is not None else None
    finally:
        db.close()


def update_trade_entry(journal_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    _ensure_trade_journal_columns()
    db = SessionLocal()
    payload: dict[str, Any] | None = None
    try:
        row = db.query(TradeJournal).filter(TradeJournal.journal_id == journal_id).first()
        if row is None:
            return None

        for key, value in updates.items():
            if hasattr(row, key):
                setattr(row, key, json.dumps(value, separators=(",", ":")) if key == "exchange_metadata" and isinstance(value, dict) else value)
        db.commit()
        payload = serialize_trade_entry(row)
    finally:
        db.close()

    if payload is not None:
        _send_supabase("trade_journal", payload, upsert=True)
    return payload


def append_trade_event(journal_id: str, event_type: str, message: str, metadata: dict[str, Any] | None = None) -> dict[str, Any] | None:
    _ensure_trade_journal_columns()
    db = SessionLocal()
    payload: dict[str, Any] | None = None
    try:
        row = db.query(TradeJournal).filter(TradeJournal.journal_id == journal_id).first()
        if row is None:
            return None

        exchange_metadata: dict[str, Any] = {}
        if row.exchange_metadata:
            try:
                exchange_metadata = json.loads(row.exchange_metadata)
            except json.JSONDecodeError:
                exchange_metadata = {}

        events = list(exchange_metadata.get("trade_events") or [])
        events.append(
            {
                "event_type": event_type,
                "message": message,
                "metadata": metadata or {},
                "created_at": _utc_now_iso(),
            }
        )
        exchange_metadata["trade_events"] = events
        row.exchange_metadata = json.dumps(exchange_metadata, separators=(",", ":"))
        db.commit()
        payload = serialize_trade_entry(row)
    finally:
        db.close()

    if payload is not None:
        _send_supabase("trade_journal", payload, upsert=True)
        log_bot_event(
            event_type,
            message,
            level="warning" if event_type.lower().endswith("failed") else "info",
            metadata={
                "journal_id": journal_id,
                "affected_module": "trade_management",
                "endpoint": "/trade-management/run",
                **(metadata or {}),
            },
        )
    return payload


def get_trade_history(limit: int = 100) -> list[dict[str, Any]]:
    _ensure_trade_journal_columns()
    db = SessionLocal()
    try:
        rows = db.query(TradeJournal).order_by(desc(TradeJournal.id)).limit(limit).all()
        return [serialize_trade_entry(row) for row in rows]
    finally:
        db.close()


def get_closed_trade_history(limit: int = 100) -> list[dict[str, Any]]:
    _ensure_trade_journal_columns()
    db = SessionLocal()
    try:
        rows = db.query(TradeJournal).filter(TradeJournal.status == "closed").order_by(desc(TradeJournal.id)).limit(limit).all()
        return [serialize_trade_entry(row) for row in rows]
    finally:
        db.close()


def get_open_trade_history(limit: int = 100) -> list[dict[str, Any]]:
    _ensure_trade_journal_columns()
    db = SessionLocal()
    try:
        rows = db.query(TradeJournal).filter(TradeJournal.status != "closed").order_by(desc(TradeJournal.id)).limit(limit).all()
        return [serialize_trade_entry(row) for row in rows]
    finally:
        db.close()


def get_bot_events(limit: int = 100) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        rows = db.query(BotEvent).order_by(desc(BotEvent.id)).limit(limit).all()
        return [serialize_bot_event(row) for row in rows]
    finally:
        db.close()


def log_bot_event(event_type: str, message: str, level: str = "info", metadata: dict[str, Any] | None = None) -> None:
    payload = {
        "event_type": event_type,
        "level": level,
        "message": message,
        "event_metadata": json.dumps(metadata or {}, separators=(",", ":")),
        "created_at": _utc_now_iso(),
    }

    db = SessionLocal()
    try:
        db.add(BotEvent(**payload))
        db.commit()
    finally:
        db.close()

    _send_supabase("bot_events", payload, upsert=False)


def serialize_trade_entry(row: TradeJournal) -> dict[str, Any]:
    metadata = {}
    if row.exchange_metadata:
        try:
            metadata = json.loads(row.exchange_metadata)
        except json.JSONDecodeError:
            metadata = {}
    strategy_name = _resolve_strategy_name(row, metadata)

    return {
        "journal_id": row.journal_id,
        "execution_key": row.execution_key,
        "symbol": row.symbol,
        "strategy_name": strategy_name,
        "strategy": strategy_name,
        "direction": row.direction,
        "execution_mode": row.execution_mode,
        "entry": row.entry_price,
        "stop_loss": row.stop_loss,
        "take_profit": row.take_profit,
        "quantity": row.quantity,
        "status": row.status,
        "result": row.result,
        "sl_hit_reason": row.sl_hit_reason,
        "close_reason": row.close_reason,
        "exit_price": row.exit_price,
        "realized_pnl": row.realized_pnl,
        "fees": row.fees,
        "order_id": row.order_id,
        "detected_at": row.detected_at,
        "opened_at": row.opened_at,
        "closed_at": row.closed_at,
        "exchange_metadata": metadata,
    }


def serialize_bot_event(row: BotEvent) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if row.event_metadata:
        try:
            metadata = json.loads(row.event_metadata)
        except json.JSONDecodeError:
            metadata = {}

    return {
        "id": row.id,
        "event_type": row.event_type,
        "level": row.level,
        "message": row.message,
        "metadata": metadata,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _build_trade_payload(trade: dict[str, Any], *, journal_id: str, default_opened_at: bool) -> dict[str, Any]:
    opened_at = trade.get("opened_at")
    if default_opened_at and not opened_at:
        opened_at = _utc_now_iso()

    return {
        "journal_id": journal_id,
        "execution_key": trade.get("execution_key"),
        "symbol": str(trade.get("symbol", "")).upper(),
        "direction": str(trade.get("direction", "")).lower(),
        "execution_mode": str(trade.get("execution_mode", "demo")).lower(),
        "entry_price": float(trade.get("entry", 0)),
        "stop_loss": float(trade.get("stop_loss", 0)),
        "take_profit": float(trade.get("take_profit", 0)),
        "quantity": _optional_float(trade.get("quantity")),
        "strategy_name": _resolve_strategy_name_from_trade(trade),
        "status": str(trade.get("status", "active")),
        "result": trade.get("result"),
        "sl_hit_reason": trade.get("sl_hit_reason"),
        "close_reason": trade.get("close_reason"),
        "exit_price": _optional_float(trade.get("exit_price")),
        "realized_pnl": _optional_float(trade.get("realized_pnl")),
        "fees": _optional_float(trade.get("fees")),
        "order_id": trade.get("order_id"),
        "detected_at": trade.get("detected_at"),
        "opened_at": opened_at,
        "closed_at": trade.get("closed_at"),
        "exchange_metadata": json.dumps(trade.get("exchange_metadata") or {}, separators=(",", ":")),
    }


def _send_supabase(table: str, payload: dict[str, Any], upsert: bool) -> None:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return

    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/{table}"
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates" if upsert else "return=minimal",
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=10):
            pass
    except (HTTPError, URLError, TimeoutError):
        return


def _make_journal_id() -> str:
    return f"jrnl-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex[:8]}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _resolve_strategy_name_from_trade(trade: dict[str, Any]) -> str:
    raw_strategy = trade.get("strategy_name") or trade.get("strategy")
    if raw_strategy is None:
        return "unknown"
    strategy_name = str(raw_strategy).strip()
    return strategy_name or "unknown"


def _resolve_strategy_name(row: TradeJournal, metadata: dict[str, Any]) -> str:
    raw_strategy = row.strategy_name or metadata.get("strategy_name") or metadata.get("strategy")
    if raw_strategy is None:
        return "unknown"
    strategy_name = str(raw_strategy).strip()
    return strategy_name or "unknown"


def _ensure_trade_journal_columns() -> None:
    inspector = inspect(engine)
    if "trade_journal" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("trade_journal")}
    column_defs = {
        "execution_key": "VARCHAR(64) NULL",
        "strategy_name": "VARCHAR(64) NULL",
        "close_reason": "VARCHAR(64) NULL",
        "exit_price": "FLOAT NULL",
        "realized_pnl": "FLOAT NULL",
        "fees": "FLOAT NULL",
    }
    with engine.begin() as connection:
        for name, definition in column_defs.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE trade_journal ADD COLUMN {name} {definition}"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_trade_journal_execution_key ON trade_journal (execution_key)"))
