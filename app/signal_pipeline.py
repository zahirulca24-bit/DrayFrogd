from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
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
MIN_RISK_REWARD_BY_TRADE_TYPE = {
    "scalping": 1.5,
    "intraday": 2.0,
}

SIGNAL_NO_SETUP = "NO_SETUP"
SIGNAL_NEAR_SETUP = "NEAR_SETUP"
SIGNAL_ACTIVE = "ACTIVE"
SIGNAL_INVALID = "INVALID"
SIGNAL_EXPIRED = "EXPIRED"
CANONICAL_SIGNAL_STATES = {
    SIGNAL_NO_SETUP,
    SIGNAL_NEAR_SETUP,
    SIGNAL_ACTIVE,
    SIGNAL_INVALID,
    SIGNAL_EXPIRED,
}
USEFUL_SIGNAL_STATES = {SIGNAL_NEAR_SETUP, SIGNAL_ACTIVE}

_INVALID_REASONS = {
    "trade_type_missing_or_invalid",
    "invalid_trade_levels",
    "invalid_trade_geometry",
    "risk_reward_below_trade_type_minimum",
    "setup_invalidated",
    "opposite_pullback_structure",
    "scanner_logic_direction_mismatch",
    "trend_conflict_uptrend_long_only",
    "trend_conflict_downtrend_short_only",
    "trend_sideways",
    "trend_insufficient_data",
    "trend_stale_data",
    "trend_not_aligned",
}


def evaluate_signal_contexts(contexts: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate ranked Scanner contexts and return one primary useful signal per symbol."""

    results: list[dict[str, Any]] = []
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
            results.append(
                normalize_strategy_result(
                    symbol=str(context.get("symbol") or ""),
                    result=result,
                    trade_type=trade_type,
                    market_rank=int(context.get("market_rank") or 0),
                    trend=dict(context.get("trend") or {}),
                    market_ranking=dict(context.get("market_ranking") or {}),
                    scanner_logic=dict(context.get("scanner_logic") or {}),
                    timeframes=dict(context.get("timeframes") or {}),
                )
            )

    primary_signals = _select_primary_signals(results)
    active_signals = [item for item in primary_signals if item.get("signal_state") == SIGNAL_ACTIVE]
    monitoring_signals = [item for item in primary_signals if item.get("signal_state") == SIGNAL_NEAR_SETUP]

    for signal_rank, signal in enumerate(primary_signals, start=1):
        signal["signal_rank"] = signal_rank

    results.sort(key=_result_sort_key)
    state_counts = {state: 0 for state in sorted(CANONICAL_SIGNAL_STATES)}
    for result in results:
        state = str(result.get("signal_state") or SIGNAL_INVALID)
        state_counts[state] = state_counts.get(state, 0) + 1

    return {
        "signals": active_signals,
        "monitoring_signals": monitoring_signals,
        "primary_signals": primary_signals,
        "results": results,
        "signals_found": len(active_signals),
        "near_setups": len(monitoring_signals),
        "useful_signals": len(primary_signals),
        "strategy_checks": len(results),
        "state_counts": state_counts,
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
    """Normalize raw strategy output into the shared five-state signal contract."""

    original_status = str(result.get("status") or "")
    direction = _normalize_direction(result.get("direction"))
    strategy_name = str(result.get("strategy_name") or result.get("strategy") or "")
    selected_trade_type = _normalize_trade_type(trade_type or result.get("trade_type"))

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
        "raw_status": original_status,
        "status": original_status,
        "signal_state": _canonical_state(original_status, result.get("rejection_reason")),
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
        "timeframes": dict(timeframes or {}),
        "primary_signal": False,
    }

    if selected_trade_type is None:
        _set_signal_state(normalized, SIGNAL_INVALID, "trade_type_missing_or_invalid")
    elif direction and normalized["signal_state"] in USEFUL_SIGNAL_STATES and not normalized["trend_aligned"]:
        _set_signal_state(
            normalized,
            SIGNAL_INVALID,
            _trend_block_reason(str(trend.get("state") or ""), direction),
        )
    elif (
        selected_trade_type == "intraday"
        and strategy_name.lower() in STRUCTURE_STRATEGIES
        and direction
        and normalized["signal_state"] in USEFUL_SIGNAL_STATES
    ):
        _apply_structure_gate(normalized, scanner_logic)

    geometry_valid = _valid_trade_geometry(normalized)
    if normalized["signal_state"] in USEFUL_SIGNAL_STATES and not geometry_valid:
        _set_signal_state(normalized, SIGNAL_INVALID, "invalid_trade_geometry")
    elif normalized["signal_state"] in USEFUL_SIGNAL_STATES and not _meets_trade_type_rr_minimum(normalized):
        _set_signal_state(normalized, SIGNAL_INVALID, "risk_reward_below_trade_type_minimum")

    normalized["geometry_valid"] = geometry_valid
    normalized["is_executable"] = normalized["signal_state"] == SIGNAL_ACTIVE and geometry_valid
    normalized["monitor_only"] = normalized["signal_state"] == SIGNAL_NEAR_SETUP and geometry_valid
    normalized["signal_score"] = _signal_score(normalized)
    normalized["signal_key"] = _signal_key(normalized)
    return normalized


def _select_primary_signals(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        if result.get("signal_state") not in USEFUL_SIGNAL_STATES:
            continue
        if not result.get("geometry_valid") or not result.get("direction"):
            continue
        grouped.setdefault(str(result.get("symbol") or ""), []).append(result)

    primary_signals: list[dict[str, Any]] = []
    for symbol in sorted(grouped):
        candidates = sorted(grouped[symbol], key=_primary_sort_key)
        primary = candidates[0]
        primary["primary_signal"] = True

        confirmations: list[dict[str, Any]] = []
        alternates: list[dict[str, Any]] = []
        for candidate in candidates[1:]:
            summary = _match_summary(candidate)
            if candidate.get("direction") == primary.get("direction"):
                confirmations.append(summary)
            else:
                alternates.append(summary)

        primary["confirmations"] = confirmations
        primary["confirmation_count"] = len(confirmations)
        primary["alternate_matches"] = alternates
        primary["matched_strategies"] = sorted(
            {
                str(candidate.get("strategy_name") or "")
                for candidate in candidates
                if candidate.get("strategy_name")
            }
        )
        primary_signals.append(primary)

    primary_signals.sort(key=_primary_sort_key)
    return primary_signals


def _apply_structure_gate(normalized: dict[str, Any], scanner_logic: dict[str, Any]) -> None:
    direction = str(normalized.get("direction") or "").lower()
    logic_direction = str(scanner_logic.get("direction") or "").lower()
    logic_status = str(scanner_logic.get("status") or "").lower()

    if logic_direction and logic_direction != direction:
        _set_signal_state(normalized, SIGNAL_INVALID, "scanner_logic_direction_mismatch")
        return

    if normalized.get("signal_state") == SIGNAL_ACTIVE and logic_status != "active":
        if logic_status == "near_setup":
            _set_signal_state(
                normalized,
                SIGNAL_NEAR_SETUP,
                scanner_logic.get("reason") or "scanner_logic_not_confirmed",
            )
        else:
            _set_signal_state(
                normalized,
                SIGNAL_NO_SETUP,
                scanner_logic.get("reason") or "scanner_logic_not_confirmed",
            )
        return

    if normalized.get("signal_state") == SIGNAL_NEAR_SETUP and logic_status in {"blocked", "rejected"}:
        _set_signal_state(
            normalized,
            SIGNAL_NO_SETUP,
            scanner_logic.get("reason") or "scanner_logic_not_confirmed",
        )


def _invalid_context_result(context: dict[str, Any], reason: str) -> dict[str, Any]:
    result = {
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
        "raw_status": "blocked",
        "status": "invalid",
        "signal_state": SIGNAL_INVALID,
        "confidence_score": None,
        "rejection_reason": reason,
        "trend_state": (context.get("trend") or {}).get("state"),
        "trend_strength": (context.get("trend") or {}).get("strength"),
        "market_score": (context.get("market_ranking") or {}).get("score"),
        "timeframes": dict(context.get("timeframes") or {}),
        "geometry_valid": False,
        "is_executable": False,
        "monitor_only": False,
        "primary_signal": False,
    }
    result["signal_score"] = _signal_score(result)
    result["signal_key"] = _signal_key(result)
    return result


def _canonical_state(status: Any, reason: Any) -> str:
    normalized_status = str(status or "").strip().upper()
    normalized_reason = str(reason or "").strip().lower()
    if normalized_status in CANONICAL_SIGNAL_STATES:
        return normalized_status
    if normalized_status == "ACTIVE":
        return SIGNAL_ACTIVE
    if normalized_status in {"NEAR_SETUP", "NEAR"}:
        return SIGNAL_NEAR_SETUP
    if normalized_status == "EXPIRED" or normalized_reason == "signal_expired":
        return SIGNAL_EXPIRED
    if normalized_status == "INVALID" or normalized_reason in _INVALID_REASONS:
        return SIGNAL_INVALID
    return SIGNAL_NO_SETUP


def _set_signal_state(result: dict[str, Any], state: str, reason: Any = None) -> None:
    result["signal_state"] = state
    result["status"] = _legacy_status(state)
    if reason is not None:
        result["rejection_reason"] = reason


def _legacy_status(state: str) -> str:
    return {
        SIGNAL_ACTIVE: "active",
        SIGNAL_NEAR_SETUP: "near_setup",
        SIGNAL_EXPIRED: "expired",
        SIGNAL_INVALID: "invalid",
        SIGNAL_NO_SETUP: "no_setup",
    }.get(state, "invalid")


def _normalize_trade_type(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in VALID_TRADE_TYPES else None


def _normalize_direction(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {"long", "short"} else None


def _valid_trade_geometry(item: dict[str, Any]) -> bool:
    direction = _normalize_direction(item.get("direction"))
    entry = _number(item.get("entry"))
    stop_loss = _number(item.get("stop_loss"))
    take_profit = _number(item.get("take_profit"))
    risk_reward = _number(item.get("risk_reward"))
    if direction is None or None in {entry, stop_loss, take_profit, risk_reward}:
        return False
    if risk_reward is None or risk_reward <= 0:
        return False
    if direction == "long":
        return stop_loss < entry < take_profit
    return take_profit < entry < stop_loss


def _meets_trade_type_rr_minimum(item: dict[str, Any]) -> bool:
    trade_type = _normalize_trade_type(item.get("trade_type"))
    risk_reward = _number(item.get("risk_reward"))
    if trade_type is None or risk_reward is None:
        return False
    return risk_reward + 1e-9 >= MIN_RISK_REWARD_BY_TRADE_TYPE[trade_type]


def _signal_score(item: dict[str, Any]) -> float:
    state_score = {
        SIGNAL_ACTIVE: 40.0,
        SIGNAL_NEAR_SETUP: 20.0,
        SIGNAL_NO_SETUP: 0.0,
        SIGNAL_INVALID: 0.0,
        SIGNAL_EXPIRED: 0.0,
    }.get(str(item.get("signal_state") or ""), 0.0)
    confidence = max(0.0, min(_number(item.get("confidence_score")) or 0.0, 100.0)) * 0.30
    risk_reward = max(0.0, min(_number(item.get("risk_reward")) or 0.0, 4.0)) * 5.0
    market_score = max(0.0, min(_number(item.get("market_score")) or 0.0, 100.0)) * 0.08
    market_rank = max(1, int(_number(item.get("market_rank")) or 9999))
    rank_score = max(0.0, 10.0 - ((market_rank - 1) * 0.3))
    geometry_score = 5.0 if item.get("geometry_valid") else 0.0
    return round(min(100.0, state_score + confidence + risk_reward + market_score + rank_score + geometry_score), 2)


def _signal_key(item: dict[str, Any]) -> str:
    return "|".join(
        [
            str(item.get("symbol") or ""),
            str(item.get("trade_type") or ""),
            str(item.get("strategy_name") or ""),
            str(item.get("direction") or ""),
            str(item.get("detected_at") or ""),
        ]
    )


def _match_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_key": item.get("signal_key"),
        "strategy_name": item.get("strategy_name"),
        "trade_type": item.get("trade_type"),
        "direction": item.get("direction"),
        "signal_state": item.get("signal_state"),
        "confidence_score": item.get("confidence_score"),
        "risk_reward": item.get("risk_reward"),
        "detected_at": item.get("detected_at"),
        "signal_score": item.get("signal_score"),
    }


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


def _primary_sort_key(item: dict[str, Any]) -> tuple[int, float, int, float, str, str, str]:
    state_priority = {SIGNAL_ACTIVE: 0, SIGNAL_NEAR_SETUP: 1}
    return (
        state_priority.get(str(item.get("signal_state") or ""), 9),
        -float(item.get("signal_score") or 0.0),
        int(item.get("market_rank") or 9999),
        -_timestamp_value(item.get("detected_at")),
        str(item.get("trade_type") or ""),
        str(item.get("strategy_name") or ""),
        str(item.get("signal_key") or ""),
    )


def _result_sort_key(item: dict[str, Any]) -> tuple[int, int, float, float, str, str, str]:
    priority = {
        SIGNAL_ACTIVE: 0,
        SIGNAL_NEAR_SETUP: 1,
        SIGNAL_NO_SETUP: 2,
        SIGNAL_INVALID: 3,
        SIGNAL_EXPIRED: 4,
    }
    return (
        priority.get(str(item.get("signal_state") or ""), 9),
        int(item.get("market_rank") or 9999),
        -float(item.get("signal_score") or 0.0),
        -_timestamp_value(item.get("detected_at")),
        str(item.get("symbol") or ""),
        str(item.get("trade_type") or ""),
        str(item.get("strategy_name") or ""),
    )


def _timestamp_value(value: Any) -> float:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
    else:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).timestamp()


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None
