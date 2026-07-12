from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

from app.close_fill_sync import _record_time_ms, _safe_fetch_closed_pnl, _timestamp_ms
from app.execution import get_active_trades, update_active_trade
from app.journal import append_trade_event, update_trade_entry


BDT = ZoneInfo("Asia/Dhaka")
FILLED_ORDER_STATUSES = {"filled", "partiallyfilled", "partially_filled"}


def sync_partial_realized_pnl(client: Any, now: datetime | None = None) -> dict[str, Any]:
    """Persist exact Bybit partial-close lifecycle evidence while a runner remains open.

    The exchange closed-PnL endpoint is authoritative for partial realized PnL and
    exact open/close fees.  Cumulative values are written both to journal columns
    (so the Journal and dashboard do not show ``N/A``/zero) and to metadata (so
    BDT-day risk accounting can attribute each close to the correct day).
    """

    current = now or datetime.now(UTC)
    synced: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for trade in get_active_trades():
        metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
        management = trade.get("management") if isinstance(trade.get("management"), dict) else {}
        if not management:
            management = metadata.get("management") if isinstance(metadata.get("management"), dict) else {}
        existing = _existing_progress(metadata)

        symbol = str(trade.get("symbol") or "").upper().strip()
        direction = str(trade.get("direction") or "").lower().strip()
        journal_id = str(trade.get("journal_id") or "").strip()
        opened_ms = _timestamp_ms(trade.get("opened_at") or trade.get("detected_at"))
        initial_quantity = _initial_quantity(trade, management)
        if (
            not symbol
            or direction not in {"long", "short"}
            or not journal_id
            or opened_ms is None
            or initial_quantity is None
        ):
            errors.append({"symbol": symbol or "UNKNOWN", "error": "partial PnL sync prerequisites unavailable"})
            continue

        if not _has_partial_close_evidence(
            trade=trade,
            management=management,
            existing=existing,
            initial_quantity=initial_quantity,
        ):
            continue

        end_ms = int(current.astimezone(UTC).timestamp() * 1000)
        ok, records, error = _safe_fetch_closed_pnl(
            client,
            symbol=symbol,
            start_ms=opened_ms,
            end_ms=end_ms,
        )
        if not ok:
            errors.append({"symbol": symbol, "error": error or "closed PnL query failed"})
            continue

        progress, aggregate_error = _aggregate_progress_with_error(
            symbol=symbol,
            direction=direction,
            initial_quantity=initial_quantity,
            opened_ms=opened_ms,
            records=records,
            synced_at=current,
        )
        if aggregate_error:
            errors.append({"symbol": symbol, "error": aggregate_error})
            continue
        if progress is None:
            continue

        aggregate_changed = _progress_changed(existing, progress)
        columns_stale = _journal_columns_stale(trade, progress)
        if not aggregate_changed and not columns_stale:
            continue

        existing_keys = {str(value) for value in (existing.get("record_keys") or []) if value}
        new_records = [
            record
            for record in progress.get("records", [])
            if str(record.get("record_key") or "") not in existing_keys
        ]
        updated_metadata = {
            **metadata,
            "risk_realized_progress": progress,
            "partial_close_sync": progress,
        }
        journal_updates = {
            "quantity": progress["remaining_quantity"],
            "exit_price": progress["avg_exit_price"],
            "realized_pnl": progress["realized_pnl"],
            "fees": progress["fees"],
            "exchange_metadata": updated_metadata,
        }

        try:
            persisted = update_trade_entry(journal_id, journal_updates)
        except Exception as exc:
            errors.append({"symbol": symbol, "error": f"journal partial PnL persistence failed: {exc}"})
            continue
        if persisted is None:
            errors.append({"symbol": symbol, "error": "journal partial PnL persistence failed: trade not found"})
            continue

        active_updates = {
            **journal_updates,
            "remaining_quantity": progress["remaining_quantity"],
            "management": management,
        }
        update_active_trade(journal_id, active_updates)

        for record in new_records:
            _safe_append_event(
                journal_id,
                "PARTIAL_CLOSE_FILL_SYNCED",
                "Exact Bybit partial-close fill, fees and realized PnL were synchronized.",
                {"symbol": symbol, **record},
            )

        event_type = "PARTIAL_REALIZED_PNL_SYNCED" if aggregate_changed else "PARTIAL_REALIZED_PNL_FIELDS_REPAIRED"
        event_message = (
            "Exact cumulative partial-close PnL and fees were synchronized."
            if aggregate_changed
            else "Journal partial-close PnL and fee columns were repaired from existing exact exchange evidence."
        )
        _safe_append_event(
            journal_id,
            event_type,
            event_message,
            {
                "symbol": symbol,
                "closed_size": progress["closed_size"],
                "remaining_quantity": progress["remaining_quantity"],
                "realized_pnl": progress["realized_pnl"],
                "fees": progress["fees"],
                "new_record_count": len(new_records),
            },
        )
        synced.append({"symbol": symbol, **progress, "journal_columns_repaired": columns_stale})

    return {
        "ok": not errors,
        "synced": synced,
        "synced_count": len(synced),
        "errors": errors,
    }


def _aggregate_progress(
    *,
    symbol: str,
    direction: str,
    initial_quantity: float,
    opened_ms: int,
    records: list[dict[str, Any]],
    synced_at: datetime,
) -> dict[str, Any] | None:
    """Compatibility wrapper used by existing tests/callers."""

    progress, _ = _aggregate_progress_with_error(
        symbol=symbol,
        direction=direction,
        initial_quantity=initial_quantity,
        opened_ms=opened_ms,
        records=records,
        synced_at=synced_at,
    )
    return progress


def _aggregate_progress_with_error(
    *,
    symbol: str,
    direction: str,
    initial_quantity: float,
    opened_ms: int,
    records: list[dict[str, Any]],
    synced_at: datetime,
) -> tuple[dict[str, Any] | None, str | None]:
    expected_side = "Sell" if direction == "long" else "Buy"
    candidates: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for record in records:
        if str(record.get("symbol") or "").upper() != symbol:
            continue
        side = str(record.get("side") or "")
        if side and side != expected_side:
            continue
        event_ms = _record_time_ms(record)
        if event_ms is None or event_ms < opened_ms:
            continue
        size = _number(record.get("closedSize") or record.get("qty"))
        pnl = _number(record.get("closedPnl"))
        exit_price = _number(record.get("avgExitPrice"))
        if size is None or size <= 0 or pnl is None or exit_price is None:
            continue
        if _number(record.get("openFee")) is None or _number(record.get("closeFee")) is None:
            return None, "Bybit partial-close record is missing exact openFee/closeFee fields"
        key = _record_key(record)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        candidates.append(record)

    if not candidates:
        return None, None

    candidates.sort(key=lambda item: _record_time_ms(item) or 0)
    selected: list[dict[str, Any]] = []
    total_size = 0.0
    tolerance = max(initial_quantity * 1e-8, 1e-12)
    for record in candidates:
        size = _number(record.get("closedSize") or record.get("qty")) or 0.0
        if total_size + size > initial_quantity + tolerance:
            continue
        selected.append(record)
        total_size += size

    if total_size <= 0:
        return None, None

    weighted_exit = 0.0
    realized_pnl = 0.0
    fees = 0.0
    pnl_by_bdt_day: dict[str, float] = {}
    fees_by_bdt_day: dict[str, float] = {}
    latest_ms = 0
    order_ids: list[str] = []
    compact_records: list[dict[str, Any]] = []

    for record in selected:
        size = _number(record.get("closedSize") or record.get("qty")) or 0.0
        exit_price = _number(record.get("avgExitPrice")) or 0.0
        pnl = _number(record.get("closedPnl")) or 0.0
        open_fee = abs(_number(record.get("openFee")) or 0.0)
        close_fee = abs(_number(record.get("closeFee")) or 0.0)
        record_fees = open_fee + close_fee
        event_ms = _record_time_ms(record) or 0
        weighted_exit += exit_price * size
        realized_pnl += pnl
        fees += record_fees
        latest_ms = max(latest_ms, event_ms)
        if event_ms:
            day = datetime.fromtimestamp(event_ms / 1000, tz=UTC).astimezone(BDT).date().isoformat()
            pnl_by_bdt_day[day] = pnl_by_bdt_day.get(day, 0.0) + pnl
            fees_by_bdt_day[day] = fees_by_bdt_day.get(day, 0.0) + record_fees
        order_id = str(record.get("orderId") or "").strip()
        if order_id and order_id not in order_ids:
            order_ids.append(order_id)
        compact_records.append(_compact_record(record))

    record_keys = [str(item["record_key"]) for item in compact_records]
    return {
        "source": "bybit_position_closed_pnl_partial",
        "authoritative_pnl_field": "closedPnl",
        "closed_size": total_size,
        "initial_quantity": initial_quantity,
        "remaining_quantity": max(initial_quantity - total_size, 0.0),
        "avg_exit_price": weighted_exit / total_size,
        "realized_pnl": realized_pnl,
        "fees": fees,
        "pnl_by_bdt_day": pnl_by_bdt_day,
        "fees_by_bdt_day": fees_by_bdt_day,
        "record_count": len(selected),
        "record_keys": record_keys,
        "records": compact_records,
        "close_order_ids": order_ids,
        "latest_close_time": datetime.fromtimestamp(latest_ms / 1000, tz=UTC).isoformat() if latest_ms else None,
        "synced_at": synced_at.astimezone(UTC).isoformat(),
    }, None


def _has_partial_close_evidence(
    *,
    trade: dict[str, Any],
    management: dict[str, Any],
    existing: dict[str, Any],
    initial_quantity: float,
) -> bool:
    if existing or management.get("tp1_done") or management.get("tp2_done"):
        return True
    statuses = (
        management.get("tp1_order_status"),
        management.get("tp2_order_status"),
    )
    if any(str(status or "").lower().replace(" ", "") in FILLED_ORDER_STATUSES for status in statuses):
        return True
    remaining = _remaining_quantity(trade, management)
    tolerance = max(initial_quantity * 1e-8, 1e-12)
    return remaining is not None and remaining < initial_quantity - tolerance


def _progress_changed(existing: dict[str, Any], progress: dict[str, Any]) -> bool:
    if not existing:
        return True
    for key in ("closed_size", "remaining_quantity", "avg_exit_price", "realized_pnl", "fees"):
        if not _numbers_equal(existing.get(key), progress.get(key)):
            return True
    existing_keys = {str(value) for value in (existing.get("record_keys") or []) if value}
    progress_keys = {str(value) for value in (progress.get("record_keys") or []) if value}
    if existing_keys != progress_keys:
        return True
    return False


def _journal_columns_stale(trade: dict[str, Any], progress: dict[str, Any]) -> bool:
    return any(
        not _numbers_equal(trade.get(field), progress.get(progress_field))
        for field, progress_field in (
            ("quantity", "remaining_quantity"),
            ("remaining_quantity", "remaining_quantity"),
            ("exit_price", "avg_exit_price"),
            ("realized_pnl", "realized_pnl"),
            ("fees", "fees"),
        )
    )


def _existing_progress(metadata: dict[str, Any]) -> dict[str, Any]:
    partial = metadata.get("partial_close_sync")
    if isinstance(partial, dict):
        return dict(partial)
    legacy = metadata.get("risk_realized_progress")
    return dict(legacy) if isinstance(legacy, dict) else {}


def _remaining_quantity(trade: dict[str, Any], management: dict[str, Any]) -> float | None:
    for value in (
        trade.get("remaining_quantity"),
        trade.get("quantity"),
        management.get("remaining_quantity"),
    ):
        numeric = _number(value)
        if numeric is not None and numeric >= 0:
            return numeric
    return None


def _initial_quantity(trade: dict[str, Any], management: dict[str, Any]) -> float | None:
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    metadata_management = metadata.get("management") if isinstance(metadata.get("management"), dict) else {}
    for value in (
        management.get("initial_quantity"),
        metadata_management.get("initial_quantity"),
        trade.get("initial_quantity"),
        trade.get("quantity"),
    ):
        numeric = _number(value)
        if numeric is not None and numeric > 0:
            return numeric
    return None


def _compact_record(record: dict[str, Any]) -> dict[str, Any]:
    event_ms = _record_time_ms(record)
    open_fee = abs(_number(record.get("openFee")) or 0.0)
    close_fee = abs(_number(record.get("closeFee")) or 0.0)
    return {
        "record_key": _record_key(record),
        "order_id": str(record.get("orderId") or "").strip() or None,
        "symbol": str(record.get("symbol") or "").upper(),
        "side": str(record.get("side") or ""),
        "closed_size": _number(record.get("closedSize") or record.get("qty")) or 0.0,
        "avg_exit_price": _number(record.get("avgExitPrice")) or 0.0,
        "realized_pnl": _number(record.get("closedPnl")) or 0.0,
        "open_fee": open_fee,
        "close_fee": close_fee,
        "fees": open_fee + close_fee,
        "closed_at": datetime.fromtimestamp(event_ms / 1000, tz=UTC).isoformat() if event_ms else None,
    }


def _record_key(record: dict[str, Any]) -> str:
    order_id = str(record.get("orderId") or "").strip()
    if order_id:
        return f"order:{order_id}"
    raw = "|".join(
        str(value or "")
        for value in (
            record.get("symbol"),
            record.get("side"),
            _record_time_ms(record),
            record.get("closedSize") or record.get("qty"),
            record.get("avgExitPrice"),
            record.get("closedPnl"),
        )
    )
    return f"record:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def _numbers_equal(left: Any, right: Any, tolerance: float = 1e-12) -> bool:
    left_number = _number(left)
    right_number = _number(right)
    if left_number is None or right_number is None:
        return left_number is None and right_number is None
    return abs(left_number - right_number) <= tolerance


def _safe_append_event(journal_id: str, event_type: str, message: str, metadata: dict[str, Any]) -> None:
    try:
        append_trade_event(journal_id, event_type, message, metadata)
    except Exception:
        return


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None
