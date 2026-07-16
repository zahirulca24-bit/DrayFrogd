from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one match in {path}, found {count}: {old[:80]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/config.py",
    '    execution_slippage_bps: float = float(os.getenv("EXECUTION_SLIPPAGE_BPS", "0.0"))\n',
    '    execution_slippage_bps: float = float(os.getenv("EXECUTION_SLIPPAGE_BPS", "2.0"))\n'
    '    execution_risk_headroom_ratio: float = float(os.getenv("EXECUTION_RISK_HEADROOM_RATIO", "0.90"))\n',
)

replace_once(
    ".env.example",
    "EXECUTION_SLIPPAGE_BPS=0.0\n",
    "EXECUTION_SLIPPAGE_BPS=2.0\nEXECUTION_RISK_HEADROOM_RATIO=0.90\n",
)

replace_once(
    "app/position_sizing.py",
    '''    if target_risk_amount is None:\n        return _reject("Fixed USDT risk amount is unavailable")\n\n    leverage_cap = _positive_float(settings.get("leverage_cap"))\n''',
    '''    if target_risk_amount is None:\n        return _reject("Fixed USDT risk amount is unavailable")\n\n    configured_target_risk_amount = target_risk_amount\n    risk_headroom_ratio = _non_negative_float(settings.get("risk_headroom_ratio"))\n    if risk_headroom_ratio is None:\n        risk_headroom_ratio = _non_negative_float(app_settings.execution_risk_headroom_ratio)\n    risk_headroom_ratio = min(max(float(risk_headroom_ratio or 0.90), 0.50), 1.0)\n    execution_risk_budget = configured_target_risk_amount * risk_headroom_ratio\n    if execution_risk_budget <= 0 or not isfinite(execution_risk_budget):\n        return _reject("Execution risk budget is invalid")\n\n    leverage_cap = _positive_float(settings.get("leverage_cap"))\n''',
)

replace_once(
    "app/position_sizing.py",
    "    raw_quantity = target_risk_amount / risk_per_unit_with_fees\n",
    "    raw_quantity = execution_risk_budget / risk_per_unit_with_fees\n",
)

replace_once(
    "app/position_sizing.py",
    '''    if actual_risk_amount > target_risk_amount * 1.001:\n        return _reject("Minimum quantity exceeds configured fee-inclusive USDT risk")\n''',
    '''    if actual_risk_amount > execution_risk_budget * 1.001:\n        return _reject("Minimum quantity exceeds the headroom-adjusted execution risk budget")\n''',
)

replace_once(
    "app/position_sizing.py",
    '''        "target_risk_amount": target_risk_amount,\n        "risk_mode": "fixed_usdt" if fixed_risk_mode else "legacy_percent",\n''',
    '''        "target_risk_amount": configured_target_risk_amount,\n        "execution_risk_budget": execution_risk_budget,\n        "risk_headroom_ratio": risk_headroom_ratio,\n        "risk_headroom_amount": configured_target_risk_amount - execution_risk_budget,\n        "risk_mode": "fixed_usdt" if fixed_risk_mode else "legacy_percent",\n''',
)

replace_once(
    "app/execution.py",
    '''from app.trade_management_profiles import (\n    build_profile_management_state,\n    extract_observed_entry_fee,\n    trade_type_from_trade,\n)\n''',
    '''from app.trade_management_profiles import (\n    build_profile_management_state,\n    extract_observed_entry_fee,\n    price_at_r,\n    trade_type_from_trade,\n)\n''',
)

replace_once(
    "app/execution.py",
    '''RISK_AMOUNT_TOLERANCE = 1.001\n\n\ndef execute_signal(client: Any, signal: dict[str, Any], auto_triggered: bool = False) -> dict[str, Any]:\n    spread_gate = _execution_spread_gate(client, str(signal.get("symbol") or "").upper())\n''',
    '''RISK_AMOUNT_TOLERANCE = 1.001\n\n\ndef _with_profile_runner_target(signal: dict[str, Any]) -> dict[str, Any]:\n    profiled = dict(signal)\n    try:\n        profile = get_engine_profile(profiled.get("trade_type"))\n        entry = float(profiled.get("entry"))\n        stop_loss = float(profiled.get("stop_loss"))\n        direction = str(profiled.get("direction") or "").lower().strip()\n    except (TypeError, ValueError):\n        return profiled\n\n    if direction not in {"long", "short"} or entry <= 0 or stop_loss <= 0 or entry == stop_loss:\n        return profiled\n\n    runner_target = price_at_r(entry, stop_loss, direction, profile.runner_r)\n    profiled["strategy_take_profit"] = profiled.get("take_profit")\n    profiled["strategy_risk_reward"] = profiled.get("risk_reward")\n    profiled["take_profit"] = runner_target\n    profiled["risk_reward"] = profile.runner_r\n    profiled["execution_target_source"] = "profile_runner"\n    return profiled\n\n\ndef execute_signal(client: Any, signal: dict[str, Any], auto_triggered: bool = False) -> dict[str, Any]:\n    signal = _with_profile_runner_target(signal)\n    spread_gate = _execution_spread_gate(client, str(signal.get("symbol") or "").upper())\n''',
)

replace_once(
    "app/execution.py",
    '''    if not actual_fill_costs.get("allowed"):\n        safe_result = _emergency_close_pending_sync(\n            client=client,\n            trade=trade,\n            error="ACTUAL_FILL_COST_VIOLATION",\n            detail=str(actual_fill_costs.get("reason") or "Actual fill failed fee-inclusive validation."),\n            sizing=result.get("sizing") or {},\n        )\n        _sync_active_safety_state(safe_result)\n        return safe_result\n\n    profiled = _apply_management_profile(client, trade, spread_gate)\n''',
    '''    if not actual_fill_costs.get("allowed"):\n        safe_result = _emergency_close_pending_sync(\n            client=client,\n            trade=trade,\n            error="ACTUAL_FILL_COST_VIOLATION",\n            detail=str(actual_fill_costs.get("reason") or "Actual fill failed fee-inclusive validation."),\n            sizing=result.get("sizing") or {},\n        )\n        _sync_active_safety_state(safe_result)\n        return safe_result\n    if actual_fill_costs.get("warning"):\n        result["execution_economics_warning"] = actual_fill_costs["warning"]\n\n    profiled = _apply_management_profile(client, trade, spread_gate)\n''',
)

replace_once(
    "app/execution.py",
    '''    trade = profiled["trade"]\n\n    native_setup = install_native_profit_orders(client, trade)\n''',
    '''    trade = profiled["trade"]\n    managed_target_costs = _validate_actual_fill_costs(result, trade)\n    managed_metadata = trade.get("exchange_metadata") if isinstance(trade.get("exchange_metadata"), dict) else {}\n    trade = {\n        **trade,\n        "exchange_metadata": {\n            **managed_metadata,\n            "managed_target_cost_validation": managed_target_costs,\n        },\n    }\n    result["managed_target_cost_validation"] = managed_target_costs\n    if not managed_target_costs.get("allowed"):\n        safe_result = _emergency_close_pending_sync(\n            client=client,\n            trade=trade,\n            error="MANAGED_TARGET_COST_VIOLATION",\n            detail=str(\n                managed_target_costs.get("reason")\n                or "Final managed target failed fee-inclusive Net RR validation."\n            ),\n            sizing=result.get("sizing") or {},\n        )\n        _sync_active_safety_state(safe_result)\n        return safe_result\n    if managed_target_costs.get("warning"):\n        result["execution_economics_warning"] = managed_target_costs["warning"]\n\n    native_setup = install_native_profit_orders(client, trade)\n''',
)

replace_once(
    "app/execution.py",
    '''    min_rr = float(validation.get("min_risk_reward") or profile_min_rr or 0.0)\n    target_risk = float(validation.get("risk_amount") or sizing.get("target_risk_amount") or 0.0)\n    fee_bps = float(sizing.get("fee_bps") if sizing.get("fee_bps") is not None else app_settings.execution_taker_fee_bps)\n''',
    '''    min_rr = float(validation.get("min_risk_reward") or profile_min_rr or 0.0)\n    target_risk = float(validation.get("risk_amount") or sizing.get("target_risk_amount") or 0.0)\n    execution_risk_budget = float(sizing.get("execution_risk_budget") or target_risk or 0.0)\n    fee_bps = float(sizing.get("fee_bps") if sizing.get("fee_bps") is not None else app_settings.execution_taker_fee_bps)\n''',
)

replace_once(
    "app/execution.py",
    '''        "target_risk": target_risk,\n        "gross_risk_reward": economics["gross_risk_reward"],\n''',
    '''        "target_risk": target_risk,\n        "execution_risk_budget": execution_risk_budget,\n        "gross_risk_reward": economics["gross_risk_reward"],\n''',
)

replace_once(
    "app/execution.py",
    '''    if target_risk > 0 and economics["net_risk"] > target_risk * RISK_AMOUNT_TOLERANCE + 1e-9:\n        return {\n            **evidence,\n            "allowed": False,\n            "reason": (\n                f"Actual fill fee-inclusive risk {economics['net_risk']:.8f} "\n                f"exceeds target {target_risk:.8f}"\n            ),\n        }\n    return {**evidence, "allowed": True, "reason": ""}\n''',
    '''    if target_risk > 0 and economics["net_risk"] > target_risk * RISK_AMOUNT_TOLERANCE + 1e-9:\n        return {\n            **evidence,\n            "allowed": False,\n            "status": "HARD_RISK_CAP_EXCEEDED",\n            "reason": (\n                f"Actual fill fee-inclusive risk {economics['net_risk']:.8f} "\n                f"exceeds hard target {target_risk:.8f}"\n            ),\n        }\n    if execution_risk_budget > 0 and economics["net_risk"] > execution_risk_budget * RISK_AMOUNT_TOLERANCE + 1e-9:\n        warning = (\n            f"Actual fill consumed execution headroom: fee-inclusive risk "\n            f"{economics['net_risk']:.8f} exceeds sizing budget {execution_risk_budget:.8f} "\n            f"but remains inside hard target {target_risk:.8f}"\n        )\n        return {\n            **evidence,\n            "allowed": True,\n            "status": "HEADROOM_CONSUMED",\n            "reason": "",\n            "warning": warning,\n        }\n    return {**evidence, "allowed": True, "reason": "", "warning": None}\n''',
)

Path("tests/test_execution_economics_guard.py").write_text(
    '''import unittest\nfrom datetime import UTC, datetime\n\nfrom app.execution import _validate_actual_fill_costs, _with_profile_runner_target\nfrom app.position_sizing import calculate_position_size\n\n\nclass FakeClient:\n    def normalize_quantity(self, value: float, qty_step: str) -> str:\n        step = float(qty_step)\n        normalized = int(value / step) * step\n        return f"{normalized:.8f}".rstrip("0").rstrip(".")\n\n\nclass ExecutionEconomicsGuardTests(unittest.TestCase):\n    def test_profile_runner_target_replaces_scanner_target_before_execution(self) -> None:\n        result = _with_profile_runner_target(\n            {\n                "symbol": "TESTUSDT",\n                "trade_type": "scalping",\n                "direction": "long",\n                "entry": 100.0,\n                "stop_loss": 99.0,\n                "take_profit": 101.5,\n                "risk_reward": 1.5,\n            }\n        )\n\n        self.assertEqual(result["strategy_take_profit"], 101.5)\n        self.assertEqual(result["take_profit"], 102.5)\n        self.assertEqual(result["risk_reward"], 2.5)\n        self.assertEqual(result["execution_target_source"], "profile_runner")\n\n    def test_position_sizing_reserves_ten_percent_risk_headroom(self) -> None:\n        result = calculate_position_size(\n            signal={\n                "symbol": "TESTUSDT",\n                "trade_type": "scalping",\n                "direction": "long",\n                "entry": 100.0,\n                "stop_loss": 99.0,\n                "take_profit": 103.0,\n                "detected_at": datetime.now(UTC).isoformat(),\n            },\n            wallet={"totalEquity": "1000", "totalAvailableBalance": "1000"},\n            symbol_info={\n                "qtyStep": "1",\n                "tickSize": "0.1",\n                "minOrderQty": "1",\n                "minNotionalValue": "5",\n            },\n            active_trades=[],\n            positions=[],\n            settings={\n                "risk_amount": 20.0,\n                "leverage_cap": 20.0,\n                "exposure_cap": 0.50,\n                "fee_bps": 5.5,\n                "slippage_bps": 2.0,\n                "risk_headroom_ratio": 0.90,\n            },\n            client=FakeClient(),\n        )\n\n        self.assertTrue(result["allowed"])\n        self.assertAlmostEqual(result["target_risk_amount"], 20.0, places=8)\n        self.assertAlmostEqual(result["execution_risk_budget"], 18.0, places=8)\n        self.assertAlmostEqual(result["risk_headroom_amount"], 2.0, places=8)\n        self.assertLessEqual(result["fee_inclusive_risk_amount"], 18.0 * 1.001)\n\n    def test_actual_fill_inside_hard_cap_uses_headroom_without_emergency_close(self) -> None:\n        result = _validate_actual_fill_costs(\n            {\n                "actual_fill": {"avg_price": 100.0, "quantity": 17.0},\n                "pre_order_risk": {\n                    "risk_amount": 20.0,\n                    "min_risk_reward": 1.5,\n                    "trade_type": "scalping",\n                },\n                "sizing": {\n                    "target_risk_amount": 20.0,\n                    "execution_risk_budget": 18.0,\n                    "fee_bps": 5.5,\n                    "slippage_bps": 2.0,\n                },\n            },\n            {\n                "symbol": "TESTUSDT",\n                "trade_type": "scalping",\n                "direction": "long",\n                "entry": 100.0,\n                "stop_loss": 99.0,\n                "take_profit": 103.0,\n                "quantity": 17.0,\n                "exchange_metadata": {},\n            },\n        )\n\n        self.assertTrue(result["allowed"])\n        self.assertEqual(result["status"], "HEADROOM_CONSUMED")\n        self.assertGreater(result["fee_inclusive_risk"], 18.0)\n        self.assertLess(result["fee_inclusive_risk"], 20.0)\n        self.assertIn("consumed execution headroom", result["warning"])\n\n    def test_final_managed_target_below_net_rr_minimum_is_rejected(self) -> None:\n        result = _validate_actual_fill_costs(\n            {\n                "actual_fill": {"avg_price": 100.0, "quantity": 100.0},\n                "pre_order_risk": {\n                    "risk_amount": 50.0,\n                    "min_risk_reward": 1.5,\n                    "trade_type": "scalping",\n                },\n                "sizing": {\n                    "target_risk_amount": 50.0,\n                    "execution_risk_budget": 45.0,\n                    "fee_bps": 5.5,\n                    "slippage_bps": 2.0,\n                },\n            },\n            {\n                "symbol": "TIGHTUSDT",\n                "trade_type": "scalping",\n                "direction": "long",\n                "entry": 100.0,\n                "stop_loss": 99.9,\n                "take_profit": 100.25,\n                "quantity": 100.0,\n                "exchange_metadata": {},\n            },\n        )\n\n        self.assertFalse(result["allowed"])\n        self.assertLess(result["net_risk_reward"], 1.5)\n        self.assertIn("below minimum", result["reason"])\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    encoding="utf-8",
)
