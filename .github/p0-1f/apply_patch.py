from pathlib import Path

root = Path("frontend/src/components")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {text.count(old)}")
    return text.replace(old, new, 1)


# Trade History: retain all existing filters, export, timeline and detail views.
p = root / "TradeHistory.tsx"
s = p.read_text()
s = replace_once(s, '  execution_key?: string | null;\n};', '  execution_key?: string | null;\n  counts_as_trade?: boolean;\n  trade_count_reason?: string | null;\n  performance_eligible?: boolean;\n  performance_exclusion_reason?: string | null;\n  financial_reconciliation_status?: string | null;\n  financial_truth_source?: string | null;\n};', "TradeHistory type")
s = replace_once(s, '  const executionFailedBeforeOrder =\n    String(item.result || "").toLowerCase() === "execution_failed" &&\n    !item.order_id &&\n    !openedAt;', '  const executionFailedBeforeOrder =\n    String(item.result || "").toLowerCase() === "execution_failed" &&\n    !item.order_id &&\n    !openedAt;\n  const backendCountsAsTrade = financial.counts_as_trade === true;\n  const backendPerformanceEligible = financial.performance_eligible === true;\n  const performanceExclusionReason = String(financial.performance_exclusion_reason || "").trim() || null;', "TradeHistory truth")
s = replace_once(s, '  const needsAttention =\n    !executionFailedBeforeOrder && (', '  const needsAttention =\n    !executionFailedBeforeOrder && (\n    (isClosed && !backendPerformanceEligible) ||', "TradeHistory attention")
s = replace_once(s, '    syncSource ? `Close PnL source: ${syncSource}` : "Close PnL source unavailable.",', '    syncSource ? `Close PnL source: ${syncSource}` : "Close PnL source unavailable.",\n    `Trade count authority: ${backendCountsAsTrade ? "COUNTED" : "EXCLUDED"}${financial.trade_count_reason ? ` (${financial.trade_count_reason})` : ""}`,\n    `Performance authority: ${backendPerformanceEligible ? "ELIGIBLE" : `EXCLUDED${performanceExclusionReason ? ` (${performanceExclusionReason})` : ""}`}`,', "TradeHistory timeline")
s = replace_once(s, '    countsAsTrade: !executionFailedBeforeOrder,', '    countsAsTrade: backendCountsAsTrade,', "TradeHistory count")
s = replace_once(s, '    countsAsTrade: true,', '    countsAsTrade: false,', "TradeHistory fallback")
p.write_text(s)

# Performance: preserve all existing charts and diagnostics, but calculate from eligible closes only.
p = root / "PerformanceStrategy.tsx"
s = p.read_text()
s = replace_once(s, '  close_reason?: string | null;\n};', '  close_reason?: string | null;\n  performance_eligible?: boolean;\n  performance_exclusion_reason?: string | null;\n};', "Performance type")
s = replace_once(s, '  pnlKnown: boolean;\n};', '  pnlKnown: boolean;\n  performanceEligible: boolean;\n};', "Performance row type")
s = replace_once(s, '    pnlKnown,\n  };', '    pnlKnown,\n    performanceEligible: financial.performance_eligible === true,\n  };', "Performance journal row")
s = replace_once(s, '      pnlKnown: trade.result === "PROFIT" || trade.result === "LOSS" || numberValue(trade.pnl) !== 0,\n    }));', '      pnlKnown: trade.result === "PROFIT" || trade.result === "LOSS" || numberValue(trade.pnl) !== 0,\n      performanceEligible: false,\n    }));', "Performance fallback")
s = replace_once(s, '  const closedRows = rows.filter((row) => String(row.tradeStatus || row.status).toLowerCase() === "closed" || row.status === "CLOSED");', '  const eligibleRows = rows.filter((row) => row.performanceEligible);\n  const closedRows = eligibleRows.filter((row) => String(row.tradeStatus || row.status).toLowerCase() === "closed" || row.status === "CLOSED");', "Performance eligible")
s = replace_once(s, '  const totalTrades = rows.length;', '  const totalTrades = eligibleRows.length;', "Performance total")
s = replace_once(s, '  const rrValues = rows.map((row) => row.rrValue)', '  const rrValues = eligibleRows.map((row) => row.rrValue)', "Performance RR")
for index in range(3):
    s = replace_once(s, '    rows.reduce((map, row) => {', '    eligibleRows.reduce((map, row) => {', f"Performance reducer {index + 1}")
p.write_text(s)

# Active Trades: preserve the original position table and controls; use eligible Journal rows for daily close counts.
p = root / "ActiveTrades.tsx"
s = p.read_text()
s = replace_once(s, 'import { AccountResponse, Trade, TradeHistoryEntry } from "../types";', 'import { AccountResponse, JournalTradeEntry, Trade, TradeHistoryEntry } from "../types";', "ActiveTrades import")
s = replace_once(s, 'type LiveTrade = Trade & {\n  liveMetricsAvailable?: boolean;\n  closeAllowed?: boolean;\n  closeBlockedReason?: string | null;\n  liquidationPrice?: number | null;\n  positionValue?: number | null;\n};', 'type LiveTrade = Trade & {\n  liveMetricsAvailable?: boolean;\n  closeAllowed?: boolean;\n  closeBlockedReason?: string | null;\n  liquidationPrice?: number | null;\n  positionValue?: number | null;\n};\n\ntype TruthJournalTrade = JournalTradeEntry & {\n  realized_pnl?: number | null;\n  performance_eligible?: boolean;\n};', "ActiveTrades type")
s = replace_once(s, '  const [reportedRealized, setReportedRealized] = useState<number | null>(null);\n\n  const todayClosedTrades = useMemo(() => tradeHistory.filter((trade) => isTodayInBdt(trade.closedAt)), [tradeHistory]);', '  const [reportedRealized, setReportedRealized] = useState<number | null>(null);\n  const [reconciledClosedTrades, setReconciledClosedTrades] = useState<TruthJournalTrade[]>([]);\n\n  const todayClosedTrades = useMemo(\n    () => reconciledClosedTrades.filter((trade) => trade.performance_eligible === true && isTodayInBdt(trade.closed_at)),\n    [reconciledClosedTrades],\n  );', "ActiveTrades rows")
s = replace_once(s, '  const todaysSlHit = todayClosedTrades.filter((trade) => trade.result === "LOSS").length;\n  const todaysTpHit = todayClosedTrades.filter((trade) => trade.result === "PROFIT").length;\n  const closedOnlyRealized = todayClosedTrades.reduce((sum, trade) => sum + numberValue(trade.pnl), 0);', '  const todaysSlHit = todayClosedTrades.filter((trade) => numberValue(trade.realized_pnl) < 0).length;\n  const todaysTpHit = todayClosedTrades.filter((trade) => numberValue(trade.realized_pnl) > 0).length;\n  const closedOnlyRealized = todayClosedTrades.reduce((sum, trade) => sum + numberValue(trade.realized_pnl), 0);', "ActiveTrades outcomes")
s = replace_once(s, '        const response = (await api.getMetrics(authToken)) as { today_realized_pnl?: number };\n        const value = Number(response.today_realized_pnl);\n        if (!cancelled) setReportedRealized(Number.isFinite(value) ? value : null);', '        const [response, journal] = await Promise.all([\n          api.getMetrics(authToken),\n          api.getJournalTrades(authToken),\n        ]);\n        const value = Number(response.today_realized_pnl);\n        if (!cancelled) {\n          setReportedRealized(Number.isFinite(value) ? value : null);\n          setReconciledClosedTrades((journal.trades || []) as TruthJournalTrade[]);\n        }', "ActiveTrades fetch")
p.write_text(s)

print("P0-1F feature-preserving UI patches applied")
