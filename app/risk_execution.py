from __future__ import annotations

from typing import Any

import app.execution as execution_module
from app.execution import execute_signal as execute_signal_core
from app.execution import get_active_trades
from app.position_sizing import calculate_position_size
from app.risk import extract_account_equity, refresh_risk_state, validate_trade


def execute_signal(client: Any, signal: dict[str, Any], auto_triggered: bool = False) -> dict[str, Any]:
    """Run the authoritative pre-order gate before the existing durable executor.

    The core executor remains responsible for reservation, idempotency, order
    confirmation and protection. This wrapper guarantees that day-start equity,
    fixed-USDT risk, margin exposure and selected leverage are resolved before
    any order can be submitted.
    """

    ok_wallet, wallet, wallet_error = client.safe_fetch_wallet_balance()
    if not ok_wallet or wallet is None:
        return {"ok": False, "error": wallet_error or "Wallet balance unavailable"}

    account_equity = extract_account_equity(wallet)
    if account_equity is None:
        return {"ok": False, "error": "Fresh account equity is unavailable"}

    refresh_risk_state(account_equity=account_equity)
    validation = validate_trade(signal, account_equity=account_equity)
    if not validation.get("allowed"):
        return {"ok": False, "error": validation.get("reason", "Risk validation failed")}

    symbol = str(signal.get("symbol") or "").upper().strip()
    ok_symbol, symbol_infos, symbol_error = client.safe_fetch_symbol_info(symbol=symbol)
    if not ok_symbol or not symbol_infos:
        return {"ok": False, "error": symbol_error or "Symbol info unavailable"}

    ok_positions, positions, positions_error = client.safe_fetch_positions()
    if not ok_positions:
        return {"ok": False, "error": positions_error or "Position data unavailable"}

    sizing = calculate_position_size(
        signal=signal,
        wallet=wallet,
        symbol_info=symbol_infos[0],
        active_trades=get_active_trades(),
        positions=positions,
        settings={
            "risk_amount": validation.get("risk_amount"),
            "risk_per_trade": validation.get("risk_per_trade"),
            "leverage_cap": validation.get("leverage_cap"),
            "exposure_cap": validation.get("exposure_cap"),
        },
        client=client,
    )
    if not sizing.get("allowed"):
        return {
            "ok": False,
            "error": sizing.get("reason", "Unsafe position sizing rejected"),
            "sizing": sizing,
        }

    selected_leverage = sizing.get("selected_leverage") or sizing.get("leverage")
    set_leverage = getattr(client, "safe_set_leverage", None)
    if callable(set_leverage) and selected_leverage is not None:
        ok_leverage, response, leverage_error = set_leverage(
            symbol=symbol,
            leverage=float(selected_leverage),
        )
        if not ok_leverage:
            normalized_error = str(leverage_error or "Leverage configuration failed")
            # Bybit may report an unchanged value as a non-action. That is safe;
            # every other leverage error blocks the order.
            if "not modified" not in normalized_error.lower() and "same leverage" not in normalized_error.lower():
                return {
                    "ok": False,
                    "error": normalized_error,
                    "sizing": sizing,
                }
    else:
        response = None

    enriched_signal = {
        **signal,
        "trade_type": validation.get("trade_type"),
        "risk_reward": validation.get("authoritative_risk_reward", signal.get("risk_reward")),
    }
    outcome = execute_signal_core(client, enriched_signal, auto_triggered)
    if isinstance(outcome, dict):
        outcome.setdefault("pre_order_risk", validation)
        outcome.setdefault("selected_leverage", selected_leverage)
        outcome.setdefault("leverage_response", response)
    return outcome


# app.main imports app.background_worker before importing execute_signal from
# app.execution. background_worker imports this module, so the runtime binding is
# replaced before route handlers capture it. Tests that import app.execution in
# isolation still exercise the durable core directly.
execution_module.execute_signal = execute_signal
