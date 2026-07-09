def _build_management_state(entry: float, stop_loss: float, take_profit: float, quantity: str, direction: str) -> dict[str, Any]:
    """
    REPAIR: Updated TP structure to:
    - TP1 = entry ± risk * 2 (RR 1:4)
    - TP2 = entry ± risk * 2.5 (RR 1:5)
    - TP3/Runner = entry ± risk * 3 (RR 1:6)
    
    Trailing stop only activates after TP2 confirmed.
    """
    risk = abs(entry - stop_loss)
    qty_value = _to_float(quantity, 0.0)
    
    if direction == "long":
        tp1 = entry + risk * 2.0      # RR 1:4
        tp2 = entry + risk * 2.5      # RR 1:5
        runner_target = entry + risk * 3.0  # RR 1:6
    else:
        tp1 = entry - risk * 2.0      # RR 1:4
        tp2 = entry - risk * 2.5      # RR 1:5
        runner_target = entry - risk * 3.0  # RR 1:6

    return {
        "tp1": tp1,
        "tp2": tp2,
        "strategy_take_profit": take_profit,
        "runner_target": runner_target,
        "tp1_fraction": 0.5,          # Close 50% at TP1
        "tp2_fraction": 0.25,         # Close 25% at TP2
        "runner_fraction": 0.25,      # Let 25% run with trailing stop
        "initial_quantity": qty_value,
        "remaining_quantity": qty_value,
        "tp1_done": False,            # Never set true until close confirmed
        "tp2_done": False,            # Never set true until close confirmed
        "break_even_set": False,      # Set true only after SL move confirmed
        "trailing_stop": None,        # Only activated after TP2 confirmed
        "last_momentum_check": None,
        "last_state_change": _utc_now_iso(),
    }
