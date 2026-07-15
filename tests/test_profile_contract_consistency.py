from __future__ import annotations

import unittest

from app.engines import ENGINE_PROFILES, INTRADAY_PROFILE, SCALPING_PROFILE
from app.intraday_protection_guard import INTRADAY_PROFILE as INTRADAY_PROTECTION_PROFILE
from app.risk import RISK_PROFILES
from app.trade_management_profiles import (
    PROFILE_NAMES,
    TRADE_MANAGEMENT_PROFILES,
    build_profile_management_state,
)


class ProfileContractConsistencyTests(unittest.TestCase):
    def test_risk_engine_profiles_derive_from_canonical_contract(self) -> None:
        self.assertEqual(set(RISK_PROFILES), set(ENGINE_PROFILES))
        for trade_type, profile in ENGINE_PROFILES.items():
            with self.subTest(trade_type=trade_type):
                self.assertEqual(RISK_PROFILES[trade_type], profile.risk_contract())

    def test_trade_management_profiles_derive_from_canonical_contract(self) -> None:
        self.assertEqual(set(TRADE_MANAGEMENT_PROFILES), set(ENGINE_PROFILES))
        self.assertEqual(PROFILE_NAMES, frozenset(profile.profile_name for profile in ENGINE_PROFILES.values()))
        for trade_type, profile in ENGINE_PROFILES.items():
            with self.subTest(trade_type=trade_type):
                self.assertEqual(TRADE_MANAGEMENT_PROFILES[trade_type], profile.management_contract())

    def test_management_state_uses_canonical_scalping_contract(self) -> None:
        state = build_profile_management_state(
            entry=100.0,
            stop_loss=99.0,
            take_profit=101.5,
            quantity=10.0,
            direction="long",
            trade_type="scalping",
        )
        self.assertEqual(state["profile_name"], SCALPING_PROFILE.profile_name)
        self.assertEqual(state["tp1_r"], SCALPING_PROFILE.tp1_r)
        self.assertEqual(state["max_hold_seconds"], SCALPING_PROFILE.max_hold_seconds)
        self.assertEqual(state["trailing_enabled"], SCALPING_PROFILE.trailing_enabled)

    def test_management_state_uses_canonical_intraday_contract(self) -> None:
        state = build_profile_management_state(
            entry=100.0,
            stop_loss=99.0,
            take_profit=102.0,
            quantity=10.0,
            direction="long",
            trade_type="intraday",
        )
        self.assertEqual(state["profile_name"], INTRADAY_PROFILE.profile_name)
        self.assertEqual(state["tp1_r"], INTRADAY_PROFILE.tp1_r)
        self.assertEqual(state["max_hold_seconds"], INTRADAY_PROFILE.max_hold_seconds)
        self.assertEqual(state["trailing_enabled"], INTRADAY_PROFILE.trailing_enabled)

    def test_intraday_fast_guard_uses_canonical_profile_name(self) -> None:
        self.assertEqual(INTRADAY_PROTECTION_PROFILE, INTRADAY_PROFILE.profile_name)


if __name__ == "__main__":
    unittest.main()
