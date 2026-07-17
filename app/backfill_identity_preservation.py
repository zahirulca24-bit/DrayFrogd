from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

_INSTALLED = False
_ORIGINAL_UPDATE_TRADE_ENTRY: Callable[..., dict[str, Any] | None] | None = None

_FALLBACK_STRATEGIES = {"", "unknown", "exchange_backfill"}


def install() -> None:
    """Preserve existing Journal identity when exchange lifecycle backfill closes a row.

    ``exchange_journal_backfill`` reconstructs authoritative close evidence from the
    Bybit transaction log.  When it matches an existing Journal reservation, the
    recovered close payload must enrich that row rather than replacing the original
    strategy and accepted-order/fill identity metadata.
    """

    global _INSTALLED, _ORIGINAL_UPDATE_TRADE_ENTRY
    if _INSTALLED:
        return

    from app import exchange_journal_backfill as backfill

    if getattr(backfill, "_P0_1E_IDENTITY_PRESERVATION_INSTALLED", False):
        _INSTALLED = True
        return

    original = backfill.update_trade_entry
    _ORIGINAL_UPDATE_TRADE_ENTRY = original

    def _update_trade_entry_preserving_identity(
        journal_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        existing = _find_existing_row(backfill, journal_id)
        return original(journal_id, merge_backfill_updates(existing, updates))

    backfill.update_trade_entry = _update_trade_entry_preserving_identity
    backfill._P0_1E_IDENTITY_PRESERVATION_INSTALLED = True
    _INSTALLED = True


def merge_backfill_updates(
    existing_row: dict[str, Any] | None,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Merge authoritative close evidence without deleting pre-existing identity."""

    merged = dict(updates)
    existing = existing_row if isinstance(existing_row, dict) else {}

    existing_metadata = (
        dict(existing.get("exchange_metadata"))
        if isinstance(existing.get("exchange_metadata"), dict)
        else {}
    )
    incoming_metadata = (
        dict(merged.get("exchange_metadata"))
        if isinstance(merged.get("exchange_metadata"), dict)
        else {}
    )

    if existing_metadata or incoming_metadata:
        combined_metadata = {**existing_metadata, **incoming_metadata}

        existing_close_sync = (
            existing_metadata.get("close_sync")
            if isinstance(existing_metadata.get("close_sync"), dict)
            else {}
        )
        incoming_close_sync = (
            incoming_metadata.get("close_sync")
            if isinstance(incoming_metadata.get("close_sync"), dict)
            else {}
        )
        if existing_close_sync or incoming_close_sync:
            combined_metadata["close_sync"] = {
                **existing_close_sync,
                **incoming_close_sync,
            }

        original_source = existing_metadata.get("source")
        backfill_source = incoming_metadata.get("source")
        if original_source and backfill_source and original_source != backfill_source:
            combined_metadata["original_source"] = original_source
            combined_metadata["backfill_source"] = backfill_source

        combined_metadata["backfill_identity_preservation"] = {
            "preserved": bool(existing_metadata),
            "preserved_strategy": _existing_strategy(existing) or None,
            "preserved_at": datetime.now(UTC).isoformat(),
        }
        merged["exchange_metadata"] = combined_metadata

    existing_strategy = _existing_strategy(existing)
    incoming_strategy = str(merged.get("strategy_name") or "").strip().lower()
    if (
        existing_strategy
        and existing_strategy.lower() not in _FALLBACK_STRATEGIES
        and incoming_strategy in _FALLBACK_STRATEGIES
    ):
        merged["strategy_name"] = existing_strategy

    return merged


def _find_existing_row(backfill: Any, journal_id: str) -> dict[str, Any] | None:
    normalized = str(journal_id or "").strip()
    if not normalized:
        return None
    try:
        rows = backfill.get_trade_history(limit=1000)
    except Exception:
        return None
    return next(
        (
            row
            for row in rows
            if isinstance(row, dict)
            and str(row.get("journal_id") or "").strip() == normalized
        ),
        None,
    )


def _existing_strategy(row: dict[str, Any]) -> str:
    return str(row.get("strategy_name") or row.get("strategy") or "").strip()
