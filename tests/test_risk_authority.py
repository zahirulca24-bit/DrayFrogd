from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from app.position_sizing import calculate_position_size
from app.risk import (
    calculate_authoritative_risk_reward,
    calculate_risk_capacity,
    calculate_trade_live_risk,
    resolve_trade_type,
    validate_trade,
)
from app.risk_sync import _aggregate_progress


class FakeSizingClient:
    @staticmethod
    def normalize_quantity(value: float, qty_step: str) -> str:
        step = float(qty_step)
        normalized = int(value / step) * step
        return f"{normalized:.8f}".rstrip("0").rstrip(".")


class RiskAuthorityTests(unittest.TestCase):
    def test_authoritative_rr_validates_direction_geometry(self) -> None:
        long_result = calculate_authoritative_risk_reward(
            direction="long",
            entry=100.0,
            stop_loss=98.0,
            take_profit=103.0,
        )
        self.assertIsNotNone(long_result)
        self.assertAlmostEqual(long_result["risk_reward"], 1.5)

        short_result = calculate_authoritative_risk_reward(
            direction="short",
            entry=100.0,
            stop_loss=102.0,
            take_profit=96.0,
        )
        self.assertIsNotNone(short_result)
        self.assertAlmostEqual(short_result["risk_reward"], 2.0)

        self.assertIsNone(
            calculate_authoritative_risk_reward(
                direction="long",
                entry=100.0,
                stop_loss=101.0,
                take_profit=103.0,
            )
        )

    def test_break_even_and_profitable_stop_reduce_live_risk_to_zero(self) -> None:
        self.assertAlmostEqual(
            calculate_trade_live_risk(
                direction="long",
                entry=100.0,
                current_stop_loss=98.0,
                remaining_quantity=10.0,
            ),
            20.0,
        )
        self.assertEqual(
            calculate_trade_live_risk(
                direction="long",
                entry=100.0,
                current_stop_loss=100.0,
                remaining_quantity=10.0,
            ),
            0.0,
        )
        self.assertEqual(
            calculate_trade_live_risk(
                direction="short",
                entry=100.0,
                current_stop_loss=99.0,
                remaining_quantity=10.0,
            ),
            0.0,
        )

    def test_profit_recycles_and_loss_reduces_dynamic_risk_capacity(self) -> None:
        profit = calculate_risk_capacity(
            day_start_equity=1000.0,
            realized_pnl_today=10.0,
            live_risk=20.0,
        )
        self.assertEqual(profit["base_risk_pool"], 50.0)
        self.assertEqual(profit["effective_risk_pool"], 60.0)
        self.assertEqual(profit["available_risk"], 40.0)

        loss = calculate_risk_capacity(
            day_start_equity=1000.0,
            realized_pnl_today=-20.0,
            live_risk=10.0,
        )
        self.assertEqual(loss["effective_risk_pool"], 30.0)
        self.assertEqual(loss["available_risk"], 20.0)

    def test_trade_type_must_be_explicit_and_valid(self) -> None:
        self.assertIsNone(resolve_trade_type({"strategy_name": "ema_pullback"}))
        self.assertIsNone(resolve_trade_type({"strategy_name": "breakout"}))
        self.assertEqual(resolve_trade_type({"trade_type": "intraday", "strategy_name": "future"}), "intraday")
        self.assertEqual(resolve_trade_type({"trade_type": "scalping", "strategy_name": "ema_pullback"}), "scalping")
        self.assertIsNone(resolve_trade_type({"strategy_name": "unknown_strategy"}))

    def test_validate_trade_returns_locked_profile_and_recomputed_rr(self) -> None:
        state = {
            "circuit_breaker_active": False,
            "circuit_breaker_reason": None,
            "day_start_equity": 1000.0,
            "symbol_cooldowns": {},
            "active_symbols": [],
            "active_trade_count": 0,
            "available_risk": 50.0,
            "live_risk": 0.0,
            "base_risk_pool": 50.0,
            "effective_risk_pool": 50.0,
        }
        signal = {
            "symbol": "BTCUSDT",
            "strategy_name": "ema_pullback",
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 98.0,
            "take_profit": 103.0,
            "risk_reward": 1.5,
            "trade_type": "scalping",
            "status": "active",
        }
        with patch("app.risk.refresh_risk_state", return_value=state):
            result = validate_trade(signal, account_equity=1000.0)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["trade_type"], "scalping")
        self.assertEqual(result["risk_amount"], 20.0)
        self.assertEqual(result["leverage_cap"], 20.0)
        self.assertEqual(result["exposure_cap"], 0.50)
        self.assertEqual(result["max_active_trades"], 5)

    def test_validate_trade_rejects_manipulated_rr(self) -> None:
        signal = {
            "symbol": "BTCUSDT",
            "strategy_name": "ema_pullback",
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 98.0,
            "take_profit": 103.0,
            "risk_reward": 9.0,
            "trade_type": "scalping",
            "status": "active",
        }
        result = validate_trade(signal, account_equity=1000.0)
        self.assertFalse(result["allowed"])
        self.assertIn("mismatch", result["reason"].lower())

    def test_fixed_risk_position_sizing_uses_profile_leverage_without_filling_budget(self) -> None:
        result = calculate_position_size(
            signal={
                "symbol": "BTCUSDT",
                "direction": "long",
                "entry": 100.0,
                "stop_loss": 99.0,
                "take_profit": 101.5,
                "detected_at": datetime.now(UTC).isoformat(),
            },
            wallet={
                "totalEquity": "1000",
                "totalAvailableBalance": "1000",
            },
            symbol_info={
                "qtyStep": "0.001",
                "tickSize": "0.1",
                "minOrderQty": "0.001",
                "minNotionalValue": "5",
            },
            active_trades=[],
            positions=[],
            settings={
                "risk_amount": 20.0,
                "leverage_cap": 20.0,
                "exposure_cap": 0.50,
            },
            client=FakeSizingClient(),
        )
        self.assertTrue(result["allowed"])
        self.assertAlmostEqual(result["target_risk_amount"], 20.0)
        self.assertAlmostEqual(result["execution_risk_budget"], 18.0)
        self.assertAlmostEqual(result["risk_amount"], 17.9995535)
        self.assertAlmostEqual(result["price_risk_amount"], 15.662)
        self.assertAlmostEqual(result["estimated_round_trip_fees"], 1.7142059)
        self.assertAlmostEqual(result["notional"], 1566.2)
        self.assertAlmostEqual(result["minimum_required_leverage"], 3.1324)
        self.assertAlmostEqual(result["selected_leverage"], 20.0)
        self.assertAlmostEqual(result["required_margin"], 78.31)
        self.assertAlmostEqual(result["trade_margin_utilization"], 0.07831)
        self.assertAlmostEqual(result["remaining_margin_capacity"], 421.69)

    def test_partial_close_progress_allocates_realized_pnl_by_bdt_day(self) -> None:
        event_ms = int(datetime(2026, 7, 12, 1, 0, tzinfo=UTC).timestamp() * 1000)
        progress = _aggregate_progress(
            symbol="BTCUSDT",
            direction="long",
            initial_quantity=10.0,
            opened_ms=event_ms - 60_000,
            records=[
                {
                    "symbol": "BTCUSDT",
                    "side": "Sell",
                    "closedSize": "5",
                    "avgExitPrice": "102",
                    "closedPnl": "10",
                    "openFee": "0.5",
                    "closeFee": "0.5",
                    "updatedTime": str(event_ms),
                    "orderId": "tp1-order",
                }
            ],
            synced_at=datetime(2026, 7, 12, 1, 1, tzinfo=UTC),
        )
        self.assertIsNotNone(progress)
        self.assertEqual(progress["closed_size"], 5.0)
        self.assertEqual(progress["realized_pnl"], 10.0)
        # 01:00 UTC is 07:00 BDT on the same calendar date.
        self.assertEqual(progress["pnl_by_bdt_day"]["2026-07-12"], 10.0)


if __name__ == "__main__":
    unittest.main()
