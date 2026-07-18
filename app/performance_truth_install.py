from __future__ import annotations

from typing import Any

from app.performance_truth import annotate_trade_truth, filter_performance_trades

_INSTALLED = False


def install() -> None:
    """Install one trade-count/performance authority across Journal and APIs."""

    global _INSTALLED
    if _INSTALLED:
        return

    from app import execution_core, journal, metrics, strategy_audit

    if getattr(journal, "_P0_1F_PERFORMANCE_TRUTH_INSTALLED", False):
        _INSTALLED = True
        return

    original_serialize = journal.serialize_trade_entry
    original_closed_history = journal.get_closed_trade_history
    original_closed_memory = execution_core.get_closed_trades
    original_today_financials = metrics._today_financials
    original_strategy_audit = strategy_audit.build_strategy_audit

    def serialize_trade_entry(row: Any) -> dict[str, Any]:
        return annotate_trade_truth(original_serialize(row))

    def get_closed_trade_history(limit: int = 100) -> list[dict[str, Any]]:
        requested = max(int(limit), 1)
        scan_limit = max(requested * 10, 1000)
        eligible = filter_performance_trades(original_closed_history(limit=scan_limit))
        return eligible[:requested]

    def get_closed_trades() -> list[dict[str, Any]]:
        durable = original_closed_history(limit=1000)
        memory = original_closed_memory()
        return filter_performance_trades(_merge_closed_truth(durable, memory))

    def today_financials(
        trades: list[dict[str, Any]],
        now: Any,
    ) -> tuple[float, float, int]:
        safe_rows = []
        for trade in trades:
            annotated = annotate_trade_truth(trade)
            if str(annotated.get("status") or "").lower() == "closed" and not annotated["performance_eligible"]:
                continue
            safe_rows.append(annotated)
        return original_today_financials(safe_rows, now)

    def build_strategy_audit(
        *,
        journal_trades: list[dict[str, Any]],
        ledger_records: list[dict[str, Any]],
        bdt_date: str,
    ) -> dict[str, Any]:
        return original_strategy_audit(
            journal_trades=filter_performance_trades(journal_trades),
            ledger_records=ledger_records,
            bdt_date=bdt_date,
        )

    journal.serialize_trade_entry = serialize_trade_entry
    journal.get_closed_trade_history = get_closed_trade_history
    execution_core.get_closed_trades = get_closed_trades
    metrics._today_financials = today_financials
    strategy_audit.build_strategy_audit = build_strategy_audit

    # Modules may already hold imported aliases during tests or reloads.
    try:
        from app import execution

        execution.get_closed_trades = get_closed_trades
    except Exception:
        pass

    metrics.get_closed_trades = get_closed_trades
    metrics.get_closed_trade_history = get_closed_trade_history

    journal._P0_1F_PERFORMANCE_TRUTH_INSTALLED = True
    _INSTALLED = True


def _merge_closed_truth(
    durable_rows: list[dict[str, Any]],
    memory_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Prefer durable Journal evidence and add only non-duplicate memory rows."""

    merged: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    for trade in [*durable_rows, *memory_rows]:
        if not isinstance(trade, dict):
            continue
        tokens = _trade_identity_tokens(trade)
        if tokens.intersection(seen_tokens):
            continue
        seen_tokens.update(tokens)
        merged.append(dict(trade))
    return merged


def _trade_identity_tokens(trade: dict[str, Any]) -> set[str]:
    tokens = {
        f"{field}:{value}"
        for field in ("journal_id", "execution_key", "order_id")
        if (value := str(trade.get(field) or "").strip())
    }
    if tokens:
        return tokens
    return {_fallback_identity(trade)}


def _trade_identity_key(trade: dict[str, Any]) -> str:
    """Compatibility helper returning one stable key for focused tests/callers."""

    for field in ("journal_id", "execution_key", "order_id"):
        value = str(trade.get(field) or "").strip()
        if value:
            return f"{field}:{value}"
    return _fallback_identity(trade)


def _fallback_identity(trade: dict[str, Any]) -> str:
    return "fallback:" + "|".join(
        [
            str(trade.get("symbol") or "").upper(),
            str(trade.get("direction") or "").lower(),
            str(trade.get("opened_at") or trade.get("detected_at") or ""),
            str(trade.get("quantity") or ""),
        ]
    )
