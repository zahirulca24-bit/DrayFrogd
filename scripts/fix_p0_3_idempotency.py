from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"anchor not found in {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/exchange_journal_backfill.py",
    '''        if matched is not None:\n            journal_id = str(matched.get("journal_id") or "")\n            persisted = update_trade_entry(journal_id, _close_updates(payload)) if journal_id else None\n''',
    '''        if matched is not None:\n            journal_id = str(matched.get("journal_id") or "")\n            matched_metadata = matched.get("exchange_metadata") if isinstance(matched.get("exchange_metadata"), dict) else {}\n            matched_close_sync = matched_metadata.get("close_sync") if isinstance(matched_metadata.get("close_sync"), dict) else {}\n            matched_record_keys = set(matched_close_sync.get("record_keys") or [])\n            payload_record_keys = set(payload["exchange_metadata"]["close_sync"]["record_keys"])\n            if (\n                str(matched.get("status") or "").lower() == "closed"\n                and payload_record_keys\n                and payload_record_keys.issubset(matched_record_keys)\n            ):\n                skipped.append(journal_id or str(payload["journal_id"]))\n                states.pop(symbol, None)\n                continue\n            persisted = update_trade_entry(journal_id, _close_updates(payload)) if journal_id else None\n''',
)

replace_once(
    "tests/test_exchange_journal_backfill.py",
    '''    def test_repeated_run_skips_stable_execution_key(self) -> None:\n        existing = {"journal_id": "existing", "execution_key": "ledger-existing"}\n        with (\n            patch("app.exchange_journal_backfill.get_trade_history", return_value=[]),\n            patch("app.exchange_journal_backfill.get_trade_by_execution_key", return_value=existing),\n            patch("app.exchange_journal_backfill.create_trade_entry") as create_mock,\n        ):\n            result = backfill_exchange_journal_lifecycle(\n                FakeClient(),\n                bdt_date="2026-07-16",\n            )\n\n        self.assertEqual(result["skipped"], ["existing"])\n        create_mock.assert_not_called()\n''',
    '''    def test_repeated_run_skips_already_closed_record_keys_without_new_event(self) -> None:\n        existing = {\n            "journal_id": "existing",\n            "execution_key": "ledger-existing",\n            "symbol": "ONDOUSDT",\n            "direction": "long",\n            "quantity": 10.0,\n            "status": "closed",\n            "exchange_metadata": {\n                "close_sync": {"record_keys": ["id:open-1", "id:close-1", "id:close-2"]}\n            },\n        }\n        with (\n            patch("app.exchange_journal_backfill.get_trade_history", return_value=[existing]),\n            patch("app.exchange_journal_backfill.update_trade_entry") as update_mock,\n            patch("app.exchange_journal_backfill.append_trade_event") as event_mock,\n            patch("app.exchange_journal_backfill.create_trade_entry") as create_mock,\n        ):\n            result = backfill_exchange_journal_lifecycle(\n                FakeClient(),\n                bdt_date="2026-07-16",\n            )\n\n        self.assertEqual(result["skipped"], ["existing"])\n        update_mock.assert_not_called()\n        event_mock.assert_not_called()\n        create_mock.assert_not_called()\n''',
)
