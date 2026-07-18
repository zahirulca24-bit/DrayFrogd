from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import wraps
from typing import Any, Callable

from sqlalchemy import desc

from app.database import SessionLocal
from app.models import BotEvent

_INSTALLED = False
_ORIGINAL_LOG: Callable[..., None] | None = None
_DEDUPE_ERROR_CODE = "SYMBOL_ALREADY_ACTIVE"


def install() -> None:
    """Keep expected same-symbol protection auditable without incident-log flooding."""

    global _INSTALLED, _ORIGINAL_LOG
    if _INSTALLED:
        return

    import app.journal as journal

    original = journal.log_bot_event
    _ORIGINAL_LOG = original

    @wraps(original)
    def policy_log_bot_event(
        event_type: str,
        message: str,
        level: str = "info",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        meta = dict(metadata or {})
        error_code = _resolve_error_code(meta)
        if str(event_type or "").lower() in {"auto_execution_failed", "trade_execution_blocked"} and error_code == _DEDUPE_ERROR_CODE:
            _record_or_increment_active_symbol_skip(original, message=message, metadata=meta)
            return
        original(event_type, message, level=level, metadata=meta)

    journal.log_bot_event = policy_log_bot_event

    # batch1 imports background_worker during package initialization, so rebind its
    # module-level reference as well as future imports from app.journal.
    try:
        import app.background_worker as background_worker

        background_worker.log_bot_event = policy_log_bot_event
    except Exception:
        pass

    _INSTALLED = True


def _record_or_increment_active_symbol_skip(
    original_log: Callable[..., None],
    *,
    message: str,
    metadata: dict[str, Any],
) -> None:
    symbol = _resolve_symbol(metadata)
    signal_identity = _resolve_signal_identity(metadata)
    fingerprint = f"{_DEDUPE_ERROR_CODE}|{symbol}|{signal_identity}"
    now = datetime.now(UTC)

    db = SessionLocal()
    try:
        rows = (
            db.query(BotEvent)
            .filter(BotEvent.event_type == "trade_execution_blocked")
            .order_by(desc(BotEvent.id))
            .limit(100)
            .all()
        )
        for row in rows:
            existing = _metadata(row.event_metadata)
            if existing.get("skip_fingerprint") != fingerprint:
                continue
            existing["skip_count"] = min(int(existing.get("skip_count") or 1) + 1, 1_000_000)
            existing["last_seen_at"] = now.isoformat()
            existing["error_code"] = _DEDUPE_ERROR_CODE
            existing["execution_blocked"] = True
            row.event_metadata = json.dumps(existing, separators=(",", ":"))
            row.level = "info"
            row.message = f"Execution guard skipped {symbol or 'symbol'} (same active position)"
            db.commit()
            return
    finally:
        db.close()

    first = {
        **metadata,
        "error_code": _DEDUPE_ERROR_CODE,
        "execution_blocked": True,
        "expected_guard_skip": True,
        "skip_fingerprint": fingerprint,
        "skip_count": 1,
        "first_seen_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
    }
    original_log(
        "trade_execution_blocked",
        f"Execution guard skipped {symbol or 'symbol'} (same active position)",
        level="info",
        metadata=first,
    )


def _resolve_error_code(metadata: dict[str, Any]) -> str:
    outcome = metadata.get("outcome") if isinstance(metadata.get("outcome"), dict) else {}
    for value in (
        outcome.get("error"),
        metadata.get("error_code"),
        metadata.get("error"),
    ):
        normalized = str(value or "").strip().upper().replace(" ", "_")
        if normalized == "SYMBOL_ALREADY_HAS_AN_ACTIVE_TRADE":
            return _DEDUPE_ERROR_CODE
        if normalized:
            return normalized
    return ""


def _resolve_symbol(metadata: dict[str, Any]) -> str:
    signal = metadata.get("signal") if isinstance(metadata.get("signal"), dict) else {}
    outcome = metadata.get("outcome") if isinstance(metadata.get("outcome"), dict) else {}
    trade = outcome.get("trade") if isinstance(outcome.get("trade"), dict) else {}
    return str(signal.get("symbol") or trade.get("symbol") or metadata.get("symbol") or "").upper().strip()


def _resolve_signal_identity(metadata: dict[str, Any]) -> str:
    signal = metadata.get("signal") if isinstance(metadata.get("signal"), dict) else {}
    explicit = str(signal.get("signal_key") or "").strip()
    if explicit:
        return explicit
    return "|".join(
        [
            str(signal.get("strategy_name") or signal.get("strategy") or ""),
            str(signal.get("direction") or ""),
            str(signal.get("detected_at") or ""),
            str(signal.get("entry") or ""),
        ]
    )


def _metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}
