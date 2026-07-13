from __future__ import annotations

import hashlib
from datetime import UTC, datetime, time
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

from app.close_fill_sync import aggregate_transaction_log_records


BDT = ZoneInfo("Asia/Dhaka")


def get_strategy_audit(
    client: Any,
    *,
    journal_trades: list[dict[str, Any]],
    bdt_date: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    target_day = _parse_bdt_date(bdt_date) or datetime.now(BDT).date()
    start = datetime.combine(target_day, time.min, tzinfo=BDT).astimezone(UTC)
    end = datetime.now(UTC)
    ok, ledger_records, error = client.safe_fetch_transaction_log(
        start_time=int(start.timestamp() * 1000),
        end_time=int(end.timestamp() * 1000),
        limit=max(1, min(limit, 500)),
    )

    if not ok:
        return {
            "ok": False,
            "date": target_day.isoformat(),
            "error": error or "Bybit transaction log query failed",
            "summary": _empty_summary(),
            "strategies": [],
            "trades": [],
        }

    return build_strategy_audit(
        journal_trades=journal_trades,
        ledger_records=ledger_records,
        bdt_date=target_day.isoformat(),
    )


def build_strategy_audit(
    *,
    journal_trades: list[dict[str, Any]],
    ledger_records: list[dict[str, Any]],
    bdt_date: str,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    used_record_keys: set[str] = set()
    eligible_trades = [
        trade
        for trade in journal_trades
        if _belongs_to_bdt_day(trade.get("closed_at") or trade.get("opened_at") or trade.get("detected_at"), bdt_date)
    ]

    for trade in sorted(eligible_trades, key=lambda item: _timestamp_ms(item.get("opened_at") or item.get("detected_at")) or 0):
        candidate_records = [
            record
            for record in ledger_records
            if _record_key(record) not in used_record_keys
            and str(record.get("symbol") or record.get("contract") or "").upper() == str(trade.get("symbol") or "").upper()
        ]
        ledger_result, ledger_error = aggregate_transaction_log_records(trade, candidate_records)
        row = _row_from_trade(trade)

        if ledger_result is not None:
            close_sync = ledger_result.get("exchange_metadata", {}).get("close_sync", {})
            for record_key in close_sync.get("record_keys") or []:
                used_record_keys.add(str(record_key))
            row.update(
                {
                    "status": "closed",
                    "result": ledger_result.get("result") or _classify_result(ledger_result.get("realized_pnl")),
                    "realized_pnl": _number(ledger_result.get("realized_pnl")),
                    "fees": _number(ledger_result.get("fees")),
                    "exit_price": _number(ledger_result.get("exit_price")),
                    "closed_at": ledger_result.get("closed_at") or row["closed_at"],
                    "pnl_source": "bybit_ledger",
                    "pnl_known": True,
                    "audit_note": "Bybit transaction log matched journal identity.",
                    "ledger_record_count": len(close_sync.get("records") or []),
                }
            )
        else:
            journal_pnl = _number(trade.get("realized_pnl"))
            if journal_pnl is not None:
                row.update(
                    {
                        "result": _classify_result(journal_pnl),
                        "realized_pnl": journal_pnl,
                        "fees": _number(trade.get("fees")),
                        "pnl_source": "journal",
                        "pnl_known": True,
                        "audit_note": "Bybit ledger match unavailable; using persisted journal realized PnL.",
                    }
                )
            else:
                row.update(
                    {
                        "pnl_source": "unmatched",
                        "pnl_known": False,
                        "audit_note": ledger_error or "No Bybit ledger close and no journal realized PnL.",
                    }
                )

        rows.append(row)

    strategies = _summarize_strategies(rows)
    known_rows = [row for row in rows if row["pnl_known"]]
    summary = {
        "trade_count": len(rows),
        "known_pnl_trades": len(known_rows),
        "ledger_matched_trades": sum(1 for row in rows if row["pnl_source"] == "bybit_ledger"),
        "journal_fallback_trades": sum(1 for row in rows if row["pnl_source"] == "journal"),
        "unmatched_trades": sum(1 for row in rows if not row["pnl_known"]),
        "wins": sum(1 for row in known_rows if row["result"] == "profit"),
        "losses": sum(1 for row in known_rows if row["result"] == "loss"),
        "flats": sum(1 for row in known_rows if row["result"] == "flat"),
        "net_pnl": sum(float(row["realized_pnl"] or 0.0) for row in known_rows),
    }
    summary["win_rate"] = summary["wins"] / (summary["wins"] + summary["losses"]) if summary["wins"] + summary["losses"] else None

    return {
        "ok": True,
        "date": bdt_date,
        "error": None,
        "summary": summary,
        "strategies": strategies,
        "trades": list(reversed(rows)),
    }


def _summarize_strategies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        strategy = row["strategy"] or "unknown"
        bucket = buckets.setdefault(
            strategy,
            {
                "strategy": strategy,
                "trade_count": 0,
                "known_pnl_trades": 0,
                "ledger_matched_trades": 0,
                "journal_fallback_trades": 0,
                "unmatched_trades": 0,
                "wins": 0,
                "losses": 0,
                "flats": 0,
                "net_pnl": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "avg_win": None,
                "avg_loss": None,
                "win_rate": None,
            },
        )
        bucket["trade_count"] += 1
        bucket["ledger_matched_trades"] += 1 if row["pnl_source"] == "bybit_ledger" else 0
        bucket["journal_fallback_trades"] += 1 if row["pnl_source"] == "journal" else 0
        bucket["unmatched_trades"] += 1 if not row["pnl_known"] else 0

        if not row["pnl_known"]:
            continue

        pnl = float(row["realized_pnl"] or 0.0)
        bucket["known_pnl_trades"] += 1
        bucket["net_pnl"] += pnl
        if row["result"] == "profit":
            bucket["wins"] += 1
            bucket["gross_profit"] += pnl
        elif row["result"] == "loss":
            bucket["losses"] += 1
            bucket["gross_loss"] += abs(pnl)
        else:
            bucket["flats"] += 1

    for bucket in buckets.values():
        wins = int(bucket["wins"])
        losses = int(bucket["losses"])
        bucket["win_rate"] = wins / (wins + losses) if wins + losses else None
        bucket["avg_win"] = bucket["gross_profit"] / wins if wins else None
        bucket["avg_loss"] = -(bucket["gross_loss"] / losses) if losses else None

    return sorted(buckets.values(), key=lambda item: abs(float(item["net_pnl"] or 0.0)), reverse=True)


def _row_from_trade(trade: dict[str, Any]) -> dict[str, Any]:
    strategy = str(trade.get("strategy_name") or trade.get("strategy") or "unknown").strip() or "unknown"
    return {
        "journal_id": trade.get("journal_id"),
        "symbol": str(trade.get("symbol") or "").upper(),
        "strategy": strategy,
        "direction": str(trade.get("direction") or "").lower(),
        "status": str(trade.get("status") or "unknown").lower(),
        "opened_at": trade.get("opened_at") or trade.get("detected_at"),
        "closed_at": trade.get("closed_at"),
        "entry": _number(trade.get("entry")),
        "exit_price": _number(trade.get("exit_price")),
        "quantity": _number(trade.get("quantity")),
        "realized_pnl": None,
        "fees": None,
        "result": "unknown",
        "pnl_source": "unmatched",
        "pnl_known": False,
        "audit_note": None,
        "ledger_record_count": 0,
    }


def _empty_summary() -> dict[str, Any]:
    return {
        "trade_count": 0,
        "known_pnl_trades": 0,
        "ledger_matched_trades": 0,
        "journal_fallback_trades": 0,
        "unmatched_trades": 0,
        "wins": 0,
        "losses": 0,
        "flats": 0,
        "net_pnl": 0.0,
        "win_rate": None,
    }


def _classify_result(value: Any) -> str:
    numeric = _number(value)
    if numeric is None:
        return "unknown"
    if numeric > 0:
        return "profit"
    if numeric < 0:
        return "loss"
    return "flat"


def _belongs_to_bdt_day(value: Any, bdt_date: str) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(BDT).date().isoformat() == bdt_date


def _timestamp_ms(value: Any) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def _record_key(record: dict[str, Any]) -> str:
    for key in ("id", "transactionId", "orderId", "execId"):
        value = str(record.get(key) or "").strip()
        if value:
            return f"{key}:{value}"
    raw = "|".join(
        str(value or "")
        for value in (
            record.get("symbol") or record.get("contract"),
            record.get("direction") or record.get("side"),
            _ledger_event_ms(record),
            record.get("qty") or record.get("quantity") or record.get("execQty"),
            record.get("tradePrice") or record.get("filledPrice") or record.get("execPrice") or record.get("price"),
            record.get("change"),
        )
    )
    return f"transaction:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def _ledger_event_ms(record: dict[str, Any]) -> int | None:
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
