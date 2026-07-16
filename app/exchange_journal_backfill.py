from __future__ import annotations

import hashlib
from datetime import UTC, datetime, time
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

from app.journal import (
    append_trade_event,
    create_trade_entry,
    get_trade_by_execution_key,
    get_trade_history,
    update_trade_entry,
)
from app.trade_state import is_capacity_blocking_status


BDT = ZoneInfo("Asia/Dhaka")


def backfill_exchange_journal_lifecycle(
    client: Any,
    *,
    bdt_date: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Recover complete exchange trade lifecycles missing from the Journal.

    The Bybit transaction log is processed chronologically. Open rows establish a
    one-way position lifecycle, partial close rows accumulate against that
    lifecycle, and the Journal is finalized only when the full opened quantity is
    closed. Stable record keys and execution keys make repeated runs idempotent.
    """

    target_day = _parse_bdt_date(bdt_date) or datetime.now(BDT).date()
    start = datetime.combine(target_day, time.min, tzinfo=BDT).astimezone(UTC)
    end = datetime.now(UTC)
    ok, raw_records, error = client.safe_fetch_transaction_log(
        start_time=int(start.timestamp() * 1000),
        end_time=int(end.timestamp() * 1000),
        limit=max(1, min(int(limit), 100)),
    )
    if not ok:
        return {
            "ok": False,
            "date": target_day.isoformat(),
            "created": [],
            "updated": [],
            "skipped": [],
            "pending": [],
            "error": error or "Bybit transaction log query failed",
        }

    records = [record for record in raw_records if _is_trade_record(record)]
    records.sort(key=lambda item: _event_ms(item) or 0)
    existing_rows = get_trade_history(limit=1000)
    states: dict[str, dict[str, Any]] = {}
    created: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []
    pending: list[dict[str, Any]] = []

    for record in records:
        symbol = str(record.get("symbol") or record.get("contract") or "").upper().strip()
        role, side = _role_and_side(record)
        qty = _number(record.get("qty") or record.get("quantity") or record.get("execQty"))
        price = _number(
            record.get("tradePrice")
            or record.get("filledPrice")
            or record.get("execPrice")
            or record.get("price")
        )
        event_ms = _event_ms(record)
        if not symbol or side is None or qty is None or qty <= 0 or event_ms is None:
            continue

        state = states.get(symbol)
        if role is None:
            if state is None:
                cash_flow = _number(record.get("cashFlow"))
                if cash_flow is not None and abs(cash_flow) > 1e-12:
                    pending.append({
                        "symbol": symbol,
                        "error": "plain-side close row has no same-day open lifecycle",
                    })
                    continue
                role = "open"
            else:
                expected_open_side = "buy" if state["direction"] == "long" else "sell"
                role = "open" if side == expected_open_side else "close"

        if role == "open":
            direction = "long" if side == "buy" else "short"
            if state is not None and state["remaining_quantity"] > state["tolerance"]:
                if state["direction"] != direction:
                    pending.append({"symbol": symbol, "error": "opposite open row encountered before lifecycle closed"})
                    continue
                _append_open_record(state, record, qty=qty, price=price, event_ms=event_ms)
                continue
            states[symbol] = _new_state(
                client=client,
                symbol=symbol,
                direction=direction,
                record=record,
                qty=qty,
                price=price,
                event_ms=event_ms,
            )
            continue

        if state is None:
            pending.append({"symbol": symbol, "error": "close row has no same-day open lifecycle"})
            continue
        expected_close_side = "sell" if state["direction"] == "long" else "buy"
        if side != expected_close_side:
            pending.append({"symbol": symbol, "error": "close side does not match open lifecycle"})
            continue

        close_result = _append_close_record(state, record, qty=qty, price=price, event_ms=event_ms)
        if close_result == "over_close":
            pending.append({"symbol": symbol, "error": "close quantity exceeds opened lifecycle quantity"})
            states.pop(symbol, None)
            continue
        if close_result != "complete":
            continue

        payload = _closed_payload(state)
        matched = _match_existing_row(existing_rows, payload)
        if matched is not None:
            journal_id = str(matched.get("journal_id") or "")
            matched_metadata = matched.get("exchange_metadata") if isinstance(matched.get("exchange_metadata"), dict) else {}
            matched_close_sync = matched_metadata.get("close_sync") if isinstance(matched_metadata.get("close_sync"), dict) else {}
            matched_record_keys = set(matched_close_sync.get("record_keys") or [])
            payload_record_keys = set(payload["exchange_metadata"]["close_sync"]["record_keys"])
            if (
                str(matched.get("status") or "").lower() == "closed"
                and payload_record_keys
                and payload_record_keys.issubset(matched_record_keys)
            ):
                skipped.append(journal_id or str(payload["journal_id"]))
                states.pop(symbol, None)
                continue
            persisted = update_trade_entry(journal_id, _close_updates(payload)) if journal_id else None
            if persisted is not None:
                append_trade_event(
                    journal_id,
                    "EXCHANGE_LIFECYCLE_BACKFILLED",
                    "Missing exchange close lifecycle was reconstructed from the Bybit transaction log.",
                    {
                        "symbol": payload["symbol"],
                        "source": "bybit_account_transaction_log",
                        "record_keys": payload["exchange_metadata"]["close_sync"]["record_keys"],
                    },
                )
                updated.append(journal_id)
                existing_rows = [persisted if row.get("journal_id") == journal_id else row for row in existing_rows]
            else:
                pending.append({"symbol": symbol, "error": "matched journal row could not be updated"})
        else:
            existing_by_key = get_trade_by_execution_key(str(payload["execution_key"]))
            if existing_by_key is not None:
                skipped.append(str(existing_by_key.get("journal_id") or payload["journal_id"]))
            else:
                persisted = create_trade_entry(payload)
                created.append(str(persisted.get("journal_id") or payload["journal_id"]))
                existing_rows.append(persisted)
        states.pop(symbol, None)

    for state in states.values():
        if state["remaining_quantity"] > state["tolerance"]:
            pending.append(
                {
                    "symbol": state["symbol"],
                    "error": "transaction-log lifecycle remains open or partially closed",
                    "remaining_quantity": state["remaining_quantity"],
                }
            )

    return {
        "ok": True,
        "date": target_day.isoformat(),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "pending": pending,
        "error": None,
    }


def _new_state(
    *,
    client: Any,
    symbol: str,
    direction: str,
    record: dict[str, Any],
    qty: float,
    price: float | None,
    event_ms: int,
) -> dict[str, Any]:
    record_key = _record_key(record)
    mode = str(getattr(client, "mode", "demo") or "demo").lower()
    seed = "|".join([mode, symbol, direction, record_key])
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    fee = abs(_number(record.get("fee") or record.get("feePaid") or record.get("execFee")) or 0.0)
    change = _number(record.get("change")) or 0.0
    return {
        "symbol": symbol,
        "direction": direction,
        "execution_mode": mode,
        "journal_id": f"exchange-ledger-{digest[:32]}",
        "execution_key": f"ledger-{digest[:48]}",
        "order_id": _record_identity(record),
        "opened_ms": event_ms,
        "opened_at": _iso_from_ms(event_ms),
        "entry_weighted": (price or 0.0) * qty,
        "initial_quantity": qty,
        "remaining_quantity": qty,
        "closed_quantity": 0.0,
        "exit_weighted": 0.0,
        "entry_fees": fee,
        "close_fees": 0.0,
        "cash_flow": 0.0,
        "net_change": change,
        "latest_close_ms": 0,
        "records": [_compact_record(record)],
        "tolerance": max(abs(qty) * 1e-6, 1e-10),
    }


def _append_open_record(
    state: dict[str, Any],
    record: dict[str, Any],
    *,
    qty: float,
    price: float | None,
    event_ms: int,
) -> None:
    state["entry_weighted"] += (price or 0.0) * qty
    state["initial_quantity"] += qty
    state["remaining_quantity"] += qty
    state["entry_fees"] += abs(_number(record.get("fee") or record.get("feePaid") or record.get("execFee")) or 0.0)
    state["net_change"] += _number(record.get("change")) or 0.0
    state["records"].append(_compact_record(record))
    state["tolerance"] = max(abs(state["initial_quantity"]) * 1e-6, 1e-10)
    state["opened_ms"] = min(state["opened_ms"], event_ms)


def _append_close_record(
    state: dict[str, Any],
    record: dict[str, Any],
    *,
    qty: float,
    price: float | None,
    event_ms: int,
) -> str:
    if qty > state["remaining_quantity"] + state["tolerance"]:
        return "over_close"
    state["remaining_quantity"] = max(state["remaining_quantity"] - qty, 0.0)
    state["closed_quantity"] += qty
    state["exit_weighted"] += (price or 0.0) * qty
    state["close_fees"] += abs(_number(record.get("fee") or record.get("feePaid") or record.get("execFee")) or 0.0)
    state["cash_flow"] += _number(record.get("cashFlow")) or 0.0
    state["net_change"] += _number(record.get("change")) or 0.0
    state["latest_close_ms"] = max(state["latest_close_ms"], event_ms)
    state["records"].append(_compact_record(record))
    return "complete" if state["remaining_quantity"] <= state["tolerance"] else "partial"


def _closed_payload(state: dict[str, Any]) -> dict[str, Any]:
    quantity = state["initial_quantity"]
    entry = state["entry_weighted"] / quantity if quantity > 0 else 0.0
    exit_price = state["exit_weighted"] / state["closed_quantity"] if state["closed_quantity"] > 0 else entry
    fees = state["entry_fees"] + state["close_fees"]
    realized = state["net_change"]
    result = "profit" if realized > 0 else "loss" if realized < 0 else "flat"
    record_keys = [record["record_key"] for record in state["records"]]
    return {
        "journal_id": state["journal_id"],
        "execution_key": state["execution_key"],
        "symbol": state["symbol"],
        "strategy_name": "exchange_backfill",
        "strategy": "exchange_backfill",
        "direction": state["direction"],
        "execution_mode": state["execution_mode"],
        "entry": entry,
        "stop_loss": entry,
        "take_profit": entry,
        "quantity": quantity,
        "status": "closed",
        "result": result,
        "close_reason": "EXCHANGE_TRANSACTION_LOG_BACKFILL",
        "exit_price": exit_price,
        "realized_pnl": realized,
        "fees": fees,
        "order_id": state["order_id"] or None,
        "opened_at": state["opened_at"],
        "closed_at": _iso_from_ms(state["latest_close_ms"]),
        "exchange_metadata": {
            "source": "exchange_transaction_log_backfill",
            "recovered": True,
            "close_sync": {
                "source": "bybit_account_transaction_log",
                "authoritative_pnl_field": "change",
                "closed_size": state["closed_quantity"],
                "avg_exit_price": exit_price,
                "realized_pnl": realized,
                "cash_flow": state["cash_flow"],
                "fees": fees,
                "entry_fees": state["entry_fees"],
                "close_fees": state["close_fees"],
                "record_count": len(state["records"]),
                "record_keys": record_keys,
                "records": state["records"],
                "synced_at": datetime.now(UTC).isoformat(),
            },
        },
    }


def _match_existing_row(rows: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any] | None:
    record_keys = set(payload["exchange_metadata"]["close_sync"]["record_keys"])
    order_id = str(payload.get("order_id") or "")
    for row in rows:
        metadata = row.get("exchange_metadata") if isinstance(row.get("exchange_metadata"), dict) else {}
        close_sync = metadata.get("close_sync") if isinstance(metadata.get("close_sync"), dict) else {}
        existing_keys = set(close_sync.get("record_keys") or [])
        if record_keys and existing_keys.intersection(record_keys):
            return row
        if order_id and str(row.get("order_id") or "") == order_id:
            return row

    candidates = [
        row
        for row in rows
        if is_capacity_blocking_status(row.get("status"))
        and str(row.get("symbol") or "").upper() == payload["symbol"]
        and str(row.get("direction") or "").lower() == payload["direction"]
    ]
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    candidate_qty = _number(candidate.get("quantity"))
    payload_qty = _number(payload.get("quantity"))
    if candidate_qty is None or payload_qty is None:
        return None
    tolerance = max(abs(payload_qty) * 1e-4, 1e-8)
    return candidate if abs(candidate_qty - payload_qty) <= tolerance else None


def _close_updates(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "closed",
        "result": payload.get("result"),
        "close_reason": payload.get("close_reason"),
        "exit_price": payload.get("exit_price"),
        "realized_pnl": payload.get("realized_pnl"),
        "fees": payload.get("fees"),
        "closed_at": payload.get("closed_at"),
        "exchange_metadata": payload.get("exchange_metadata"),
    }


def _is_trade_record(record: dict[str, Any]) -> bool:
    return str(record.get("type") or record.get("transactionType") or "").lower() in {"", "trade"}


def _role_and_side(record: dict[str, Any]) -> tuple[str | None, str | None]:
    raw = str(record.get("direction") or record.get("side") or "").strip().lower()
    normalized = " ".join(raw.replace("_", " ").split())
    if normalized in {"open buy", "buy open"}:
        return "open", "buy"
    if normalized in {"open sell", "sell open"}:
        return "open", "sell"
    if normalized in {"close buy", "buy close"}:
        return "close", "buy"
    if normalized in {"close sell", "sell close"}:
        return "close", "sell"
    if normalized == "buy":
        return None, "buy"
    if normalized == "sell":
        return None, "sell"
    return None, None


def _compact_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_key": _record_key(record),
        "transaction_id": _record_identity(record),
        "event_time": _iso_from_ms(_event_ms(record) or 0),
        "direction": str(record.get("direction") or record.get("side") or ""),
        "quantity": _number(record.get("qty") or record.get("quantity") or record.get("execQty")),
        "filled_price": _number(
            record.get("tradePrice")
            or record.get("filledPrice")
            or record.get("execPrice")
            or record.get("price")
        ),
        "fee": _number(record.get("fee") or record.get("feePaid") or record.get("execFee")),
        "cash_flow": _number(record.get("cashFlow")),
        "change": _number(record.get("change")),
        "order_id": str(record.get("orderId") or ""),
        "order_link_id": str(record.get("orderLinkId") or ""),
        "exec_id": str(record.get("execId") or ""),
    }


def _record_identity(record: dict[str, Any]) -> str:
    return str(
        record.get("id")
        or record.get("transactionId")
        or record.get("execId")
        or record.get("orderId")
        or ""
    )


def _record_key(record: dict[str, Any]) -> str:
    identity = _record_identity(record)
    if identity:
        return f"id:{identity}"
    seed = "|".join(
        [
            str(_event_ms(record) or ""),
            str(record.get("symbol") or record.get("contract") or ""),
            str(record.get("direction") or record.get("side") or ""),
            str(record.get("qty") or record.get("quantity") or record.get("execQty") or ""),
            str(record.get("filledPrice") or record.get("tradePrice") or record.get("execPrice") or ""),
        ]
    )
    return f"hash:{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:32]}"


def _event_ms(record: dict[str, Any]) -> int | None:
    for key in ("transactionTime", "transactTime", "execTime", "createdTime", "updatedTime"):
        try:
            value = int(record.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _iso_from_ms(value: int) -> str:
    return datetime.fromtimestamp(max(value, 0) / 1000, tz=UTC).isoformat()


def _parse_bdt_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None
