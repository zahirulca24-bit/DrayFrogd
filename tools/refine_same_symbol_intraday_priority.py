from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one match in {path}, found {count}: {old[:120]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/signal_pipeline.py",
    "        candidates = sorted(grouped[symbol], key=_primary_sort_key)",
    "        candidates = sorted(grouped[symbol], key=_primary_candidate_sort_key)",
)

replace_once(
    "app/signal_pipeline.py",
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
    '''def _primary_candidate_sort_key(item: dict[str, Any]) -> tuple[int, int, float, int, float, str, str]:
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
    )


def _primary_sort_key(item: dict[str, Any]) -> tuple[int, float, int, float, str, str, str]:
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
)

replace_once(
    "tests/test_profile_selection_priority.py",
    '''    def test_opposite_active_profile_directions_block_execution(self) -> None:
        scalping = self._context("SOLUSDT", "scalping")''',
    '''    def test_different_symbols_keep_score_based_global_ranking(self) -> None:
        contexts = [self._context("ETHUSDT", "scalping"), self._context("BTCUSDT", "intraday")]
        outputs = [
            [self._signal("long", "active", confidence=60)],
            [self._signal("long", "active", confidence=99)],
        ]
        with patch("app.signal_pipeline.evaluate_registered_strategies", side_effect=outputs):
            result = evaluate_signal_contexts(contexts)

        self.assertEqual([item["symbol"] for item in result["signals"]], ["ETHUSDT", "BTCUSDT"])
        self.assertEqual([item["trade_type"] for item in result["signals"]], ["scalping", "intraday"])

    def test_opposite_active_profile_directions_block_execution(self) -> None:
        scalping = self._context("SOLUSDT", "scalping")''',
)
