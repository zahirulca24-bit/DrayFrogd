"""
Validation script for DrayFrogd backend execution and risk consistency.
Run: python -m app.validation
"""
from __future__ import annotations

import sys
from typing import Any


def validate_imports() -> tuple[bool, list[str]]:
    """Test all critical imports."""
    errors: list[str] = []
    modules = [
        "app.config",
        "app.database",
        "app.models",
        "app.exchange",
        "app.execution",
        "app.trade_management",
        "app.reconciliation",
        "app.risk",
        "app.position_sizing",
        "app.journal",
        "app.bot_controls",
        "app.strategy",
        "app.scanner",
        "app.main",
    ]

    for module_name in modules:
        try:
            __import__(module_name)
        except Exception as exc:
            errors.append(f"Import failed for {module_name}: {exc}")

    return len(errors) == 0, errors


def validate_execution_logic() -> tuple[bool, list[str]]:
    """Validate execution module logic."""
    errors: list[str] = []

    try:
        from app.execution import _build_management_state

        # Test long trade
        mgmt_long = _build_management_state(
            entry=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            quantity="1.0",
            direction="long"
        )

        risk = 5.0  # 100 - 95

        # Verify scalping_v2 TP1 = 1.5R
        expected_tp1 = 100.0 + risk * 1.5  # 107.5
        if abs(mgmt_long["tp1"] - expected_tp1) > 0.0001:
            errors.append(f"Long TP1 mismatch: got {mgmt_long['tp1']}, expected {expected_tp1}")

        # Verify scalping_v2 TP2 = 2.0R
        expected_tp2 = 100.0 + risk * 2.0  # 110
        if abs(mgmt_long["tp2"] - expected_tp2) > 0.0001:
            errors.append(f"Long TP2 mismatch: got {mgmt_long['tp2']}, expected {expected_tp2}")

        # Verify scalping_v2 runner = 2.5R
        expected_runner = 100.0 + risk * 2.5  # 112.5
        if abs(mgmt_long["runner_target"] - expected_runner) > 0.0001:
            errors.append(f"Long Runner mismatch: got {mgmt_long['runner_target']}, expected {expected_runner}")

        # Verify flags are false initially
        if mgmt_long["tp1_done"] or mgmt_long["tp2_done"]:
            errors.append("TP flags should be False initially")

        if mgmt_long["trailing_stop"] is not None:
            errors.append("Trailing stop should be None initially")

        # Test short trade
        mgmt_short = _build_management_state(
            entry=100.0,
            stop_loss=105.0,
            take_profit=90.0,
            quantity="1.0",
            direction="short"
        )

        risk_short = 5.0  # 105 - 100

        # Verify scalping_v2 short TP1 = 1.5R
        expected_tp1_short = 100.0 - risk_short * 1.5  # 92.5
        if abs(mgmt_short["tp1"] - expected_tp1_short) > 0.0001:
            errors.append(f"Short TP1 mismatch: got {mgmt_short['tp1']}, expected {expected_tp1_short}")

        # Verify scalping_v2 short TP2 = 2.0R
        expected_tp2_short = 100.0 - risk_short * 2.0  # 90
        if abs(mgmt_short["tp2"] - expected_tp2_short) > 0.0001:
            errors.append(f"Short TP2 mismatch: got {mgmt_short['tp2']}, expected {expected_tp2_short}")

    except Exception as exc:
        errors.append(f"Execution logic validation error: {exc}")

    return len(errors) == 0, errors


def validate_risk_consistency() -> tuple[bool, list[str]]:
    """Validate risk module consistency."""
    errors: list[str] = []

    try:
        from app.risk import _is_valid_trade_levels, MIN_RISK_REWARD

        # Test valid long: entry < stop_loss < take_profit
        if not _is_valid_trade_levels(100.0, 95.0, 110.0):
            errors.append("Valid long trade rejected")

        # Test valid short: take_profit < stop_loss < entry
        if not _is_valid_trade_levels(100.0, 105.0, 90.0):
            errors.append("Valid short trade rejected")

        # Test invalid: all same
        if _is_valid_trade_levels(100.0, 100.0, 100.0):
            errors.append("Invalid trade (all same) accepted")

        # Test invalid: entry = stop_loss
        if _is_valid_trade_levels(100.0, 100.0, 110.0):
            errors.append("Invalid trade (entry=SL) accepted")

        # Verify minimum risk reward is aligned with the scalping strategy contract.
        if MIN_RISK_REWARD != 1.5:
            errors.append(f"MIN_RISK_REWARD should be 1.5, got {MIN_RISK_REWARD}")

    except Exception as exc:
        errors.append(f"Risk consistency validation error: {exc}")

    return len(errors) == 0, errors


def validate_position_sizing() -> tuple[bool, list[str]]:
    """Validate position sizing logic."""
    errors: list[str] = []

    try:
        from app.position_sizing import _positive_float, _normalize_signal, SIGNAL_MAX_AGE_MINUTES

        # Test positive float
        if _positive_float(1.5) != 1.5:
            errors.append("_positive_float(1.5) failed")

        if _positive_float(0.0) is not None:
            errors.append("_positive_float(0.0) should return None")

        if _positive_float(-1.0) is not None:
            errors.append("_positive_float(-1.0) should return None")

        if _positive_float("invalid") is not None:
            errors.append("_positive_float('invalid') should return None")

        # Test signal normalization
        signal_valid = {
            "symbol": "btcusdt",
            "entry": 50000.0,
            "stop_loss": 49000.0,
            "take_profit": 51000.0,
            "detected_at": "2026-07-09T00:00:00Z"
        }
        normalized = _normalize_signal(signal_valid)
        if normalized is None:
            errors.append("Valid signal rejected")
        elif normalized["symbol"] != "BTCUSDT":
            errors.append("Symbol not uppercased")

        # Test invalid signal
        signal_invalid = {"entry": "invalid"}
        if _normalize_signal(signal_invalid) is not None:
            errors.append("Invalid signal accepted")

        # Verify signal max age
        if SIGNAL_MAX_AGE_MINUTES != 10:
            errors.append(f"SIGNAL_MAX_AGE_MINUTES should be 10, got {SIGNAL_MAX_AGE_MINUTES}")

    except Exception as exc:
        errors.append(f"Position sizing validation error: {exc}")

    return len(errors) == 0, errors


def validate_trade_management() -> tuple[bool, list[str]]:
    """Validate trade management confirmation logic."""
    errors: list[str] = []

    try:
        # Import to verify structure exists
        from app.trade_management import (
            manage_open_trades,
            _close_quantity,
            _set_protection,
            _trailing_stop,
        )

        # Verify functions exist and are callable
        if not callable(manage_open_trades):
            errors.append("manage_open_trades is not callable")
        if not callable(_close_quantity):
            errors.append("_close_quantity is not callable")
        if not callable(_set_protection):
            errors.append("_set_protection is not callable")
        if not callable(_trailing_stop):
            errors.append("_trailing_stop is not callable")

    except Exception as exc:
        errors.append(f"Trade management validation error: {exc}")

    return len(errors) == 0, errors


def validate_reconciliation() -> tuple[bool, list[str]]:
    """Validate reconciliation logic."""
    errors: list[str] = []

    try:
        from app.reconciliation import (
            reconcile_state,
            _position_is_open,
            _resolve_close_result,
        )

        # Verify functions exist
        if not callable(reconcile_state):
            errors.append("reconcile_state is not callable")
        if not callable(_position_is_open):
            errors.append("_position_is_open is not callable")
        if not callable(_resolve_close_result):
            errors.append("_resolve_close_result is not callable")

        # Test position open check
        open_pos = {"size": 1.5, "symbol": "BTCUSDT"}
        if not _position_is_open(open_pos):
            errors.append("Open position not detected")

        closed_pos = {"size": 0.0, "symbol": "BTCUSDT"}
        if _position_is_open(closed_pos):
            errors.append("Closed position detected as open")

        # Test close result resolution
        trade = {
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 95.0,
            "take_profit": 110.0,
        }
        result = _resolve_close_result(trade, 93.0)  # Below SL
        if result.get("result") != "sl":
            errors.append(f"SL result mismatch: got {result.get('result')}, expected 'sl'")

    except Exception as exc:
        errors.append(f"Reconciliation validation error: {exc}")

    return len(errors) == 0, errors


def main() -> int:
    """Run all validations."""
    print("=" * 80)
    print("DrayFrogd Backend Validation Suite")
    print("=" * 80)

    validations = [
        ("Imports", validate_imports),
        ("Execution Logic (TP Structure)", validate_execution_logic),
        ("Risk Consistency", validate_risk_consistency),
        ("Position Sizing", validate_position_sizing),
        ("Trade Management", validate_trade_management),
        ("Reconciliation", validate_reconciliation),
    ]

    all_passed = True
    for name, validator in validations:
        passed, errors = validator()
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"\n{status}: {name}")

        if errors:
            all_passed = False
            for error in errors:
                print(f"  - {error}")

    print("\n" + "=" * 80)
    if all_passed:
        print("✓ ALL VALIDATIONS PASSED")
        return 0
    else:
        print("✗ SOME VALIDATIONS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
