from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.authoritative_risk_engine import issue_execution_approval, verify_risk_approval


NOW = datetime(2026, 7, 17, 1, 30, tzinfo=UTC)


def signal(**updates):
    payload = {
        "symbol": "HYPEUSDT",
        "strategy_name": "ema_pullback",
        "trade_type": "scalping",
        "direction": "short",
        "entry": 100.0,
        "stop_loss": 101.0,
        "take_profit": 98.0,
        "risk_reward": 2.0,
        "detected_at": (NOW - timedelta(seconds=10)).isoformat(),
        "status": "active",
        "signal_state": "ACTIVE",
        "is_executable": True,
        "primary_signal": True,
    }
    payload.update(updates)
    return payload


class FakeClient:
    def __init__(self, positions=None):
        self.positions = list(positions or [])

    def safe_fetch_positions(self):
        return True, list(self.positions), None

    def safe_fetch_wallet_balance(self):
        return True, {"totalEquity": "1000"}, None


VALIDATION = {
    "allowed": True,
    "reason": "",
    "trade_type": "scalping",
    "risk_amount": 20.0,
    "risk_per_trade": 0.02,
    "leverage_cap": 20.0,
    "exposure_cap": 0.50,
    "min_risk_reward": 1.5,
    "max_active_trades": 5,
    "max_daily_trades": 8,
    "reentry_cooldown_minutes": 30,
}
RISK_STATE = {"active_symbols": [], "active_trade_count": 0, "available_risk": 50.0}


class AuthoritativeRiskEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        mode_patch = patch("app.authoritative_risk_engine.get_execution_mode", return_value="demo")
        mode_patch.start()
        self.addCleanup(mode_patch.stop)

    def test_signed_approval_is_signal_bound_short_lived_and_one_time(self) -> None:
        payload = signal()
        with patch("app.authoritative_risk_engine.get_trade_by_execution_key", return_value=None):
            approval = issue_execution_approval(
                FakeClient(),
                {**payload, "auto_triggered": True},
                auto_triggered=True,
                now=NOW,
                wallet={"totalEquity": "1000"},
                positions=[],
                account_equity=1000.0,
                validation=VALIDATION,
                risk_state=RISK_STATE,
            )

        self.assertTrue(approval["allowed"])
        self.assertEqual(approval["decision"]["risk_amount"], 20.0)
        self.assertEqual(approval["decision"]["execution_mode"], "demo")
        verified = verify_risk_approval(
            approval["token"],
            {**payload, "auto_triggered": True},
            execution_mode="demo",
            consume=True,
            now=NOW,
        )
        self.assertTrue(verified["allowed"])
        replay = verify_risk_approval(
            approval["token"],
            {**payload, "auto_triggered": True},
            execution_mode="demo",
            consume=True,
            now=NOW,
        )
        self.assertFalse(replay["allowed"])
        self.assertEqual(replay["error"], "RISK_APPROVAL_ALREADY_USED")

    def test_stale_signal_is_rejected_before_portfolio_checks(self) -> None:
        stale = signal(detected_at=(NOW - timedelta(seconds=421)).isoformat())
        approval = issue_execution_approval(
            FakeClient(),
            {**stale, "auto_triggered": True},
            auto_triggered=True,
            now=NOW,
        )
        self.assertFalse(approval["allowed"])
        self.assertEqual(approval["error"], "SIGNAL_STALE")

    def test_exchange_position_blocks_same_symbol(self) -> None:
        with patch("app.authoritative_risk_engine.get_trade_by_execution_key", return_value=None):
            approval = issue_execution_approval(
                FakeClient([{"symbol": "HYPEUSDT", "size": "1"}]),
                signal(),
                now=NOW,
            )
        self.assertFalse(approval["allowed"])
        self.assertEqual(approval["error"], "SYMBOL_ALREADY_ACTIVE")

    def test_fee_gate_rejects_target_with_no_net_reward(self) -> None:
        payload = signal(take_profit=99.95, risk_reward=0.05)
        with patch("app.authoritative_risk_engine.get_trade_by_execution_key", return_value=None):
            approval = issue_execution_approval(
                FakeClient(),
                payload,
                now=NOW,
                wallet={"totalEquity": "1000"},
                positions=[],
                account_equity=1000.0,
                validation=VALIDATION,
                risk_state=RISK_STATE,
            )
        self.assertFalse(approval["allowed"])
        self.assertEqual(approval["error"], "FEE_VIABILITY_REJECTED")

    def test_approval_cannot_authorize_a_different_signal(self) -> None:
        payload = signal()
        with patch("app.authoritative_risk_engine.get_trade_by_execution_key", return_value=None):
            approval = issue_execution_approval(
                FakeClient(),
                payload,
                now=NOW,
                wallet={"totalEquity": "1000"},
                positions=[],
                account_equity=1000.0,
                validation=VALIDATION,
                risk_state=RISK_STATE,
            )
        mismatch = verify_risk_approval(
            approval["token"],
            signal(symbol="ONDOUSDT"),
            execution_mode="demo",
            now=NOW,
        )
        self.assertFalse(mismatch["allowed"])
        self.assertEqual(mismatch["error"], "RISK_APPROVAL_SIGNAL_MISMATCH")


if __name__ == "__main__":
    unittest.main()
