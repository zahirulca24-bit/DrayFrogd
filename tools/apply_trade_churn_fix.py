from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one source block in {path}, found {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/models.py",
    '    max_daily_trades: Mapped[int] = mapped_column(Integer, default=0, nullable=False)\n',
    '    max_daily_trades: Mapped[int] = mapped_column(Integer, default=8, nullable=False)\n',
)

replace_once(
    "app/bot_controls.py",
    '    # Zero means unlimited. Signal quality, dynamic risk and active-trade gates\n'
    '    # are the authorities instead of a daily trade-count cap.\n'
    '    "max_daily_trades": 0,\n',
    '    # Locked turnover guard. Eight exchange attempts per BDT day prevents\n'
    '    # fee churn while preserving enough capacity for both trade profiles.\n'
    '    "max_daily_trades": 8,\n',
)
replace_once(
    "app/bot_controls.py",
    '    if max_daily_trades is not None and int(max_daily_trades) != 0:\n'
    '        raise ValueError("Daily executable trade count is unlimited; use 0")\n',
    '    if max_daily_trades is not None and int(max_daily_trades) not in {0, 8}:\n'
    '        raise ValueError("Daily executable trade count is locked at 8")\n',
)
replace_once(
    "app/bot_controls.py",
    '        "daily_trade_limit_enabled": False,\n',
    '        "daily_trade_limit_enabled": True,\n',
)
replace_once(
    "app/bot_controls.py",
    '        "max_daily_trades": "INTEGER NOT NULL DEFAULT 0",\n',
    '        "max_daily_trades": "INTEGER NOT NULL DEFAULT 8",\n',
)

replace_once(
    "app/risk.py",
    'from app.models import RiskRuntimeState, TradeJournal\n',
    'from app.models import RiskRuntimeState, TradeJournal\n'
    'from app.trade_state import CAPACITY_BLOCKING_STATUSES\n',
)
replace_once(
    "app/risk.py",
    'ACTIVE_TRADE_LIMIT = 5\n',
    'ACTIVE_TRADE_LIMIT = 5\n'
    'DAILY_EXECUTED_TRADE_LIMIT = 8\n',
)
replace_once(
    "app/risk.py",
    '    if state["active_trade_count"] >= ACTIVE_TRADE_LIMIT:\n'
    '        return _reject("Active trade limit reached")\n\n'
    '    new_trade_risk = profile["risk_amount"]\n',
    '    if state["active_trade_count"] >= ACTIVE_TRADE_LIMIT:\n'
    '        return _reject("Active trade limit reached")\n'
    '    daily_limit = int(state.get("max_trades_per_day") or DAILY_EXECUTED_TRADE_LIMIT)\n'
    '    if int(state.get("trades_today") or 0) >= daily_limit:\n'
    '        return _reject("DAILY_TRADE_LIMIT_REACHED")\n\n'
    '    new_trade_risk = profile["risk_amount"]\n',
)
replace_once(
    "app/risk.py",
    '        "active_trade_count": state["active_trade_count"],\n'
    '        "max_active_trades": ACTIVE_TRADE_LIMIT,\n',
    '        "active_trade_count": state["active_trade_count"],\n'
    '        "max_active_trades": ACTIVE_TRADE_LIMIT,\n'
    '        "trades_today": int(state.get("trades_today") or 0),\n'
    '        "max_daily_trades": daily_limit,\n'
    '        "reentry_cooldown_minutes": LOSS_COOLDOWN_MINUTES,\n',
)
replace_once(
    "app/risk.py",
    '            trades_today = sum(\n'
    '                1\n'
    '                for item in journal_rows\n'
    '                if _timestamp_is_on_bdt_day(item.opened_at or item.detected_at, current_day)\n'
    '            )\n',
    '            trades_today = sum(\n'
    '                1\n'
    '                for item in journal_rows\n'
    '                if _journal_row_consumes_daily_slot(item, current_day)\n'
    '            )\n',
)
replace_once(
    "app/risk.py",
    '                "max_trades_per_day": 0,\n'
    '                "daily_trade_limit_enabled": False,\n',
    '                "max_trades_per_day": DAILY_EXECUTED_TRADE_LIMIT,\n'
    '                "daily_trade_limit_enabled": True,\n',
)
replace_once(
    "app/risk.py",
    'def _realized_pnl_for_day(row: TradeJournal, expected_day: str) -> float:\n',
    'def _journal_row_consumes_daily_slot(row: TradeJournal, expected_day: str) -> bool:\n'
    '    status = str(row.status or "").lower()\n'
    '    result = str(row.result or "").lower()\n'
    '    if status == "closed" and result == "execution_failed":\n'
    '        return False\n'
    '    if row.opened_at and _timestamp_is_on_bdt_day(row.opened_at, expected_day):\n'
    '        return True\n'
    '    return bool(\n'
    '        status in CAPACITY_BLOCKING_STATUSES\n'
    '        and _timestamp_is_on_bdt_day(row.detected_at, expected_day)\n'
    '    )\n\n\n'
    'def _realized_pnl_for_day(row: TradeJournal, expected_day: str) -> float:\n',
)

replace_once(
    "app/execution_service.py",
    '            required_risk=float(validation["risk_amount"]),\n'
    '            max_active_trades=int(validation["max_active_trades"]),\n',
    '            required_risk=float(validation["risk_amount"]),\n'
    '            max_active_trades=int(validation["max_active_trades"]),\n'
    '            max_daily_trades=int(validation["max_daily_trades"]),\n'
    '            reentry_cooldown_minutes=int(validation["reentry_cooldown_minutes"]),\n',
)

replace_once(
    "app/execution_reservation.py",
    'import json\nfrom typing import Any\n',
    'import json\nfrom datetime import UTC, datetime, timedelta\nfrom typing import Any\n',
)
replace_once(
    "app/execution_reservation.py",
    '    required_risk: float | None = None,\n'
    '    max_active_trades: int | None = None,\n'
    ') -> dict[str, Any]:\n',
    '    required_risk: float | None = None,\n'
    '    max_active_trades: int | None = None,\n'
    '    max_daily_trades: int | None = None,\n'
    '    reentry_cooldown_minutes: int | None = None,\n'
    '    now: datetime | None = None,\n'
    ') -> dict[str, Any]:\n',
)
replace_once(
    "app/execution_reservation.py",
    '    risk_amount = float(required_risk)\n'
    '    active_limit = int(max_active_trades)\n',
    '    risk_amount = float(required_risk)\n'
    '    active_limit = int(max_active_trades)\n'
    '    daily_limit = int(max_daily_trades or 0)\n'
    '    cooldown_minutes = int(reentry_cooldown_minutes or 0)\n'
    '    current = now.astimezone(UTC) if now and now.tzinfo else (now.replace(tzinfo=UTC) if now else datetime.now(UTC))\n',
)
replace_once(
    "app/execution_reservation.py",
    '    if active_limit <= 0:\n'
    '        raise ValueError("max_active_trades must be positive")\n',
    '    if active_limit <= 0:\n'
    '        raise ValueError("max_active_trades must be positive")\n'
    '    if daily_limit <= 0:\n'
    '        raise ValueError("max_daily_trades must be positive")\n'
    '    if cooldown_minutes < 0:\n'
    '        raise ValueError("reentry_cooldown_minutes cannot be negative")\n',
)
replace_once(
    "app/execution_reservation.py",
    '        if bool(state.circuit_breaker_active):\n'
    '            return {\n'
    '                "reserved": False,\n'
    '                "reason": state.circuit_breaker_reason or "DAILY_NET_LOSS_CIRCUIT_BREAKER",\n'
    '                "trade": None,\n'
    '            }\n\n'
    '        open_rows = db.query(TradeJournal).filter(TradeJournal.status.in_(sorted(CAPACITY_BLOCKING_STATUSES))).all()\n',
    '        if bool(state.circuit_breaker_active):\n'
    '            return {\n'
    '                "reserved": False,\n'
    '                "reason": state.circuit_breaker_reason or "DAILY_NET_LOSS_CIRCUIT_BREAKER",\n'
    '                "trade": None,\n'
    '            }\n'
    '        trades_today = int(state.trades_today or 0)\n'
    '        if trades_today >= daily_limit:\n'
    '            return {\n'
    '                "reserved": False,\n'
    '                "reason": "DAILY_TRADE_LIMIT_REACHED",\n'
    '                "trades_today": trades_today,\n'
    '                "max_daily_trades": daily_limit,\n'
    '                "trade": None,\n'
    '            }\n'
    '        recent_close = (\n'
    '            db.query(TradeJournal)\n'
    '            .filter(\n'
    '                TradeJournal.symbol == symbol,\n'
    '                TradeJournal.status == "closed",\n'
    '                TradeJournal.opened_at.isnot(None),\n'
    '                TradeJournal.closed_at.isnot(None),\n'
    '                or_(TradeJournal.result.is_(None), TradeJournal.result != "execution_failed"),\n'
    '            )\n'
    '            .order_by(TradeJournal.id.desc())\n'
    '            .first()\n'
    '        )\n'
    '        cooldown_until = _cooldown_until(recent_close, cooldown_minutes)\n'
    '        if cooldown_until is not None and current < cooldown_until:\n'
    '            return {\n'
    '                "reserved": False,\n'
    '                "reason": "SYMBOL_REENTRY_COOLDOWN",\n'
    '                "cooldown_until": cooldown_until.isoformat(),\n'
    '                "trade": None,\n'
    '            }\n\n'
    '        open_rows = db.query(TradeJournal).filter(TradeJournal.status.in_(sorted(CAPACITY_BLOCKING_STATUSES))).all()\n',
)
replace_once(
    "app/execution_reservation.py",
    '            "active_trades_before": len(open_rows),\n'
    '            "active_trades_after": len(open_rows) + 1,\n'
    '        }\n',
    '            "active_trades_before": len(open_rows),\n'
    '            "active_trades_after": len(open_rows) + 1,\n'
    '            "trades_today_before": trades_today,\n'
    '            "trades_today_after": trades_today + 1,\n'
    '            "max_daily_trades": daily_limit,\n'
    '            "reentry_cooldown_minutes": cooldown_minutes,\n'
    '        }\n',
)
replace_once(
    "app/execution_reservation.py",
    '        state.active_trade_count = len(open_rows) + 1\n'
    '        state.live_risk = float(state.live_risk or 0.0) + risk_amount\n',
    '        state.active_trade_count = len(open_rows) + 1\n'
    '        state.trades_today = trades_today + 1\n'
    '        state.live_risk = float(state.live_risk or 0.0) + risk_amount\n',
)
replace_once(
    "app/execution_reservation.py",
    'def _decode_symbols(value: str | None) -> list[str]:\n',
    'def _cooldown_until(row: TradeJournal | None, cooldown_minutes: int) -> datetime | None:\n'
    '    if row is None or cooldown_minutes <= 0:\n'
    '        return None\n'
    '    parsed = _parse_timestamp(row.closed_at)\n'
    '    return parsed + timedelta(minutes=cooldown_minutes) if parsed is not None else None\n\n\n'
    'def _parse_timestamp(value: str | None) -> datetime | None:\n'
    '    if not value:\n'
    '        return None\n'
    '    try:\n'
    '        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))\n'
    '    except ValueError:\n'
    '        return None\n'
    '    if parsed.tzinfo is None:\n'
    '        parsed = parsed.replace(tzinfo=UTC)\n'
    '    return parsed.astimezone(UTC)\n\n\n'
    'def _decode_symbols(value: str | None) -> list[str]:\n',
)

replace_once(
    "app/background_worker.py",
    'NATIVE_TP_MONITOR_SECONDS = 2\n',
    'NATIVE_TP_MONITOR_SECONDS = 2\n'
    'EXPECTED_EXECUTION_BLOCKS = {\n'
    '    "DUPLICATE_EXECUTION",\n'
    '    "SYMBOL_ALREADY_ACTIVE",\n'
    '    "ACTIVE_TRADE_LIMIT_REACHED",\n'
    '    "DYNAMIC_RISK_CAPACITY_EXCEEDED",\n'
    '    "DAILY_TRADE_LIMIT_REACHED",\n'
    '    "SYMBOL_REENTRY_COOLDOWN",\n'
    '}\n',
)
replace_once(
    "app/background_worker.py",
    '                    else:\n'
    '                        error_message = outcome.get("error", "Unknown execution failure")\n'
    '                        logger.warning("Auto execution failed for %s: %s", signal.get("symbol"), error_message)\n'
    '                        _safe_log_bot_event(\n'
    '                            "auto_execution_failed",\n'
    '                            f"Auto execution failed for {signal.get(\'symbol\')}",\n'
    '                            level="warning",\n'
    '                            metadata={\n'
    '                                "endpoint": "background:auto_execution",\n'
    '                                "affected_module": "execution",\n'
    '                                "error_code": "AUTO_EXECUTION_FAILED",\n'
    '                                "signal": signal,\n'
    '                                "outcome": outcome,\n'
    '                                "error": error_message,\n'
    '                            },\n'
    '                        )\n',
    '                    else:\n'
    '                        error_message = outcome.get("error", "Unknown execution failure")\n'
    '                        if _is_expected_execution_block(error_message):\n'
    '                            logger.debug("Auto execution blocked for %s: %s", signal.get("symbol"), error_message)\n'
    '                            _safe_log_bot_event(\n'
    '                                "trade_execution_blocked",\n'
    '                                f"Execution guard blocked {signal.get(\'symbol\')}",\n'
    '                                level="info",\n'
    '                                metadata={\n'
    '                                    "endpoint": "background:auto_execution",\n'
    '                                    "affected_module": "execution",\n'
    '                                    "error_code": str(error_message),\n'
    '                                    "signal": signal,\n'
    '                                    "outcome": outcome,\n'
    '                                },\n'
    '                            )\n'
    '                        else:\n'
    '                            logger.warning("Auto execution failed for %s: %s", signal.get("symbol"), error_message)\n'
    '                            _safe_log_bot_event(\n'
    '                                "auto_execution_failed",\n'
    '                                f"Auto execution failed for {signal.get(\'symbol\')}",\n'
    '                                level="warning",\n'
    '                                metadata={\n'
    '                                    "endpoint": "background:auto_execution",\n'
    '                                    "affected_module": "execution",\n'
    '                                    "error_code": "AUTO_EXECUTION_FAILED",\n'
    '                                    "signal": signal,\n'
    '                                    "outcome": outcome,\n'
    '                                    "error": error_message,\n'
    '                                },\n'
    '                            )\n',
)
replace_once(
    "app/background_worker.py",
    'async def native_profit_monitor_loop() -> None:\n',
    'def _is_expected_execution_block(value: object) -> bool:\n'
    '    return str(value or "").strip() in EXPECTED_EXECUTION_BLOCKS\n\n\n'
    'async def native_profit_monitor_loop() -> None:\n',
)

Path("tests/test_trade_churn_guards.py").write_text('''from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from tempfile import NamedTemporaryFile
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.background_worker import _is_expected_execution_block
from app.bot_controls import DEFAULT_RISK_SETTINGS
from app.database import Base
from app.execution_reservation import reserve_execution_capacity
from app.models import RiskRuntimeState, TradeJournal
from app.risk import refresh_risk_state, validate_trade


class TradeChurnGuardTests(unittest.TestCase):
    def test_policy_locks_daily_execution_limit_to_eight(self) -> None:
        self.assertEqual(DEFAULT_RISK_SETTINGS["max_daily_trades"], 8)

    def test_preflight_blocks_ninth_trade(self) -> None:
        state = {
            "circuit_breaker_active": False,
            "circuit_breaker_reason": None,
            "day_start_equity": 1000.0,
            "symbol_cooldowns": {},
            "active_symbols": [],
            "active_trade_count": 0,
            "available_risk": 50.0,
            "live_risk": 0.0,
            "base_risk_pool": 50.0,
            "effective_risk_pool": 50.0,
            "trades_today": 8,
            "max_trades_per_day": 8,
        }
        with patch("app.risk.refresh_risk_state", return_value=state):
            result = validate_trade(self._signal(), account_equity=1000.0)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "DAILY_TRADE_LIMIT_REACHED")

    def test_atomic_reservation_cannot_exceed_daily_limit(self) -> None:
        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
        with self._database(trades_today=7, available_risk=100.0) as resources:
            TestSession, test_engine = resources
            with self._reservation_patches(TestSession, test_engine):
                first = reserve_execution_capacity(
                    self._trade("BTCUSDT"),
                    "a" * 64,
                    required_risk=20.0,
                    max_active_trades=5,
                    max_daily_trades=8,
                    reentry_cooldown_minutes=30,
                    now=now,
                )
                ninth = reserve_execution_capacity(
                    self._trade("ETHUSDT"),
                    "b" * 64,
                    required_risk=20.0,
                    max_active_trades=5,
                    max_daily_trades=8,
                    reentry_cooldown_minutes=30,
                    now=now,
                )
            self.assertTrue(first["reserved"])
            self.assertFalse(ninth["reserved"])
            self.assertEqual(ninth["reason"], "DAILY_TRADE_LIMIT_REACHED")

    def test_recent_terminal_close_blocks_same_symbol_reentry(self) -> None:
        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
        with self._database(trades_today=1, available_risk=100.0) as resources:
            TestSession, test_engine = resources
            self._add_closed_trade(TestSession, "BTCUSDT", now - timedelta(minutes=10))
            with self._reservation_patches(TestSession, test_engine):
                result = reserve_execution_capacity(
                    self._trade("BTCUSDT"),
                    "c" * 64,
                    required_risk=20.0,
                    max_active_trades=5,
                    max_daily_trades=8,
                    reentry_cooldown_minutes=30,
                    now=now,
                )
            self.assertFalse(result["reserved"])
            self.assertEqual(result["reason"], "SYMBOL_REENTRY_COOLDOWN")
            self.assertIn("cooldown_until", result)

    def test_symbol_can_reenter_after_cooldown_expiry(self) -> None:
        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
        with self._database(trades_today=1, available_risk=100.0) as resources:
            TestSession, test_engine = resources
            self._add_closed_trade(TestSession, "BTCUSDT", now - timedelta(minutes=31))
            with self._reservation_patches(TestSession, test_engine):
                result = reserve_execution_capacity(
                    self._trade("BTCUSDT"),
                    "d" * 64,
                    required_risk=20.0,
                    max_active_trades=5,
                    max_daily_trades=8,
                    reentry_cooldown_minutes=30,
                    now=now,
                )
            self.assertTrue(result["reserved"])

    def test_execution_failed_row_does_not_consume_daily_slot_after_refresh(self) -> None:
        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
        with self._database(trades_today=1, available_risk=50.0) as resources:
            TestSession, test_engine = resources
            db = TestSession()
            try:
                db.add(
                    TradeJournal(
                        journal_id="failed-row",
                        execution_key="f" * 64,
                        symbol="BTCUSDT",
                        direction="long",
                        execution_mode="demo",
                        entry_price=100.0,
                        stop_loss=99.0,
                        take_profit=101.5,
                        quantity=1.0,
                        strategy_name="ema_pullback",
                        status="closed",
                        result="execution_failed",
                        detected_at=now.isoformat(),
                        opened_at=None,
                        closed_at=now.isoformat(),
                    )
                )
                db.commit()
            finally:
                db.close()
            with (
                patch("app.risk.SessionLocal", TestSession),
                patch("app.risk.engine", test_engine),
                patch("app.risk._ensure_risk_runtime_columns"),
            ):
                state = refresh_risk_state(account_equity=1000.0, now=now)
            self.assertEqual(state["trades_today"], 0)

    def test_expected_guard_blocks_are_not_execution_failures(self) -> None:
        for code in (
            "DUPLICATE_EXECUTION",
            "SYMBOL_ALREADY_ACTIVE",
            "DAILY_TRADE_LIMIT_REACHED",
            "SYMBOL_REENTRY_COOLDOWN",
        ):
            with self.subTest(code=code):
                self.assertTrue(_is_expected_execution_block(code))
        self.assertFalse(_is_expected_execution_block("ORDER_NOT_ACCEPTED"))

    @staticmethod
    def _signal() -> dict:
        return {
            "symbol": "BTCUSDT",
            "strategy_name": "ema_pullback",
            "trade_type": "scalping",
            "direction": "long",
            "entry": 100.0,
            "stop_loss": 99.0,
            "take_profit": 101.5,
            "risk_reward": 1.5,
            "status": "active",
        }

    @staticmethod
    def _trade(symbol: str) -> dict:
        return {
            "symbol": symbol,
            "strategy_name": "breakout",
            "direction": "long",
            "execution_mode": "demo",
            "entry": 100.0,
            "stop_loss": 98.0,
            "take_profit": 103.0,
            "quantity": 10.0,
            "detected_at": "2026-07-14T11:59:00+00:00",
            "exchange_metadata": {},
        }

    @staticmethod
    def _add_closed_trade(TestSession, symbol: str, closed_at: datetime) -> None:
        db = TestSession()
        try:
            db.add(
                TradeJournal(
                    journal_id=f"closed-{symbol}-{int(closed_at.timestamp())}",
                    execution_key=(symbol.lower() + "0" * 64)[:64],
                    symbol=symbol,
                    direction="long",
                    execution_mode="demo",
                    entry_price=100.0,
                    stop_loss=99.0,
                    take_profit=101.5,
                    quantity=1.0,
                    strategy_name="ema_pullback",
                    status="closed",
                    result="loss",
                    detected_at=(closed_at - timedelta(minutes=10)).isoformat(),
                    opened_at=(closed_at - timedelta(minutes=9)).isoformat(),
                    closed_at=closed_at.isoformat(),
                )
            )
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _reservation_patches(TestSession, test_engine):
        return _PatchGroup(
            patch("app.execution_reservation.SessionLocal", TestSession),
            patch("app.journal.SessionLocal", TestSession),
            patch("app.journal.engine", test_engine),
        )

    @staticmethod
    def _database(*, trades_today: int, available_risk: float):
        return _TemporaryDatabase(trades_today=trades_today, available_risk=available_risk)


class _PatchGroup:
    def __init__(self, *patchers):
        self.patchers = patchers

    def __enter__(self):
        for patcher in self.patchers:
            patcher.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        for patcher in reversed(self.patchers):
            patcher.stop()


class _TemporaryDatabase:
    def __init__(self, *, trades_today: int, available_risk: float):
        self.trades_today = trades_today
        self.available_risk = available_risk
        self.file = None
        self.engine = None
        self.Session = None

    def __enter__(self):
        self.file = NamedTemporaryFile(suffix=".db")
        self.engine = create_engine(
            f"sqlite:///{self.file.name}",
            connect_args={"check_same_thread": False},
        )
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        db = self.Session()
        try:
            db.add(
                RiskRuntimeState(
                    id=1,
                    trades_day="2026-07-14",
                    trades_today=self.trades_today,
                    active_symbols="[]",
                    symbol_cooldowns="{}",
                    day_start_equity=1000.0,
                    live_risk=0.0,
                    base_risk_pool=100.0,
                    effective_risk_pool=100.0,
                    available_risk=self.available_risk,
                    active_trade_count=0,
                    circuit_breaker_active=False,
                )
            )
            db.commit()
        finally:
            db.close()
        return self.Session, self.engine

    def __exit__(self, exc_type, exc, tb):
        if self.engine is not None:
            self.engine.dispose()
        if self.file is not None:
            self.file.close()


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")
