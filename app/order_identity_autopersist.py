from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import wraps
from typing import Any, Callable

from app.database import SessionLocal
from app.journal import append_trade_event, log_bot_event
from app.models import TradeJournal

_INSTALLED = False
_ORIGINAL_PLACE_MARKET_ORDER: Callable[..., dict[str, Any]] | None = None


def install() -> None:
    """Install an idempotent accepted-order identity persistence hook.

    The authoritative execution service imports _place_market_order from
    app.execution_core. We patch that core function before execution_service is
    imported so every accepted exchange order is persisted to the reserved
    Journal row immediately, before fill confirmation/protection work begins.
    """

    global _INSTALLED, _ORIGINAL_PLACE_MARKET_ORDER
    if _INSTALLED:
        return

    import app.execution_core as execution_core

    original = execution_core._place_market_order
    _ORIGINAL_PLACE_MARKET_ORDER = original

    @wraps(original)
    def wrapped_place_market_order(client: Any, *, symbol: str, side: str, qty: str, order_link_id: str) -> dict[str, Any]:
        order_result = original(client, symbol=symbol, side=side, qty=qty, order_link_id=order_link_id)
        _persist_accepted_order_identity(
            symbol=symbol,
            order_link_id=order_link_id,
            order_result=order_result if isinstance(order_result, dict) else {},
        )
        return order_result

    execution_core._place_market_order = wrapped_place_market_order
    _INSTALLED = True


def _persist_accepted_order_identity(*, symbol: str, order_link_id: str, order_result: dict[str, Any]) -> None:
    order_id = str(order_result.get("orderId") or order_result.get("order_id") or "").strip()
    link_id = str(order_result.get("orderLinkId") or order_result.get("order_link_id") or order_link_id or "").strip()
    if not order_id and not link_id:
        return

    submitted_at = datetime.now(UTC).isoformat()
    db = SessionLocal()
    row: TradeJournal | None = None
    try:
        query = db.query(TradeJournal).filter(TradeJournal.symbol == str(symbol or "").upper())
        if link_id:
            row = query.filter(TradeJournal.exchange_metadata.like(f'%"{link_id}"%')).order_by(TradeJournal.id.desc()).first()
        if row is None and order_id:
            row = query.filter(TradeJournal.order_id == order_id).order_by(TradeJournal.id.desc()).first()
        if row is None:
            _safe_log_identity_issue(
                "ORDER_IDENTITY_ROW_NOT_FOUND",
                "Accepted exchange order could not be matched to a reserved Journal row.",
                symbol=symbol,
                order_id=order_id,
                order_link_id=link_id,
            )
            return

        metadata = _decode_metadata(row.exchange_metadata)
        metadata.update(
            {
                "order_response": order_result,
                "order_id": order_id or row.order_id,
                "order_link_id": link_id or metadata.get("order_link_id"),
                "order_identity_persisted_at": submitted_at,
                "order_identity_source": "accepted_order_response",
            }
        )
        if order_id:
            row.order_id = order_id
        if row.status == "pending_execution":
            row.status = "order_submitted"
        if not row.opened_at:
            row.opened_at = submitted_at
        row.exchange_metadata = json.dumps(metadata, separators=(",", ":"))
        db.commit()
        journal_id = row.journal_id
    except Exception as exc:
        db.rollback()
        _safe_log_identity_issue(
            "ORDER_IDENTITY_PERSIST_FAILED",
            "Accepted exchange order identity could not be persisted before fill confirmation.",
            symbol=symbol,
            order_id=order_id,
            order_link_id=link_id,
            error=str(exc),
        )
        return
    finally:
        db.close()

    try:
        append_trade_event(
            journal_id,
            "ORDER_IDENTITY_PERSISTED",
            "Accepted exchange order identity persisted before fill confirmation.",
            {"symbol": symbol, "order_id": order_id, "order_link_id": link_id, "source": "accepted_order_response"},
        )
    except Exception:
        return


def _decode_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _safe_log_identity_issue(event_type: str, message: str, **metadata: Any) -> None:
    try:
        log_bot_event(event_type, message, level="error", metadata=metadata)
    except Exception:
        return
