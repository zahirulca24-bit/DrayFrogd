from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Callable

_INSTALLED = False
_ORIGINAL_UPDATE_TRADE_ENTRY: Callable[..., dict[str, Any] | None] | None = None

_FALLBACK_STRATEGIES = {"", "unknown", "exchange_backfill"}
_NESTED_IDENTITY_KEYS = {
    "fill_confirmation",
    "order_response",
    "management",
    "native_profit_orders",
    "manual_close",
    "exchange_identity",
    "position_snapshot",
}


def install() -> None:
    """Preserve existing Journal identity when exchange lifecycle backfill closes a row.

    ``exchange_journal_backfill`` reconstructs authoritative close evidence from the
    Bybit transaction log. When it matches an existing Journal reservation, the
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
        return _preserving_update(backfill, original, journal_id, updates)

    backfill.update_trade_entry = _update_trade_entry_preserving_identity
    backfill._P0_1E_IDENTITY_PRESERVATION_INSTALLED = True
    _INSTALLED = True


def _preserving_update(
    backfill: Any,
    original: Callable[[str, dict[str, Any]], dict[str, Any] | None],
    journal_id: str,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    existing = _find_existing_row(backfill, journal_id)
    if existing is None:
        # Backfill updates only target rows already matched from Journal history.
        # If that row cannot be re-read, fail closed instead of risking identity loss.
        return None
    return original(journal_id, merge_backfill_updates(existing, updates))


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

        for key in _NESTED_IDENTITY_KEYS:
            existing_value = existing_metadata.get(key)
            incoming_value = incoming_metadata.get(key)
            if isinstance(existing_value, dict) and isinstance(incoming_value, dict):
                combined_metadata[key] = _merge_evidence_dict(existing_value, incoming_value)
            elif key in existing_metadata and not isinstance(incoming_value, dict):
                # Identity containers are dictionaries. Ignore malformed/null incoming
                # values instead of deleting accepted-order or execution evidence.
                combined_metadata[key] = existing_value

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
            combined_metadata["close_sync"] = _merge_close_sync(
                existing_close_sync,
                incoming_close_sync,
            )

        original_source = existing_metadata.get("source")
        backfill_source = incoming_metadata.get("source")
        if original_source:
            combined_metadata["source"] = original_source
        if backfill_source and backfill_source != original_source:
            combined_metadata["backfill_source"] = backfill_source
        if original_source and backfill_source and original_source != backfill_source:
            combined_metadata["original_source"] = original_source

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


def _merge_close_sync(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    merged = _merge_evidence_dict(existing, incoming)
    if str(existing.get("identity_match") or "").lower() == "exact":
        merged["identity_match"] = "exact"

    records = merged.get("records")
    record_keys = merged.get("record_keys")
    if isinstance(records, list):
        merged["record_count"] = len(records)
    elif isinstance(record_keys, list):
        merged["record_count"] = len(record_keys)
    return merged


def _merge_evidence_dict(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(existing)
    for key, incoming_value in incoming.items():
        existing_value = merged.get(key)
        if isinstance(existing_value, dict) and isinstance(incoming_value, dict):
            merged[key] = _merge_evidence_dict(existing_value, incoming_value)
        elif isinstance(existing_value, list) and isinstance(incoming_value, list):
            merged[key] = _merge_lists(existing_value, incoming_value)
        else:
            merged[key] = incoming_value
    return merged


def _merge_lists(existing: list[Any], incoming: list[Any]) -> list[Any]:
    merged: list[Any] = []
    seen: set[str] = set()
    for item in [*existing, *incoming]:
        key = _stable_item_key(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _stable_item_key(value: Any) -> str:
    if isinstance(value, dict):
        for field in (
            "record_key",
            "exec_id",
            "execId",
            "transaction_id",
            "transactionId",
            "id",
        ):
            identity = str(value.get(field) or "").strip()
            if identity:
                return f"{field}:{identity}"
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return repr(value)


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
