from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one match in {path}, found {count}: {old[:80]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/trade_management_profiles.py",
    '        "max_hold_seconds": 59 * 60,',
    '        "max_hold_seconds": 30 * 60,',
)

replace_once(
    "app/trade_management_rules.py",
    '    opened_at = _parse_time(trade.get("opened_at")) or now',
    '    opened_at = _parse_time(trade.get("opened_at") or trade.get("detected_at")) or now',
)

replace_once(
    "app/risk.py",
    'def start_loss_cooldown(symbol: str | None = None, now: datetime | None = None) -> None:\n'
    '    normalized_symbol = str(symbol or "*").upper().strip() or "*"\n'
    '    current = _as_utc(now)\n'
    '    expiry = current + timedelta(minutes=LOSS_COOLDOWN_MINUTES)',
    'def start_loss_cooldown(\n'
    '    symbol: str | None = None,\n'
    '    now: datetime | None = None,\n'
    '    duration_minutes: int = LOSS_COOLDOWN_MINUTES,\n'
    ') -> None:\n'
    '    normalized_symbol = str(symbol or "*").upper().strip() or "*"\n'
    '    current = _as_utc(now)\n'
    '    duration = max(int(duration_minutes), 1)\n'
    '    expiry = current + timedelta(minutes=duration)',
)

replace_once(
    "app/risk.py",
    '            cooldowns = _decode_cooldowns(row.symbol_cooldowns)\n'
    '            cooldowns[normalized_symbol] = expiry\n'
    '            row.symbol_cooldowns = _encode_cooldowns(cooldowns)',
    '            cooldowns = _decode_cooldowns(row.symbol_cooldowns)\n'
    '            existing_expiry = cooldowns.get(normalized_symbol)\n'
    '            if existing_expiry is None or expiry > existing_expiry:\n'
    '                cooldowns[normalized_symbol] = expiry\n'
    '            row.symbol_cooldowns = _encode_cooldowns(cooldowns)',
)

replace_once(
    "app/risk_cooldown_sync.py",
    'from app.risk import LOSS_COOLDOWN_MINUTES, start_loss_cooldown',
    'from app.risk import LOSS_COOLDOWN_MINUTES, start_loss_cooldown\n'
    'from app.scalping_cooldown import sync_scalping_reentry_cooldowns',
)

replace_once(
    "app/risk_cooldown_sync.py",
    '    return {"ok": True, "applied": applied, "applied_count": len(applied)}',
    '    scalping_reentry = sync_scalping_reentry_cooldowns(now=current)\n'
    '    return {\n'
    '        "ok": bool(scalping_reentry.get("ok", False)),\n'
    '        "applied": applied,\n'
    '        "applied_count": len(applied),\n'
    '        "scalping_reentry": scalping_reentry,\n'
    '    }',
)

replace_once(
    "app/scanner.py",
    'from app.signal_pipeline import evaluate_signal_contexts, normalize_strategy_result',
    'from app.scalping_cooldown import sync_scalping_reentry_cooldowns\n'
    'from app.signal_pipeline import evaluate_signal_contexts, normalize_strategy_result',
)

replace_once(
    "app/scanner.py",
    '    pipeline = evaluate_signal_contexts(strategy_contexts)\n'
    '    signals = list(pipeline.get("signals") or [])\n'
    '    scan_results = list(pipeline.get("results") or [])',
    '    pipeline = evaluate_signal_contexts(strategy_contexts)\n'
    '    raw_signals = list(pipeline.get("signals") or [])\n'
    '    raw_scan_results = list(pipeline.get("results") or [])\n'
    '    suppression = sync_scalping_reentry_cooldowns(now=reference)\n'
    '    suppressed_symbols = set(suppression.get("active_symbols") or [])\n'
    '    signals, scan_results, suppressed_rows = _apply_scalping_suppression(\n'
    '        raw_signals,\n'
    '        raw_scan_results,\n'
    '        suppressed_symbols=suppressed_symbols,\n'
    '        fail_closed=not bool(suppression.get("ok", False)),\n'
    '    )',
)

replace_once(
    "app/scanner.py",
    '        "strategy_checks": int(pipeline.get("strategy_checks") or 0),\n'
    '        "signals": signals,\n'
    '        "results": scan_results,',
    '        "strategy_checks": len(scan_results),\n'
    '        "signals": signals,\n'
    '        "results": scan_results,\n'
    '        "scalping_signal_suppression": {\n'
    '            "ok": bool(suppression.get("ok", False)),\n'
    '            "active_symbols": sorted(suppressed_symbols),\n'
    '            "suppressed_rows": len(suppressed_rows),\n'
    '            "error": suppression.get("error"),\n'
    '        },',
)

replace_once(
    "app/scanner.py",
    '\n\ndef get_latest_signals() -> list[dict[str, Any]]:',
    '''\n\ndef _apply_scalping_suppression(\n    signals: list[dict[str, Any]],\n    scan_results: list[dict[str, Any]],\n    *,\n    suppressed_symbols: set[str],\n    fail_closed: bool = False,\n) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:\n    normalized_symbols = {str(symbol or "").upper().strip() for symbol in suppressed_symbols if str(symbol or "").strip()}\n\n    def is_suppressed(item: dict[str, Any]) -> bool:\n        if str(item.get("trade_type") or "").lower().strip() != "scalping":\n            return False\n        if fail_closed:\n            return True\n        return str(item.get("symbol") or "").upper().strip() in normalized_symbols\n\n    suppressed_rows = [item for item in scan_results if is_suppressed(item)]\n    visible_signals = [item for item in signals if not is_suppressed(item)]\n    visible_results = [item for item in scan_results if not is_suppressed(item)]\n    return visible_signals, visible_results, suppressed_rows\n\n\ndef get_latest_signals() -> list[dict[str, Any]]:''',
)

Path("app/scalping_cooldown.py").write_text(
    '''from __future__ import annotations\n\nimport json\nfrom datetime import UTC, datetime, timedelta\nfrom typing import Any\n\nfrom app.database import SessionLocal\nfrom app.models import TradeJournal\nfrom app.risk import start_loss_cooldown\n\n\nSCALPING_REENTRY_COOLDOWN_MINUTES = 60\n\n\ndef sync_scalping_reentry_cooldowns(now: datetime | None = None) -> dict[str, Any]:\n    """Rebuild persistent 60-minute Scalping symbol cooldowns from closed Journal rows.\n\n    This is idempotent: each expiry is anchored to the authoritative close timestamp,\n    and app.risk.start_loss_cooldown never shortens a longer existing cooldown.\n    """\n\n    current = _as_utc(now)\n    cutoff = current - timedelta(minutes=SCALPING_REENTRY_COOLDOWN_MINUTES)\n    active: dict[str, datetime] = {}\n    applied: list[dict[str, str]] = []\n\n    db = SessionLocal()\n    try:\n        rows = db.query(TradeJournal).filter(TradeJournal.status == "closed").all()\n        for row in rows:\n            closed_at = _parse_time(row.closed_at)\n            if closed_at is None or closed_at <= cutoff or closed_at > current + timedelta(minutes=1):\n                continue\n            if not _is_scalping_trade(row):\n                continue\n\n            symbol = str(row.symbol or "").upper().strip()\n            if not symbol:\n                continue\n            expiry = closed_at + timedelta(minutes=SCALPING_REENTRY_COOLDOWN_MINUTES)\n            previous = active.get(symbol)\n            if previous is None or expiry > previous:\n                active[symbol] = expiry\n\n        for symbol, expiry in sorted(active.items()):\n            closed_at = expiry - timedelta(minutes=SCALPING_REENTRY_COOLDOWN_MINUTES)\n            start_loss_cooldown(\n                symbol=symbol,\n                now=closed_at,\n                duration_minutes=SCALPING_REENTRY_COOLDOWN_MINUTES,\n            )\n            applied.append(\n                {\n                    "symbol": symbol,\n                    "closed_at": closed_at.isoformat(),\n                    "cooldown_until": expiry.isoformat(),\n                }\n            )\n    except Exception as exc:\n        return {\n            "ok": False,\n            "active_symbols": [],\n            "suppressions": {},\n            "applied": [],\n            "applied_count": 0,\n            "error": str(exc),\n        }\n    finally:\n        db.close()\n\n    return {\n        "ok": True,\n        "active_symbols": sorted(active),\n        "suppressions": {symbol: expiry.isoformat() for symbol, expiry in sorted(active.items())},\n        "applied": applied,\n        "applied_count": len(applied),\n        "error": None,\n    }\n\n\ndef _is_scalping_trade(row: Any) -> bool:\n    metadata = _metadata(getattr(row, "exchange_metadata", None))\n    management = metadata.get("management") if isinstance(metadata.get("management"), dict) else {}\n    validation = metadata.get("risk_validation") if isinstance(metadata.get("risk_validation"), dict) else {}\n    candidates = (\n        getattr(row, "trade_type", None),\n        metadata.get("trade_type"),\n        management.get("trade_type"),\n        validation.get("trade_type"),\n    )\n    if any(str(value or "").lower().strip() == "scalping" for value in candidates):\n        return True\n    return str(management.get("profile_name") or "").lower().strip().startswith("scalping_")\n\n\ndef _metadata(value: Any) -> dict[str, Any]:\n    if isinstance(value, dict):\n        return value\n    if not value:\n        return {}\n    try:\n        parsed = json.loads(str(value))\n    except (json.JSONDecodeError, TypeError, ValueError):\n        return {}\n    return parsed if isinstance(parsed, dict) else {}\n\n\ndef _parse_time(value: Any) -> datetime | None:\n    if not value:\n        return None\n    if isinstance(value, datetime):\n        return _as_utc(value)\n    try:\n        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))\n    except ValueError:\n        return None\n    return _as_utc(parsed)\n\n\ndef _as_utc(value: datetime | None) -> datetime:\n    if value is None:\n        return datetime.now(UTC)\n    if value.tzinfo is None:\n        return value.replace(tzinfo=UTC)\n    return value.astimezone(UTC)\n''',
    encoding="utf-8",
)

Path("tests/test_scalping_timeout_suppression.py").write_text(
    '''from __future__ import annotations\n\nimport json\nimport unittest\nfrom datetime import UTC, datetime, timedelta\nfrom types import SimpleNamespace\nfrom unittest.mock import patch\n\nfrom app.scalping_cooldown import SCALPING_REENTRY_COOLDOWN_MINUTES, sync_scalping_reentry_cooldowns\nfrom app.scanner import _apply_scalping_suppression\nfrom app.trade_management_profiles import build_profile_management_state\nfrom app.trade_management_rules import evaluate_management_action\n\n\nclass _FakeQuery:\n    def __init__(self, rows):\n        self.rows = rows\n\n    def filter(self, *_args, **_kwargs):\n        return self\n\n    def all(self):\n        return list(self.rows)\n\n\nclass _FakeSession:\n    def __init__(self, rows):\n        self.rows = rows\n        self.closed = False\n\n    def query(self, *_args, **_kwargs):\n        return _FakeQuery(self.rows)\n\n    def close(self):\n        self.closed = True\n\n\nclass ScalpingTimeoutSuppressionTests(unittest.TestCase):\n    def _management(self, trade_type: str) -> dict:\n        return build_profile_management_state(\n            entry=100.0,\n            stop_loss=99.0,\n            take_profit=101.5 if trade_type == "scalping" else 102.0,\n            quantity=1.0,\n            direction="long",\n            trade_type=trade_type,\n        )\n\n    def test_scalping_holds_before_30_minutes_and_closes_at_30_minutes(self) -> None:\n        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)\n        management = self._management("scalping")\n        before = evaluate_management_action(\n            {\n                "direction": "long",\n                "entry": 100.0,\n                "stop_loss": 99.0,\n                "opened_at": (now - timedelta(minutes=29, seconds=59)).isoformat(),\n                "management": management,\n            },\n            100.0,\n            now,\n        )\n        at_limit = evaluate_management_action(\n            {\n                "direction": "long",\n                "entry": 100.0,\n                "stop_loss": 99.0,\n                "opened_at": (now - timedelta(minutes=30)).isoformat(),\n                "management": management,\n            },\n            100.0,\n            now,\n        )\n        self.assertEqual(before["action"], "hold")\n        self.assertEqual(at_limit["action"], "max_hold_close")\n        self.assertEqual(management["max_hold_seconds"], 30 * 60)\n\n    def test_intraday_does_not_inherit_scalping_30_minute_timeout(self) -> None:\n        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)\n        management = self._management("intraday")\n        decision = evaluate_management_action(\n            {\n                "direction": "long",\n                "entry": 100.0,\n                "stop_loss": 99.0,\n                "opened_at": (now - timedelta(minutes=30)).isoformat(),\n                "management": management,\n            },\n            100.0,\n            now,\n        )\n        self.assertEqual(decision["action"], "hold")\n        self.assertEqual(management["max_hold_seconds"], 6 * 60 * 60)\n\n    def test_detected_at_is_used_when_opened_at_is_missing(self) -> None:\n        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)\n        decision = evaluate_management_action(\n            {\n                "direction": "long",\n                "entry": 100.0,\n                "stop_loss": 99.0,\n                "detected_at": (now - timedelta(minutes=30)).isoformat(),\n                "management": self._management("scalping"),\n            },\n            100.0,\n            now,\n        )\n        self.assertEqual(decision["action"], "max_hold_close")\n\n    def test_any_closed_scalping_result_creates_60_minute_cooldown(self) -> None:\n        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)\n        closed_at = now - timedelta(minutes=10)\n        rows = [\n            SimpleNamespace(\n                status="closed",\n                symbol="BTCUSDT",\n                closed_at=closed_at.isoformat(),\n                realized_pnl=12.5,\n                exchange_metadata=json.dumps({"management": {"trade_type": "scalping", "profile_name": "scalping_v2"}}),\n            )\n        ]\n        session = _FakeSession(rows)\n        with patch("app.scalping_cooldown.SessionLocal", return_value=session), patch(\n            "app.scalping_cooldown.start_loss_cooldown"\n        ) as start_cooldown:\n            result = sync_scalping_reentry_cooldowns(now=now)\n\n        self.assertTrue(result["ok"])\n        self.assertEqual(result["active_symbols"], ["BTCUSDT"])\n        self.assertEqual(SCALPING_REENTRY_COOLDOWN_MINUTES, 60)\n        start_cooldown.assert_called_once_with(\n            symbol="BTCUSDT",\n            now=closed_at,\n            duration_minutes=60,\n        )\n        self.assertTrue(session.closed)\n\n    def test_intraday_close_does_not_create_scalping_suppression(self) -> None:\n        now = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)\n        rows = [\n            SimpleNamespace(\n                status="closed",\n                symbol="ETHUSDT",\n                closed_at=(now - timedelta(minutes=5)).isoformat(),\n                exchange_metadata=json.dumps({"management": {"trade_type": "intraday", "profile_name": "intraday_v1"}}),\n            )\n        ]\n        with patch("app.scalping_cooldown.SessionLocal", return_value=_FakeSession(rows)), patch(\n            "app.scalping_cooldown.start_loss_cooldown"\n        ) as start_cooldown:\n            result = sync_scalping_reentry_cooldowns(now=now)\n\n        self.assertTrue(result["ok"])\n        self.assertEqual(result["active_symbols"], [])\n        start_cooldown.assert_not_called()\n\n    def test_scanner_hides_suppressed_scalping_but_keeps_intraday_and_other_symbols(self) -> None:\n        signals = [\n            {"symbol": "BTCUSDT", "trade_type": "scalping", "status": "active"},\n            {"symbol": "BTCUSDT", "trade_type": "intraday", "status": "active"},\n            {"symbol": "ETHUSDT", "trade_type": "scalping", "status": "active"},\n        ]\n        results = list(signals)\n        visible_signals, visible_results, suppressed = _apply_scalping_suppression(\n            signals, results, suppressed_symbols={"BTCUSDT"}\n        )\n        self.assertEqual(\n            [(item["symbol"], item["trade_type"]) for item in visible_signals],\n            [("BTCUSDT", "intraday"), ("ETHUSDT", "scalping")],\n        )\n        self.assertEqual(len(visible_results), 2)\n        self.assertEqual([(item["symbol"], item["trade_type"]) for item in suppressed], [("BTCUSDT", "scalping")])\n\n    def test_scanner_suppression_failure_fails_closed_for_scalping_only(self) -> None:\n        signals = [\n            {"symbol": "BTCUSDT", "trade_type": "scalping", "status": "active"},\n            {"symbol": "ETHUSDT", "trade_type": "intraday", "status": "active"},\n        ]\n        visible_signals, visible_results, suppressed = _apply_scalping_suppression(\n            signals, list(signals), suppressed_symbols=set(), fail_closed=True\n        )\n        self.assertEqual([(item["symbol"], item["trade_type"]) for item in visible_signals], [("ETHUSDT", "intraday")])\n        self.assertEqual(len(visible_results), 1)\n        self.assertEqual([(item["symbol"], item["trade_type"]) for item in suppressed], [("BTCUSDT", "scalping")])\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    encoding="utf-8",
)
