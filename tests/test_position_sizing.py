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
        self.assertEqual(result["quantity"], "2")
        self.assertEqual(result["risk_amount"], 10.0)
        self.assertEqual(result["notional"], 200.0)

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


if __name__ == "__main__":
    unittest.main()
