from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import desc

from app.config import settings
from app.database import SessionLocal
from app.models import BotEvent, TradeJournal


def create_trade_entry(trade: dict[str, Any]) -> dict[str, Any]:
    journal_id = str(trade.get("journal_id") or _make_journal_id())
    payload = {
        "journal_id": journal_id,
        "symbol": str(trade.get("symbol", "")).upper(),
        "direction": str(trade.get("direction", "")).lower(),
        "execution_mode": str(trade.get("execution_mode", "demo")).lower(),
        "entry_price": float(trade.get("entry", 0)),
        "stop_loss": float(trade.get("stop_loss", 0)),
        "take_profit": float(trade.get("take_profit", 0)),
        "quantity": _optional_float(trade.get("quantity")),
        "status": str(trade.get("status", "active")),
        "result": trade.get("result"),
        "sl_hit_reason": trade.get("sl_hit_reason"),
        "order_id": trade.get("order_id"),
        "detected_at": trade.get("detected_at"),
        "opened_at": trade.get("opened_at") or _utc_now_iso(),
        "closed_at": trade.get("closed_at"),
        "exchange_metadata": json.dumps(trade.get("exchange_metadata") or {}, separators=(",", ":")),
    }

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


def update_trade_entry(journal_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
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
    db = SessionLocal()
    try:
        rows = db.query(TradeJournal).order_by(desc(TradeJournal.id)).limit(limit).all()
        return [serialize_trade_entry(row) for row in rows]
    finally:
        db.close()


def get_closed_trade_history(limit: int = 100) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        rows = (
            db.query(TradeJournal)
            .filter(TradeJournal.status == "closed")
            .order_by(desc(TradeJournal.id))
            .limit(limit)
            .all()
        )
        return [serialize_trade_entry(row) for row in rows]
    finally:
        db.close()


def get_open_trade_history(limit: int = 100) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        rows = (
            db.query(TradeJournal)
            .filter(TradeJournal.status != "closed")
            .order_by(desc(TradeJournal.id))
            .limit(limit)
            .all()
        )
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

    return {
        "journal_id": row.journal_id,
        "symbol": row.symbol,
        "direction": row.direction,
        "execution_mode": row.execution_mode,
        "entry": row.entry_price,
        "stop_loss": row.stop_loss,
        "take_profit": row.take_profit,
        "quantity": row.quantity,
        "status": row.status,
        "result": row.result,
        "sl_hit_reason": row.sl_hit_reason,
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
        # Supabase journaling is best-effort only.
        return


def _make_journal_id() -> str:
    return f"jrnl-{int(datetime.now(UTC).timestamp() * 1000)}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
