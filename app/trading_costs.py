from __future__ import annotations

from math import isfinite

DEFAULT_TAKER_FEE_BPS = 5.5
DEFAULT_SLIPPAGE_BPS = 0.0


def calculate_cost_adjusted_geometry(
    *,
    direction: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    quantity: float = 1.0,
    fee_bps: float = DEFAULT_TAKER_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    observed_entry_fee: float | None = None,
) -> dict[str, float] | None:
    """Return gross and fee/slippage-adjusted risk/reward economics.

    All monetary values are calculated for ``quantity`` units. Entry and exit
    costs are treated as adverse costs. When an exchange-observed entry fee is
    available it replaces the estimated entry fee for actual-fill validation.
    """

    try:
        entry_value = float(entry)
        stop_value = float(stop_loss)
        target_value = float(take_profit)
        qty = float(quantity)
        fee_rate = max(float(fee_bps), 0.0) / 10_000.0
        slippage_rate = max(float(slippage_bps), 0.0) / 10_000.0
    except (TypeError, ValueError):
        return None

    if not all(isfinite(value) and value > 0 for value in (entry_value, stop_value, target_value, qty)):
        return None

    normalized_direction = str(direction or "").lower().strip()
    if normalized_direction == "long":
        if not stop_value < entry_value < target_value:
            return None
        gross_risk_per_unit = entry_value - stop_value
        gross_reward_per_unit = target_value - entry_value
    elif normalized_direction == "short":
        if not target_value < entry_value < stop_value:
            return None
        gross_risk_per_unit = stop_value - entry_value
        gross_reward_per_unit = entry_value - target_value
    else:
        return None

    estimated_entry_fee = entry_value * qty * fee_rate
    if observed_entry_fee is not None:
        try:
            candidate = abs(float(observed_entry_fee))
        except (TypeError, ValueError):
            candidate = estimated_entry_fee
        if isfinite(candidate):
            estimated_entry_fee = candidate

    stop_exit_fee = stop_value * qty * fee_rate
    target_exit_fee = target_value * qty * fee_rate
    entry_slippage = entry_value * qty * slippage_rate
    stop_exit_slippage = stop_value * qty * slippage_rate
    target_exit_slippage = target_value * qty * slippage_rate

    gross_risk = gross_risk_per_unit * qty
    gross_reward = gross_reward_per_unit * qty
    estimated_stop_costs = estimated_entry_fee + stop_exit_fee + entry_slippage + stop_exit_slippage
    estimated_target_costs = estimated_entry_fee + target_exit_fee + entry_slippage + target_exit_slippage
    net_risk = gross_risk + estimated_stop_costs
    net_reward = gross_reward - estimated_target_costs
    gross_rr = gross_reward / gross_risk if gross_risk > 0 else 0.0
    net_rr = net_reward / net_risk if net_risk > 0 and net_reward > 0 else 0.0

    return {
        "quantity": qty,
        "fee_bps": fee_rate * 10_000.0,
        "slippage_bps": slippage_rate * 10_000.0,
        "gross_risk_per_unit": gross_risk_per_unit,
        "gross_reward_per_unit": gross_reward_per_unit,
        "gross_risk": gross_risk,
        "gross_reward": gross_reward,
        "gross_risk_reward": gross_rr,
        "estimated_entry_fee": estimated_entry_fee,
        "estimated_stop_exit_fee": stop_exit_fee,
        "estimated_target_exit_fee": target_exit_fee,
        "estimated_entry_slippage": entry_slippage,
        "estimated_stop_exit_slippage": stop_exit_slippage,
        "estimated_target_exit_slippage": target_exit_slippage,
        "estimated_stop_costs": estimated_stop_costs,
        "estimated_target_costs": estimated_target_costs,
        "net_risk": net_risk,
        "net_reward": net_reward,
        "net_risk_reward": net_rr,
    }
