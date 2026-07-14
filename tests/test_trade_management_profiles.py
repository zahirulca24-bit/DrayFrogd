from __future__ import annotations

import unittest

from app.trade_management_profiles import (
    break_even_stop,
    build_profile_management_state,
    is_scalping_management,
    max_hold_seconds,
    normalize_trade_type,
    post_tp2_stop,
    trade_type_from_trade,
    trailing_enabled,
)


class TradeManagementProfileTests(unittest.TestCase):
    def test_scalping_profile_uses_one_point_five_two_and_two_point_five_r(self) -> None:
        management = build_profile_management_state(
            entry=100.0,
            stop_loss=98.0,
            take_profit=103.0,
            quantity=10.0,
            direction="long",
            trade_type="scalping",
            observed_entry_fee=0.5,
        )

        self.assertEqual(management["profile_name"], "scalping_v2")
        self.assertEqual(management["tp1"], 103.0)
        self.assertEqual(management["tp2"], 104.0)
        self.assertEqual(management["runner_target"], 105.0)
        self.assertFalse(management["trailing_enabled"])
        self.assertEqual(max_hold_seconds(management), 30 * 60)
        self.assertTrue(is_scalping_management(management))
        self.assertAlmostEqual(management["break_even_price"], 100.1)
        self.assertEqual(post_tp2_stop({"entry": 100.0, "stop_loss": 98.0, "direction": "long"}, management, 104.0), 103.0)

    def test_short_scalping_break_even_buffer_moves_below_entry(self) -> None:
        management = build_profile_management_state(
            entry=100.0,
            stop_loss=102.0,
            take_profit=97.0,
            quantity=10.0,
            direction="short",
            trade_type="scalping",
            observed_entry_fee=0.5,
        )

        self.assertAlmostEqual(break_even_stop({}, management), 99.9)
        self.assertEqual(management["tp1"], 97.0)
        self.assertEqual(management["tp2"], 96.0)
        self.assertEqual(management["runner_target"], 95.0)

    def test_intraday_profile_keeps_existing_targets_and_trailing(self) -> None:
        management = build_profile_management_state(
            entry=100.0,
            stop_loss=95.0,
            take_profit=110.0,
            quantity=4.0,
            direction="long",
            trade_type="intraday",
        )

        self.assertEqual(management["profile_name"], "intraday_v1")
        self.assertEqual(management["tp1"], 110.0)
        self.assertEqual(management["tp2"], 112.5)
        self.assertEqual(management["runner_target"], 115.0)
        self.assertTrue(trailing_enabled(management))
        self.assertEqual(max_hold_seconds(management), 6 * 60 * 60)

    def test_no_fee_observation_does_not_invent_fee_rate(self) -> None:
        management = build_profile_management_state(
            entry=100.0,
            stop_loss=98.0,
            take_profit=103.0,
            quantity=10.0,
            direction="long",
            trade_type="scalping",
            observed_entry_fee=0.0,
        )

        self.assertEqual(management["break_even_price"], 100.0)
        self.assertEqual(management["fee_buffer_source"], "entry_fee_unavailable")

    def test_missing_trade_type_does_not_default_to_scalping(self) -> None:
        self.assertIsNone(normalize_trade_type(None))
        self.assertIsNone(trade_type_from_trade({"strategy": "ema_pullback"}))
        with self.assertRaises(ValueError):
            build_profile_management_state(
                entry=100.0,
                stop_loss=98.0,
                take_profit=103.0,
                quantity=10.0,
                direction="long",
                trade_type=None,
            )


if __name__ == "__main__":
    unittest.main()
