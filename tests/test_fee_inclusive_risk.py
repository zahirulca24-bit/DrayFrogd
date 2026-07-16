import unittest
from datetime import UTC, datetime

from app.execution import _validate_actual_fill_costs
from app.position_sizing import calculate_position_size
from app.trading_costs import calculate_cost_adjusted_geometry


class FakeClient:
    def normalize_quantity(self, value: float, qty_step: str) -> str:
        step = float(qty_step)
        normalized = int(value / step) * step
        return f"{normalized:.8f}".rstrip("0").rstrip(".")


class FeeInclusiveRiskTests(unittest.TestCase):
    def test_cost_geometry_increases_risk_and_reduces_reward(self) -> None:
        result = calculate_cost_adjusted_geometry(
            direction="long",
            entry=100.0,
            stop_loss=98.0,
            take_profit=104.0,
            quantity=10.0,
            fee_bps=5.5,
            slippage_bps=0.0,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertAlmostEqual(result["gross_risk"], 20.0, places=8)
        self.assertAlmostEqual(result["gross_risk_reward"], 2.0, places=8)
        self.assertGreater(result["net_risk"], result["gross_risk"])
        self.assertLess(result["net_reward"], result["gross_reward"])
        self.assertLess(result["net_risk_reward"], result["gross_risk_reward"])

    def test_scalping_sizing_keeps_fees_inside_twenty_usdt_budget(self) -> None:
        result = calculate_position_size(
            signal={
                "symbol": "DOGEUSDT",
                "trade_type": "scalping",
                "direction": "long",
                "entry": 0.0732,
                "stop_loss": 0.0728,
                "take_profit": 0.0744,
                "detected_at": datetime.now(UTC).isoformat(),
            },
            wallet={"totalEquity": "1000", "totalAvailableBalance": "1000"},
            symbol_info={
                "qtyStep": "1",
                "tickSize": "0.0001",
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
                "slippage_bps": 0.0,
            },
            client=FakeClient(),
        )

        self.assertTrue(result["allowed"])
        self.assertEqual(result["min_net_risk_reward"], 1.5)
        self.assertLess(result["gross_price_risk_amount"], 20.0)
        self.assertGreater(result["estimated_stop_costs"], 0.0)
        self.assertLessEqual(result["fee_inclusive_risk_amount"], 20.0 * 1.001)
        self.assertGreaterEqual(result["net_risk_reward"], 1.5)

    def test_nominal_one_point_five_r_is_rejected_when_fees_break_net_rr(self) -> None:
        result = calculate_position_size(
            signal={
                "symbol": "DOGEUSDT",
                "trade_type": "scalping",
                "direction": "long",
                "entry": 0.0732,
                "stop_loss": 0.0728,
                "take_profit": 0.0738,
                "detected_at": datetime.now(UTC).isoformat(),
            },
            wallet={"totalEquity": "1000", "totalAvailableBalance": "1000"},
            symbol_info={
                "qtyStep": "1",
                "tickSize": "0.0001",
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
                "slippage_bps": 0.0,
            },
            client=FakeClient(),
        )

        self.assertFalse(result["allowed"])
        self.assertIn("Net risk reward", result["reason"])
        self.assertIn("after fees and slippage", result["reason"])

    def test_intraday_uses_two_r_net_minimum_from_profile(self) -> None:
        result = calculate_position_size(
            signal={
                "symbol": "BTCUSDT",
                "trade_type": "intraday",
                "direction": "long",
                "entry": 100.0,
                "stop_loss": 99.0,
                "take_profit": 102.0,
                "detected_at": datetime.now(UTC).isoformat(),
            },
            wallet={"totalEquity": "1000", "totalAvailableBalance": "1000"},
            symbol_info={
                "qtyStep": "0.001",
                "tickSize": "0.1",
                "minOrderQty": "0.001",
                "minNotionalValue": "5",
            },
            active_trades=[],
            positions=[],
            settings={
                "risk_amount": 50.0,
                "leverage_cap": 10.0,
                "exposure_cap": 0.50,
                "fee_bps": 5.5,
                "slippage_bps": 0.0,
            },
            client=FakeClient(),
        )

        self.assertFalse(result["allowed"])
        self.assertIn("minimum 2.0000", result["reason"])

    def test_actual_fill_rejects_fee_inclusive_risk_above_budget(self) -> None:
        result = _validate_actual_fill_costs(
            {
                "actual_fill": {"avg_price": 100.0, "quantity": 10.0},
                "pre_order_risk": {
                    "risk_amount": 20.0,
                    "min_risk_reward": 1.5,
                    "trade_type": "scalping",
                },
                "sizing": {"fee_bps": 5.5, "slippage_bps": 0.0},
            },
            {
                "symbol": "TESTUSDT",
                "trade_type": "scalping",
                "direction": "long",
                "entry": 100.0,
                "stop_loss": 98.0,
                "take_profit": 104.0,
                "quantity": 10.0,
                "exchange_metadata": {},
            },
        )

        self.assertFalse(result["allowed"])
        self.assertAlmostEqual(result["gross_price_risk"], 20.0, places=8)
        self.assertGreater(result["fee_inclusive_risk"], 20.0)
        self.assertIn("fee-inclusive risk", result["reason"])

    def test_actual_fill_rejects_net_rr_below_profile_minimum(self) -> None:
        result = _validate_actual_fill_costs(
            {
                "actual_fill": {"avg_price": 0.0732, "quantity": 1000.0},
                "pre_order_risk": {
                    "risk_amount": 1000.0,
                    "min_risk_reward": 1.5,
                    "trade_type": "scalping",
                },
                "sizing": {"fee_bps": 5.5, "slippage_bps": 0.0},
            },
            {
                "symbol": "DOGEUSDT",
                "trade_type": "scalping",
                "direction": "long",
                "entry": 0.0732,
                "stop_loss": 0.0728,
                "take_profit": 0.0738,
                "quantity": 1000.0,
                "exchange_metadata": {},
            },
        )

        self.assertFalse(result["allowed"])
        self.assertAlmostEqual(result["gross_risk_reward"], 1.5, places=8)
        self.assertLess(result["net_risk_reward"], 1.5)
        self.assertIn("net RR", result["reason"])


if __name__ == "__main__":
    unittest.main()
