from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta

from app.batch1_execution_safety import EXPECTED_BLOCK_CODES
from app.batch3_backtest_truth import (
    _simulate_trade_next_open,
    _validate_and_annotate_dataset,
)
from app.bot_controls import DEFAULT_RISK_SETTINGS
from app.database import Base, SessionLocal, engine
from app.engines.profiles import INTRADAY_PROFILE, SCALPING_PROFILE, apply_strategy_profile
from app.journal import log_bot_event
from app.models import BotEvent


class Batch3StrategyIntegrityTests(unittest.TestCase):
    def test_intraday_profile_raises_valid_long_and_short_targets_to_two_r(self) -> None:
        long_result = apply_strategy_profile(
            {
                "status": "active",
                "direction": "long",
                "entry": 100.0,
                "stop_loss": 99.0,
                "take_profit": 101.5,
                "risk_reward": 1.5,
            },
            INTRADAY_PROFILE,
        )
        short_result = apply_strategy_profile(
            {
                "status": "active",
                "direction": "short",
                "entry": 100.0,
                "stop_loss": 101.0,
                "take_profit": 98.5,
                "risk_reward": 1.5,
            },
            INTRADAY_PROFILE,
        )

        self.assertEqual(long_result["take_profit"], 102.0)
        self.assertEqual(short_result["take_profit"], 98.0)
        self.assertEqual(long_result["risk_reward"], 2.0)
        self.assertEqual(short_result["risk_reward"], 2.0)
        self.assertEqual(long_result["raw_take_profit"], 101.5)
        self.assertEqual(short_result["raw_take_profit"], 98.5)

    def test_scalping_profile_remains_one_point_five_r(self) -> None:
        result = apply_strategy_profile(
            {
                "status": "active",
                "direction": "long",
                "entry": 100.0,
                "stop_loss": 99.0,
                "take_profit": 101.5,
                "risk_reward": 1.5,
            },
            SCALPING_PROFILE,
        )
        self.assertEqual(result["take_profit"], 101.5)
        self.assertEqual(result["risk_reward"], 1.5)
        self.assertFalse(result["profile_adjusted_target"])

    def test_invalid_geometry_is_not_repaired_by_profile(self) -> None:
        result = apply_strategy_profile(
            {
                "status": "active",
                "direction": "long",
                "entry": 100.0,
                "stop_loss": 101.0,
                "take_profit": 101.5,
                "risk_reward": 1.5,
            },
            INTRADAY_PROFILE,
        )
        self.assertEqual(result["stop_loss"], 101.0)
        self.assertEqual(result["take_profit"], 101.5)
        self.assertFalse(result["profile_adjusted_target"])

    def test_backtest_dataset_annotates_close_time_and_rejects_missing_candle(self) -> None:
        start = datetime(2026, 7, 18, 10, 0, tzinfo=UTC)
        candles = [self._candle(start + timedelta(minutes=index)) for index in range(3)]
        normalized = _validate_and_annotate_dataset(candles, 1)
        self.assertEqual(
            normalized[0]["_backtest_close_timestamp"],
            (start + timedelta(minutes=1)).isoformat(),
        )

        missing = [candles[0], candles[2]]
        with self.assertRaisesRegex(ValueError, "missing_or_irregular_candle"):
            _validate_and_annotate_dataset(missing, 1)

    def test_backtest_dataset_rejects_duplicate_and_out_of_order_candles(self) -> None:
        start = datetime(2026, 7, 18, 10, 0, tzinfo=UTC)
        first = self._candle(start)
        second = self._candle(start + timedelta(minutes=1))
        with self.assertRaisesRegex(ValueError, "duplicate_timestamp"):
            _validate_and_annotate_dataset([first, first], 1)
        with self.assertRaisesRegex(ValueError, "out_of_order_timestamp"):
            _validate_and_annotate_dataset([second, first], 1)

    def test_simulator_enters_at_next_candle_open_and_uses_entry_exit_fee_notionals(self) -> None:
        start = datetime(2026, 7, 18, 10, 0, tzinfo=UTC)
        candles = _validate_and_annotate_dataset(
            [
                self._candle(start, open_price=100.0, high=100.2, low=99.8, close=100.0),
                self._candle(start + timedelta(minutes=1), open_price=100.2, high=102.1, low=100.1, close=101.9),
            ],
            1,
        )
        signal = {
            "strategy_name": "ema_pullback",
            "trade_type": "intraday",
            "engine_profile": "intraday",
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 99.0,
            "take_profit": 102.0,
            "risk_reward": 2.0,
            "detected_at": candles[0]["_backtest_close_timestamp"],
            "signal_state": "ACTIVE",
        }
        result = _simulate_trade_next_open(
            signal,
            candles,
            start_index=1,
            risk_amount=50.0,
            fee_rate=0.00055,
            max_hold_candles=10,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["planned_entry"], 100.0)
        self.assertEqual(result["entry"], 100.2)
        self.assertEqual(result["exit_price"], 102.0)
        expected_quantity = 50.0 / (100.2 - 99.0)
        expected_fees = (100.2 * expected_quantity * 0.00055) + (102.0 * expected_quantity * 0.00055)
        self.assertAlmostEqual(result["quantity"], expected_quantity)
        self.assertAlmostEqual(result["fees"], expected_fees)
        self.assertEqual(result["opened_at"], candles[1]["timestamp"])

    def test_same_candle_stop_and_target_is_conservative_stop_first(self) -> None:
        start = datetime(2026, 7, 18, 10, 0, tzinfo=UTC)
        candles = _validate_and_annotate_dataset(
            [
                self._candle(start),
                self._candle(start + timedelta(minutes=1), open_price=100.0, high=102.2, low=98.8, close=101.0),
            ],
            1,
        )
        result = _simulate_trade_next_open(
            {
                "direction": "long",
                "entry": 100.0,
                "stop_loss": 99.0,
                "take_profit": 102.0,
                "risk_reward": 2.0,
            },
            candles,
            start_index=1,
            risk_amount=50.0,
            fee_rate=0.0,
            max_hold_candles=10,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["result"], "loss")
        self.assertEqual(result["exit_reason"], "stop_loss")
        self.assertEqual(result["diagnosis"], "SL_AND_TP_SAME_CANDLE_CONSERVATIVE_SL_FIRST")

    def test_daily_trade_count_remains_reporting_only_and_safety_blocks_remain(self) -> None:
        self.assertEqual(DEFAULT_RISK_SETTINGS["max_daily_trades"], 0)
        self.assertNotIn("DAILY_TRADE_LIMIT_REACHED", EXPECTED_BLOCK_CODES)
        for required in (
            "SYMBOL_ALREADY_ACTIVE",
            "ACTIVE_TRADE_LIMIT_REACHED",
            "DYNAMIC_RISK_CAPACITY_EXCEEDED",
            "SYMBOL_REENTRY_COOLDOWN",
            "DAILY_LOSS_CIRCUIT_BREAKER",
        ):
            self.assertIn(required, EXPECTED_BLOCK_CODES)

    def test_repeated_same_symbol_active_block_is_one_aggregated_event(self) -> None:
        Base.metadata.create_all(bind=engine)
        symbol = "DEDUPEXYZUSDT"
        signal = {
            "symbol": symbol,
            "strategy_name": "ema_pullback",
            "direction": "long",
            "detected_at": "2026-07-18T12:00:00+00:00",
            "entry": 1.0,
        }
        metadata = {
            "signal": signal,
            "outcome": {"ok": False, "error": "SYMBOL_ALREADY_ACTIVE", "execution_blocked": True},
        }

        log_bot_event("auto_execution_failed", f"Auto execution failed for {symbol}", level="warning", metadata=metadata)
        log_bot_event("auto_execution_failed", f"Auto execution failed for {symbol}", level="warning", metadata=metadata)

        db = SessionLocal()
        try:
            rows = db.query(BotEvent).filter(BotEvent.event_type == "trade_execution_blocked").all()
            matching = []
            for row in rows:
                payload = json.loads(row.event_metadata or "{}")
                if payload.get("signal", {}).get("symbol") == symbol:
                    matching.append((row, payload))
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0][1]["skip_count"], 2)
            self.assertEqual(matching[0][0].level, "info")
            for row, _ in matching:
                db.delete(row)
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _candle(
        timestamp: datetime,
        *,
        open_price: float = 100.0,
        high: float = 100.5,
        low: float = 99.5,
        close: float = 100.1,
    ) -> dict:
        return {
            "timestamp": timestamp.isoformat(),
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1000.0,
            "confirm": True,
        }


if __name__ == "__main__":
    unittest.main()
