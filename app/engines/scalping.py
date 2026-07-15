from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from app.engines.profiles import SCALPING_PROFILE, apply_strategy_profile


StrategyEvaluator = Callable[[str, list[dict[str, Any]], list[dict[str, Any]], datetime | None], list[dict[str, Any]]]


def build_context(
    *,
    symbol: str,
    trend: dict[str, Any],
    scanner_logic: dict[str, Any],
    setup_candles: list[dict[str, Any]],
    trigger_candles: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "trade_type": SCALPING_PROFILE.trade_type,
        "engine_profile": SCALPING_PROFILE.trade_type,
        "trend": dict(trend),
        "scanner_logic": dict(scanner_logic),
        "setup_candles": list(setup_candles),
        "trigger_candles": list(trigger_candles),
        "timeframes": SCALPING_PROFILE.timeframes(),
        "risk_contract": SCALPING_PROFILE.risk_contract(),
    }


def evaluate_strategies(
    *,
    symbol: str,
    setup_candles: list[dict[str, Any]],
    trigger_candles: list[dict[str, Any]],
    evaluator: StrategyEvaluator,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    raw_results = evaluator(symbol, setup_candles, trigger_candles, now)
    return [apply_strategy_profile(result, SCALPING_PROFILE) for result in raw_results]
