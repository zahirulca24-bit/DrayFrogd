from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"Expected one match in {path}: {old[:80]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "tests/test_position_sizing.py",
    '''        self.assertEqual(result["quantity"], "1.958")\n        self.assertAlmostEqual(result["risk_amount"], 9.9999955)\n        self.assertAlmostEqual(result["price_risk_amount"], 9.79)\n        self.assertAlmostEqual(result["estimated_round_trip_fees"], 0.2099955)\n        self.assertAlmostEqual(result["notional"], 195.8)\n''',
    '''        self.assertEqual(result["quantity"], "1.748")\n        self.assertAlmostEqual(result["target_risk_amount"], 10.0)\n        self.assertAlmostEqual(result["execution_risk_budget"], 9.0)\n        self.assertAlmostEqual(result["risk_amount"], 8.995645)\n        self.assertAlmostEqual(result["price_risk_amount"], 8.74)\n        self.assertAlmostEqual(result["estimated_round_trip_fees"], 0.187473)\n        self.assertAlmostEqual(result["notional"], 174.8)\n''',
)

replace_once(
    "tests/test_position_sizing.py",
    '''        self.assertEqual(result["quantity"], "40.4")\n        self.assertAlmostEqual(result["risk_amount"], 19.973, places=3)\n        self.assertAlmostEqual(result["price_risk_amount"], 16.564, places=3)\n        self.assertAlmostEqual(result["estimated_round_trip_fees"], 3.409, places=3)\n        self.assertAlmostEqual(result["notional"], 3090.60, places=2)\n        self.assertEqual(result["selected_leverage"], 20.0)\n        self.assertAlmostEqual(result["required_margin"], 154.53, places=4)\n        self.assertLess(result["trade_margin_utilization"], 0.32)\n        self.assertGreater(result["remaining_margin_capacity"], 145.0)\n''',
    '''        self.assertEqual(result["quantity"], "34.2")\n        self.assertAlmostEqual(result["target_risk_amount"], 20.0)\n        self.assertAlmostEqual(result["execution_risk_budget"], 18.0)\n        self.assertAlmostEqual(result["risk_amount"], 17.9569665, places=6)\n        self.assertAlmostEqual(result["price_risk_amount"], 14.022, places=3)\n        self.assertAlmostEqual(result["estimated_round_trip_fees"], 2.8856421, places=6)\n        self.assertAlmostEqual(result["notional"], 2616.30, places=2)\n        self.assertEqual(result["selected_leverage"], 20.0)\n        self.assertAlmostEqual(result["required_margin"], 130.815, places=4)\n        self.assertLess(result["trade_margin_utilization"], 0.23)\n        self.assertGreater(result["remaining_margin_capacity"], 169.0)\n''',
)

replace_once(
    "tests/test_position_sizing.py",
    '        self.assertEqual(result["quantity"], "1.955")\n',
    '        self.assertEqual(result["quantity"], "1.746")\n        self.assertAlmostEqual(result["execution_risk_budget"], 9.0)\n',
)

replace_once(
    "tests/test_position_sizing.py",
    '''        self.assertEqual(result["quantity"], "3751")\n        self.assertLessEqual(result["risk_amount"], 20.0)\n        self.assertAlmostEqual(result["price_risk_amount"], 16.8795, places=4)\n        self.assertAlmostEqual(result["estimated_round_trip_fees"], 3.1179, places=4)\n''',
    '''        self.assertEqual(result["quantity"], "3195")\n        self.assertAlmostEqual(result["target_risk_amount"], 20.0)\n        self.assertAlmostEqual(result["execution_risk_budget"], 18.0)\n        self.assertLessEqual(result["risk_amount"], 18.0)\n        self.assertAlmostEqual(result["price_risk_amount"], 14.3775, places=4)\n        self.assertAlmostEqual(result["estimated_round_trip_fees"], 2.655731925, places=6)\n''',
)

replace_once(
    "tests/test_risk_authority.py",
    '''        self.assertAlmostEqual(result["risk_amount"], 19.9989457)\n        self.assertAlmostEqual(result["price_risk_amount"], 18.026)\n        self.assertAlmostEqual(result["estimated_round_trip_fees"], 1.9729457)\n        self.assertAlmostEqual(result["notional"], 1802.6)\n        self.assertAlmostEqual(result["minimum_required_leverage"], 3.6052)\n        self.assertAlmostEqual(result["selected_leverage"], 20.0)\n        self.assertAlmostEqual(result["required_margin"], 90.13)\n        self.assertAlmostEqual(result["trade_margin_utilization"], 0.09013)\n        self.assertAlmostEqual(result["remaining_margin_capacity"], 409.87)\n''',
    '''        self.assertAlmostEqual(result["target_risk_amount"], 20.0)\n        self.assertAlmostEqual(result["execution_risk_budget"], 18.0)\n        self.assertAlmostEqual(result["risk_amount"], 17.9995535)\n        self.assertAlmostEqual(result["price_risk_amount"], 15.662)\n        self.assertAlmostEqual(result["estimated_round_trip_fees"], 1.7142059)\n        self.assertAlmostEqual(result["notional"], 1566.2)\n        self.assertAlmostEqual(result["minimum_required_leverage"], 3.1324)\n        self.assertAlmostEqual(result["selected_leverage"], 20.0)\n        self.assertAlmostEqual(result["required_margin"], 78.31)\n        self.assertAlmostEqual(result["trade_margin_utilization"], 0.07831)\n        self.assertAlmostEqual(result["remaining_margin_capacity"], 421.69)\n''',
)
