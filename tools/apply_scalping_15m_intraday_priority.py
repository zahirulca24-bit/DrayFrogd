from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one match in {path}, found {count}: {old[:120]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_exact_count(path: str, old: str, new: str, expected_count: int) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected_count:
        raise RuntimeError(
            f"Expected exactly {expected_count} matches in {path}, found {count}: {old[:120]!r}"
        )
    file_path.write_text(text.replace(old, new), encoding="utf-8")


replace_once(
    "app/scanner.py",
    "        scalping_trend = _profile_trend(closed_5m, interval_minutes=5, now=reference)",
    "        scalping_trend = _profile_trend(closed_15m, interval_minutes=15, now=reference)",
)

replace_once(
    "app/scanner.py",
    '                        "reason": "scalping_5m_trend_eligible",',
    '                        "reason": "scalping_15m_trend_eligible",',
)

replace_once(
    "app/scanner.py",
    '''def _scalping_timeframes() -> dict[str, Any]:
    return {
        "trend": "5m",
        "setup": "5m",
        "trigger": "1m",
        "open_candle_confirmation": False,
    }''',
    '''def _scalping_timeframes() -> dict[str, Any]:
    return {
        "trend": "15m",
        "setup": "5m",
        "trigger": "1m",
        "open_candle_confirmation": False,
    }''',
)

replace_once(
    "app/signal_pipeline.py",
    '    "trend_not_aligned",\n}',
    '    "trend_not_aligned",\n    "profile_direction_conflict",\n}',
)

replace_once(
    "app/signal_pipeline.py",
    "    primary_signals = _select_primary_signals(results)",
    "    _invalidate_cross_profile_direction_conflicts(results)\n    primary_signals = _select_primary_signals(results)",
)

replace_once(
    "app/signal_pipeline.py",
    "\n\ndef _select_primary_signals(results: list[dict[str, Any]]) -> list[dict[str, Any]]:",
    '''

def _invalidate_cross_profile_direction_conflicts(results: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        if result.get("signal_state") != SIGNAL_ACTIVE:
            continue
        trade_type = _normalize_trade_type(result.get("trade_type"))
        direction = _normalize_direction(result.get("direction"))
        if trade_type is None or direction is None:
            continue
        grouped.setdefault(str(result.get("symbol") or ""), []).append(result)

    for symbol_results in grouped.values():
        trade_types = {str(item.get("trade_type") or "") for item in symbol_results}
        directions = {str(item.get("direction") or "") for item in symbol_results}
        if not {"scalping", "intraday"}.issubset(trade_types) or len(directions) <= 1:
            continue
        for item in symbol_results:
            _set_signal_state(item, SIGNAL_INVALID, "profile_direction_conflict")
            item["is_executable"] = False
            item["monitor_only"] = False
            item["signal_score"] = _signal_score(item)


def _select_primary_signals(results: list[dict[str, Any]]) -> list[dict[str, Any]]:''',
)

replace_once(
    "app/signal_pipeline.py",
    '''def _primary_sort_key(item: dict[str, Any]) -> tuple[int, float, int, float, str, str, str]:
    state_priority = {SIGNAL_ACTIVE: 0, SIGNAL_NEAR_SETUP: 1}
    return (
        state_priority.get(str(item.get("signal_state") or ""), 9),
        -float(item.get("signal_score") or 0.0),
        int(item.get("market_rank") or 9999),
        -_timestamp_value(item.get("detected_at")),
        str(item.get("trade_type") or ""),
        str(item.get("strategy_name") or ""),
        str(item.get("signal_key") or ""),
    )''',
    '''def _primary_sort_key(item: dict[str, Any]) -> tuple[int, int, float, int, float, str, str]:
    state_priority = {SIGNAL_ACTIVE: 0, SIGNAL_NEAR_SETUP: 1}
    trade_type_priority = {"intraday": 0, "scalping": 1}
    return (
        state_priority.get(str(item.get("signal_state") or ""), 9),
        trade_type_priority.get(str(item.get("trade_type") or ""), 9),
        -float(item.get("signal_score") or 0.0),
        int(item.get("market_rank") or 9999),
        -_timestamp_value(item.get("detected_at")),
        str(item.get("strategy_name") or ""),
        str(item.get("signal_key") or ""),
    )''',
)

replace_once(
    "tests/test_scanner_integration.py",
    '        self.assertEqual([call[1] for call in client.calls], ["60", "15", "5", "1"])\n        self.assertEqual(result["timeframes"]["scalping"]["setup"], "5m")',
    '        self.assertEqual([call[1] for call in client.calls], ["60", "15", "5", "1"])\n        self.assertEqual(result["timeframes"]["scalping"]["trend"], "15m")\n        self.assertEqual(result["timeframes"]["scalping"]["setup"], "5m")',
)

replace_once(
    "tests/test_signal_pipeline.py",
    '''        self.assertEqual(primary["strategy_name"], "breakout")
        self.assertEqual(primary["trade_type"], "scalping")
        self.assertTrue(primary["primary_signal"])
        self.assertEqual(primary["confirmation_count"], 1)
        self.assertEqual(primary["confirmations"][0]["strategy_name"], "ema_pullback")''',
    '''        self.assertEqual(primary["strategy_name"], "ema_pullback")
        self.assertEqual(primary["trade_type"], "intraday")
        self.assertTrue(primary["primary_signal"])
        self.assertEqual(primary["confirmation_count"], 1)
        self.assertEqual(primary["confirmations"][0]["strategy_name"], "breakout")''',
)

replace_exact_count(
    "tests/test_signal_pipeline.py",
    '{"trend": "5m", "setup": "5m", "trigger": "1m"}',
    '{"trend": "15m", "setup": "5m", "trigger": "1m"}',
    2,
)

Path("tests/test_profile_selection_priority.py").write_text(
    '''from __future__ import annotations

import unittest
from unittest.mock import patch

from app.signal_pipeline import SIGNAL_ACTIVE, SIGNAL_INVALID, SIGNAL_NEAR_SETUP, evaluate_signal_contexts


class ProfileSelectionPriorityTests(unittest.TestCase):
    def test_active_intraday_beats_higher_score_active_scalping_on_same_symbol(self) -> None:
        contexts = [self._context("BTCUSDT", "scalping"), self._context("BTCUSDT", "intraday")]
        outputs = [
            [self._signal("long", "active", confidence=70)],
            [self._signal("long", "active", confidence=99)],
        ]
        with patch("app.signal_pipeline.evaluate_registered_strategies", side_effect=outputs):
            result = evaluate_signal_contexts(contexts)

        self.assertEqual(result["signals_found"], 1)
        self.assertEqual(result["signals"][0]["trade_type"], "intraday")
        self.assertEqual(result["signals"][0]["signal_state"], SIGNAL_ACTIVE)
        self.assertEqual(result["signals"][0]["confirmation_count"], 1)

    def test_active_scalping_beats_near_setup_intraday(self) -> None:
        contexts = [self._context("ETHUSDT", "scalping"), self._context("ETHUSDT", "intraday")]
        outputs = [
            [self._signal("long", "near_setup", confidence=99)],
            [self._signal("long", "active", confidence=70)],
        ]
        with patch("app.signal_pipeline.evaluate_registered_strategies", side_effect=outputs):
            result = evaluate_signal_contexts(contexts)

        self.assertEqual(result["signals_found"], 1)
        self.assertEqual(result["signals"][0]["trade_type"], "scalping")
        self.assertEqual(result["signals"][0]["signal_state"], SIGNAL_ACTIVE)
        intraday = next(item for item in result["results"] if item["trade_type"] == "intraday")
        self.assertEqual(intraday["signal_state"], SIGNAL_NEAR_SETUP)

    def test_opposite_active_profile_directions_block_execution(self) -> None:
        scalping = self._context("SOLUSDT", "scalping")
        scalping["trend"] = {"state": "DOWNTREND", "strength": 90.0, "reason": "test"}
        scalping["scanner_logic"]["direction"] = "short"
        intraday = self._context("SOLUSDT", "intraday")
        contexts = [scalping, intraday]
        outputs = [
            [self._signal("long", "active", confidence=90)],
            [self._signal("short", "active", confidence=90)],
        ]
        with patch("app.signal_pipeline.evaluate_registered_strategies", side_effect=outputs):
            result = evaluate_signal_contexts(contexts)

        self.assertEqual(result["signals_found"], 0)
        self.assertEqual(result["primary_signals"], [])
        conflicted = [item for item in result["results"] if item["rejection_reason"] == "profile_direction_conflict"]
        self.assertEqual(len(conflicted), 2)
        self.assertTrue(all(item["signal_state"] == SIGNAL_INVALID for item in conflicted))
        self.assertTrue(all(not item["is_executable"] for item in conflicted))

    @staticmethod
    def _context(symbol: str, trade_type: str) -> dict:
        return {
            "symbol": symbol,
            "market_rank": 1,
            "trade_type": trade_type,
            "trend": {"state": "UPTREND", "strength": 90.0, "reason": "test"},
            "market_ranking": {"score": 90.0, "components": {}},
            "scanner_logic": {
                "status": "active" if trade_type == "intraday" else "eligible",
                "direction": "long",
                "reason": "test",
            },
            "setup_candles": [],
            "trigger_candles": [],
            "timeframes": (
                {"trend": "15m", "setup": "5m", "trigger": "1m"}
                if trade_type == "scalping"
                else {"trend": "1h", "setup": "15m", "trigger": "5m"}
            ),
        }

    @staticmethod
    def _signal(direction: str, status: str, *, confidence: int) -> dict:
        return {
            "strategy_name": "ema_pullback",
            "strategy": "ema_pullback",
            "direction": direction,
            "entry": 100.0,
            "stop_loss": 99.0 if direction == "long" else 101.0,
            "take_profit": 102.0 if direction == "long" else 98.0,
            "risk_reward": 2.0,
            "detected_at": "2026-07-15T00:00:00+00:00",
            "status": status,
            "confidence_score": confidence,
            "rejection_reason": "waiting_for_trigger" if status == "near_setup" else None,
        }


if __name__ == "__main__":
    unittest.main()
''',
    encoding="utf-8",
)
