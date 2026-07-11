from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

from app.close_fill_sync import _record_time_ms, _safe_fetch_closed_pnl, _timestamp_ms
from app.execution import get_active_trades, update_active_trade
from app.journal import append_trade_event, update_trade_entry


BDT = ZoneInfo("Asia/Dhaka")


def sync_partial_realized_pnl(client: Any, now: datetime | None = None) -> dict[str, Any]:
    """Persist exact Bybit partial-close PnL while a runner remains active.

    A TP1/TP2 close creates realized PnL before the entire position disappears.
    This synchronizer records that cumulative exchange evidence by BDT day so
    the risk pool can recycle profit without waiting for the final close.
    """

    current = now or datetime.now(UTC)
    synced: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for trade in get_active_trades():
        metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
        management = trade.get("management") if isinstance(trade.get("management"), dict) else {}
        if not management:
            management = metadata.get("management") if isinstance(metadata.get("management"), dict) else {}
        existing = metadata.get("risk_realized_progress") if isinstance(metadata.get("risk_realized_progress"), dict) else {}

        if not (management.get("tp1_done") or management.get("tp2_done") or existing):
            continue

        symbol = str(trade.get("symbol") or "").upper().strip()
        direction = str(trade.get("direction") or "").lower().strip()
        opened_ms = _timestamp_ms(trade.get("opened_at") or trade.get("detected_at"))
        initial_quantity = _initial_quantity(trade, management)
        if not symbol or direction not in {"long", "short"} or opened_ms is None or initial_quantity is None:
            errors.append({"symbol": symbol or "UNKNOWN", "error": "partial PnL sync prerequisites unavailable"})
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

        progress = _aggregate_progress(
            symbol=symbol,
            direction=direction,
            initial_quantity=initial_quantity,
            opened_ms=opened_ms,
            records=records,
            synced_at=current,
        )
        if progress is None:
            continue

        previous_size = _number(existing.get("closed_size")) or 0.0
        previous_pnl = _number(existing.get("realized_pnl")) or 0.0
        if (
            abs(previous_size - progress["closed_size"]) <= 1e-12
            and abs(previous_pnl - progress["realized_pnl"]) <= 1e-12
        ):
            continue

        updated_metadata = {**metadata, "risk_realized_progress": progress}
        updates = {
            "exchange_metadata": updated_metadata,
            "management": management,
        }
        journal_id = str(trade.get("journal_id") or "")
        update_active_trade(journal_id, updates)
        if journal_id:
            update_trade_entry(journal_id, {"exchange_metadata": updated_metadata})
            append_trade_event(
                journal_id,
                "PARTIAL_REALIZED_PNL_SYNCED",
                "Exact partial-close PnL was synchronized for dynamic risk capacity.",
                {
                    "symbol": symbol,
                    "closed_size": progress["closed_size"],
                    "realized_pnl": progress["realized_pnl"],
                    "fees": progress["fees"],
                },
            )
        synced.append({"symbol": symbol, **progress})

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
    expected_side = "Sell" if direction == "long" else "Buy"
    candidates: list[dict[str, Any]] = []

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
        candidates.append(record)

    if not candidates:
        return None

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
        return None

    weighted_exit = 0.0
    realized_pnl = 0.0
    fees = 0.0
    pnl_by_bdt_day: dict[str, float] = {}
    latest_ms = 0
    order_ids: list[str] = []

    for record in selected:
        size = _number(record.get("closedSize") or record.get("qty")) or 0.0
        exit_price = _number(record.get("avgExitPrice")) or 0.0
        pnl = _number(record.get("closedPnl")) or 0.0
        open_fee = _number(record.get("openFee")) or 0.0
        close_fee = _number(record.get("closeFee")) or 0.0
        event_ms = _record_time_ms(record) or 0
        weighted_exit += exit_price * size
        realized_pnl += pnl
        fees += open_fee + close_fee
        latest_ms = max(latest_ms, event_ms)
        if event_ms:
            day = datetime.fromtimestamp(event_ms / 1000, tz=UTC).astimezone(BDT).date().isoformat()
            pnl_by_bdt_day[day] = pnl_by_bdt_day.get(day, 0.0) + pnl
        order_id = str(record.get("orderId") or "").strip()
        if order_id and order_id not in order_ids:
            order_ids.append(order_id)

    return {
        "source": "bybit_position_closed_pnl_partial",
        "closed_size": total_size,
        "initial_quantity": initial_quantity,
        "remaining_quantity": max(initial_quantity - total_size, 0.0),
        "avg_exit_price": weighted_exit / total_size,
        "realized_pnl": realized_pnl,
        "fees": fees,
        "pnl_by_bdt_day": pnl_by_bdt_day,
        "record_count": len(selected),
        "close_order_ids": order_ids,
        "latest_close_time": datetime.fromtimestamp(latest_ms / 1000, tz=UTC).isoformat() if latest_ms else None,
        "synced_at": synced_at.astimezone(UTC).isoformat(),
    }


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


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None
