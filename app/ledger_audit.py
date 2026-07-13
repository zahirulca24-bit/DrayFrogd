from __future__ import annotations

from datetime import UTC, datetime, time
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo


BDT = ZoneInfo("Asia/Dhaka")


def get_account_ledger_audit(
    client: Any,
    *,
    bdt_date: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    target_day = _parse_bdt_date(bdt_date) or datetime.now(BDT).date()
    start = datetime.combine(target_day, time.min, tzinfo=BDT).astimezone(UTC)
    end = datetime.now(UTC)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    ok, records, error = client.safe_fetch_transaction_log(
        start_time=start_ms,
        end_time=end_ms,
        limit=max(1, min(limit, 100)),
    )
    if not ok:
        return {
            "ok": False,
            "date": target_day.isoformat(),
            "error": error or "Bybit transaction log query failed",
            "summary": _empty_summary(),
            "by_symbol": [],
            "records": [],
        }

    normalized = [_normalize_record(record) for record in records]
    normalized = [record for record in normalized if record["event_time"]]
    normalized.sort(key=lambda item: item["event_time"])

    summary = _summarize(normalized)
    by_symbol = _summarize_by_symbol(normalized)

    return {
        "ok": True,
        "date": target_day.isoformat(),
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "error": None,
        "summary": summary,
        "by_symbol": by_symbol,
        "records": list(reversed(normalized))[:limit],
    }


def _empty_summary() -> dict[str, Any]:
    return {
        "record_count": 0,
        "trade_count": 0,
        "net_change": 0.0,
        "trade_change": 0.0,
        "cash_flow": 0.0,
        "fees": 0.0,
        "funding": 0.0,
        "first_wallet_balance": None,
        "last_wallet_balance": None,
        "wallet_balance_delta": None,
    }


def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _empty_summary()
    summary["record_count"] = len(records)
    wallet_values = [record["wallet_balance"] for record in records if record["wallet_balance"] is not None]

    for record in records:
        change = record["change"] or 0.0
        summary["net_change"] += change
        summary["cash_flow"] += record["cash_flow"] or 0.0
        summary["fees"] += abs(record["fee"] or 0.0)
        if record["type"].lower() == "trade":
            summary["trade_count"] += 1
            summary["trade_change"] += change
        if "funding" in record["type"].lower():
            summary["funding"] += record["funding"] or change

    if wallet_values:
        summary["first_wallet_balance"] = wallet_values[0]
        summary["last_wallet_balance"] = wallet_values[-1]
        summary["wallet_balance_delta"] = wallet_values[-1] - wallet_values[0]

    return summary


def _summarize_by_symbol(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for record in records:
        symbol = record["symbol"] or "ACCOUNT"
        bucket = buckets.setdefault(
            symbol,
            {
                "symbol": symbol,
                "record_count": 0,
                "net_change": 0.0,
                "cash_flow": 0.0,
                "fees": 0.0,
                "latest_event_time": None,
            },
        )
        bucket["record_count"] += 1
        bucket["net_change"] += record["change"] or 0.0
        bucket["cash_flow"] += record["cash_flow"] or 0.0
        bucket["fees"] += abs(record["fee"] or 0.0)
        bucket["latest_event_time"] = record["event_time"]

    return sorted(buckets.values(), key=lambda item: abs(item["net_change"]), reverse=True)


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    event_ms = _event_ms(record)
    return {
        "event_time": datetime.fromtimestamp(event_ms / 1000, tz=UTC).isoformat() if event_ms else None,
        "symbol": str(record.get("symbol") or record.get("contract") or "").upper(),
        "type": str(record.get("type") or record.get("transactionType") or ""),
        "direction": str(record.get("side") or record.get("direction") or ""),
        "quantity": _number(record.get("qty") or record.get("quantity") or record.get("execQty")),
        "filled_price": _number(record.get("tradePrice") or record.get("filledPrice") or record.get("execPrice") or record.get("price")),
        "fee": _number(record.get("fee") or record.get("feePaid") or record.get("execFee")),
        "funding": _number(record.get("funding") or record.get("fundingFee")),
        "cash_flow": _number(record.get("cashFlow")),
        "change": _number(record.get("change")),
        "wallet_balance": _number(record.get("cashBalance") or record.get("walletBalance")),
        "transaction_id": str(record.get("id") or record.get("transactionId") or record.get("execId") or record.get("orderId") or ""),
    }


def _event_ms(record: dict[str, Any]) -> int | None:
    for key in ("transactionTime", "transactTime", "execTime", "createdTime", "updatedTime"):
        try:
            value = int(record.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


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
