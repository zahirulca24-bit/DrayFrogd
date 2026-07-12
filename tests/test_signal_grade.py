from __future__ import annotations

import unittest

import app.scanner as scanner
from app.scanner import _grade_counts, _normalize_strategy_result, get_active_signals, get_watchlist_signals
from app.signal_grade import (
    ACTION_EXECUTE,
    ACTION_REJECT,
    ACTION_WATCHLIST,
    GRADE_A,
    GRADE_A_PLUS,
    GRADE_B_PLUS,
    GRADE_REJECT,
    grade_signal,
)


class SignalGradeEngineTests(unittest.TestCase):
    def test_a_plus_scalping_requires_strong_quality_and_preferred_rr(self) -> None:
        result = grade_signal(self._signal(rr=2.5, quality=100))

        self.assertEqual(result["grade"], GRADE_A_PLUS)
        self.assertEqual(result["grade_action"], ACTION_EXECUTE)
        self.assertTrue(result["executable"])
        self.assertFalse(result["watchlist_only"])
        self.assertEqual(result["authoritative_risk_reward"], 2.5)

    def test_a_scalping_accepts_locked_one_point_five_minimum(self) -> None:
        result = grade_signal(self._signal(rr=1.5, quality=90))

        self.assertEqual(result["grade"], GRADE_A)
        self.assertEqual(result["grade_minimum_rr"], 1.5)
        self.assertTrue(result["executable"])

    def test_a_intraday_accepts_locked_two_point_zero_minimum(self) -> None:
        result = grade_signal(self._signal(rr=2.0, quality=90, trade_type="intraday"))

        self.assertEqual(result["grade"], GRADE_A)
        self.assertEqual(result["grade_minimum_rr"], 2.0)
        self.assertTrue(result["executable"])

    def test_intraday_below_two_point_zero_is_rejected(self) -> None:
        result = grade_signal(self._signal(rr=1.5, quality=100, trade_type="intraday"))

        self.assertEqual(result["grade"], GRADE_REJECT)
        self.assertEqual(result["grade_action"], ACTION_REJECT)
        self.assertIn("risk_reward_below_profile_minimum", result["grade_reasons"])

    def test_b_plus_is_near_setup_watchlist_only(self) -> None:
        result = grade_signal(self._signal(rr=1.5, quality=90, status="near_setup"))

        self.assertEqual(result["grade"], GRADE_B_PLUS)
        self.assertEqual(result["grade_action"], ACTION_WATCHLIST)
        self.assertFalse(result["executable"])
        self.assertTrue(result["watchlist_only"])

    def test_active_signal_below_a_quality_is_rejected_not_watchlisted(self) -> None:
        result = grade_signal(self._signal(rr=1.5, quality=70, status="active"))

        self.assertEqual(result["grade"], GRADE_REJECT)
        self.assertEqual(result["grade_action"], ACTION_REJECT)
        self.assertFalse(result["watchlist_only"])
        self.assertIn("active_signal_quality_below_A_threshold", result["grade_reasons"])

    def test_blocked_signal_is_rejected(self) -> None:
        result = grade_signal(self._signal(rr=2.5, quality=100, status="blocked"))

        self.assertEqual(result["grade"], GRADE_REJECT)
        self.assertIn("signal_not_active_or_near_setup", result["grade_reasons"])

    def test_trend_misaligned_signal_is_rejected(self) -> None:
        signal = self._signal(rr=2.5, quality=100)
        signal["trend_aligned"] = False
        result = grade_signal(signal)

        self.assertEqual(result["grade"], GRADE_REJECT)
        self.assertIn("signal_not_aligned_with_1h_trend", result["grade_reasons"])

    def test_invalid_geometry_is_rejected(self) -> None:
        signal = self._signal(rr=2.5, quality=100)
        signal["stop_loss"] = 101.0
        result = grade_signal(signal)

        self.assertEqual(result["grade"], GRADE_REJECT)
        self.assertIn("invalid_trade_geometry", result["grade_reasons"])

    def test_authoritative_rr_is_calculated_from_prices(self) -> None:
        signal = self._signal(rr=2.5, quality=100)
        signal["risk_reward"] = 99.0
        result = grade_signal(signal)

        self.assertEqual(result["authoritative_risk_reward"], 2.5)
        self.assertEqual(result["grade"], GRADE_A_PLUS)

    def test_intraday_two_point_five_cannot_receive_a_plus(self) -> None:
        result = grade_signal(self._signal(rr=2.5, quality=100, trade_type="intraday"))

        self.assertEqual(result["grade"], GRADE_A)
        self.assertEqual(result["grade_preferred_rr"], 3.0)

    def test_weak_volume_prevents_a_plus(self) -> None:
        signal = self._signal(rr=2.5, quality=100)
        signal["market_score_components"]["volume"] = 3.0
        result = grade_signal(signal)

        self.assertNotEqual(result["grade"], GRADE_A_PLUS)
        self.assertEqual(result["grade"], GRADE_A)

    def test_unknown_trade_type_uses_scalping_profile(self) -> None:
        result = grade_signal(self._signal(rr=1.5, quality=90, trade_type="unknown"))

        self.assertEqual(result["grade_trade_type"], "scalping")
        self.assertEqual(result["grade_minimum_rr"], 1.5)

    @staticmethod
    def _signal(
        *,
        rr: float,
        quality: float,
        status: str = "active",
        trade_type: str = "scalping",
    ) -> dict:
        entry = 100.0
        stop_loss = 99.0
        take_profit = entry + rr
        return {
            "symbol": "BTCUSDT",
            "strategy_name": "ema_pullback",
            "trade_type": trade_type,
            "direction": "long",
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_reward": rr,
            "status": status,
            "trend_aligned": True,
            "trend_strength": quality,
            "confidence_score": quality,
            "market_score": quality,
            "market_score_components": {"volume": 15.0},
            "setup_15m": {"score": quality},
            "confirmation_5m": {"score": quality if status == "active" else 70.0},
        }


class ScannerGradeRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        with scanner._signals_lock:
            scanner._latest_signals.clear()
            scanner._latest_watchlist_signals.clear()
            scanner._latest_scan_results.clear()

    def test_scanner_normalization_attaches_a_grade(self) -> None:
        result = _normalize_strategy_result(
            symbol="BTCUSDT",
            result=self._strategy_result(status="active", rr=1.5, confidence=90),
            trend={"state": "UPTREND", "strength": 90.0, "reason": "test"},
            market_ranking={"score": 90.0, "components": {"volume": 15.0}},
            scanner_logic=self._scanner_logic(status="active", score=90),
        )

        self.assertEqual(result["grade"], GRADE_A)
        self.assertTrue(result["executable"])
        self.assertEqual(result["grade_action"], ACTION_EXECUTE)

    def test_scanner_normalization_routes_near_setup_to_b_plus(self) -> None:
        result = _normalize_strategy_result(
            symbol="BTCUSDT",
            result=self._strategy_result(status="near_setup", rr=1.5, confidence=90),
            trend={"state": "UPTREND", "strength": 90.0, "reason": "test"},
            market_ranking={"score": 90.0, "components": {"volume": 15.0}},
            scanner_logic=self._scanner_logic(status="near_setup", score=90),
        )

        self.assertEqual(result["grade"], GRADE_B_PLUS)
        self.assertTrue(result["watchlist_only"])
        self.assertFalse(result["executable"])

    def test_structure_gate_downgrade_is_graded_as_watchlist(self) -> None:
        result = _normalize_strategy_result(
            symbol="BTCUSDT",
            result={**self._strategy_result(status="active", rr=1.5, confidence=90), "strategy_name": "pure_smc", "strategy": "pure_smc"},
            trend={"state": "UPTREND", "strength": 90.0, "reason": "test"},
            market_ranking={"score": 90.0, "components": {"volume": 15.0}},
            scanner_logic=self._scanner_logic(status="near_setup", score=90),
        )

        self.assertEqual(result["original_status"], "active")
        self.assertEqual(result["status"], "near_setup")
        self.assertEqual(result["grade"], GRADE_B_PLUS)
        self.assertTrue(result["watchlist_only"])

    def test_active_signal_accessor_returns_only_a_and_a_plus(self) -> None:
        executable = {"status": "active", "grade": GRADE_A, "executable": True, "symbol": "BTCUSDT"}
        non_executable = {"status": "active", "grade": GRADE_REJECT, "executable": False, "symbol": "ETHUSDT"}
        with scanner._signals_lock:
            scanner._latest_signals.extend([executable, non_executable])

        self.assertEqual(get_active_signals(), [executable])

    def test_watchlist_accessor_returns_b_plus_only_routed_items(self) -> None:
        watchlist = {"status": "near_setup", "grade": GRADE_B_PLUS, "watchlist_only": True, "symbol": "BTCUSDT"}
        with scanner._signals_lock:
            scanner._latest_watchlist_signals.append(watchlist)

        self.assertEqual(get_watchlist_signals(), [watchlist])

    def test_grade_counts_are_deterministic(self) -> None:
        counts = _grade_counts(
            [
                {"grade": GRADE_A_PLUS},
                {"grade": GRADE_A},
                {"grade": GRADE_A},
                {"grade": GRADE_B_PLUS},
                {"grade": GRADE_REJECT},
                {},
            ]
        )

        self.assertEqual(counts, {GRADE_A_PLUS: 1, GRADE_A: 2, GRADE_B_PLUS: 1, GRADE_REJECT: 2})

    @staticmethod
    def _strategy_result(*, status: str, rr: float, confidence: float) -> dict:
        return {
            "strategy_name": "ema_pullback",
            "strategy": "ema_pullback",
            "trade_type": "scalping",
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 99.0,
            "take_profit": 100.0 + rr,
            "risk_reward": rr,
            "detected_at": "2026-01-01T00:00:00+00:00",
            "status": status,
            "confidence_score": confidence,
            "rejection_reason": None,
        }

    @staticmethod
    def _scanner_logic(*, status: str, score: float) -> dict:
        return {
            "status": status,
            "direction": "long",
            "reason": "test",
            "confidence_score": score,
            "setup_15m": {"score": score, "qualified": True},
            "confirmation_5m": {"score": score if status == "active" else 70.0},
        }


if __name__ == "__main__":
    unittest.main()
