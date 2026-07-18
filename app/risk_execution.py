"""Automatic execution boundary with fee-budget and post-fill degradation guards.

This module becomes the installed public executor after the existing Batch-1
safety contract has wrapped ``app.execution._execute_signal_authoritatively``.
It therefore preserves the daily-loss authority and all authoritative risk,
reservation, sizing, fill, and protection checks while adding two controls:

1. Reject automatic entries when estimated round-trip taker fees consume too
   much of the fixed risk budget.
2. Do not immediately market-close a position merely because optional partial
   take-profit automation failed, provided full-position SL/TP protection was
   already verified from the exchange.
"""

from __future__ import annotations

from typing import Any

import app.execution as public_execution
from app.config import settings
from app.execution_core import get_active_trades
from app.position_sizing import calculate_position_size
from app.risk import extract_account_equity, validate_trade


def _execute_signal_authoritatively(
    client: Any,
    signal: dict[str, Any],
    auto_triggered: bool = False,
) -> dict[str, Any]:
    """Use the currently installed guarded authoritative delegate."""

    return public_execution._execute_signal_authoritatively(client, signal, auto_triggered)


def execute_signal(client: Any, signal: dict[str, Any], auto_triggered: bool = False) -> dict[str, Any]:
    """Execute without high-fee entries or optional-setup panic closes."""

    profiled_signal = public_execution._with_profile_runner_target(signal)
    fee_gate: dict[str, Any] = {
        "allowed": True,
        "status": "NOT_REQUIRED_FOR_MANUAL_EXECUTION",
    }
    if auto_triggered:
        fee_gate = _fee_budget_preflight(client, profiled_signal)
        if not fee_gate.get("allowed"):
            return {
                "ok": False,
                "error": fee_gate.get("error") or "FEE_BUDGET_EXCEEDED",
                "detail": fee_gate.get("reason"),
                "fee_budget": fee_gate,
            }

    spread_gate = public_execution._execution_spread_gate(
        client,
        str(profiled_signal.get("symbol") or "").upper(),
    )
    if not spread_gate.get("allowed"):
        return {
            "ok": False,
            "error": "SPREAD_GATE_REJECTED",
            "detail": spread_gate.get("reason"),
            "spread": spread_gate,
            "fee_budget": fee_gate,
        }

    result = _execute_signal_authoritatively(client, profiled_signal, auto_triggered)

    if result.get("error") == "FILL_CONFIRMATION_UNAVAILABLE":
        trade = result.get("trade") if isinstance(result.get("trade"), dict) else None
        if not trade:
            return result
        return _hard_safety_close(
            client=client,
            trade=trade,
            error="FILL_CONFIRMATION_UNAVAILABLE",
            detail=str(
                (trade.get("exchange_metadata") or {}).get("fill_confirmation_error")
                or "Order fill could not be confirmed; emergency close was required."
            ),
            result=result,
        )

    if not result.get("ok"):
        return result

    trade = result.get("trade") if isinstance(result.get("trade"), dict) else None
    if not trade:
        return {"ok": False, "error": "ACTIVE_TRADE_PAYLOAD_UNAVAILABLE", **result}

    actual_fill_costs = public_execution._validate_actual_fill_costs(result, trade)
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    trade = {
        **trade,
        "exchange_metadata": {
            **metadata,
            "actual_fill_cost_validation": actual_fill_costs,
            "fee_budget_preflight": fee_gate,
            "execution_spread": spread_gate,
        },
    }
    result["trade"] = trade
    result["actual_fill_cost_validation"] = actual_fill_costs
    result["fee_budget"] = fee_gate
    result["spread"] = spread_gate

    if not actual_fill_costs.get("allowed"):
        return _hard_safety_close(
            client=client,
            trade=trade,
            error="ACTUAL_FILL_COST_VIOLATION",
            detail=str(actual_fill_costs.get("reason") or "Actual fill failed fee-inclusive validation."),
            result=result,
        )

    if actual_fill_costs.get("warning"):
        result["execution_economics_warning"] = actual_fill_costs["warning"]

    profiled = public_execution._apply_management_profile(client, trade, spread_gate)
    if not profiled.get("ok"):
        candidate = profiled.get("trade") if isinstance(profiled.get("trade"), dict) else trade
        detail = str(profiled.get("error") or "Trade management profile could not be installed and verified.")
        if _has_verified_full_position_protection(candidate):
            return _keep_protected_trade_active(
                trade=candidate,
                result=result,
                error="MANAGEMENT_PROFILE_INSTALLATION_FAILED",
                detail=detail,
                spread_gate=spread_gate,
            )
        return _hard_safety_close(
            client=client,
            trade=candidate,
            error="MANAGEMENT_PROFILE_INSTALLATION_FAILED",
            detail=detail,
            result=result,
        )

    trade = profiled["trade"]
    managed_target_costs = public_execution._validate_actual_fill_costs(result, trade)
    managed_metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    trade = {
        **trade,
        "exchange_metadata": {
            **managed_metadata,
            "managed_target_cost_validation": managed_target_costs,
            "fee_budget_preflight": fee_gate,
        },
    }
    result["trade"] = trade
    result["managed_target_cost_validation"] = managed_target_costs
    if not managed_target_costs.get("allowed"):
        return _hard_safety_close(
            client=client,
            trade=trade,
            error="MANAGED_TARGET_COST_VIOLATION",
            detail=str(
                managed_target_costs.get("reason")
                or "Final managed target failed fee-inclusive Net RR validation."
            ),
            result=result,
        )
    if managed_target_costs.get("warning"):
        result["execution_economics_warning"] = managed_target_costs["warning"]

    native_setup = public_execution.install_native_profit_orders(client, trade)
    if not native_setup.get("ok"):
        public_execution.cancel_native_profit_orders(client, trade)
        detail = str(native_setup.get("error") or "Exchange-native TP1/TP2 orders could not be installed.")
        if _has_verified_full_position_protection(trade):
            return _keep_protected_trade_active(
                trade=trade,
                result=result,
                error="NATIVE_TP_INSTALLATION_FAILED",
                detail=detail,
                spread_gate=spread_gate,
            )
        return _hard_safety_close(
            client=client,
            trade=trade,
            error="NATIVE_TP_INSTALLATION_FAILED",
            detail=detail,
            result=result,
        )

    management = dict(native_setup.get("management") or {})
    orders = dict(native_setup.get("orders") or {})
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    updated_trade = {
        **trade,
        "status": "active",
        "trade_type": management.get("trade_type"),
        "take_profit": management.get("runner_target"),
        "management": management,
        "exchange_metadata": {
            **metadata,
            "trade_type": management.get("trade_type"),
            "management": management,
            "native_profit_orders": orders,
            "execution_spread": spread_gate,
            "fee_budget_preflight": fee_gate,
        },
    }
    journal_id = str(updated_trade.get("journal_id") or "")
    try:
        persisted = public_execution.update_trade_entry(
            journal_id,
            {
                "status": "active",
                "take_profit": updated_trade.get("take_profit"),
                "exchange_metadata": updated_trade["exchange_metadata"],
            },
        )
    except Exception as exc:
        persisted = None
        persist_error = str(exc)
    else:
        persist_error = "journal entry not found" if persisted is None else ""

    if persisted is None:
        public_execution.cancel_native_profit_orders(client, updated_trade)
        detail = persist_error or "Native TP state could not be persisted."
        if _has_verified_full_position_protection(updated_trade):
            return _keep_protected_trade_active(
                trade=updated_trade,
                result=result,
                error="NATIVE_TP_STATE_PERSIST_FAILED",
                detail=detail,
                spread_gate=spread_gate,
            )
        return _hard_safety_close(
            client=client,
            trade=updated_trade,
            error="NATIVE_TP_STATE_PERSIST_FAILED",
            detail=detail,
            result=result,
        )

    public_execution.update_active_trade(
        journal_id,
        {
            "status": "active",
            "trade_type": management.get("trade_type"),
            "take_profit": management.get("runner_target"),
            "management": management,
            "exchange_metadata": updated_trade["exchange_metadata"],
        },
    )
    _safe_trade_event(
        journal_id,
        "NATIVE_TP_ORDERS_INSTALLED",
        "Exchange-native TP1 and TP2 reduce-only orders were installed.",
        {
            "symbol": updated_trade.get("symbol"),
            "trade_type": management.get("trade_type"),
            "profile_name": management.get("profile_name"),
            "tp1": orders.get("tp1"),
            "tp2": orders.get("tp2"),
        },
    )

    result["trade"] = updated_trade
    result["native_profit_orders"] = orders
    result["management_profile"] = management.get("profile_name")
    return result


def _fee_budget_preflight(client: Any, signal: dict[str, Any]) -> dict[str, Any]:
    symbol = str(signal.get("symbol") or "").upper().strip()
    if not symbol:
        return _fee_reject("FEE_PREFLIGHT_UNAVAILABLE", "Signal symbol is unavailable")

    ok_wallet, wallet, wallet_error = client.safe_fetch_wallet_balance()
    if not ok_wallet or wallet is None:
        return _fee_reject("FEE_PREFLIGHT_UNAVAILABLE", wallet_error or "Wallet balance unavailable")
    equity = extract_account_equity(wallet)
    if equity is None:
        return _fee_reject("FEE_PREFLIGHT_UNAVAILABLE", "Fresh account equity is unavailable")

    ok_symbol, symbol_infos, symbol_error = client.safe_fetch_symbol_info(symbol=symbol)
    if not ok_symbol or not symbol_infos:
        return _fee_reject("FEE_PREFLIGHT_UNAVAILABLE", symbol_error or "Symbol info unavailable")

    ok_positions, positions, positions_error = client.safe_fetch_positions()
    if not ok_positions:
        return _fee_reject("FEE_PREFLIGHT_UNAVAILABLE", positions_error or "Position data unavailable")

    validation = validate_trade(signal, account_equity=equity)
    if not validation.get("allowed"):
        return _fee_reject("RISK_POLICY_REJECTED", str(validation.get("reason") or "Risk validation failed"))

    sizing = calculate_position_size(
        signal=signal,
        wallet=wallet,
        symbol_info=symbol_infos[0],
        active_trades=get_active_trades(),
        positions=positions,
        settings={
            "risk_amount": validation.get("risk_amount"),
            "leverage_cap": validation.get("leverage_cap"),
            "exposure_cap": validation.get("exposure_cap"),
            "min_risk_reward": validation.get("min_risk_reward"),
        },
        client=client,
    )
    if not sizing.get("allowed"):
        return _fee_reject("POSITION_SIZING_REJECTED", str(sizing.get("reason") or "Unsafe position sizing rejected"))

    estimated_fees = _non_negative_float(sizing.get("estimated_round_trip_fees"))
    risk_budget = _positive_float(sizing.get("target_risk_amount") or validation.get("risk_amount"))
    if estimated_fees is None or risk_budget is None:
        return _fee_reject("FEE_PREFLIGHT_UNAVAILABLE", "Fee or risk-budget evidence is unavailable")

    fee_to_risk_ratio = estimated_fees / risk_budget
    max_ratio = max(float(settings.execution_max_round_trip_fee_risk_ratio), 0.0)
    evidence = {
        "allowed": fee_to_risk_ratio <= max_ratio + 1e-12,
        "error": None,
        "reason": "",
        "estimated_round_trip_fees": estimated_fees,
        "risk_budget": risk_budget,
        "fee_to_risk_ratio": fee_to_risk_ratio,
        "max_fee_to_risk_ratio": max_ratio,
        "notional": sizing.get("notional"),
        "selected_leverage": sizing.get("selected_leverage"),
        "sizing": sizing,
    }
    if evidence["allowed"]:
        return evidence
    return {
        **evidence,
        "error": "FEE_BUDGET_EXCEEDED",
        "reason": (
            f"Estimated round-trip fees {estimated_fees:.4f} consume "
            f"{fee_to_risk_ratio:.1%} of the {risk_budget:.4f} risk budget; "
            f"maximum allowed is {max_ratio:.1%}"
        ),
    }


def _hard_safety_close(
    *,
    client: Any,
    trade: dict[str, Any],
    error: str,
    detail: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    safe_result = public_execution._emergency_close_pending_sync(
        client=client,
        trade=trade,
        error=error,
        detail=detail,
        sizing=result.get("sizing") or {},
    )
    updated_trade = safe_result.get("trade") if isinstance(safe_result.get("trade"), dict) else None
    if updated_trade and updated_trade.get("journal_id"):
        public_execution.update_active_trade(
            str(updated_trade["journal_id"]),
            {
                "status": updated_trade.get("status"),
                "result": updated_trade.get("result"),
                "close_reason": updated_trade.get("close_reason"),
                "exchange_metadata": updated_trade.get("exchange_metadata"),
            },
        )
    return safe_result


def _has_verified_full_position_protection(trade: dict[str, Any]) -> bool:
    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    management = trade.get("management") or metadata.get("management") or {}
    return bool(
        metadata.get("protection_verified")
        or metadata.get("profile_protection_verified")
        or management.get("profile_protection_verified")
    )


def _keep_protected_trade_active(
    *,
    trade: dict[str, Any],
    result: dict[str, Any],
    error: str,
    detail: str,
    spread_gate: dict[str, Any],
) -> dict[str, Any]:
    """Degrade optional automation only when exchange SL/TP is proven."""

    if not _has_verified_full_position_protection(trade):
        return {
            **result,
            "ok": False,
            "error": "PROTECTION_EVIDENCE_UNAVAILABLE",
            "detail": detail,
            "trade": trade,
        }

    metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}
    management = trade.get("management") or metadata.get("management") or {}
    management = {
        **dict(management),
        "native_tp_enabled": False,
        "native_tp_degraded": True,
        "native_tp_degraded_reason": detail,
        "fallback_mode": "verified_full_position_sl_tp",
    }
    degraded = {
        **trade,
        "status": "active",
        "management": management,
        "exchange_metadata": {
            **metadata,
            "management": management,
            "execution_spread": spread_gate,
            "post_fill_degradation": {
                "error": error,
                "detail": detail,
                "position_action": "KEPT_ACTIVE",
                "protection_mode": "VERIFIED_FULL_POSITION_SL_TP",
            },
        },
    }
    journal_id = str(degraded.get("journal_id") or "")
    persist_warning = None
    try:
        persisted = public_execution.update_trade_entry(
            journal_id,
            {
                "status": "active",
                "take_profit": degraded.get("take_profit"),
                "exchange_metadata": degraded["exchange_metadata"],
            },
        )
        if persisted is None:
            persist_warning = "journal entry not found"
    except Exception as exc:
        persist_warning = str(exc)

    if journal_id:
        public_execution.update_active_trade(
            journal_id,
            {
                "status": "active",
                "management": management,
                "exchange_metadata": degraded["exchange_metadata"],
            },
        )
        _safe_trade_event(
            journal_id,
            "OPTIONAL_MANAGEMENT_DEGRADED",
            "Optional partial-profit automation failed; verified full-position SL/TP remains active.",
            {
                "symbol": degraded.get("symbol"),
                "error": error,
                "detail": detail,
                "persist_warning": persist_warning,
            },
        )

    warning = f"{error}: {detail}. Position kept active under verified full-position SL/TP."
    if persist_warning:
        warning = f"{warning} Journal warning: {persist_warning}."

    return {
        **result,
        "ok": True,
        "error": None,
        "trade": degraded,
        "native_profit_orders": {},
        "management_profile": management.get("profile_name"),
        "execution_warning": warning,
        "degraded": True,
    }


def _safe_trade_event(
    journal_id: str,
    event_type: str,
    message: str,
    metadata: dict[str, Any],
) -> None:
    if not journal_id:
        return
    try:
        public_execution.append_trade_event(journal_id, event_type, message, metadata)
    except Exception:
        pass


def _fee_reject(error: str, reason: str) -> dict[str, Any]:
    return {"allowed": False, "error": error, "reason": reason}


def _positive_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric > 0 else None


def _non_negative_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric >= 0 else None


__all__ = ["execute_signal"]
