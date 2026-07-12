from __future__ import annotations

from typing import Any

from app.scanner_trend import (
    TREND_DOWN,
    TREND_INSUFFICIENT,
    TREND_SIDEWAYS,
    TREND_UP,
    direction_allowed,
)
from app.strategy import evaluate_registered_strategies


VALID_TRADE_TYPES = {"scalping", "intraday"}
STRUCTURE_STRATEGIES = {"pure_smc", "hybrid"}


def evaluate_signal_contexts(contexts: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate strategies only after Scanner has produced eligible ranked contexts."""

    results: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []

    ordered_contexts = sorted(
        contexts,
        key=lambda item: (
            int(item.get("market_rank") or 9999),
            str(item.get("symbol") or ""),
            str(item.get("trade_type") or ""),
        ),
    )

    for context in ordered_contexts:
        trade_type = _normalize_trade_type(context.get("trade_type"))
        if trade_type is None:
            results.append(_invalid_context_result(context, "trade_type_missing_or_invalid"))
            continue

        strategy_results = evaluate_registered_strategies(
            symbol=str(context.get("symbol") or ""),
            candles_5m=list(context.get("setup_candles") or []),
            candles_1m=list(context.get("trigger_candles") or []),
        )
        for result in strategy_results:
            normalized = normalize_strategy_result(
                symbol=str(context.get("symbol") or ""),
                result=result,
                trade_type=trade_type,
                market_rank=int(context.get("market_rank") or 0),
                trend=dict(context.get("trend") or {}),
                market_ranking=dict(context.get("market_ranking") or {}),
                scanner_logic=dict(context.get("scanner_logic") or {}),
                timeframes=dict(context.get("timeframes") or {}),
            )
            results.append(normalized)
            if normalized.get("direction") and normalized.get("status") == "active":
                signals.append(normalized)

    signals.sort(key=_signal_sort_key)
    results.sort(key=_result_sort_key)
    return {
        "signals": signals,
        "results": results,
        "signals_found": len(signals),
        "strategy_checks": len(results),
    }


def normalize_strategy_result(
    *,
    symbol: str,
    result: dict[str, Any],
    trend: dict[str, Any],
    market_ranking: dict[str, Any],
    scanner_logic: dict[str, Any],
    trade_type: str | None = None,
    market_rank: int | None = None,
    timeframes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the shared signal contract without silently selecting a trade profile."""

    original_status = result.get("status")
    direction = result.get("direction")
    strategy_name = str(result.get("strategy_name") or result.get("strategy") or "")
    selected_trade_type = _normalize_trade_type(trade_type or result.get("trade_type"))
    selected_timeframes = dict(timeframes or {})

    normalized = {
        "symbol": symbol,
        "market_rank": market_rank,
        "strategy_name": strategy_name,
        "strategy": result.get("strategy") or result.get("strategy_name"),
        "trade_type": selected_trade_type,
        "direction": direction,
        "entry": result.get("entry"),
        "stop_loss": result.get("stop_loss"),
        "take_profit": result.get("take_profit"),
        "risk_reward": result.get("risk_reward"),
        "detected_at": result.get("detected_at"),
        "status": original_status,
        "confidence_score": result.get("confidence_score"),
        "rejection_reason": result.get("rejection_reason"),
        "trend_state": trend.get("state"),
        "trend_strength": trend.get("strength"),
        "trend_reason": trend.get("reason"),
        "trend_aligned": direction_allowed(str(trend.get("state") or ""), direction),
        "market_score": market_ranking.get("score"),
        "market_score_components": market_ranking.get("components"),
        "scanner_logic_status": scanner_logic.get("status"),
        "scanner_logic_direction": scanner_logic.get("direction"),
        "scanner_logic_reason": scanner_logic.get("reason"),
        "scanner_logic_confidence": scanner_logic.get("confidence_score"),
        "setup_15m": scanner_logic.get("setup_15m"),
        "confirmation_5m": scanner_logic.get("confirmation_5m"),
        "timeframes": selected_timeframes,
    }

    if selected_trade_type is None:
        normalized["status"] = "blocked"
        normalized["rejection_reason"] = "trade_type_missing_or_invalid"
        return normalized

    if direction and original_status in {"active", "near_setup"} and not normalized["trend_aligned"]:
        normalized["original_status"] = original_status
        normalized["status"] = "blocked"
        normalized["rejection_reason"] = _trend_block_reason(str(trend.get("state") or ""), str(direction))
        return normalized

    if (
        selected_trade_type == "intraday"
        and strategy_name.lower() in STRUCTURE_STRATEGIES
        and direction
        and original_status in {"active", "near_setup"}
    ):
        _apply_structure_gate(normalized, scanner_logic)

    return normalized


def _apply_structure_gate(normalized: dict[str, Any], scanner_logic: dict[str, Any]) -> None:
    original_status = str(normalized.get("status") or "")
    direction = str(normalized.get("direction") or "").lower()
    logic_direction = str(scanner_logic.get("direction") or "").lower()
    logic_status = str(scanner_logic.get("status") or "")

    if logic_direction and logic_direction != direction:
        normalized["original_status"] = original_status
        normalized["status"] = "blocked"
        normalized["rejection_reason"] = "scanner_logic_direction_mismatch"
        return

    if original_status == "active" and logic_status != "active":
        normalized["original_status"] = original_status
        normalized["status"] = "near_setup" if logic_status == "near_setup" else "blocked"
        normalized["rejection_reason"] = scanner_logic.get("reason") or "scanner_logic_not_confirmed"
        return

    if original_status == "near_setup" and logic_status in {"blocked", "rejected"}:
        normalized["original_status"] = original_status
        normalized["status"] = "blocked"
        normalized["rejection_reason"] = scanner_logic.get("reason") or "scanner_logic_not_confirmed"


def _invalid_context_result(context: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "symbol": context.get("symbol"),
        "market_rank": context.get("market_rank"),
        "strategy_name": None,
        "strategy": None,
        "trade_type": None,
        "direction": None,
        "entry": None,
        "stop_loss": None,
        "take_profit": None,
        "risk_reward": None,
        "detected_at": None,
        "status": "blocked",
        "confidence_score": None,
        "rejection_reason": reason,
        "trend_state": (context.get("trend") or {}).get("state"),
        "trend_strength": (context.get("trend") or {}).get("strength"),
        "market_score": (context.get("market_ranking") or {}).get("score"),
        "timeframes": dict(context.get("timeframes") or {}),
    }


def _normalize_trade_type(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in VALID_TRADE_TYPES else None


def _trend_block_reason(trend_state: str, direction: str) -> str:
    if trend_state == TREND_SIDEWAYS:
        return "trend_sideways"
    if trend_state == TREND_INSUFFICIENT:
        return "trend_insufficient_data"
    if trend_state == "STALE_DATA":
        return "trend_stale_data"
    if trend_state == TREND_UP and direction.lower() != "long":
        return "trend_conflict_uptrend_long_only"
    if trend_state == TREND_DOWN and direction.lower() != "short":
        return "trend_conflict_downtrend_short_only"
    return "trend_not_aligned"


def _signal_sort_key(item: dict[str, Any]) -> tuple[int, float, float, str, str, str]:
    return (
        int(item.get("market_rank") or 9999),
        -float(item.get("market_score") or 0.0),
        -float(item.get("confidence_score") or 0.0),
        str(item.get("symbol") or ""),
        str(item.get("trade_type") or ""),
        str(item.get("strategy_name") or ""),
    )


def _result_sort_key(item: dict[str, Any]) -> tuple[int, int, float, str, str, str]:
    priority = {"active": 0, "near_setup": 1, "blocked": 2, "rejected": 3, "expired": 4}
    return (
        priority.get(str(item.get("status") or ""), 9),
        int(item.get("market_rank") or 9999),
        -float(item.get("confidence_score") or 0.0),
        str(item.get("symbol") or ""),
        str(item.get("trade_type") or ""),
        str(item.get("strategy_name") or ""),
    )
