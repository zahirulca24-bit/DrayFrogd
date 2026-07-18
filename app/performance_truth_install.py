from __future__ import annotations

from typing import Any

from app.performance_truth import (
    annotate_trade_truth,
    filter_performance_trades,
    journal_daily_financial_eligible,
)

_INSTALLED = False


class AuthoritativeTradeHistory(list[dict[str, Any]]):
    """A serializable list that remains truthy when no eligible closes exist.

    Existing endpoints use ``filtered or legacy_fallback``. Returning a truthy empty
    list prevents rejected or incomplete legacy rows from re-entering the response.
    """

    def __bool__(self) -> bool:
        return True


def install() -> None:
    """Install shared annotations and operational/performance truth filtering."""

    global _INSTALLED
    if _INSTALLED:
        return

    from app import execution, journal, metrics

    if getattr(journal, "_P0_1F_PERFORMANCE_TRUTH_INSTALLED", False):
        _INSTALLED = True
        return

    original_serialize = journal.serialize_trade_entry
    original_closed_history = metrics.get_closed_trade_history
    original_closed_memory = metrics.get_closed_trades
    original_today_financials = metrics._today_financials

    def serialize_trade_entry(row: Any) -> dict[str, Any]:
        return annotate_trade_truth(original_serialize(row))

    def eligible_closed_history(limit: int = 100) -> AuthoritativeTradeHistory:
        requested = max(int(limit), 1)
        scan_limit = max(requested * 10, 1000)
        eligible = filter_performance_trades(original_closed_history(limit=scan_limit))
        return AuthoritativeTradeHistory(eligible[:requested])

    def eligible_closed_trades() -> AuthoritativeTradeHistory:
        durable = original_closed_history(limit=1000)
        memory = original_closed_memory()
        eligible = filter_performance_trades(_merge_closed_truth(durable, memory))
        return AuthoritativeTradeHistory(eligible)

    def today_financials(
        trades: list[dict[str, Any]],
        now: Any,
    ) -> tuple[float, float, int]:
        safe_rows = [trade for trade in trades if journal_daily_financial_eligible(trade)]
        return original_today_financials(safe_rows, now)

    journal.serialize_trade_entry = serialize_trade_entry

    # Metrics and the operational /trade-history endpoint must use the same closed
    # trade authority, while execution_core lifecycle storage remains untouched.
    metrics.get_closed_trades = eligible_closed_trades
    metrics.get_closed_trade_history = eligible_closed_history
    metrics._today_financials = today_financials
    execution.get_closed_trades = eligible_closed_trades

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
