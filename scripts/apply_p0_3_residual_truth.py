from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected anchor not found in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app/exchange_journal_backfill.py",
    '''            matched_record_keys = set(matched_close_sync.get("record_keys") or [])
            payload_record_keys = set(payload["exchange_metadata"]["close_sync"]["record_keys"])
            if (
                str(matched.get("status") or "").lower() == "closed"
                and payload_record_keys
                and payload_record_keys.issubset(matched_record_keys)
            ):
''',
    '''            matched_record_keys = set(matched_close_sync.get("record_keys") or [])
            payload_record_keys = set(payload["exchange_metadata"]["close_sync"]["record_keys"])
            matched_strategy = str(matched.get("strategy_name") or matched.get("strategy") or "").strip().lower()
            if (
                str(matched.get("status") or "").lower() == "closed"
                and matched_strategy not in {"", "unknown"}
                and payload_record_keys
                and payload_record_keys.issubset(matched_record_keys)
            ):
''',
)

replace_once(
    "app/exchange_journal_backfill.py",
    '''    return {
        "status": "closed",
        "result": payload.get("result"),
''',
    '''    return {
        "status": "closed",
        "strategy_name": payload.get("strategy_name") or "exchange_backfill",
        "result": payload.get("result"),
''',
)

replace_once(
    "tests/test_exchange_journal_backfill.py",
    '''        self.assertEqual(updates["status"], "closed")
        self.assertAlmostEqual(updates["realized_pnl"], 1.20)
''',
    '''        self.assertEqual(updates["status"], "closed")
        self.assertEqual(updates["strategy_name"], "exchange_backfill")
        self.assertAlmostEqual(updates["realized_pnl"], 1.20)
''',
)

replace_once(
    "tests/test_exchange_journal_backfill.py",
    '''    def test_repeated_run_skips_already_closed_record_keys_without_new_event(self) -> None:
''',
    '''    def test_closed_unknown_strategy_row_is_reclassified_before_idempotent_skip(self) -> None:
        existing = {
            "journal_id": "existing-unknown",
            "execution_key": "ledger-existing-unknown",
            "symbol": "ONDOUSDT",
            "direction": "long",
            "quantity": 10.0,
            "status": "closed",
            "strategy_name": "unknown",
            "exchange_metadata": {
                "close_sync": {"record_keys": ["id:open-1", "id:close-1", "id:close-2"]}
            },
        }
        persisted = {**existing, "strategy_name": "exchange_backfill"}
        with (
            patch("app.exchange_journal_backfill.get_trade_history", return_value=[existing]),
            patch("app.exchange_journal_backfill.update_trade_entry", return_value=persisted) as update_mock,
            patch("app.exchange_journal_backfill.append_trade_event") as event_mock,
            patch("app.exchange_journal_backfill.create_trade_entry") as create_mock,
        ):
            result = backfill_exchange_journal_lifecycle(
                FakeClient(),
                bdt_date="2026-07-16",
            )

        self.assertEqual(result["updated"], ["existing-unknown"])
        self.assertEqual(update_mock.call_args.args[1]["strategy_name"], "exchange_backfill")
        event_mock.assert_called_once()
        create_mock.assert_not_called()

    def test_repeated_run_skips_already_closed_record_keys_without_new_event(self) -> None:
''',
)

replace_once(
    "frontend/src/components/TradeHistory.tsx",
    '''  const outcome = deriveOutcome(pnlValue, item.result, isClosed);
  const strategy = String(financial.strategy_name || financial.strategy || metadata.strategy_name || metadata.strategy || "unknown");
  const leverage = nullableNumber(metadata.leverage ?? orderResponse.leverage ?? positionSnapshot.leverage);
  const executionKey = String(financial.execution_key || metadata.execution_key || "").trim() || null;
  const syncSource = String(closeSync.source || metadata.close_sync_source || "").trim() || null;
''',
    '''  const outcome = deriveOutcome(pnlValue, item.result, isClosed);
  const rawStrategy = String(financial.strategy_name || financial.strategy || metadata.strategy_name || metadata.strategy || "unknown");
  const leverage = nullableNumber(metadata.leverage ?? orderResponse.leverage ?? positionSnapshot.leverage);
  const executionKey = String(financial.execution_key || metadata.execution_key || "").trim() || null;
  const syncSource = String(closeSync.source || metadata.close_sync_source || "").trim() || null;
  const isExchangeBackfill =
    metadata.source === "exchange_transaction_log_backfill" ||
    syncSource === "bybit_account_transaction_log" ||
    String(financial.close_reason || "").toUpperCase() === "EXCHANGE_TRANSACTION_LOG_BACKFILL" ||
    String(item.journal_id || "").startsWith("exchange-ledger-") ||
    Boolean(executionKey?.startsWith("ledger-"));
  const strategy = rawStrategy.toLowerCase() === "unknown" && isExchangeBackfill ? "exchange_backfill" : rawStrategy;
''',
)

replace_once(
    "frontend/src/components/TradeHistory.tsx",
    '''  const missingClosedEvidence = isClosed && (exitValue === null || pnlValue === null || feesValue === null);
  const needsAttention =
    ["FAILED", "UNCERTAIN", "UNKNOWN"].includes(status) ||
    (isClosed && outcome === "UNKNOWN") ||
    missingClosedEvidence ||
    strategy.toLowerCase() === "unknown" ||
    (!item.order_id && !adoptedPosition);
''',
    '''  const missingClosedEvidence = isClosed && (exitValue === null || pnlValue === null || feesValue === null);
  const exactExchangeCloseComplete =
    isExchangeBackfill &&
    isClosed &&
    exitValue !== null &&
    pnlValue !== null &&
    feesValue !== null &&
    Boolean(syncSource);
  const needsAttention =
    ["FAILED", "UNCERTAIN", "UNKNOWN"].includes(status) ||
    (isClosed && outcome === "UNKNOWN") ||
    missingClosedEvidence ||
    (!isExchangeBackfill && strategy.toLowerCase() === "unknown") ||
    (!item.order_id && !adoptedPosition && !exactExchangeCloseComplete);
''',
)

replace_once(
    "frontend/src/components/TradeHistory.tsx",
    '''    rrValue: calcRr(entryPrice, stopLoss, takeProfit),
''',
    '''    rrValue: protectionAttached === true ? calcRr(entryPrice, stopLoss, takeProfit) : null,
''',
)

replace_once(
    "frontend/src/components/TradeHistory.tsx",
    '''        <DetailMetric label="Entry" value={formatMoney(trade.entryPrice)} />
        <DetailMetric label="Stop Loss" value={formatMoney(trade.stopLoss)} tone="bad" />
        <DetailMetric label="Take Profit" value={formatMoney(trade.takeProfit)} tone="good" />
        <DetailMetric label="Exit" value={formatMoney(trade.exitValue)} />
''',
    '''        <DetailMetric label="Entry" value={formatMoney(trade.entryPrice)} />
        <DetailMetric label="Stop Loss" value={trade.protectionAttached === true ? formatMoney(trade.stopLoss) : "N/A"} tone="bad" />
        <DetailMetric label="Take Profit" value={trade.protectionAttached === true ? formatMoney(trade.takeProfit) : "N/A"} tone="good" />
        <DetailMetric label="Exit" value={formatMoney(trade.exitValue)} />
''',
)
