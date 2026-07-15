from __future__ import annotations

from pathlib import Path
from textwrap import dedent, indent
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{label}: expected one match, found {text.count(old)}")
    return text.replace(old, new, 1)


def block(value: str, spaces: int = 0) -> str:
    normalized = dedent(value).strip("\n") + "\n"
    return indent(normalized, " " * spaces) if spaces else normalized


def update_environment() -> None:
    path = Path(".env.example")
    text = path.read_text()
    for line in (
        "EXECUTION_TAKER_FEE_BPS=5.5",
        "EXECUTION_SLIPPAGE_BPS=0.0",
    ):
        if line not in text:
            text = text.rstrip() + "\n" + line + "\n"
    path.write_text(text)


def update_config() -> None:
    path = Path("app/config.py")
    text = path.read_text()
    anchor = '    bot_scan_interval_seconds: int = int(os.getenv("BOT_SCAN_INTERVAL_SECONDS", "30"))\n'
    addition = (
        anchor
        + '    execution_taker_fee_bps: float = float(os.getenv("EXECUTION_TAKER_FEE_BPS", "5.5"))\n'
        + '    execution_slippage_bps: float = float(os.getenv("EXECUTION_SLIPPAGE_BPS", "0.0"))\n'
    )
    if "execution_taker_fee_bps" not in text:
        text = replace_once(text, anchor, addition, "config settings")
    path.write_text(text)


def update_position_sizing() -> None:
    path = Path("app/position_sizing.py")
    text = path.read_text()

    text = replace_once(
        text,
        "from app.exchange import BybitClient\n",
        block(
            """
            from app.exchange import BybitClient
            from app.trading_costs import (
                DEFAULT_SLIPPAGE_BPS,
                DEFAULT_TAKER_FEE_BPS,
                calculate_cost_adjusted_geometry,
            )
            """
        ),
        "position sizing imports",
    )
    text = text.replace("DEFAULT_FEE_BPS_PER_SIDE = 5.5\n", "")

    old_unit = block(
        """
        fee_bps_per_side = _non_negative_float(settings.get("fee_bps_per_side"))
        if fee_bps_per_side is None:
            fee_bps_per_side = DEFAULT_FEE_BPS_PER_SIDE
        fee_rate = fee_bps_per_side / 10_000
        estimated_fee_per_unit = (entry + stop_loss) * fee_rate
        risk_per_unit_with_fees = sl_distance + estimated_fee_per_unit
        if risk_per_unit_with_fees <= 0 or not isfinite(risk_per_unit_with_fees):
            return _reject("Position risk including fees is invalid")

        raw_quantity = target_risk_amount / risk_per_unit_with_fees
        """,
        4,
    )
    new_unit = block(
        """
        fee_bps = _non_negative_float(settings.get("fee_bps"))
        if fee_bps is None:
            fee_bps = _non_negative_float(settings.get("fee_bps_per_side"))
        if fee_bps is None:
            fee_bps = DEFAULT_TAKER_FEE_BPS
        slippage_bps = _non_negative_float(settings.get("slippage_bps"))
        if slippage_bps is None:
            slippage_bps = DEFAULT_SLIPPAGE_BPS
        min_net_risk_reward = _non_negative_float(settings.get("min_risk_reward")) or 0.0

        unit_economics = calculate_cost_adjusted_geometry(
            direction=normalized["direction"],
            entry=entry,
            stop_loss=stop_loss,
            take_profit=normalized["take_profit"],
            quantity=1.0,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        if unit_economics is None:
            return _reject("Invalid entry/SL/TP geometry")
        if unit_economics["net_reward"] <= 0:
            return _reject("Estimated fees and slippage eliminate the trade reward")
        if unit_economics["net_risk_reward"] + 1e-9 < min_net_risk_reward:
            return _reject(
                f"Net risk reward {unit_economics['net_risk_reward']:.4f} is below "
                f"minimum {min_net_risk_reward:.4f} after fees and slippage"
            )

        risk_per_unit_with_fees = unit_economics["net_risk"]
        raw_quantity = target_risk_amount / risk_per_unit_with_fees
        """,
        4,
    )
    text = replace_once(text, old_unit, new_unit, "unit economics")

    old_risk = block(
        """
        price_risk_amount = quantity * sl_distance
        estimated_open_fee = quantity * entry * fee_rate
        estimated_stop_fee = quantity * stop_loss * fee_rate
        estimated_round_trip_fees = estimated_open_fee + estimated_stop_fee
        actual_risk_amount = price_risk_amount + estimated_round_trip_fees
        if price_risk_amount <= 0 or actual_risk_amount <= 0 or not isfinite(actual_risk_amount):
            return _reject("Position risk is invalid")
        if actual_risk_amount > target_risk_amount * 1.001:
            return _reject("Minimum quantity exceeds configured fixed USDT risk after fees")
        """,
        4,
    )
    new_risk = block(
        """
        economics = calculate_cost_adjusted_geometry(
            direction=normalized["direction"],
            entry=entry,
            stop_loss=stop_loss,
            take_profit=normalized["take_profit"],
            quantity=quantity,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        if economics is None:
            return _reject("Position economics are invalid")

        actual_risk_amount = economics["net_risk"]
        price_risk_amount = economics["gross_risk"]
        estimated_open_fee = economics["estimated_entry_fee"]
        estimated_stop_fee = economics["estimated_stop_exit_fee"]
        estimated_round_trip_fees = economics["estimated_stop_costs"]
        if price_risk_amount <= 0 or actual_risk_amount <= 0 or not isfinite(actual_risk_amount):
            return _reject("Position risk is invalid")
        if actual_risk_amount > target_risk_amount * 1.001:
            return _reject("Minimum quantity exceeds configured fee-inclusive USDT risk")
        if economics["net_risk_reward"] + 1e-9 < min_net_risk_reward:
            return _reject(
                f"Net risk reward {economics['net_risk_reward']:.4f} is below "
                f"minimum {min_net_risk_reward:.4f} after quantity normalization"
            )
        """,
        4,
    )
    text = replace_once(text, old_risk, new_risk, "normalized economics")

    old_output = block(
        """
        "price_risk_amount": price_risk_amount,
        "estimated_open_fee": estimated_open_fee,
        "estimated_stop_fee": estimated_stop_fee,
        "estimated_round_trip_fees": estimated_round_trip_fees,
        "fee_bps_per_side": fee_bps_per_side,
        "risk_per_unit_with_fees": risk_per_unit_with_fees,
        "target_risk_amount": target_risk_amount,
        """,
        8,
    )
    new_output = block(
        """
        "price_risk_amount": price_risk_amount,
        "gross_price_risk_amount": price_risk_amount,
        "fee_inclusive_risk_amount": actual_risk_amount,
        "estimated_open_fee": estimated_open_fee,
        "estimated_entry_fee": estimated_open_fee,
        "estimated_stop_fee": estimated_stop_fee,
        "estimated_stop_exit_fee": estimated_stop_fee,
        "estimated_round_trip_fees": estimated_round_trip_fees,
        "estimated_stop_costs": economics["estimated_stop_costs"],
        "estimated_net_reward": economics["net_reward"],
        "gross_risk_reward": economics["gross_risk_reward"],
        "net_risk_reward": economics["net_risk_reward"],
        "fee_bps_per_side": fee_bps,
        "fee_bps": fee_bps,
        "slippage_bps": slippage_bps,
        "min_net_risk_reward": min_net_risk_reward,
        "risk_per_unit_with_fees": risk_per_unit_with_fees,
        "target_risk_amount": target_risk_amount,
        """,
        8,
    )
    text = replace_once(text, old_output, new_output, "position sizing output")
    path.write_text(text)


def update_execution_service() -> None:
    path = Path("app/execution_service.py")
    text = path.read_text()
    text = replace_once(
        text,
        "from app.bot_controls import can_execute, get_execution_mode\n",
        "from app.bot_controls import can_execute, get_execution_mode\nfrom app.config import settings as app_settings\n",
        "execution settings import",
    )
    text = replace_once(
        text,
        "from app.trade_management_profiles import build_profile_management_state, extract_observed_entry_fee\n",
        "from app.trade_management_profiles import build_profile_management_state, extract_observed_entry_fee\nfrom app.trading_costs import calculate_cost_adjusted_geometry\n",
        "execution cost import",
    )

    old_settings = block(
        """
        "risk_amount": validation.get("risk_amount"),
        "leverage_cap": validation.get("leverage_cap"),
        "exposure_cap": validation.get("exposure_cap"),
        """,
        12,
    )
    new_settings = block(
        """
        "risk_amount": validation.get("risk_amount"),
        "leverage_cap": validation.get("leverage_cap"),
        "exposure_cap": validation.get("exposure_cap"),
        "min_risk_reward": validation.get("min_risk_reward"),
        "fee_bps": app_settings.execution_taker_fee_bps,
        "slippage_bps": app_settings.execution_slippage_bps,
        """,
        12,
    )
    text = replace_once(text, old_settings, new_settings, "execution sizing settings")

    old_fill = block(
        """
        actual_entry = float(fill["avg_price"])
        actual_quantity = float(fill["quantity"])
        actual_check = _validate_actual_fill(
            direction=execution_signal["direction"],
            entry=actual_entry,
            stop_loss=float(stop_loss),
            take_profit=float(execution_signal["take_profit"]),
            quantity=actual_quantity,
            validation=validation,
        )

        provisional_trade_for_fee = {
            "exchange_metadata": {
                "fill_confirmation": fill,
            },
        }
        management = build_profile_management_state(
            entry=actual_entry,
            stop_loss=float(stop_loss),
            take_profit=float(execution_signal["take_profit"]),
            quantity=actual_quantity,
            direction=execution_signal["direction"],
            trade_type=validation.get("trade_type"),
            observed_entry_fee=extract_observed_entry_fee(provisional_trade_for_fee),
        )
        """,
        4,
    )
    new_fill = block(
        """
        actual_entry = float(fill["avg_price"])
        actual_quantity = float(fill["quantity"])
        provisional_trade_for_fee = {
            "exchange_metadata": {
                "fill_confirmation": fill,
            },
        }
        observed_entry_fee = extract_observed_entry_fee(provisional_trade_for_fee)
        actual_check = _validate_actual_fill(
            direction=execution_signal["direction"],
            entry=actual_entry,
            stop_loss=float(stop_loss),
            take_profit=float(execution_signal["take_profit"]),
            quantity=actual_quantity,
            validation=validation,
            fee_bps=float(sizing.get("fee_bps") or 0.0),
            slippage_bps=float(sizing.get("slippage_bps") or 0.0),
            observed_entry_fee=observed_entry_fee if observed_entry_fee > 0 else None,
        )

        management = build_profile_management_state(
            entry=actual_entry,
            stop_loss=float(stop_loss),
            take_profit=float(execution_signal["take_profit"]),
            quantity=actual_quantity,
            direction=execution_signal["direction"],
            trade_type=validation.get("trade_type"),
            observed_entry_fee=float(actual_check.get("estimated_entry_fee") or observed_entry_fee or 0.0),
        )
        """,
        4,
    )
    text = replace_once(text, old_fill, new_fill, "actual fill economics")

    replacement = block(
        """
        def _validate_actual_fill(
            *,
            direction: str,
            entry: float,
            stop_loss: float,
            take_profit: float,
            quantity: float,
            validation: dict[str, Any],
            fee_bps: float = 0.0,
            slippage_bps: float = 0.0,
            observed_entry_fee: float | None = None,
        ) -> dict[str, Any]:
            geometry = calculate_authoritative_risk_reward(
                direction=direction,
                entry=entry,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
            economics = calculate_cost_adjusted_geometry(
                direction=direction,
                entry=entry,
                stop_loss=stop_loss,
                take_profit=take_profit,
                quantity=quantity,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                observed_entry_fee=observed_entry_fee,
            )
            if geometry is None or economics is None:
                return {"allowed": False, "reason": "Actual fill invalidated entry/SL/TP geometry"}

            min_rr = float(validation.get("min_risk_reward") or 0.0)
            if economics["net_risk_reward"] + 1e-9 < min_rr:
                return {
                    "allowed": False,
                    "reason": (
                        f"Actual fill net RR {economics['net_risk_reward']:.4f} is below "
                        f"minimum {min_rr:.4f} after fees and slippage"
                    ),
                    "actual_risk_reward": geometry["risk_reward"],
                    "actual_net_risk_reward": economics["net_risk_reward"],
                    "actual_risk": economics["net_risk"],
                    "gross_price_risk": economics["gross_risk"],
                    "target_risk": float(validation.get("risk_amount") or 0.0),
                    "estimated_entry_fee": economics["estimated_entry_fee"],
                    "estimated_stop_exit_fee": economics["estimated_stop_exit_fee"],
                }

            actual_risk = economics["net_risk"]
            target_risk = float(validation.get("risk_amount") or 0.0)
            if actual_risk > target_risk * RISK_AMOUNT_TOLERANCE + 1e-9:
                return {
                    "allowed": False,
                    "reason": f"Actual fill fee-inclusive risk {actual_risk:.8f} exceeds target {target_risk:.8f}",
                    "actual_risk": actual_risk,
                    "gross_price_risk": economics["gross_risk"],
                    "target_risk": target_risk,
                    "actual_risk_reward": geometry["risk_reward"],
                    "actual_net_risk_reward": economics["net_risk_reward"],
                    "estimated_entry_fee": economics["estimated_entry_fee"],
                    "estimated_stop_exit_fee": economics["estimated_stop_exit_fee"],
                }
            return {
                "allowed": True,
                "reason": "",
                "actual_risk": actual_risk,
                "gross_price_risk": economics["gross_risk"],
                "target_risk": target_risk,
                "actual_risk_reward": geometry["risk_reward"],
                "actual_net_risk_reward": economics["net_risk_reward"],
                "estimated_entry_fee": economics["estimated_entry_fee"],
                "estimated_stop_exit_fee": economics["estimated_stop_exit_fee"],
                "estimated_stop_costs": economics["estimated_stop_costs"],
                "estimated_net_reward": economics["net_reward"],
                "fee_bps": economics["fee_bps"],
                "slippage_bps": economics["slippage_bps"],
            }
        """
    ).rstrip()
    pattern = r"def _validate_actual_fill\(.*?\n\n\ndef _attach_and_verify_protection"
    text, count = re.subn(
        pattern,
        replacement + "\n\n\ndef _attach_and_verify_protection",
        text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError(f"actual fill validator: expected one match, found {count}")
    path.write_text(text)


def add_tests() -> None:
    Path("tests/test_fee_risk_net_rr.py").write_text(
        dedent(
            '''
            from __future__ import annotations

            import unittest
            from datetime import UTC, datetime

            from app.execution_service import _validate_actual_fill
            from app.position_sizing import calculate_position_size
            from app.trading_costs import calculate_cost_adjusted_geometry


            class _Client:
                def normalize_quantity(self, value: float, qty_step: str) -> str:
                    step = float(qty_step)
                    normalized = int(value / step) * step
                    return f"{normalized:.8f}".rstrip("0").rstrip(".")


            class FeeRiskNetRRTests(unittest.TestCase):
                def test_cost_authority_reduces_nominal_one_point_five_r_below_minimum(self) -> None:
                    economics = calculate_cost_adjusted_geometry(
                        direction="long", entry=100.0, stop_loss=99.0,
                        take_profit=101.5, quantity=1.0, fee_bps=5.5,
                        slippage_bps=0.0,
                    )
                    self.assertIsNotNone(economics)
                    assert economics is not None
                    self.assertAlmostEqual(economics["gross_risk_reward"], 1.5)
                    self.assertLess(economics["net_risk_reward"], 1.5)

                def test_position_sizing_rejects_when_fees_reduce_net_rr(self) -> None:
                    result = calculate_position_size(
                        signal={
                            "symbol": "BTCUSDT", "direction": "long",
                            "entry": 100.0, "stop_loss": 99.0,
                            "take_profit": 101.5,
                            "detected_at": datetime.now(UTC).isoformat(),
                        },
                        wallet={"totalEquity": "1000", "totalAvailableBalance": "1000"},
                        symbol_info={
                            "qtyStep": "0.001", "tickSize": "0.1",
                            "minOrderQty": "0.001", "minNotionalValue": "5",
                        },
                        active_trades=[], positions=[],
                        settings={
                            "risk_amount": 20.0, "leverage_cap": 20.0,
                            "exposure_cap": 0.5, "fee_bps": 5.5,
                            "slippage_bps": 0.0, "min_risk_reward": 1.5,
                        },
                        client=_Client(),
                    )
                    self.assertFalse(result["allowed"])
                    self.assertIn("Net risk reward", result["reason"])

                def test_actual_fill_uses_observed_fee_and_net_rr(self) -> None:
                    result = _validate_actual_fill(
                        direction="long", entry=100.0, stop_loss=99.0,
                        take_profit=101.5, quantity=10.0,
                        validation={"min_risk_reward": 1.5, "risk_amount": 20.0},
                        fee_bps=5.5, slippage_bps=0.0,
                        observed_entry_fee=2.0,
                    )
                    self.assertFalse(result["allowed"])
                    self.assertIn("net RR", result["reason"])
                    self.assertEqual(result["estimated_entry_fee"], 2.0)

                def test_valid_fill_exposes_fee_inclusive_economics(self) -> None:
                    result = _validate_actual_fill(
                        direction="long", entry=100.0, stop_loss=99.0,
                        take_profit=103.0, quantity=10.0,
                        validation={"min_risk_reward": 1.5, "risk_amount": 20.0},
                        fee_bps=5.5, slippage_bps=0.0,
                    )
                    self.assertTrue(result["allowed"])
                    self.assertLessEqual(result["actual_risk"], 20.0)
                    self.assertGreaterEqual(result["actual_net_risk_reward"], 1.5)
                    self.assertGreater(result["estimated_stop_costs"], 0.0)


            if __name__ == "__main__":
                unittest.main()
            '''
        ).lstrip()
    )


def main() -> None:
    update_environment()
    update_config()
    update_position_sizing()
    update_execution_service()
    add_tests()


if __name__ == "__main__":
    main()
