from __future__ import annotations

import unittest

from app.sl_forensics import (
    FORENSIC_SCHEMA_VERSION,
    SL_REASON_FEE_DRAG_LOSS,
    SL_REASON_OVERHELD_SCALPING,
    SL_REASON_STOP_PRICE_CONFIRMED,
    build_sl_forensics,
    enrich_close_with_sl_forensics,
)


class SLForensicsTests(unittest.TestCase):
    def test_stop_exit_near_sl_is_classified_as_confirmed_stop(self) -> None:
        payload = build_sl_forensics(
            {
                "symbol": "BTCUSDT",
                "strategy_name": "EMA Rejection",
                "direction": "long",
                "entry": 100.0,
                "stop_loss": 99.0,
                "take_profit": 102.5,
                "quantity": 10,
                "opened_at": "2026-07-17T09:00:00+00:00",
                "exchange_metadata": {
                    "position_sizing": {"trade_type": "scalping"},
                },
            },
            {
                "result": "sl",
                "close_reason": "SL_TRIGGERED",
                "exit_price": 99.02,
                "fees": 1.0,
                "closed_at": "2026-07-17T09:07:30+00:00",
            },
        )

        self.assertEqual(payload["schema_version"], FORENSIC_SCHEMA_VERSION)
        self.assertEqual(payload["sl_hit_reason"], SL_REASON_STOP_PRICE_CONFIRMED)
        self.assertEqual(payload["strategy_name"], "EMA Rejection")
        self.assertEqual(payload["trade_type"], "scalping")
        self.assertAlmostEqual(payload["held_minutes"], 7.5)
        self.assertIn("exit_near_stop", payload["forensic_flags"])

    def test_fee_drag_loss_is_classified_when_fees_dominate_net_loss(self) -> None:
        payload = build_sl_forensics(
            {
                "symbol": "DOGEUSDT",
                "strategy": "Breakout Retest",
                "direction": "long",
                "entry": 1.00,
                "stop_loss": 0.98,
                "take_profit": 1.05,
                "quantity": 100,
                "exchange_metadata": {
                    "position_sizing": {"trade_type": "scalping"},
                },
            },
            {
                "result": "sl",
                "close_reason": "MANUAL_RISK_CLOSE",
                "exit_price": 0.995,
                "realized_pnl": -2.0,
                "fees": 1.25,
            },
        )

        self.assertEqual(payload["sl_hit_reason"], SL_REASON_FEE_DRAG_LOSS)
        self.assertIn("high_fee_drag", payload["forensic_flags"])
        self.assertAlmostEqual(payload["fee_drag_r"], 0.625)

    def test_overheld_scalping_sl_is_flagged_when_fast_trade_stays_open_too_long(self) -> None:
        payload = build_sl_forensics(
            {
                "symbol": "SOLUSDT",
                "strategy_name": "Liquidity Sweep",
                "direction": "short",
                "entry": 100.0,
                "stop_loss": 101.0,
                "take_profit": 97.5,
                "quantity": 5,
                "opened_at": "2026-07-17T09:00:00+00:00",
                "exchange_metadata": {
                    "position_sizing": {"trade_type": "scalping"},
                },
            },
            {
                "result": "sl",
                "close_reason": "RISK_REVIEW_CLOSE",
                "exit_price": 100.4,
                "fees": 0.25,
                "closed_at": "2026-07-17T10:15:00+00:00",
            },
        )

        self.assertEqual(payload["sl_hit_reason"], SL_REASON_OVERHELD_SCALPING)
        self.assertEqual(payload["held_seconds"], 4500)
        self.assertIn("overheld_scalping", payload["forensic_flags"])

    def test_enrich_close_fields_merges_forensics_into_exchange_metadata(self) -> None:
        enriched = enrich_close_with_sl_forensics(
            {
                "symbol": "BTCUSDT",
                "direction": "long",
                "entry": 100.0,
                "stop_loss": 99.0,
                "take_profit": 102.0,
                "quantity": 1,
                "exchange_metadata": {"existing": True},
            },
            {
                "result": "sl",
                "exit_price": 99.0,
                "close_reason": "EXCHANGE_STOP_LOSS",
            },
        )

        self.assertIn("sl_forensics", enriched["exchange_metadata"])
        self.assertTrue(enriched["exchange_metadata"]["existing"])
        self.assertEqual(enriched["sl_hit_reason"], SL_REASON_STOP_PRICE_CONFIRMED)


if __name__ == "__main__":
    unittest.main()
