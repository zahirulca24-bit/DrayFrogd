from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from app.scalping_cooldown import SCALPING_REENTRY_COOLDOWN_MINUTES, sync_scalping_reentry_cooldowns
from app.scanner import _apply_scalping_suppression
from app.trade_management_profiles import build_profile_management_state
from app.trade_management_rules import evaluate_management_action


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self.rows)


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.closed = False

    def query(self, *_args, **_kwargs):
        return _FakeQuery(self.rows)

    def close(self):
        self.closed = True


class ScalpingTimeoutSuppressionTests(unittest.TestCase):
    def _management(self, trade_type: str) -> dict:
        return build_profile_management_state(
            entry=100.0,
            stop_loss=99.0,
            take_profit=101.5 if trade_type == "scalping" else 102.0,
            quantity=1.0,
            direction="long",
            trade_type=trade_type,
        )

    def test_scalping_holds_before_30_minutes_and_closes_at_30_minutes(self) -> None:
        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
        management = self._management("scalping")
        before = evaluate_management_action(
            {
                "direction": "long",
                "entry": 100.0,
                "stop_loss": 99.0,
                "opened_at": (now - timedelta(minutes=29, seconds=59)).isoformat(),
                "management": management,
            },
            100.0,
            now,
        )
        at_limit = evaluate_management_action(
            {
                "direction": "long",
                "entry": 100.0,
                "stop_loss": 99.0,
                "opened_at": (now - timedelta(minutes=30)).isoformat(),
                "management": management,
            },
            100.0,
            now,
        )
        self.assertEqual(before["action"], "hold")
        self.assertEqual(at_limit["action"], "max_hold_close")
        self.assertEqual(management["max_hold_seconds"], 30 * 60)

    def test_intraday_does_not_inherit_scalping_30_minute_timeout(self) -> None:
        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
        management = self._management("intraday")
        decision = evaluate_management_action(
            {
                "direction": "long",
                "entry": 100.0,
                "stop_loss": 99.0,
                "opened_at": (now - timedelta(minutes=30)).isoformat(),
                "management": management,
            },
            100.0,
            now,
        )
        self.assertEqual(decision["action"], "hold")
        self.assertEqual(management["max_hold_seconds"], 6 * 60 * 60)

    def test_detected_at_is_used_when_opened_at_is_missing(self) -> None:
        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
        decision = evaluate_management_action(
            {
                "direction": "long",
                "entry": 100.0,
                "stop_loss": 99.0,
                "detected_at": (now - timedelta(minutes=30)).isoformat(),
                "management": self._management("scalping"),
            },
            100.0,
            now,
        )
        self.assertEqual(decision["action"], "max_hold_close")

    def test_any_closed_scalping_result_creates_60_minute_cooldown(self) -> None:
        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
        closed_at = now - timedelta(minutes=10)
        rows = [
            SimpleNamespace(
                status="closed",
                symbol="BTCUSDT",
                closed_at=closed_at.isoformat(),
                realized_pnl=12.5,
                exchange_metadata=json.dumps({"management": {"trade_type": "scalping", "profile_name": "scalping_v2"}}),
            )
        ]
        session = _FakeSession(rows)
        with patch("app.scalping_cooldown.SessionLocal", return_value=session), patch(
            "app.scalping_cooldown.start_loss_cooldown"
        ) as start_cooldown:
            result = sync_scalping_reentry_cooldowns(now=now)

        self.assertTrue(result["ok"])
        self.assertEqual(result["active_symbols"], ["BTCUSDT"])
        self.assertEqual(SCALPING_REENTRY_COOLDOWN_MINUTES, 60)
        start_cooldown.assert_called_once_with(
            symbol="BTCUSDT",
            now=closed_at,
            duration_minutes=60,
        )
        self.assertTrue(session.closed)

    def test_intraday_close_does_not_create_scalping_suppression(self) -> None:
        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
        rows = [
            SimpleNamespace(
                status="closed",
                symbol="ETHUSDT",
                closed_at=(now - timedelta(minutes=5)).isoformat(),
                exchange_metadata=json.dumps({"management": {"trade_type": "intraday", "profile_name": "intraday_v1"}}),
            )
        ]
        with patch("app.scalping_cooldown.SessionLocal", return_value=_FakeSession(rows)), patch(
            "app.scalping_cooldown.start_loss_cooldown"
        ) as start_cooldown:
            result = sync_scalping_reentry_cooldowns(now=now)

        self.assertTrue(result["ok"])
        self.assertEqual(result["active_symbols"], [])
        start_cooldown.assert_not_called()

    def test_scanner_hides_suppressed_scalping_but_keeps_intraday_and_other_symbols(self) -> None:
        signals = [
            {"symbol": "BTCUSDT", "trade_type": "scalping", "status": "active"},
            {"symbol": "BTCUSDT", "trade_type": "intraday", "status": "active"},
            {"symbol": "ETHUSDT", "trade_type": "scalping", "status": "active"},
        ]
        results = list(signals)
        visible_signals, visible_results, suppressed = _apply_scalping_suppression(
            signals, results, suppressed_symbols={"BTCUSDT"}
        )
        self.assertEqual(
            [(item["symbol"], item["trade_type"]) for item in visible_signals],
            [("BTCUSDT", "intraday"), ("ETHUSDT", "scalping")],
        )
        self.assertEqual(len(visible_results), 2)
        self.assertEqual([(item["symbol"], item["trade_type"]) for item in suppressed], [("BTCUSDT", "scalping")])

    def test_scanner_suppression_failure_fails_closed_for_scalping_only(self) -> None:
        signals = [
            {"symbol": "BTCUSDT", "trade_type": "scalping", "status": "active"},
            {"symbol": "ETHUSDT", "trade_type": "intraday", "status": "active"},
        ]
        visible_signals, visible_results, suppressed = _apply_scalping_suppression(
            signals, list(signals), suppressed_symbols=set(), fail_closed=True
        )
        self.assertEqual([(item["symbol"], item["trade_type"]) for item in visible_signals], [("ETHUSDT", "intraday")])
        self.assertEqual(len(visible_results), 1)
        self.assertEqual([(item["symbol"], item["trade_type"]) for item in suppressed], [("BTCUSDT", "scalping")])


if __name__ == "__main__":
    unittest.main()
