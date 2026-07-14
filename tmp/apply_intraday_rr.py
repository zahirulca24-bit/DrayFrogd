from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one source block in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


signal_path = Path("app/signal_pipeline.py")
replace_once(
    signal_path,
    "from app.strategy import evaluate_registered_strategies\n",
    "from app.strategy import evaluate_registered_strategies\n"
    "from app.trade_management_profiles import TRADE_MANAGEMENT_PROFILES, price_at_r\n",
)
replace_once(
    signal_path,
    '        "take_profit": result.get("take_profit"),\n'
    '        "risk_reward": result.get("risk_reward"),\n',
    '        "take_profit": result.get("take_profit"),\n'
    '        "strategy_take_profit": result.get("take_profit"),\n'
    '        "risk_reward": result.get("risk_reward"),\n'
    '        "strategy_risk_reward": result.get("risk_reward"),\n'
    '        "target_authority": "strategy_output",\n',
)
replace_once(
    signal_path,
    "        _apply_structure_gate(normalized, scanner_logic)\n\n"
    "    geometry_valid = _valid_trade_geometry(normalized)\n",
    "        _apply_structure_gate(normalized, scanner_logic)\n\n"
    "    _apply_profile_target(normalized)\n\n"
    "    geometry_valid = _valid_trade_geometry(normalized)\n",
)
helper = '''def _apply_profile_target(item: dict[str, Any]) -> None:\n    \"\"\"Use the approved trade-management profile as canonical TP authority.\n\n    Strategies identify the setup, direction, entry and structural stop. The\n    selected Scalping/Intraday profile owns the executable reward target. Raw\n    strategy TP/RR values remain persisted separately for audit evidence.\n    \"\"\"\n\n    if item.get(\"signal_state\") not in USEFUL_SIGNAL_STATES:\n        return\n\n    trade_type = _normalize_trade_type(item.get(\"trade_type\"))\n    direction = _normalize_direction(item.get(\"direction\"))\n    entry = _number(item.get(\"entry\"))\n    stop_loss = _number(item.get(\"stop_loss\"))\n    if trade_type is None or direction is None or entry is None or stop_loss is None:\n        return\n    if direction == \"long\" and not stop_loss < entry:\n        return\n    if direction == \"short\" and not entry < stop_loss:\n        return\n\n    profile = TRADE_MANAGEMENT_PROFILES.get(trade_type) or {}\n    target_r = _number(profile.get(\"tp1_r\"))\n    if target_r is None or target_r <= 0:\n        return\n\n    item[\"take_profit\"] = price_at_r(entry, stop_loss, direction, target_r)\n    item[\"risk_reward\"] = target_r\n    item[\"profile_target_r\"] = target_r\n    item[\"target_authority\"] = \"trade_management_profile\"\n\n\n'''
replace_once(
    signal_path,
    "def _valid_trade_geometry(item: dict[str, Any]) -> bool:\n",
    helper + "def _valid_trade_geometry(item: dict[str, Any]) -> bool:\n",
)


test_path = Path("tests/test_signal_pipeline.py")
old_test = '''    def test_intraday_requires_two_r_minimum(self) -> None:\n        raw = self._raw_signal(status=\"active\")\n        raw[\"risk_reward\"] = 1.5\n        result = normalize_strategy_result(\n            symbol=\"BTCUSDT\",\n            result=raw,\n            trade_type=\"intraday\",\n            market_rank=1,\n            trend=self._trend(\"UPTREND\"),\n            market_ranking={\"score\": 90.0, \"components\": {}},\n            scanner_logic={\"status\": \"active\", \"direction\": \"long\"},\n        )\n\n        self.assertEqual(result[\"signal_state\"], SIGNAL_INVALID)\n        self.assertEqual(result[\"rejection_reason\"], \"risk_reward_below_trade_type_minimum\")\n        self.assertFalse(result[\"is_executable\"])\n\n'''
new_test = '''    def test_intraday_profile_retargets_current_strategy_to_two_r(self) -> None:\n        raw = self._raw_signal(status=\"active\")\n        raw[\"take_profit\"] = 101.5\n        raw[\"risk_reward\"] = 1.5\n        result = normalize_strategy_result(\n            symbol=\"BTCUSDT\",\n            result=raw,\n            trade_type=\"intraday\",\n            market_rank=1,\n            trend=self._trend(\"UPTREND\"),\n            market_ranking={\"score\": 90.0, \"components\": {}},\n            scanner_logic={\"status\": \"active\", \"direction\": \"long\"},\n        )\n\n        self.assertEqual(result[\"signal_state\"], SIGNAL_ACTIVE)\n        self.assertTrue(result[\"is_executable\"])\n        self.assertEqual(result[\"take_profit\"], 102.0)\n        self.assertEqual(result[\"risk_reward\"], 2.0)\n        self.assertEqual(result[\"strategy_take_profit\"], 101.5)\n        self.assertEqual(result[\"strategy_risk_reward\"], 1.5)\n        self.assertEqual(result[\"target_authority\"], \"trade_management_profile\")\n\n    def test_scalping_profile_remains_one_point_five_r(self) -> None:\n        result = normalize_strategy_result(\n            symbol=\"BTCUSDT\",\n            result=self._raw_signal(status=\"active\"),\n            trade_type=\"scalping\",\n            market_rank=1,\n            trend=self._trend(\"UPTREND\"),\n            market_ranking={\"score\": 90.0, \"components\": {}},\n            scanner_logic={\"status\": \"eligible\", \"direction\": \"long\"},\n        )\n\n        self.assertEqual(result[\"signal_state\"], SIGNAL_ACTIVE)\n        self.assertEqual(result[\"take_profit\"], 101.5)\n        self.assertEqual(result[\"risk_reward\"], 1.5)\n        self.assertEqual(result[\"strategy_take_profit\"], 102.0)\n        self.assertEqual(result[\"strategy_risk_reward\"], 2.0)\n\n    def test_intraday_short_profile_retargets_to_two_r(self) -> None:\n        raw = self._raw_signal(direction=\"short\", status=\"active\")\n        raw[\"take_profit\"] = 98.5\n        raw[\"risk_reward\"] = 1.5\n        result = normalize_strategy_result(\n            symbol=\"BTCUSDT\",\n            result=raw,\n            trade_type=\"intraday\",\n            market_rank=1,\n            trend=self._trend(\"DOWNTREND\"),\n            market_ranking={\"score\": 90.0, \"components\": {}},\n            scanner_logic={\"status\": \"active\", \"direction\": \"short\"},\n        )\n\n        self.assertEqual(result[\"signal_state\"], SIGNAL_ACTIVE)\n        self.assertTrue(result[\"is_executable\"])\n        self.assertEqual(result[\"take_profit\"], 98.0)\n        self.assertEqual(result[\"risk_reward\"], 2.0)\n\n'''
replace_once(test_path, old_test, new_test)
