from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from app.scalping_entry_authority import (
    APPROVE,
    MISSED,
    REJECT,
    REASON_PRICE_ESCAPED,
    REASON_RR_DEGRADED,
    REASON_SPIKE,
    REASON_SPREAD,
    REASON_STALE_QUOTE,
    EntryAuthorityConfig,
    detect_abnormal_spike,
    evaluate_entry_authority,
)


class ScalpingEntryAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
        self.config = EntryAuthorityConfig(max_signal_age_seconds=180, max_quote_age_ms=500)

    def test_zec_type_chase_long_is_missed_before_order(self) -> None:
        result = evaluate_entry_authority(
            self._signal(allowed_entry_max=50.08),
            quote=self._quote(bid=50.34, ask=50.35),
            now=self.now,
            config=self.config,
        )
        self.assertEqual(result["decision"], MISSED)
        self.assertEqual(result["reason_code"], REASON_PRICE_ESCAPED)
        self.assertFalse(result["ok"])
        self.assertEqual(result["worker"], "ScalpingEntryAuthorityWorkerV1")
        self.assertEqual(result["mode"], "dry_run_no_order_submission")
        self.assertEqual(result["evidence"]["allowed_entry_max"], 50.08)
        self.assertGreater(result["evidence"]["executable_price"], 50.08)

    def test_valid_fast_entry_is_approved_as_ioc_limit_decision(self) -> None:
        result = evaluate_entry_authority(
            self._signal(allowed_entry_max=50.08),
            quote=self._quote(bid=50.02, ask=50.03),
            now=self.now,
            config=self.config,
        )
        self.assertEqual(result["decision"], APPROVE)
        self.assertTrue(result["ok"])
        self.assertEqual(result["evidence"]["selected_order_type"], "MARKETABLE_LIMIT_IOC")
        self.assertEqual(result["evidence"]["limit_price"], 50.08)
        self.assertGreaterEqual(result["evidence"]["net_rr"], self.config.min_net_rr)

    def test_stale_quote_is_rejected(self) -> None:
        old_quote_time = (self.now - timedelta(seconds=2)).isoformat()
        result = evaluate_entry_authority(
            self._signal(allowed_entry_max=50.08),
            quote=self._quote(bid=50.02, ask=50.03, fetched_at=old_quote_time),
            now=self.now,
            config=self.config,
        )
        self.assertEqual(result["decision"], REJECT)
        self.assertEqual(result["reason_code"], REASON_STALE_QUOTE)
        self.assertGreater(result["evidence"]["quote_age_ms"], self.config.max_quote_age_ms)

    def test_spread_explosion_is_rejected(self) -> None:
        result = evaluate_entry_authority(
            self._signal(allowed_entry_max=50.08),
            quote=self._quote(bid=50.00, ask=50.08),
            now=self.now,
            config=self.config,
        )
        self.assertEqual(result["decision"], REJECT)
        self.assertEqual(result["reason_code"], REASON_SPREAD)
        self.assertGreater(result["evidence"]["spread_bps"], self.config.max_spread_bps)

    def test_abnormal_spike_is_rejected_even_inside_band(self) -> None:
        candles = [{"high": 50.05, "low": 49.95} for _ in range(30)]
        candles.append({"high": 50.40, "low": 49.90})
        spike = detect_abnormal_spike(candles)
        self.assertTrue(spike["abnormal"])

        result = evaluate_entry_authority(
            self._signal(allowed_entry_max=50.08),
            quote=self._quote(bid=50.02, ask=50.03),
            now=self.now,
            recent_candles=candles,
            config=self.config,
        )
        self.assertEqual(result["decision"], REJECT)
        self.assertEqual(result["reason_code"], REASON_SPIKE)

    def test_fee_adjusted_rr_degradation_is_rejected(self) -> None:
        signal = self._signal(
            entry=50.00,
            stop_loss=49.90,
            take_profit=50.14,
            risk_reward=1.4,
            allowed_entry_max=50.03,
        )
        result = evaluate_entry_authority(
            signal,
            quote=self._quote(bid=50.01, ask=50.02),
            now=self.now,
            config=self.config,
        )
        self.assertEqual(result["decision"], REJECT)
        self.assertEqual(result["reason_code"], REASON_RR_DEGRADED)
        self.assertLess(result["evidence"]["net_rr"], self.config.min_net_rr)

    def _signal(
        self,
        *,
        entry: float = 50.00,
        stop_loss: float = 49.70,
        take_profit: float = 50.60,
        risk_reward: float = 2.0,
        allowed_entry_max: float | None = None,
    ) -> dict:
        payload = {
            "symbol": "ZECUSDT",
            "strategy_name": "compression_expansion_v1",
            "trade_type": "scalping",
            "direction": "long",
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_reward": risk_reward,
            "detected_at": self.now.isoformat(),
            "status": "active",
            "allowed_entry_min": entry,
        }
        if allowed_entry_max is not None:
            payload["allowed_entry_max"] = allowed_entry_max
        return payload

    def _quote(self, *, bid: float, ask: float, fetched_at: str | None = None) -> dict:
        return {
            "ok": True,
            "symbol": "ZECUSDT",
            "fetched_at": fetched_at or self.now.isoformat(),
            "ticker": {
                "bid1Price": str(bid),
                "ask1Price": str(ask),
                "markPrice": str((bid + ask) / 2.0),
                "lastPrice": str((bid + ask) / 2.0),
            },
        }


if __name__ == "__main__":
    unittest.main()
