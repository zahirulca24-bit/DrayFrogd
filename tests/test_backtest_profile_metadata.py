from __future__ import annotations

import unittest

from app.backtest import _profile_config
from app.engines import INTRADAY_PROFILE, SCALPING_PROFILE


class BacktestProfileMetadataTests(unittest.TestCase):
    def test_scalping_metadata_matches_canonical_profile(self) -> None:
        profile = _profile_config("scalping")
        self.assertEqual(profile["timeframes"], SCALPING_PROFILE.timeframes())
        self.assertEqual(profile["risk_contract"], SCALPING_PROFILE.risk_contract())
        self.assertEqual(profile["management_contract"], SCALPING_PROFILE.management_contract())

    def test_intraday_metadata_matches_canonical_profile(self) -> None:
        profile = _profile_config("intraday")
        self.assertEqual(profile["timeframes"], INTRADAY_PROFILE.timeframes())
        self.assertEqual(profile["risk_contract"], INTRADAY_PROFILE.risk_contract())
        self.assertEqual(profile["management_contract"], INTRADAY_PROFILE.management_contract())


if __name__ == "__main__":
    unittest.main()
