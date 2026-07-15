from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from math import isfinite
from typing import Any


BYBIT_MAX_WINDOW_MS = 7 * 24 * 60 * 60 * 1000 - 1
BYBIT_PAGE_LIMIT = 100


def fetch_exact_close_result(
    client: Any,
    trade: dict[str, Any],
    now: datetime | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    symbol = str(trade.get("symbol") or "").upper().strip()
    opened_at = trade.get("opened_at") or trade.get("detected_at")
    if not symbol:
        return None, "trade symbol is missing"
    start_ms = _timestamp_ms(opened_at)
    if start_ms is None:
        return None, "trade opened_at is missing or invalid"

    current = now or datetime.now(UTC)
    end_ms = int(current.astimezone(UTC).timestamp() * 1000)
    ok, records, error = _safe_fetch_closed_pnl(client, symbol=symbol, start_ms=start_ms, end_ms=end_ms)
    if not ok:
        ledger_result, ledger_error = fetch_transaction_log_close_result(
            client,
            trade,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        if ledger_result is not None:
            return ledger_result, None
        return None, ledger_error or error or "Bybit closed PnL query failed"

    exact_result, exact_error = aggregate_closed_pnl_records(trade, records, opened_ms=start_ms)
    if exact_result is not None:
        return exact_result, None

    ledger_result, ledger_error = fetch_transaction_log_close_result(
        client,
        trade,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    if ledger_result is not None:
        return ledger_result, None
    return None, exact_error or ledger_error


def fetch_transaction_log_close_result(
    client: Any,
    trade: dict[str, Any],
    *,
    start_ms: int,
    end_ms: int,
) -> tuple[dict[str, Any] | None, str | None]:
    ok, records, error = _safe_fetch_transaction_log(client, start_ms=start_ms, end_ms=end_ms)
    if not ok:
        return None, error or "Bybit transaction log query failed"
    return aggregate_transaction_log_records(trade, records, opened_ms=start_ms)


def repair_incomplete_journal_closes(client: Any, *, limit: int = 100) -> dict[str, Any]:
    from app.journal import append_trade_event, get_trade_history, update_trade_entry

    repaired: list[dict[str, Any]] = []
    pending: list[dict[str, str]] = []
    current = datetime.now(UTC)
    end_ms = int(current.timestamp() * 1000)

    for trade in get_trade_history(limit=limit):
        status = str(trade.get("status") or "").lower()
        if status not in {"closed", "close_pending_sync"}:
            continue
        if all(_number(trade.get(field)) is not None for field in ("exit_price", "realized_pnl", "fees")):
            continue
        start_ms = _timestamp_ms(trade.get("opened_at") or trade.get("detected_at"))
        if start_ms is None:
            pending.append({"symbol": str(trade.get("symbol") or "UNKNOWN"), "error": "opened_at is unavailable"})
            continue

        close_result, error = fetch_transaction_log_close_result(
            client,
            trade,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        if close_result is None:
            pending.append({"symbol": str(trade.get("symbol") or "UNKNOWN"), "error": error or "ledger close unavailable"})
            continue

        journal_id = str(trade.get("journal_id") or "")
        updates = {
            "status": "closed",
            "result": close_result.get("result"),
            "sl_hit_reason": close_result.get("sl_hit_reason"),
            "close_reason": close_result.get("close_reason"),
            "closed_at": close_result.get("closed_at"),
            "exit_price": close_result.get("exit_price"),
            "realized_pnl": close_result.get("realized_pnl"),
            "fees": close_result.get("fees"),
            "exchange_metadata": close_result.get("exchange_metadata"),
        }
        persisted = update_trade_entry(journal_id, updates) if journal_id else None
        if persisted is None:
            pending.append({"symbol": str(trade.get("symbol") or "UNKNOWN"), "error": "journal row not found"})
            continue
        append_trade_event(
            journal_id,
            "LEDGER_CLOSE_SYNC_REPAIRED",
            "Exact Bybit transaction-log close evidence repaired an incomplete Journal row.",
            {
                "symbol": trade.get("symbol"),
                "source": "bybit_account_transaction_log",
                "realized_pnl": close_result.get("realized_pnl"),
                "fees": close_result.get("fees"),
            },
        )
        repaired.append({"symbol": str(trade.get("symbol") or ""), "journal_id": journal_id})

    return {"ok": not pending, "repaired": repaired, "pending": pending}


def aggregate_closed_pnl_records(
    trade: dict[str, Any],
    records: list[dict[str, Any]],
    opened_ms: int | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    symbol = str(trade.get("symbol") or "").upper().strip()
    direction = str(trade.get("direction") or "").lower().strip()
    expected_side = "Sell" if direction == "long" else "Buy" if direction == "short" else ""
    target_qty = _initial_quantity(trade)
    opened_ms = opened_ms if opened_ms is not None else _timestamp_ms(trade.get("opened_at") or trade.get("detected_at"))

    if not symbol or not expected_side:
        return None, "trade direction or symbol is invalid"
    if target_qty is None or target_qty <= 0:
        return None, "initial trade quantity is unavailable"
    if opened_ms is None:
        return None, "trade opened_at is missing or invalid"

    identity = _trade_exchange_identity(trade)
    close_identity_available = _has_close_identity(identity)

    candidates: list[dict[str, Any]] = []
    for record in records:
        if str(record.get("symbol") or "").upper() != symbol:
            continue
        if close_identity_available and not _record_matches_role_identity(
            record, identity, role="close"
        ):
            continue
        side = str(record.get("side") or "")
        if side and side != expected_side:
            continue
        event_ms = _record_time_ms(record)
        if event_ms is None or event_ms < opened_ms:
            continue
        closed_size = _number(record.get("closedSize") or record.get("qty"))
        exit_price = _number(record.get("avgExitPrice"))
        closed_pnl = _number(record.get("closedPnl"))
        open_fee = _number(record.get("openFee"))
        close_fee = _number(record.get("closeFee"))
        if closed_size is None or closed_size <= 0:
            continue
        if exit_price is None or closed_pnl is None:
            continue
        if open_fee is None or close_fee is None:
            return None, "Bybit close record is missing exact openFee/closeFee fields"
        candidates.append(record)

    if not candidates:
        if close_identity_available:
            return None, "exact Bybit closed PnL record for this trade identity is not available yet"
        return None, "exact Bybit closed PnL record is not available yet"

    candidates.sort(key=lambda item: _record_time_ms(item) or 0)
    selected: list[dict[str, Any]] = []
    total_size = 0.0
    tolerance = max(abs(target_qty) * 1e-8, 1e-12)

    for record in candidates:
        selected.append(record)
        total_size += float(record.get("closedSize") or record.get("qty"))
        if total_size >= target_qty - tolerance:
            break

    if total_size < target_qty - tolerance:
        return None, f"partial close data only: {total_size} of {target_qty}"
    if total_size > target_qty + tolerance:
        return None, f"closed PnL records exceed expected quantity: {total_size} > {target_qty}"

    weighted_exit = 0.0
    realized_pnl = 0.0
    open_fee_total = 0.0
    close_fee_total = 0.0
    fill_count = 0
    close_time_ms = 0

    for record in selected:
        size = float(record.get("closedSize") or record.get("qty"))
        weighted_exit += float(record["avgExitPrice"]) * size
        realized_pnl += float(record["closedPnl"])
        open_fee_total += float(record["openFee"])
        close_fee_total += float(record["closeFee"])
        fill_count += int(float(record.get("fillCount") or 0))
        close_time_ms = max(close_time_ms, _record_time_ms(record) or 0)

    avg_exit_price = weighted_exit / total_size
    total_fees = open_fee_total + close_fee_total
    result = "profit" if realized_pnl > 0 else "loss" if realized_pnl < 0 else "flat"
    closed_at = datetime.fromtimestamp(close_time_ms / 1000, tz=UTC).isoformat() if close_time_ms else datetime.now(UTC).isoformat()
    existing_metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}

    close_sync = {
        "source": "bybit_position_closed_pnl",
        "authoritative_pnl_field": "closedPnl",
        "closed_size": total_size,
        "avg_exit_price": avg_exit_price,
        "realized_pnl": realized_pnl,
        "open_fee": open_fee_total,
        "close_fee": close_fee_total,
        "fees": total_fees,
        "fill_count": fill_count,
        "record_count": len(selected),
        "close_order_ids": [str(item.get("orderId") or "") for item in selected if item.get("orderId")],
        "identity_match": "exact" if close_identity_available else "legacy_single_trade",
        "synced_at": datetime.now(UTC).isoformat(),
        "records": selected,
    }

    return {
        "result": result,
        "sl_hit_reason": None,
        "close_reason": "exchange_closed_pnl",
        "closed_at": closed_at,
        "exit_price": avg_exit_price,
        "realized_pnl": realized_pnl,
        "fees": total_fees,
        "exchange_metadata": {**existing_metadata, "close_sync": close_sync},
    }, None


def _safe_fetch_closed_pnl(
    client: Any,
    *,
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> tuple[bool, list[dict[str, Any]], str | None]:
    public_method = getattr(client, "safe_fetch_closed_pnl", None)
    if callable(public_method):
        try:
            return public_method(symbol=symbol, start_time=start_ms, end_time=end_ms)
        except TypeError:
            return public_method(symbol, start_ms, end_ms)
        except Exception as exc:
            return False, [], str(exc)

    private_get = getattr(client, "_private_get", None)
    if not callable(private_get):
        return False, [], "Bybit closed PnL client method is unavailable"

    records: list[dict[str, Any]] = []
    window_start = start_ms
    try:
        while window_start <= end_ms:
            window_end = min(end_ms, window_start + BYBIT_MAX_WINDOW_MS)
            cursor: str | None = None
            while True:
                params = {
                    "category": "linear",
                    "symbol": symbol,
                    "startTime": str(window_start),
                    "endTime": str(window_end),
                    "limit": str(BYBIT_PAGE_LIMIT),
                }
                if cursor:
                    params["cursor"] = cursor
                payload = private_get("/v5/position/closed-pnl", params)
                records.extend(payload.get("list", []) or [])
                cursor = str(payload.get("nextPageCursor") or "").strip() or None
                if not cursor:
                    break
            window_start = window_end + 1
    except Exception as exc:
        return False, [], str(exc)

    return True, records, None


def _safe_fetch_transaction_log(
    client: Any,
    *,
    start_ms: int,
    end_ms: int,
) -> tuple[bool, list[dict[str, Any]], str | None]:
    public_method = getattr(client, "safe_fetch_transaction_log", None)
    if callable(public_method):
        try:
            return public_method(start_time=start_ms, end_time=end_ms)
        except TypeError:
            return public_method("linear", "UNIFIED", "USDT", start_ms, end_ms)
        except Exception as exc:
            return False, [], str(exc)

    private_get = getattr(client, "_private_get", None)
    if not callable(private_get):
        return False, [], "Bybit transaction log client method is unavailable"

    records: list[dict[str, Any]] = []
    cursor: str | None = None
    try:
        while True:
            params = {
                "accountType": "UNIFIED",
                "category": "linear",
                "currency": "USDT",
                "startTime": str(start_ms),
                "endTime": str(end_ms),
                "limit": str(BYBIT_PAGE_LIMIT),
            }
            if cursor:
                params["cursor"] = cursor
            payload = private_get("/v5/account/transaction-log", params)
            records.extend(payload.get("list", []) or [])
            cursor = str(payload.get("nextPageCursor") or "").strip() or None
            if not cursor:
                break
    except Exception as exc:
        return False, [], str(exc)

    return True, records, None


def aggregate_transaction_log_records(
    trade: dict[str, Any],
    records: list[dict[str, Any]],
    opened_ms: int | None = None,
    *,
    require_exact_identity: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    symbol = str(trade.get("symbol") or "").upper().strip()
    direction = str(trade.get("direction") or "").lower().strip()
    entry_side = "Buy" if direction == "long" else "Sell" if direction == "short" else ""
    close_side = "Sell" if direction == "long" else "Buy" if direction == "short" else ""
    target_qty = _initial_quantity(trade)
    opened_ms = opened_ms if opened_ms is not None else _timestamp_ms(trade.get("opened_at") or trade.get("detected_at"))

    if not symbol or not entry_side or not close_side:
        return None, "trade direction or symbol is invalid"
    if target_qty is None or target_qty <= 0:
        return None, "initial trade quantity is unavailable"
    if opened_ms is None:
        return None, "trade opened_at is missing or invalid"

    identity = _trade_exchange_identity(trade)
    entry_identity_available = _has_entry_identity(identity)
    close_identity_available = _has_close_identity(identity)
    strict_identity = require_exact_identity or (
        entry_identity_available and close_identity_available
    )
    if require_exact_identity and not entry_identity_available:
        return None, "exact entry order identity is required for overlapping trades"
    if require_exact_identity and not close_identity_available:
        return None, "exact close order identity is required for overlapping trades"

    trade_rows: list[dict[str, Any]] = []
    close_rows: list[dict[str, Any]] = []
    for record in records:
        if str(record.get("symbol") or record.get("contract") or "").upper() != symbol:
            continue
        event_ms = _transaction_time_ms(record)
        if event_ms is None or event_ms < opened_ms:
            continue
        if str(record.get("type") or "").lower() not in {"trade", ""}:
            continue
        direction_value = _transaction_direction(record)
        if direction_value not in {entry_side, close_side}:
            continue
        if strict_identity:
            role = "entry" if direction_value == entry_side else "close"
            if not _record_matches_role_identity(record, identity, role=role):
                continue
        qty = _number(record.get("qty") or record.get("quantity") or record.get("execQty"))
        if qty is None or qty <= 0:
            continue
        trade_rows.append(record)
        if direction_value == close_side:
            close_rows.append(record)

    if not close_rows:
        if strict_identity:
            return None, "exact Bybit transaction log close row for this trade identity is not available yet"
        return None, "Bybit transaction log close row is not available yet"
    if strict_identity and not any(
        _transaction_direction(record) == entry_side for record in trade_rows
    ):
        return None, "exact Bybit transaction log entry row for this trade identity is not available yet"

    trade_rows.sort(key=lambda item: _transaction_time_ms(item) or 0)
    close_rows.sort(key=lambda item: _transaction_time_ms(item) or 0)

    selected_close: list[dict[str, Any]] = []
    closed_size = 0.0
    tolerance = max(abs(target_qty) * 1e-6, 1e-10)
    for record in close_rows:
        qty = _number(record.get("qty") or record.get("quantity") or record.get("execQty")) or 0.0
        if closed_size + qty > target_qty + tolerance:
            remaining = target_qty - closed_size
            if remaining <= tolerance:
                break
            return None, f"transaction log close rows exceed expected quantity: {closed_size + qty} > {target_qty}"
        selected_close.append(record)
        closed_size += qty
        if closed_size >= target_qty - tolerance:
            break

    if closed_size < target_qty - tolerance:
        return None, f"transaction log partial close data only: {closed_size} of {target_qty}"

    close_keys = {_transaction_key(record) for record in selected_close}
    latest_close_ms = max(_transaction_time_ms(record) or 0 for record in selected_close)
    selected_rows = [
        record
        for record in trade_rows
        if (_transaction_direction(record) == entry_side and (_transaction_time_ms(record) or 0) <= latest_close_ms)
        or _transaction_key(record) in close_keys
    ]

    weighted_exit = 0.0
    close_fee_total = 0.0
    all_fee_total = 0.0
    close_cash_flow = 0.0
    net_change = 0.0
    for record in selected_close:
        qty = _number(record.get("qty") or record.get("quantity") or record.get("execQty")) or 0.0
        price = _transaction_price(record)
        if price is None:
            return None, "Bybit transaction log close row is missing filled price"
        weighted_exit += price * qty
        close_fee_total += abs(_number(record.get("fee") or record.get("feePaid") or record.get("execFee")) or 0.0)
        close_cash_flow += _number(record.get("cashFlow")) or 0.0

    for record in selected_rows:
        all_fee_total += abs(_number(record.get("fee") or record.get("feePaid") or record.get("execFee")) or 0.0)
        net_change += _number(record.get("change")) or 0.0

    avg_exit_price = weighted_exit / closed_size
    realized_pnl = net_change if selected_rows else close_cash_flow - close_fee_total
    result = "profit" if realized_pnl > 0 else "loss" if realized_pnl < 0 else "flat"
    closed_at = datetime.fromtimestamp(latest_close_ms / 1000, tz=UTC).isoformat() if latest_close_ms else datetime.now(UTC).isoformat()
    existing_metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    compact_records = [_compact_transaction_record(record) for record in selected_rows]

    close_sync = {
        "source": "bybit_account_transaction_log",
        "authoritative_pnl_field": "change",
        "closed_size": closed_size,
        "avg_exit_price": avg_exit_price,
        "realized_pnl": realized_pnl,
        "cash_flow": close_cash_flow,
        "fees": all_fee_total,
        "close_fees": close_fee_total,
        "record_count": len(compact_records),
        "record_keys": [record["record_key"] for record in compact_records],
        "identity_match": "exact" if strict_identity else "legacy_single_trade",
        "matched_entry_order_ids": sorted(identity["entry_order_ids"]),
        "matched_close_order_ids": sorted(identity["close_order_ids"]),
        "matched_entry_order_link_ids": sorted(identity["entry_order_link_ids"]),
        "matched_close_order_link_ids": sorted(identity["close_order_link_ids"]),
        "synced_at": datetime.now(UTC).isoformat(),
        "records": compact_records,
    }

    return {
        "result": result,
        "sl_hit_reason": None,
        "close_reason": "exchange_transaction_log",
        "closed_at": closed_at,
        "exit_price": avg_exit_price,
        "realized_pnl": realized_pnl,
        "fees": all_fee_total,
        "exchange_metadata": {**existing_metadata, "close_sync": close_sync},
    }, None


def _trade_exchange_identity(trade: dict[str, Any]) -> dict[str, set[str]]:
    identity: dict[str, set[str]] = {
        "entry_order_ids": set(),
        "entry_order_link_ids": set(),
        "entry_exec_ids": set(),
        "close_order_ids": set(),
        "close_order_link_ids": set(),
        "close_exec_ids": set(),
        "position_idxs": set(),
    }
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    management = trade.get("management") if isinstance(trade.get("management"), dict) else {}
    metadata_management = metadata.get("management") if isinstance(metadata.get("management"), dict) else {}
    merged_management = {**metadata_management, **management}

    _add_identity(identity["entry_order_ids"], trade.get("order_id"), metadata.get("order_id"))
    _add_identity(identity["entry_order_link_ids"], metadata.get("order_link_id"))

    for source in (metadata.get("order_response"), metadata.get("fill_confirmation")):
        _collect_identity_mapping(source, identity, role="entry")
    fill_confirmation = metadata.get("fill_confirmation")
    if isinstance(fill_confirmation, dict):
        _collect_identity_mapping(fill_confirmation.get("raw"), identity, role="entry")

    for prefix in ("tp1", "tp2"):
        _add_identity(
            identity["close_order_ids"],
            merged_management.get(f"{prefix}_order_id"),
        )
        _add_identity(
            identity["close_order_link_ids"],
            merged_management.get(f"{prefix}_order_link_id"),
        )

    native_orders = metadata.get("native_profit_orders")
    if isinstance(native_orders, dict):
        for source in native_orders.values():
            _collect_identity_mapping(source, identity, role="close")

    manual_close = metadata.get("manual_close")
    if isinstance(manual_close, dict):
        _add_identity(identity["close_order_link_ids"], manual_close.get("request_id"))
        for key in ("order_response", "recovered_order"):
            _collect_identity_mapping(manual_close.get(key), identity, role="close")

    close_sync = metadata.get("close_sync")
    if isinstance(close_sync, dict):
        _add_identity(identity["close_order_ids"], *(close_sync.get("close_order_ids") or []))
        for source in close_sync.get("records") or []:
            _collect_identity_mapping(source, identity, role="close")

    exchange_identity = metadata.get("exchange_identity")
    if isinstance(exchange_identity, dict):
        _add_identity(identity["position_idxs"], exchange_identity.get("position_idx"))
    position_snapshot = metadata.get("position_snapshot")
    if isinstance(position_snapshot, dict):
        _add_identity(identity["position_idxs"], position_snapshot.get("positionIdx"))
    _add_identity(identity["position_idxs"], trade.get("position_idx"))

    return identity


def _collect_identity_mapping(
    source: Any,
    identity: dict[str, set[str]],
    *,
    role: str,
) -> None:
    if not isinstance(source, dict):
        return
    prefix = "entry" if role == "entry" else "close"
    _add_identity(
        identity[f"{prefix}_order_ids"],
        source.get("orderId"),
        source.get("order_id"),
    )
    _add_identity(
        identity[f"{prefix}_order_link_ids"],
        source.get("orderLinkId"),
        source.get("order_link_id"),
        source.get("request_id"),
    )
    _add_identity(
        identity[f"{prefix}_exec_ids"],
        source.get("execId"),
        source.get("exec_id"),
    )
    _add_identity(
        identity["position_idxs"],
        source.get("positionIdx"),
        source.get("position_idx"),
    )


def _add_identity(target: set[str], *values: Any) -> None:
    for value in values:
        if isinstance(value, (list, tuple, set)):
            _add_identity(target, *value)
            continue
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            target.add(normalized)


def _has_entry_identity(identity: dict[str, set[str]]) -> bool:
    return bool(
        identity["entry_order_ids"]
        or identity["entry_order_link_ids"]
        or identity["entry_exec_ids"]
    )


def _has_close_identity(identity: dict[str, set[str]]) -> bool:
    return bool(
        identity["close_order_ids"]
        or identity["close_order_link_ids"]
        or identity["close_exec_ids"]
    )


def _record_matches_role_identity(
    record: dict[str, Any],
    identity: dict[str, set[str]],
    *,
    role: str,
) -> bool:
    prefix = "entry" if role == "entry" else "close"
    record_order_id = str(record.get("orderId") or record.get("order_id") or "").strip()
    record_order_link_id = str(
        record.get("orderLinkId") or record.get("order_link_id") or ""
    ).strip()
    record_exec_id = str(record.get("execId") or record.get("exec_id") or "").strip()
    position_idx_value = record.get("positionIdx")
    if position_idx_value is None:
        position_idx_value = record.get("position_idx")
    record_position_idx = (
        "" if position_idx_value is None else str(position_idx_value).strip()
    )

    if identity["position_idxs"] and record_position_idx:
        if record_position_idx not in identity["position_idxs"]:
            return False

    return bool(
        (record_order_id and record_order_id in identity[f"{prefix}_order_ids"])
        or (
            record_order_link_id
            and record_order_link_id in identity[f"{prefix}_order_link_ids"]
        )
        or (record_exec_id and record_exec_id in identity[f"{prefix}_exec_ids"])
    )


def _initial_quantity(trade: dict[str, Any]) -> float | None:
    management = trade.get("management") if isinstance(trade.get("management"), dict) else {}
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    metadata_management = metadata.get("management") if isinstance(metadata.get("management"), dict) else {}
    candidates = [
        _number(trade.get("initial_quantity")),
        _number(trade.get("quantity")),
        _number(trade.get("remaining_quantity")),
        _number(management.get("initial_quantity")),
        _number(metadata_management.get("initial_quantity")),
    ]
    positive = [value for value in candidates if value is not None and value > 0]
    if not positive:
        return None

    # The initial quantity cannot be smaller than a confirmed current/remaining
    # quantity. Selecting the largest persisted candidate is fail-safe when old
    # management metadata conflicts with a newer journal or exchange quantity:
    # it prevents a partial close from being accepted as a complete close.
    return max(positive)


def _record_time_ms(record: dict[str, Any]) -> int | None:
    for key in ("updatedTime", "createdTime"):
        value = record.get(key)
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            continue
        if numeric > 0:
            return numeric
    return None


def _transaction_time_ms(record: dict[str, Any]) -> int | None:
    for key in ("transactionTime", "transactTime", "execTime", "createdTime", "updatedTime"):
        value = record.get(key)
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            continue
        if numeric > 0:
            return numeric
    value = record.get("time")
    if value:
        return _timestamp_ms(value)
    return None


def _transaction_direction(record: dict[str, Any]) -> str:
    value = str(record.get("side") or record.get("direction") or "").strip().lower()
    if value in {"buy", "open buy", "close buy"}:
        return "Buy"
    if value in {"sell", "open sell", "close sell"}:
        return "Sell"
    return ""


def _transaction_price(record: dict[str, Any]) -> float | None:
    return _number(record.get("tradePrice") or record.get("filledPrice") or record.get("execPrice") or record.get("price"))


def _transaction_key(record: dict[str, Any]) -> str:
    for key in ("id", "transactionId", "orderId", "execId"):
        value = str(record.get(key) or "").strip()
        if value:
            return f"{key}:{value}"
    raw = "|".join(
        str(value or "")
        for value in (
            record.get("symbol") or record.get("contract"),
            _transaction_direction(record),
            _transaction_time_ms(record),
            record.get("qty") or record.get("quantity") or record.get("execQty"),
            _transaction_price(record),
            record.get("change"),
        )
    )
    return f"transaction:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def _compact_transaction_record(record: dict[str, Any]) -> dict[str, Any]:
    event_ms = _transaction_time_ms(record)
    return {
        "record_key": _transaction_key(record),
        "order_id": str(record.get("orderId") or record.get("order_id") or "").strip() or None,
        "order_link_id": str(record.get("orderLinkId") or record.get("order_link_id") or "").strip() or None,
        "exec_id": str(record.get("execId") or record.get("exec_id") or "").strip() or None,
        "position_idx": str(record.get("positionIdx") or record.get("position_idx") or "").strip() or None,
        "symbol": str(record.get("symbol") or record.get("contract") or "").upper(),
        "direction": str(record.get("direction") or record.get("side") or ""),
        "quantity": _number(record.get("qty") or record.get("quantity") or record.get("execQty")) or 0.0,
        "filled_price": _transaction_price(record),
        "fee": abs(_number(record.get("fee") or record.get("feePaid") or record.get("execFee")) or 0.0),
        "cash_flow": _number(record.get("cashFlow")),
        "change": _number(record.get("change")),
        "wallet_balance": _number(record.get("cashBalance") or record.get("walletBalance")),
        "created_at": datetime.fromtimestamp(event_ms / 1000, tz=UTC).isoformat() if event_ms else None,
    }


def _timestamp_ms(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.astimezone(UTC).timestamp() * 1000)


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None
