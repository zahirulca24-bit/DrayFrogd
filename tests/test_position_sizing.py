import unittest
from datetime import UTC, datetime

from app.position_sizing import calculate_position_size


class FakeClient:
    def normalize_quantity(self, value: float, qty_step: str) -> str:
        step = float(qty_step)
        normalized = int(value / step) * step
        return f"{normalized:.6f}".rstrip("0").rstrip(".")


class PositionSizingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.signal = {
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 95.0,
            "take_profit": 110.0,
            "detected_at": datetime.now(UTC).isoformat(),
        }
        self.wallet = {"totalEquity": "1000", "totalAvailableBalance": "500"}
        self.symbol_info = {
            "qtyStep": "0.001",
            "tickSize": "0.1",
            "minOrderQty": "0.001",
            "minNotionalValue": "5",
        }
        self.settings = {
            "risk_per_trade": 0.01,
            "leverage_cap": 5,
            "exposure_cap": 0.5,
        }

    def test_calculates_quantity_from_risk_and_sl_distance(self) -> None:
        result = calculate_position_size(
            signal=self.signal,
            wallet=self.wallet,
            symbol_info=self.symbol_info,
            active_trades=[],
            positions=[],
            settings=self.settings,
            client=FakeClient(),
        )

        self.assertTrue(result["allowed"])
        self.assertEqual(result["quantity"], "1.748")
        self.assertAlmostEqual(result["target_risk_amount"], 10.0)
        self.assertAlmostEqual(result["execution_risk_budget"], 9.0)
        self.assertAlmostEqual(result["risk_amount"], 8.995645)
        self.assertAlmostEqual(result["price_risk_amount"], 8.74)
        self.assertAlmostEqual(result["estimated_round_trip_fees"], 0.187473)
        self.assertAlmostEqual(result["notional"], 174.8)

    def test_rejects_when_required_margin_exceeds_available_balance(self) -> None:
        result = calculate_position_size(
            signal=self.signal,
            wallet={"totalEquity": "1000", "totalAvailableBalance": "10"},
            symbol_info=self.symbol_info,
            active_trades=[],
            positions=[],
            settings=self.settings,
            client=FakeClient(),
        )

        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "Required margin exceeds available balance")

    def test_rejects_when_exposure_cap_is_exceeded(self) -> None:
        result = calculate_position_size(
            signal=self.signal,
            wallet=self.wallet,
            symbol_info=self.symbol_info,
            active_trades=[{"required_margin": 480.0}],
            positions=[],
            settings=self.settings,
            client=FakeClient(),
        )

        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "Exposure cap exceeded")

    def test_exchange_positions_are_authoritative_when_available(self) -> None:
        result = calculate_position_size(
            signal=self.signal,
            wallet=self.wallet,
            symbol_info=self.symbol_info,
            active_trades=[{"required_margin": 490.0}],
            positions=[{"symbol": "BTCUSDT", "side": "Buy", "size": "1", "markPrice": "100", "leverage": "5"}],
            settings=self.settings,
            client=FakeClient(),
        )

        self.assertTrue(result["allowed"])
        self.assertEqual(result["current_exposure"], 20.0)

    def test_active_trades_are_used_as_fallback_when_positions_missing(self) -> None:
        result = calculate_position_size(
            signal=self.signal,
            wallet=self.wallet,
            symbol_info=self.symbol_info,
            active_trades=[{"required_margin": 480.0}],
            positions=[],
            settings=self.settings,
            client=FakeClient(),
        )

        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "Exposure cap exceeded")

    def test_duplicate_positions_are_counted_once(self) -> None:
        duplicated_position = {
            "symbol": "BTCUSDT",
            "side": "Buy",
            "positionIdx": "1",
            "size": "1",
            "positionIM": "400",
        }
        result = calculate_position_size(
            signal=self.signal,
            wallet=self.wallet,
            symbol_info=self.symbol_info,
            active_trades=[],
            positions=[duplicated_position, dict(duplicated_position)],
            settings=self.settings,
            client=FakeClient(),
        )

        self.assertTrue(result["allowed"])
        self.assertEqual(result["current_exposure"], 400.0)

    def test_hedge_mode_long_and_short_positions_remain_separate(self) -> None:
        result = calculate_position_size(
            signal=self.signal,
            wallet=self.wallet,
            symbol_info=self.symbol_info,
            active_trades=[],
            positions=[
                {"symbol": "BTCUSDT", "side": "Buy", "positionIdx": "1", "size": "1", "positionIM": "100"},
                {"symbol": "BTCUSDT", "side": "Sell", "positionIdx": "2", "size": "1", "positionIM": "100"},
            ],
            settings=self.settings,
            client=FakeClient(),
        )

        self.assertTrue(result["allowed"])
        self.assertEqual(result["current_exposure"], 200.0)

    def test_sol_scalping_regression_does_not_fill_remaining_exposure_budget(self) -> None:
        result = calculate_position_size(
            signal={
                "symbol": "SOLUSDT",
                "direction": "short",
                "entry": 76.50,
                "stop_loss": 76.91,
                "take_profit": 75.27,
                "detected_at": datetime.now(UTC).isoformat(),
            },
            wallet={"totalEquity": "600", "totalAvailableBalance": "600"},
            symbol_info={
                "qtyStep": "0.1",
                "tickSize": "0.01",
                "minOrderQty": "0.1",
                "minNotionalValue": "5",
            },
            active_trades=[],
            positions=[],
            settings={
                "risk_amount": 20.0,
                "leverage_cap": 20.0,
                "exposure_cap": 0.50,
            },
            client=FakeClient(),
        )

        self.assertTrue(result["allowed"])
        self.assertEqual(result["quantity"], "34.2")
        self.assertAlmostEqual(result["target_risk_amount"], 20.0)
        self.assertAlmostEqual(result["execution_risk_budget"], 18.0)
        self.assertAlmostEqual(result["risk_amount"], 17.9569665, places=6)
        self.assertAlmostEqual(result["price_risk_amount"], 14.022, places=3)
        self.assertAlmostEqual(result["estimated_round_trip_fees"], 2.8856421, places=6)
        self.assertAlmostEqual(result["notional"], 2616.30, places=2)
        self.assertEqual(result["selected_leverage"], 20.0)
        self.assertAlmostEqual(result["required_margin"], 130.815, places=4)
        self.assertLess(result["trade_margin_utilization"], 0.23)
        self.assertGreater(result["remaining_margin_capacity"], 169.0)

    def test_fixed_risk_trade_is_rejected_when_profile_leverage_cannot_fit_portfolio_cap(self) -> None:
        result = calculate_position_size(
            signal={
                "symbol": "SOLUSDT",
                "direction": "short",
                "entry": 76.50,
                "stop_loss": 76.91,
                "take_profit": 75.27,
                "detected_at": datetime.now(UTC).isoformat(),
            },
            wallet={"totalEquity": "600", "totalAvailableBalance": "600"},
            symbol_info={
                "qtyStep": "0.1",
                "tickSize": "0.01",
                "minOrderQty": "0.1",
                "minNotionalValue": "5",
            },
            active_trades=[{"required_margin": 250.0}],
            positions=[],
            settings={
                "risk_amount": 20.0,
                "leverage_cap": 20.0,
                "exposure_cap": 0.50,
            },
            client=FakeClient(),
        )

        self.assertFalse(result["allowed"])
        self.assertIn("profile cap", result["reason"])

    def test_rejects_long_when_stop_is_not_below_entry(self) -> None:
        result = calculate_position_size(
            signal={**self.signal, "stop_loss": 101.0, "take_profit": 110.0},
            wallet=self.wallet,
            symbol_info=self.symbol_info,
            active_trades=[],
            positions=[],
            settings=self.settings,
            client=FakeClient(),
        )

        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "Invalid SL/TP geometry for direction")

    def test_rejects_short_when_take_profit_is_not_below_entry(self) -> None:
        result = calculate_position_size(
            signal={**self.signal, "direction": "short", "stop_loss": 105.0, "take_profit": 102.0},
            wallet=self.wallet,
            symbol_info=self.symbol_info,
            active_trades=[],
            positions=[],
            settings=self.settings,
            client=FakeClient(),
        )

        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "Invalid SL/TP geometry for direction")

    def test_valid_short_keeps_strategy_levels_and_only_sizes_quantity(self) -> None:
        result = calculate_position_size(
            signal={**self.signal, "direction": "short", "stop_loss": 105.0, "take_profit": 90.0},
            wallet=self.wallet,
            symbol_info=self.symbol_info,
            active_trades=[],
            positions=[],
            settings=self.settings,
            client=FakeClient(),
        )

        self.assertTrue(result["allowed"])
        self.assertEqual(result["direction"], "short")
        self.assertEqual(result["stop_loss"], 105.0)
        self.assertEqual(result["take_profit"], 90.0)
        self.assertEqual(result["quantity"], "1.746")
        self.assertAlmostEqual(result["execution_risk_budget"], 9.0)

    def test_fee_aware_sui_regression_keeps_net_stop_loss_inside_target_risk(self) -> None:
        result = calculate_position_size(
            signal={
                "symbol": "SUIUSDT",
                "direction": "short",
                "entry": 0.7534,
                "stop_loss": 0.7579,
                "take_profit": 0.74665,
                "detected_at": datetime.now(UTC).isoformat(),
            },
            wallet={"totalEquity": "970", "totalAvailableBalance": "970"},
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
            },
            client=FakeClient(),
        )

        self.assertTrue(result["allowed"])
        self.assertEqual(result["quantity"], "3195")
        self.assertAlmostEqual(result["target_risk_amount"], 20.0)
        self.assertAlmostEqual(result["execution_risk_budget"], 18.0)
        self.assertLessEqual(result["risk_amount"], 18.0)
        self.assertAlmostEqual(result["price_risk_amount"], 14.3775, places=4)
        self.assertAlmostEqual(result["estimated_round_trip_fees"], 2.655731925, places=6)


if __name__ == "__main__":
    unittest.main()
