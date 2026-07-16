from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"anchor not found in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/exchange_journal_backfill.py",
    '''        if not symbol or role is None or side is None or qty is None or qty <= 0 or event_ms is None:\n            continue\n\n        state = states.get(symbol)\n        if role == "open":\n''',
    '''        if not symbol or side is None or qty is None or qty <= 0 or event_ms is None:\n            continue\n\n        state = states.get(symbol)\n        if role is None:\n            if state is None:\n                cash_flow = _number(record.get("cashFlow"))\n                if cash_flow is not None and abs(cash_flow) > 1e-12:\n                    pending.append({\n                        "symbol": symbol,\n                        "error": "plain-side close row has no same-day open lifecycle",\n                    })\n                    continue\n                role = "open"\n            else:\n                expected_open_side = "buy" if state["direction"] == "long" else "sell"\n                role = "open" if side == expected_open_side else "close"\n\n        if role == "open":\n''',
)

replace_once(
    "app/exchange_journal_backfill.py",
    '''    if normalized in {"close sell", "sell close"}:\n        return "close", "sell"\n    return None, None\n''',
    '''    if normalized in {"close sell", "sell close"}:\n        return "close", "sell"\n    if normalized == "buy":\n        return None, "buy"\n    if normalized == "sell":\n        return None, "sell"\n    return None, None\n''',
)

replace_once(
    "tests/test_exchange_journal_backfill.py",
    '''def records() -> list[dict]:\n    return [\n''',
    '''def records() -> list[dict]:\n    return [\n''',
)

replace_once(
    "tests/test_exchange_journal_backfill.py",
    '''    ]\n\n\nclass FakeClient:\n''',
    '''    ]\n\n\ndef plain_side_records() -> list[dict]:\n    payload = [dict(record) for record in records()]\n    payload[0]["direction"] = "Buy"\n    payload[1]["direction"] = "Sell"\n    payload[2]["direction"] = "Sell"\n    return payload\n\n\nclass FakeClient:\n''',
)

replace_once(
    "tests/test_exchange_journal_backfill.py",
    '''    def test_existing_recovered_open_row_is_finalized_not_duplicated(self) -> None:\n''',
    '''    def test_plain_buy_sell_rows_are_classified_from_lifecycle_sequence(self) -> None:\n        with (\n            patch("app.exchange_journal_backfill.get_trade_history", return_value=[]),\n            patch("app.exchange_journal_backfill.get_trade_by_execution_key", return_value=None),\n            patch("app.exchange_journal_backfill.create_trade_entry", side_effect=lambda value: value) as create_mock,\n        ):\n            result = backfill_exchange_journal_lifecycle(\n                FakeClient(plain_side_records()),\n                bdt_date="2026-07-16",\n            )\n\n        self.assertTrue(result["ok"])\n        self.assertEqual(result["pending"], [])\n        create_mock.assert_called_once()\n        payload = create_mock.call_args.args[0]\n        self.assertEqual(payload["direction"], "long")\n        self.assertEqual(payload["status"], "closed")\n        self.assertAlmostEqual(payload["realized_pnl"], 1.20)\n        self.assertAlmostEqual(payload["fees"], 0.20)\n\n    def test_plain_side_close_without_open_is_not_fabricated(self) -> None:\n        orphan = [dict(records()[1])]\n        orphan[0]["direction"] = "Sell"\n        with (\n            patch("app.exchange_journal_backfill.get_trade_history", return_value=[]),\n            patch("app.exchange_journal_backfill.create_trade_entry") as create_mock,\n        ):\n            result = backfill_exchange_journal_lifecycle(\n                FakeClient(orphan),\n                bdt_date="2026-07-16",\n            )\n\n        self.assertTrue(result["ok"])\n        self.assertIn("no same-day open lifecycle", result["pending"][0]["error"])\n        create_mock.assert_not_called()\n\n    def test_existing_recovered_open_row_is_finalized_not_duplicated(self) -> None:\n''',
)
