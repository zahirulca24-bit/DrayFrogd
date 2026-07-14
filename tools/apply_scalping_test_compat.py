from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one match in {path}, found {count}: {old[:100]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "tests/test_execution_idempotency.py",
    '    "strategy_name": "breakout",\n    "direction": "long",',
    '    "strategy_name": "breakout",\n    "trade_type": "scalping",\n    "direction": "long",',
)

replace_once(
    "tests/test_execution_idempotency.py",
    '    "allowed": True,\n    "risk_per_trade": 0.01,',
    '    "allowed": True,\n    "trade_type": "scalping",\n    "risk_per_trade": 0.01,',
)

replace_once(
    "tests/test_strategy_persistence.py",
    '        signal = {\n            "symbol": "BTCUSDT",\n            "strategy_name": "ema_pullback",\n            "direction": "long",',
    '        signal = {\n            "symbol": "BTCUSDT",\n            "strategy_name": "ema_pullback",\n            "trade_type": "scalping",\n            "direction": "long",',
)

replace_once(
    "tests/test_strategy_persistence.py",
    'patch("app.execution_core.validate_trade", return_value={"allowed": True, "risk_per_trade": 0.01, "leverage_cap": 5, "exposure_cap": 0.3}),',
    'patch("app.execution_core.validate_trade", return_value={"allowed": True, "trade_type": "scalping", "risk_per_trade": 0.01, "leverage_cap": 5, "exposure_cap": 0.3}),',
)

replace_once(
    "tests/test_rr_policy_alignment.py",
    '            validation = validate_trade(signal.to_dict(), account_equity=1000.0)',
    '            validation = validate_trade({**signal.to_dict(), "trade_type": "scalping"}, account_equity=1000.0)',
)

replace_once(
    "tests/test_rr_policy_alignment.py",
    '            "strategy_name": "breakout",\n            "direction": "long",',
    '            "strategy_name": "breakout",\n            "trade_type": "scalping",\n            "direction": "long",',
)

replace_once(
    "tests/test_scanner_integration.py",
    '            scanner._latest_signals.clear()\n            scanner._latest_scan_results.clear()',
    '            scanner._latest_signals.clear()\n            scanner._latest_scan_results.clear()\n        suppression_patcher = patch(\n            "app.scanner.sync_scalping_reentry_cooldowns",\n            return_value={"ok": True, "active_symbols": [], "error": None},\n        )\n        suppression_patcher.start()\n        self.addCleanup(suppression_patcher.stop)',
)

replace_once(
    "tests/test_trade_management_profiles.py",
    '        self.assertEqual(max_hold_seconds(management), 59 * 60)',
    '        self.assertEqual(max_hold_seconds(management), 30 * 60)',
)
