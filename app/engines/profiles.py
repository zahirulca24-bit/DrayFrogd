from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any


@dataclass(frozen=True, slots=True)
class EngineProfile:
    trade_type: str
    profile_name: str
    trend_interval: str
    trend_label: str
    trend_minutes: int
    setup_interval: str
    setup_label: str
    setup_minutes: int
    trigger_interval: str
    trigger_label: str
    trigger_minutes: int
    risk_amount: float
    leverage_cap: float
    min_risk_reward: float
    strategy_target_r_multiple: float
    tp1_r: float
    tp2_r: float
    runner_r: float
    tp1_fraction: float
    tp2_fraction: float
    runner_fraction: float
    break_even_trigger_r: float
    post_tp2_stop_r: float | None
    trailing_enabled: bool
    max_hold_seconds: int

    def timeframes(self) -> dict[str, Any]:
        return {
            "trend": self.trend_label,
            "setup": self.setup_label,
            "trigger": self.trigger_label,
            "open_candle_confirmation": False,
        }

    def risk_contract(self) -> dict[str, float]:
        return {
            "risk_amount": self.risk_amount,
            "leverage_cap": self.leverage_cap,
            "min_risk_reward": self.min_risk_reward,
        }

    def management_contract(self) -> dict[str, Any]:
        return {
            "profile_name": self.profile_name,
            "tp1_r": self.tp1_r,
            "tp2_r": self.tp2_r,
            "runner_r": self.runner_r,
            "tp1_fraction": self.tp1_fraction,
            "tp2_fraction": self.tp2_fraction,
            "runner_fraction": self.runner_fraction,
            "break_even_trigger_r": self.break_even_trigger_r,
            "post_tp2_stop_r": self.post_tp2_stop_r,
            "trailing_enabled": self.trailing_enabled,
            "max_hold_seconds": self.max_hold_seconds,
        }


SCALPING_PROFILE = EngineProfile(
    trade_type="scalping",
    profile_name="scalping_v2",
    trend_interval="15",
    trend_label="15m",
    trend_minutes=15,
    setup_interval="5",
    setup_label="5m",
    setup_minutes=5,
    trigger_interval="1",
    trigger_label="1m",
    trigger_minutes=1,
    risk_amount=20.0,
    leverage_cap=20.0,
    min_risk_reward=1.5,
    strategy_target_r_multiple=1.5,
    tp1_r=1.5,
    tp2_r=2.0,
    runner_r=2.5,
    tp1_fraction=0.50,
    tp2_fraction=0.25,
    runner_fraction=0.25,
    break_even_trigger_r=1.0,
    post_tp2_stop_r=1.5,
    trailing_enabled=False,
    max_hold_seconds=30 * 60,
)

INTRADAY_PROFILE = EngineProfile(
    trade_type="intraday",
    profile_name="intraday_v1",
    trend_interval="60",
    trend_label="1h",
    trend_minutes=60,
    setup_interval="15",
    setup_label="15m",
    setup_minutes=15,
    trigger_interval="5",
    trigger_label="5m",
    trigger_minutes=5,
    risk_amount=50.0,
    leverage_cap=10.0,
    min_risk_reward=2.0,
    strategy_target_r_multiple=2.0,
    tp1_r=2.0,
    tp2_r=2.5,
    runner_r=3.0,
    tp1_fraction=0.50,
    tp2_fraction=0.25,
    runner_fraction=0.25,
    break_even_trigger_r=2.0,
    post_tp2_stop_r=None,
    trailing_enabled=True,
    max_hold_seconds=6 * 60 * 60,
)

ENGINE_PROFILES: dict[str, EngineProfile] = {
    SCALPING_PROFILE.trade_type: SCALPING_PROFILE,
    INTRADAY_PROFILE.trade_type: INTRADAY_PROFILE,
}


def get_engine_profile(trade_type: Any) -> EngineProfile:
    normalized = str(trade_type or "").strip().lower()
    profile = ENGINE_PROFILES.get(normalized)
    if profile is None:
        raise ValueError("trade_type must be scalping or intraday")
    return profile


def apply_strategy_profile(result: dict[str, Any], profile: EngineProfile) -> dict[str, Any]:
    """Attach one explicit engine contract and raise valid low-R targets to its minimum."""

    profiled = dict(result)
    profiled["engine_profile"] = profile.trade_type
    profiled["engine_profile_name"] = profile.profile_name
    profiled["engine_min_risk_reward"] = profile.min_risk_reward
    profiled["engine_target_r_multiple"] = profile.strategy_target_r_multiple
    profiled["profile_adjusted_target"] = False

    status = str(profiled.get("status") or "").strip().lower()
    if status not in {"active", "near_setup"}:
        return profiled

    direction = str(profiled.get("direction") or "").strip().lower()
    entry = _number(profiled.get("entry"))
    stop_loss = _number(profiled.get("stop_loss"))
    take_profit = _number(profiled.get("take_profit"))
    if direction not in {"long", "short"} or None in {entry, stop_loss, take_profit}:
        return profiled

    if direction == "long":
        if not stop_loss < entry < take_profit:
            return profiled
        risk_distance = entry - stop_loss
        reward_distance = take_profit - entry
    else:
        if not take_profit < entry < stop_loss:
            return profiled
        risk_distance = stop_loss - entry
        reward_distance = entry - take_profit

    if risk_distance <= 0 or reward_distance <= 0:
        return profiled
    actual_risk_reward = reward_distance / risk_distance
    min_rr = profile.min_risk_reward
    if actual_risk_reward + 1e-9 >= min_rr:
        profiled["risk_reward"] = round(actual_risk_reward, 4)
        return profiled

    profiled["status"] = "rejected"
    profiled["rejection_reason"] = "risk_reward_below_trade_type_minimum"
    profiled["risk_reward"] = round(actual_risk_reward, 4)
    return profiled


def _number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) and numeric > 0 else None
