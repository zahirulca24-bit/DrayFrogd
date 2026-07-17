from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any, Callable

_INSTALLED = False
_ORIGINAL_CONFIRM_FILL: Callable[..., tuple[dict[str, Any] | None, str | None]] | None = None


def install() -> None:
    """Install execId-aware fill confirmation without changing strategy/risk logic.

    The authoritative execution path already calls ``execution_service._confirm_fill``
    after an exchange order is accepted. This hook enriches that confirmation by
    preferring Bybit execution-list records when available, so Journal metadata can
    carry exchange-native ``execId`` evidence instead of relying only on order or
    position snapshots.
    """

    global _INSTALLED, _ORIGINAL_CONFIRM_FILL
    if _INSTALLED:
        return

    from app import execution_service

    if getattr(execution_service, "_P0_1B_EXEC_FILL_EVIDENCE_INSTALLED", False):
        _INSTALLED = True
        return

    original = execution_service._confirm_fill
    _ORIGINAL_CONFIRM_FILL = original

    def _confirm_fill_with_exec_evidence(
        client: Any,
        *,
        symbol: str,
        direction: str,
        order_link_id: str,
        order_id: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        execution_fill, execution_error = fetch_execution_fill_evidence(
            client,
            symbol=symbol,
            direction=direction,
            order_link_id=order_link_id,
            order_id=order_id,
        )
        if execution_fill is not None:
            return execution_fill, None

        fallback_fill, fallback_error = original(
            client,
            symbol=symbol,
            direction=direction,
            order_link_id=order_link_id,
            order_id=order_id,
        )
        if fallback_fill is not None:
            return {
                **fallback_fill,
                "execution_evidence_status": "unavailable",
                "execution_evidence_error": execution_error,
            }, None
        return None, execution_error or fallback_error

    execution_service._confirm_fill = _confirm_fill_with_exec_evidence
    execution_service._P0_1B_EXEC_FILL_EVIDENCE_INSTALLED = True
    _INSTALLED = True


def fetch_execution_fill_evidence(
    client: Any,
    *,
    symbol: str,
    direction: str,
    order_link_id: str,
    order_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    ok, records, error = _fetch_execution_records(
        client,
        symbol=symbol,
        order_link_id=order_link_id,
        order_id=order_id,
    )
    if not ok:
        return None, error or "Execution list fetch failed"

    matched = _match_execution_records(
        records,
        symbol=symbol,
        direction=direction,
        order_link_id=order_link_id,
        order_id=order_id,
    )
    if not matched:
        return None, "No Bybit execution record matched accepted order identity"

    total_qty = 0.0
    notional = 0.0
    total_fee = 0.0
    exec_ids: list[str] = []
    latest_time: int | None = None
    side: str | None = None
    position_idx: str | int | None = None
    resolved_order_id = order_id or None
    resolved_order_link_id = order_link_id or None

    for record in matched:
        qty = _positive_float(record.get("execQty") or record.get("qty"))
        price = _positive_float(record.get("execPrice") or record.get("price"))
        if qty is None or price is None:
            continue
        total_qty += qty
        notional += qty * price
        fee = _non_negative_float(record.get("execFee") or record.get("fee"))
        if fee is not None:
            total_fee += fee
        exec_id = str(record.get("execId") or "").strip()
        if exec_id and exec_id not in exec_ids:
            exec_ids.append(exec_id)
        if not resolved_order_id and record.get("orderId"):
            resolved_order_id = str(record.get("orderId"))
        if not resolved_order_link_id and record.get("orderLinkId"):
            resolved_order_link_id = str(record.get("orderLinkId"))
        if side is None and record.get("side"):
            side = str(record.get("side"))
        if position_idx is None and record.get("positionIdx") is not None:
            position_idx = record.get("positionIdx")
        event_time = _integer_time(record.get("execTime") or record.get("updatedTime") or record.get("createdTime"))
        if event_time is not None and (latest_time is None or event_time > latest_time):
            latest_time = event_time

    if total_qty <= 0 or notional <= 0:
        return None, "Matched execution records did not include positive fill quantity and price"

    return {
        "source": "bybit_execution_list",
        "order_id": resolved_order_id,
        "order_link_id": resolved_order_link_id,
        "status": "ExecutionConfirmed",
        "avg_price": notional / total_qty,
        "quantity": total_qty,
        "fee": total_fee,
        "exec_id": exec_ids[0] if exec_ids else None,
        "exec_ids": exec_ids,
        "side": side,
        "position_idx": position_idx,
        "filled_at": _timestamp_to_iso(latest_time),
        "raw": matched,
    }, None


def _fetch_execution_records(
    client: Any,
    *,
    symbol: str,
    order_link_id: str,
    order_id: str,
) -> tuple[bool, list[dict[str, Any]], str | None]:
    method = getattr(client, "safe_fetch_executions", None)
    if callable(method):
        try:
            return method(symbol=symbol, order_link_id=order_link_id, order_id=order_id)
        except TypeError:
            try:
                return method(symbol=symbol, order_id=order_id)
            except Exception as exc:  # pragma: no cover - defensive compatibility
                return False, [], str(exc)
        except Exception as exc:  # pragma: no cover - defensive compatibility
            return False, [], str(exc)

    private_get = getattr(client, "_private_get", None)
    if not callable(private_get):
        return False, [], "Bybit execution-list endpoint is unavailable on client"

    params: dict[str, str] = {
        "category": "linear",
        "symbol": symbol,
        "limit": "50",
    }
    if order_id:
        params["orderId"] = order_id
    elif order_link_id:
        params["orderLinkId"] = order_link_id

    try:
        payload = private_get("/v5/execution/list", params)
    except Exception as exc:
        return False, [], str(exc)

    records = payload.get("list", []) if isinstance(payload, dict) else []
    if not isinstance(records, list):
        return False, [], "Bybit execution-list response was not a list"
    return True, [record for record in records if isinstance(record, dict)], None


def _match_execution_records(
    records: list[dict[str, Any]],
    *,
    symbol: str,
    direction: str,
    order_link_id: str,
    order_id: str,
) -> list[dict[str, Any]]:
    expected_symbol = symbol.upper().strip()
    expected_side = "Buy" if direction.lower().strip() == "long" else "Sell"
    matched: list[dict[str, Any]] = []
    for record in records:
        if str(record.get("symbol") or "").upper().strip() != expected_symbol:
            continue
        if str(record.get("side") or "") and str(record.get("side")) != expected_side:
            continue
        record_order_id = str(record.get("orderId") or "")
        record_link_id = str(record.get("orderLinkId") or "")
        if order_id and record_order_id and record_order_id != order_id:
            continue
        if order_link_id and record_link_id and record_link_id != order_link_id:
            continue
        if not (record_order_id or record_link_id):
            continue
        matched.append(record)
    return matched


def _positive_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) and numeric > 0 else None


def _non_negative_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) and numeric >= 0 else None


def _integer_time(value: Any) -> int | None:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric > 0 else None


def _timestamp_to_iso(value: int | None) -> str:
    if value is None:
        return datetime.now(UTC).isoformat()
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()
