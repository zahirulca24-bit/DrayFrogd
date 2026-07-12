from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.scanner import _normalize_strategy_result
from app.scanner_logic import (
    PriceZone,
    StructureEvent,
    _displacement_confirmed,
    _find_liquidity_sweep,
    _latest_structure_event,
    _normalize_candles,
    analyze_15m_setup,
    confirm_5m_entry,
    evaluate_multitimeframe_logic,
)


class ScannerLogicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_time = datetime(2026, 1, 1, tzinfo=UTC)
        self.candles = self._candles(30)
        self.long_event = StructureEvent(
            direction="long",
            event_type="CHOCH",
            index=20,
            reference_high=110.0,
            reference_low=90.0,
            prior_structure="bearish",
        )
        self.short_event = StructureEvent(
            direction="short",
            event_type="CHOCH",
            index=20,
            reference_high=110.0,
            reference_low=90.0,
            prior_structure="bullish",
        )

    def test_15m_missing_data_is_rejected(self) -> None:
        result = analyze_15m_setup(self.candles[:10], trend_state="UPTREND")
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "missing_15m_data")

    def test_15m_structure_conflict_with_1h_trend_is_blocked(self) -> None:
        with patch("app.scanner_logic._latest_structure_event", return_value=self.short_event):
            result = analyze_15m_setup(self.candles, trend_state="UPTREND")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "15m_structure_conflicts_with_1h_trend")

    def test_15m_setup_requires_all_locked_components(self) -> None:
        with self._qualified_setup_patches(), patch("app.scanner_logic._find_liquidity_sweep", return_value=None):
            result = analyze_15m_setup(self.candles, trend_state="UPTREND")
        self.assertFalse(result["qualified"])
        self.assertEqual(result["reason"], "15m_liquidity_sweep_not_found")
        self.assertEqual(result["score"], 80)

    def test_15m_setup_qualifies_bos_choch_sweep_fvg_ob_and_discount(self) -> None:
        with self._qualified_setup_patches():
            result = analyze_15m_setup(self.candles, trend_state="UPTREND")
        self.assertTrue(result["qualified"])
        self.assertEqual(result["status"], "near_setup")
        self.assertEqual(result["location"], "discount")
        self.assertEqual(result["score"], 100)
        self.assertTrue(all(result["checks"].values()))

    def test_15m_long_setup_rejects_premium_location(self) -> None:
        with patch("app.scanner_logic._latest_structure_event", return_value=self.long_event), patch(
            "app.scanner_logic._find_liquidity_sweep",
            return_value={"side": "sell_side"},
        ), patch(
            "app.scanner_logic._find_order_block",
            return_value=PriceZone(104.0, 106.0),
        ), patch(
            "app.scanner_logic._find_fvg",
            return_value=PriceZone(105.0, 107.0),
        ):
            result = analyze_15m_setup(self.candles, trend_state="UPTREND")
        self.assertFalse(result["qualified"])
        self.assertEqual(result["location"], "premium")
        self.assertEqual(result["reason"], "15m_premium_discount_invalid")

    def test_5m_is_blocked_until_15m_setup_is_qualified(self) -> None:
        result = confirm_5m_entry(self.candles, {"qualified": False, "direction": "long"})
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "15m_setup_not_qualified")

    def test_5m_waits_for_choch_not_bos(self) -> None:
        bos_event = StructureEvent(
            direction="long",
            event_type="BOS",
            index=20,
            reference_high=110.0,
            reference_low=90.0,
            prior_structure="bullish",
        )
        with patch("app.scanner_logic._latest_structure_event", return_value=bos_event), patch(
            "app.scanner_logic._displacement_confirmed", return_value=True
        ):
            result = confirm_5m_entry(self.candles, self._qualified_setup())
        self.assertEqual(result["status"], "near_setup")
        self.assertEqual(result["reason"], "waiting_for_5m_choch")

    def test_5m_waits_for_displacement_after_choch(self) -> None:
        with patch("app.scanner_logic._latest_structure_event", return_value=self.long_event), patch(
            "app.scanner_logic._displacement_confirmed", return_value=False
        ), patch("app.scanner_logic._find_fvg", return_value=PriceZone(99.0, 100.0)), patch(
            "app.scanner_logic._find_order_block", return_value=PriceZone(98.0, 99.5)
        ):
            result = confirm_5m_entry(self.candles, self._qualified_setup())
        self.assertEqual(result["status"], "near_setup")
        self.assertEqual(result["reason"], "waiting_for_5m_displacement")

    def test_5m_active_on_choch_displacement_and_fvg_retest(self) -> None:
        with self._active_confirmation_patches(fvg_retest=True, ob_reaction=False):
            result = confirm_5m_entry(self.candles, self._qualified_setup())
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["reason"], "5m_entry_confirmed")
        self.assertEqual(result["risk_reward"], 1.5)
        self.assertLess(result["stop_loss"], result["entry"])
        self.assertGreater(result["take_profit"], result["entry"])

    def test_5m_active_on_order_block_reaction_without_fvg_retest(self) -> None:
        with self._active_confirmation_patches(fvg_retest=False, ob_reaction=True):
            result = confirm_5m_entry(self.candles, self._qualified_setup())
        self.assertEqual(result["status"], "active")
        self.assertFalse(result["fvg_retest"])
        self.assertTrue(result["order_block_reaction"])

    def test_5m_rejects_invalid_trade_geometry(self) -> None:
        with self._active_confirmation_patches(fvg_retest=True, ob_reaction=False), patch(
            "app.scanner_logic._entry_stop_loss", return_value=101.0
        ):
            result = confirm_5m_entry(self.candles, self._qualified_setup())
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "invalid_5m_trade_geometry")

    def test_liquidity_sweep_detects_wick_and_close_reclaim(self) -> None:
        candles = _normalize_candles(self.candles)
        target_index = self.long_event.index - 1
        source = candles[target_index]
        modified = list(candles)
        modified[target_index] = type(source)(
            timestamp=source.timestamp,
            open=91.0,
            high=92.0,
            low=89.0,
            close=91.0,
            volume=source.volume,
        )
        sweep = _find_liquidity_sweep(modified, self.long_event)
        self.assertIsNotNone(sweep)
        self.assertEqual(sweep["side"], "sell_side")

    def test_displacement_requires_large_directional_body(self) -> None:
        candles = _normalize_candles(self._candles(20, body=0.2))
        source = candles[15]
        candles[15] = type(source)(
            timestamp=source.timestamp,
            open=100.0,
            high=102.5,
            low=99.8,
            close=102.0,
            volume=2000.0,
        )
        self.assertTrue(_displacement_confirmed(candles, 15, "long"))
        self.assertFalse(_displacement_confirmed(candles, 15, "short"))

    def test_latest_structure_event_classifies_choch_from_prior_bearish_structure(self) -> None:
        normalized = _normalize_candles(self.candles)
        swings = {
            "highs": [
                {"index": 4, "price": 112.0},
                {"index": 10, "price": 110.0},
            ],
            "lows": [
                {"index": 6, "price": 94.0},
                {"index": 12, "price": 92.0},
            ],
        }
        breakout = normalized[20]
        normalized[20] = type(breakout)(
            timestamp=breakout.timestamp,
            open=109.0,
            high=112.0,
            low=108.5,
            close=111.0,
            volume=breakout.volume,
        )
        with patch("app.scanner_logic._confirmed_swings", return_value=swings):
            event = _latest_structure_event(normalized)
        self.assertIsNotNone(event)
        self.assertEqual(event.direction, "long")
        self.assertEqual(event.event_type, "CHOCH")

    def test_multitimeframe_result_combines_setup_and_confirmation(self) -> None:
        setup = self._qualified_setup()
        confirmation = {"status": "active", "direction": "long", "reason": "5m_entry_confirmed", "score": 100}
        with patch("app.scanner_logic.analyze_15m_setup", return_value=setup), patch(
            "app.scanner_logic.confirm_5m_entry", return_value=confirmation
        ):
            result = evaluate_multitimeframe_logic("BTCUSDT", self.candles, self.candles, trend_state="UPTREND")
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["direction"], "long")
        self.assertIn("setup_15m", result)
        self.assertIn("confirmation_5m", result)

    def test_scanner_gate_downgrades_pure_smc_without_5m_confirmation(self) -> None:
        result = _normalize_strategy_result(
            symbol="BTCUSDT",
            result=self._strategy_result("pure_smc"),
            trend={"state": "UPTREND", "strength": 90, "reason": "test"},
            market_ranking={"score": 80, "components": {}},
            scanner_logic={
                "status": "near_setup",
                "direction": "long",
                "reason": "waiting_for_5m_choch",
                "confidence_score": 70,
                "setup_15m": {},
                "confirmation_5m": {},
            },
        )
        self.assertEqual(result["status"], "near_setup")
        self.assertEqual(result["original_status"], "active")
        self.assertEqual(result["rejection_reason"], "waiting_for_5m_choch")

    def test_scanner_gate_does_not_change_non_structure_strategy(self) -> None:
        result = _normalize_strategy_result(
            symbol="BTCUSDT",
            result=self._strategy_result("ema_pullback"),
            trend={"state": "UPTREND", "strength": 90, "reason": "test"},
            market_ranking={"score": 80, "components": {}},
            scanner_logic={
                "status": "blocked",
                "direction": None,
                "reason": "15m_structure_event_not_found",
                "confidence_score": 0,
                "setup_15m": {},
                "confirmation_5m": {},
            },
        )
        self.assertEqual(result["status"], "active")

    def _qualified_setup_patches(self):
        return _PatchBundle(
            patch("app.scanner_logic._latest_structure_event", return_value=self.long_event),
            patch("app.scanner_logic._find_liquidity_sweep", return_value={"side": "sell_side"}),
            patch("app.scanner_logic._find_order_block", return_value=PriceZone(94.0, 96.0)),
            patch("app.scanner_logic._find_fvg", return_value=PriceZone(95.0, 97.0)),
        )

    def _active_confirmation_patches(self, *, fvg_retest: bool, ob_reaction: bool):
        return _PatchBundle(
            patch("app.scanner_logic._latest_structure_event", return_value=self.long_event),
            patch("app.scanner_logic._displacement_confirmed", return_value=True),
            patch("app.scanner_logic._find_fvg", return_value=PriceZone(99.0, 100.0)),
            patch("app.scanner_logic._find_order_block", return_value=PriceZone(98.0, 99.5)),
            patch("app.scanner_logic._zone_retested", return_value=fvg_retest),
            patch("app.scanner_logic._order_block_reaction", return_value=ob_reaction),
        )

    def _qualified_setup(self) -> dict:
        return {
            "qualified": True,
            "status": "near_setup",
            "direction": "long",
            "reason": "15m_setup_qualified_waiting_for_5m",
            "score": 100,
            "invalidation": 95.0,
        }

    @staticmethod
    def _strategy_result(strategy_name: str) -> dict:
        return {
            "strategy_name": strategy_name,
            "strategy": strategy_name,
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 99.0,
            "take_profit": 101.5,
            "risk_reward": 1.5,
            "detected_at": "2026-01-01T00:00:00+00:00",
            "status": "active",
            "confidence_score": 80,
            "rejection_reason": None,
        }

    def _candles(self, count: int, *, body: float = 0.2) -> list[dict[str, float | str]]:
        candles: list[dict[str, float | str]] = []
        for index in range(count):
            open_price = 100.0 + ((index % 3) * 0.05)
            close = open_price + body
            candles.append(
                {
                    "timestamp": (self.base_time + timedelta(minutes=5 * index)).isoformat(),
                    "open": open_price,
                    "high": close + 0.2,
                    "low": open_price - 0.2,
                    "close": close,
                    "volume": 1000.0,
                }
            )
        return candles


class _PatchBundle:
    def __init__(self, *patchers):
        self.patchers = patchers

    def __enter__(self):
        for patcher in self.patchers:
            patcher.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        for patcher in reversed(self.patchers):
            patcher.stop()
        return False


if __name__ == "__main__":
    unittest.main()
