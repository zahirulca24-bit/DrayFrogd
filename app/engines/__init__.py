from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from app.engines import intraday, scalping
from app.engines.profiles import ENGINE_PROFILES, INTRADAY_PROFILE, SCALPING_PROFILE, EngineProfile, get_engine_profile


StrategyEvaluator = Callable[[str, list[dict[str, Any]], list[dict[str, Any]], datetime | None], list[dict[str, Any]]]


def build_engine_context(
    trade_type: str,
    *,
    symbol: str,
    trend: dict[str, Any],
    scanner_logic: dict[str, Any],
    setup_candles: list[dict[str, Any]],
    trigger_candles: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized = get_engine_profile(trade_type).trade_type
    builder = scalping.build_context if normalized == "scalping" else intraday.build_context
    return builder(
        symbol=symbol,
        trend=trend,
        scanner_logic=scanner_logic,
        setup_candles=setup_candles,
        trigger_candles=trigger_candles,
    )


def evaluate_engine_strategies(
    trade_type: str,
    *,
    symbol: str,
    setup_candles: list[dict[str, Any]],
    trigger_candles: list[dict[str, Any]],
    evaluator: StrategyEvaluator,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    normalized = get_engine_profile(trade_type).trade_type
    engine = scalping if normalized == "scalping" else intraday
    return engine.evaluate_strategies(
        symbol=symbol,
        setup_candles=setup_candles,
        trigger_candles=trigger_candles,
        evaluator=evaluator,
        now=now,
    )


__all__ = [
    "ENGINE_PROFILES",
    "EngineProfile",
    "INTRADAY_PROFILE",
    "SCALPING_PROFILE",
    "build_engine_context",
    "evaluate_engine_strategies",
    "get_engine_profile",
]
