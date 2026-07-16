import unittest
from datetime import UTC, datetime

from app.execution import _validate_actual_fill_costs, _with_profile_runner_target
from app.position_sizing import calculate_position_size


class FakeClient:
    def normalize_quantity(self, value: float, qty_step: str) -> str:
        step = float(qty_step)
        normalized = int(value / step) * step
        return f"{normalized:.8f}".rstrip("0").rstrip(".")


class ExecutionEconomicsGuardTests(unittest.TestCase):
    """Regression contract for final-target Net RR and execution headroom."""

    def test_profile_runner_target_replaces_scanner_target_before_execution(self) -> None:
        result = _with_profile_runner_target(
            {
                "symbol": "TESTUSDT",
                "trade_type": "scalping",
                "direction": "long",
                "entry": 100.0,
                "stop_loss": 99.0,
                "take_profit": 101.5,
                "risk_reward": 1.5,
            }
        )

        self.assertEqual(result["strategy_take_profit"], 101.5)
        self.assertEqual(result["take_profit"], 102.5)
        self.assertEqual(result["risk_reward"], 2.5)
        self.assertEqual(result["execution_target_source"], "profile_runner")

    def test_position_sizing_reserves_ten_percent_risk_headroom(self) -> None:
        result = calculate_position_size(
            signal={
                "symbol": "TESTUSDT",
                "trade_type": "scalping",
                "direction": "long",
                "entry": 100.0,
                "stop_loss": 99.0,
                "take_profit": 103.0,
                "detected_at": datetime.now(UTC).isoformat(),
            },
            wallet={"totalEquity": "1000", "totalAvailableBalance": "1000"},
            symbol_info={
                "qtyStep": "1",
                "tickSize": "0.1",
                "minOrderQty": "1",
                "minNotionalValue": "5",
            },
            active_trades=[],
            positions=[],
            settings={
                "risk_amount": 20.0,
                "leverage_cap": 20.0,
                "exposure_cap": 0.50,
                "fee_bps": 5.5,
                "slippage_bps": 2.0,
                "risk_headroom_ratio": 0.90,
            },
            client=FakeClient(),
        )

        self.assertTrue(result["allowed"])
        self.assertAlmostEqual(result["target_risk_amount"], 20.0, places=8)
        self.assertAlmostEqual(result["execution_risk_budget"], 18.0, places=8)
        self.assertAlmostEqual(result["risk_headroom_amount"], 2.0, places=8)
        self.assertLessEqual(result["fee_inclusive_risk_amount"], 18.0 * 1.001)

    def test_actual_fill_inside_hard_cap_uses_headroom_without_emergency_close(self) -> None:
        result = _validate_actual_fill_costs(
            {
                "actual_fill": {"avg_price": 100.0, "quantity": 17.0},
                "pre_order_risk": {
                    "risk_amount": 20.0,
                    "min_risk_reward": 1.5,
                    "trade_type": "scalping",
                },
                "sizing": {
                    "target_risk_amount": 20.0,
                    "execution_risk_budget": 18.0,
                    "fee_bps": 5.5,
                    "slippage_bps": 2.0,
                },
            },
            {
                "symbol": "TESTUSDT",
                "trade_type": "scalping",
                "direction": "long",
                "entry": 100.0,
                "stop_loss": 99.0,
                "take_profit": 103.0,
                "quantity": 17.0,
                "exchange_metadata": {},
            },
        )

        self.assertTrue(result["allowed"])
        self.assertEqual(result["status"], "HEADROOM_CONSUMED")
        self.assertGreater(result["fee_inclusive_risk"], 18.0)
        self.assertLess(result["fee_inclusive_risk"], 20.0)
        self.assertIn("consumed execution headroom", result["warning"])

    def test_final_managed_target_below_net_rr_minimum_is_rejected(self) -> None:
        result = _validate_actual_fill_costs(
            {
                "actual_fill": {"avg_price": 100.0, "quantity": 100.0},
                "pre_order_risk": {
                    "risk_amount": 50.0,
                    "min_risk_reward": 1.5,
                    "trade_type": "scalping",
                },
                "sizing": {
                    "target_risk_amount": 50.0,
                    "execution_risk_budget": 45.0,
                    "fee_bps": 5.5,
                    "slippage_bps": 2.0,
                },
            },
            {
                "symbol": "TIGHTUSDT",
                "trade_type": "scalping",
                "direction": "long",
                "entry": 100.0,
                "stop_loss": 99.9,
                "take_profit": 100.25,
                "quantity": 100.0,
                "exchange_metadata": {},
            },
        )

        self.assertFalse(result["allowed"])
        self.assertLess(result["net_risk_reward"], 1.5)
        self.assertIn("below minimum", result["reason"])


if __name__ == "__main__":
    unittest.main()
