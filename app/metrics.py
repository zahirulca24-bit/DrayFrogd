from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

from app.authoritative_state import get_snapshot
from app.execution import get_active_trades, get_closed_trades
from app.journal import get_closed_trade_history, get_trade_history


BDT = ZoneInfo("Asia/Dhaka")


def get_metrics(now: datetime | None = None) -> dict[str, Any]:
    snapshot = get_snapshot()
    active_trades = list(snapshot.get("trades") or []) if int(snapshot.get("version") or 0) > 0 else get_active_trades()
    closed_trades = get_closed_trades() or get_closed_trade_history()
    total_trades = len(active_trades) + len(closed_trades)
    outcomes = [_classify_outcome(trade) for trade in closed_trades]
    win_trades = sum(1 for outcome in outcomes if outcome == "win")
    loss_trades = sum(1 for outcome in outcomes if outcome == "loss")
    known_closed_trades = win_trades + loss_trades
    win_rate = (win_trades / known_closed_trades) if known_closed_trades else 0.0
    pnl_r = (win_trades * 2.0) - loss_trades
    current = now or datetime.now(UTC)
    journal_trades = get_trade_history(limit=1000)
    today_realized_pnl, today_fees = _today_financials(journal_trades, current)

    return {
        "total_trades": total_trades,
        "active_trades_count": len(active_trades),
        "closed_trades_count": len(closed_trades),
        "win_trades": win_trades,
        "loss_trades": loss_trades,
        "known_closed_trades": known_closed_trades,
        "unknown_closed_trades": max(len(closed_trades) - known_closed_trades, 0),
        "win_rate": round(win_rate, 4),
        "pnl_r": round(pnl_r, 4),
        "today_realized_pnl": round(today_realized_pnl, 8),
        "today_fees": round(today_fees, 8),
        "daily_accounting_timezone": "Asia/Dhaka",
    }


def get_portfolio_summary() -> dict[str, Any]:
    metrics = get_metrics()
    return {
        "active_trades": metrics["active_trades_count"],
        "closed_trades": metrics["closed_trades_count"],
        "total_trades": metrics["total_trades"],
        "win_rate": metrics["win_rate"],
        "pnl_r": metrics["pnl_r"],
        "today_realized_pnl": metrics["today_realized_pnl"],
        "today_fees": metrics["today_fees"],
        "execution_mode": str(get_snapshot().get("mode") or next((trade.get("execution_mode") for trade in get_active_trades() if trade.get("execution_mode")), "demo")),
    }


def _today_financials(trades: list[dict[str, Any]], now: datetime) -> tuple[float, float]:
    today = now.astimezone(BDT).date().isoformat()
    realized = 0.0
    fees = 0.0

    for trade in trades:
        status = str(trade.get("status") or "").lower()
        metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
        partial = metadata.get("partial_close_sync") if isinstance(metadata.get("partial_close_sync"), dict) else {}
        if not partial:
            partial = metadata.get("risk_realized_progress") if isinstance(metadata.get("risk_realized_progress"), dict) else {}

        if status != "closed":
            pnl_by_day = partial.get("pnl_by_bdt_day") if isinstance(partial.get("pnl_by_bdt_day"), dict) else {}
            fees_by_day = partial.get("fees_by_bdt_day") if isinstance(partial.get("fees_by_bdt_day"), dict) else {}
            realized += _number(pnl_by_day.get(today)) or 0.0
            fees += abs(_number(fees_by_day.get(today)) or 0.0)
            continue

        closed_at = _parse_time(trade.get("closed_at"))
        if closed_at is None or closed_at.astimezone(BDT).date().isoformat() != today:
            continue
        realized += _number(trade.get("realized_pnl")) or 0.0
        fees += abs(_number(trade.get("fees")) or 0.0)

    return realized, fees


def _classify_outcome(trade: dict[str, Any]) -> str:
    realized_pnl = _number(trade.get("realized_pnl"))
    if realized_pnl is not None:
        if realized_pnl > 0:
            return "win"
        if realized_pnl < 0:
            return "loss"
        return "flat"

    result = str(trade.get("result") or "").lower().strip()
    if result in {"tp", "profit", "win", "take_profit"}:
        return "win"
    if result in {"sl", "loss", "stop_loss"}:
        return "loss"
    if result in {"flat", "breakeven", "break_even"}:
        return "flat"
    return "unknown"


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None
