import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, BarChart3, LineChart, ShieldAlert, Target } from "lucide-react";
import { api } from "../api";
import { JournalTradeEntry, MetricsResponse, StrategyAuditResponse, TradeHistoryEntry } from "../types";
import { normalizeTrade, normalizeTradeHistoryEntry } from "../tradeTruth";

interface PerformanceStrategyProps {
  authToken: string | null;
  history: TradeHistoryEntry[];
  metrics: MetricsResponse;
}

type FinancialJournalTrade = JournalTradeEntry & {
  strategy_name?: string | null;
  strategy?: string | null;
  exit_price?: number | null;
  realized_pnl?: number | null;
  fees?: number | null;
  close_reason?: string | null;
};

type PerformanceRow = TradeHistoryEntry & {
  tradeStatus: string;
  strategy: string;
  symbol: string;
  session: "Asia" | "Europe" | "US" | "Late";
  rrValue: number | null;
  pnlKnown: boolean;
};

const BDT_DATE = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Dhaka",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const BDT_DATE_TIME = new Intl.DateTimeFormat("en-BD", {
  timeZone: "Asia/Dhaka",
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: true,
});

function numberValue(value: unknown) {
  const numeric = Number(value || 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function nullableNumber(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function formatMoney(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "N/A";
  }
  return `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "N/A";
  }
  return `${(value * 100).toFixed(2)}%`;
}

function calcRr(entry: number, stop: number, takeProfit: number) {
  const risk = Math.abs(entry - stop);
  const reward = Math.abs(takeProfit - entry);
  if (risk <= 0 || reward <= 0) {
    return null;
  }
  return reward / risk;
}

function getSession(value?: string | null): "Asia" | "Europe" | "US" | "Late" {
  if (!value) {
    return "Late";
  }
  const hour = Number(new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Dhaka", hour: "2-digit", hour12: false }).format(new Date(value)));
  if (hour >= 6 && hour < 12) {
    return "Asia";
  }
  if (hour >= 12 && hour < 17) {
    return "Europe";
  }
  if (hour >= 17 && hour < 23) {
    return "US";
  }
  return "Late";
}

function computeProfitFactor(rows: PerformanceRow[]) {
  const validPnlRows = rows.filter((row) => row.pnl !== null);
  const gains = validPnlRows.filter((row) => (row.pnl ?? 0) > 0).reduce((sum, row) => sum + (row.pnl ?? 0), 0);
  const losses = Math.abs(validPnlRows.filter((row) => (row.pnl ?? 0) < 0).reduce((sum, row) => sum + (row.pnl ?? 0), 0));
  if (losses === 0) {
    return gains > 0 ? Infinity : null;
  }
  return gains / losses;
}

function computeMaxDrawdown(rows: PerformanceRow[]) {
  const validPnlRows = rows.filter((row) => row.pnl !== null);
  let equity = 0;
  let peak = 0;
  let maxDrawdown = 0;
  validPnlRows.forEach((row) => {
    equity += row.pnl ?? 0;
    peak = Math.max(peak, equity);
    maxDrawdown = Math.max(maxDrawdown, peak - equity);
  });
  return maxDrawdown;
}

function toBdtDate(value?: string | null) {
  return value ? BDT_DATE.format(new Date(value)) : "N/A";
}

function classifyOutcome(realizedPnl: number | null, rawResult: string) {
  if (realizedPnl !== null) {
    if (realizedPnl > 0) return "PROFIT";
    if (realizedPnl < 0) return "LOSS";
  }

  if (rawResult === "tp" || rawResult === "profit") return "PROFIT";
  if (rawResult === "sl" || rawResult === "loss") return "LOSS";
  return "UNKNOWN";
}

function deriveLossReason(item: JournalTradeEntry, outcome: "PROFIT" | "LOSS" | "UNKNOWN") {
  if (outcome !== "LOSS") {
    return null;
  }

  const financial = item as FinancialJournalTrade;
  const slReason = String(item.sl_hit_reason || "").trim();
  if (slReason) {
    return slReason;
  }

  const closeReason = String(financial.close_reason || "").trim().toUpperCase();
  if (!closeReason) {
    return "UNKNOWN_LOSS_EXIT";
  }

  if (closeReason === "EXCHANGE_CLOSED_PNL") return "STOP_LOSS_OR_PROTECTIVE_CLOSE";
  if (closeReason === "MAX_HOLD_TIME") return "MAX_HOLD_TIME";
  if (closeReason === "MOMENTUM_FAILED") return "MOMENTUM_FAILED";
  if (closeReason === "MANUAL_MARKET_CLOSE") return "MANUAL_MARKET_CLOSE";
  if (closeReason === "ORDER_NOT_ACCEPTED") return "ORDER_NOT_ACCEPTED";
  return closeReason;
}

function journalToPerformanceRow(item: JournalTradeEntry, index: number): PerformanceRow {
  const normTrade = normalizeTrade(item, index);
  const historyEntry = normalizeTradeHistoryEntry(normTrade);

  const isClosed = normTrade.status === "CLOSED";
  const pnlKnown = isClosed && normTrade.realizedPnl !== null;
  const closedAt = normTrade.closedAt || normTrade.timestamp || new Date().toISOString();
  const rawResult = String(item.result || "").toLowerCase();
  const outcome = classifyOutcome(normTrade.realizedPnl, rawResult);
  const lossReason = deriveLossReason(item, outcome);

  return {
    ...historyEntry,
    id: normTrade.id,
    pair: normTrade.pair,
    strategy: normTrade.strategy,
    direction: normTrade.direction,
    entryPrice: normTrade.entryPrice,
    currentPrice: normTrade.currentPrice,
    stopLoss: normTrade.stopLoss,
    takeProfit: normTrade.takeProfit,
    size: normTrade.size,
    margin: normTrade.margin,
    leverage: normTrade.leverage,
    unrealizedPnl: normTrade.unrealizedPnl,
    pnlPercent: normTrade.pnlPercent,
    status: normTrade.status,
    timestamp: normTrade.timestamp,
    orderConfirmed: normTrade.orderConfirmed,
    rawStatus: normTrade.rawStatus,
    journalId: normTrade.journalId,
    executionMode: normTrade.executionMode,
    exitPrice: normTrade.exitPrice,
    pnl: historyEntry.pnl,
    result: outcome as TradeHistoryEntry["result"],
    reason: lossReason || normTrade.closeReason || normTrade.slHitReason || (isClosed ? "unknown" : "open"),
    closedAt,
    tradeStatus: normTrade.rawStatus || (isClosed ? "closed" : "active"),
    symbol: normTrade.pair,
    session: getSession(closedAt),
    rrValue: calcRr(normTrade.entryPrice, normTrade.stopLoss, normTrade.takeProfit),
    pnlKnown,
  };
}

export default function PerformanceStrategy({ authToken, history, metrics }: PerformanceStrategyProps) {
  const [journalTrades, setJournalTrades] = useState<JournalTradeEntry[]>([]);
  const [strategyAudit, setStrategyAudit] = useState<StrategyAuditResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const bdtDayRef = useRef(BDT_DATE.format(new Date()));

  useEffect(() => {
    if (!authToken) {
      return;
    }
    let cancelled = false;

    const loadJournal = async () => {
      try {
        const [response, auditResponse] = await Promise.all([
          api.getJournalTrades(authToken),
          api.getStrategyAudit(authToken, bdtDayRef.current),
        ]);
        if (!cancelled) {
          setJournalTrades(response.trades || []);
          setStrategyAudit(auditResponse);
          setError(null);
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(err?.message || "Failed to load persisted journal data");
        }
      }
    };

    loadJournal();
    const interval = setInterval(() => {
      const current = BDT_DATE.format(new Date());
      if (current !== bdtDayRef.current) {
        bdtDayRef.current = current;
      }
      void loadJournal();
    }, 10000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [authToken]);

  const rows = useMemo<PerformanceRow[]>(() => {
    if (journalTrades.length > 0) {
      return journalTrades.map(journalToPerformanceRow);
    }

    return history.map((trade, index) => {
      const normTrade = normalizeTrade(trade, index);
      const historyEntry = normalizeTradeHistoryEntry(normTrade);
      const isClosed = normTrade.status === "CLOSED";
      const pnlKnown = isClosed && normTrade.realizedPnl !== null;
      return {
        ...historyEntry,
        tradeStatus: normTrade.rawStatus || (isClosed ? "closed" : "active"),
        strategy: normTrade.strategy || "unknown",
        symbol: normTrade.pair,
        session: getSession(normTrade.closedAt),
        rrValue: calcRr(normTrade.entryPrice, normTrade.stopLoss, normTrade.takeProfit),
        pnlKnown,
      };
    });
  }, [history, journalTrades]);

  const closedRows = rows.filter((row) => String(row.tradeStatus || row.status).toLowerCase() === "closed" || row.status === "CLOSED");
  const knownClosedRows = closedRows.filter((row) => row.result === "PROFIT" || row.result === "LOSS");
  const knownPnlClosedRows = closedRows.filter((row) => row.pnl !== null);
  const openRows = rows.filter((row) => !closedRows.includes(row));

  const totalTrades = rows.length;
  const winTrades = knownClosedRows.filter((row) => row.result === "PROFIT").length;
  const lossTrades = knownClosedRows.filter((row) => row.result === "LOSS").length;
  const winRate = knownClosedRows.length > 0 ? winTrades / knownClosedRows.length : null;
  const netPnl = knownPnlClosedRows.length > 0 ? knownPnlClosedRows.reduce((sum, row) => sum + (row.pnl ?? 0), 0) : null;
  const profitFactor = knownClosedRows.length > 0 ? computeProfitFactor(knownClosedRows) : null;
  const rrValues = rows.map((row) => row.rrValue).filter((value): value is number => value !== null);
  const avgRr = rrValues.length > 0 ? rrValues.reduce((sum, value) => sum + value, 0) / rrValues.length : null;

  const winTradesWithPnl = knownClosedRows.filter((row) => row.result === "PROFIT" && row.pnl !== null);
  const avgWin = winTradesWithPnl.length > 0 ? winTradesWithPnl.reduce((sum, row) => sum + (row.pnl ?? 0), 0) / winTradesWithPnl.length : null;

  const lossTradesWithPnl = knownClosedRows.filter((row) => row.result === "LOSS" && row.pnl !== null);
  const avgLoss = lossTradesWithPnl.length > 0 ? lossTradesWithPnl.reduce((sum, row) => sum + (row.pnl ?? 0), 0) / lossTradesWithPnl.length : null;

  const maxDrawdown = knownPnlClosedRows.length > 0 ? computeMaxDrawdown(knownPnlClosedRows) : null;

  const totalClosed = closedRows.length;
  const coveredClosed = knownPnlClosedRows.length;
  const pnlCoverage = totalClosed > 0 ? (coveredClosed / totalClosed) * 100 : 100;

  const equityCurve = knownPnlClosedRows.reduce<Array<{ x: string; y: number }>>((acc, row) => {
    const previous = acc[acc.length - 1]?.y || 0;
    acc.push({ x: toBdtDate(row.closedAt), y: previous + (row.pnl ?? 0) });
    return acc;
  }, []);

  const dailyPnl = Array.from(
    knownPnlClosedRows.reduce((map, row) => {
      const key = toBdtDate(row.closedAt);
      map.set(key, (map.get(key) || 0) + (row.pnl ?? 0));
      return map;
    }, new Map<string, number>()),
  ).map(([date, pnl]) => ({ date, pnl }));

  const strategyBreakdown = Array.from(
    rows.reduce((map, row) => {
      const current = map.get(row.strategy) || { trades: 0, pnl: 0, wins: 0, knownPnl: 0 };
      current.trades += 1;
      if (row.pnl !== null) {
        current.pnl += row.pnl;
        current.knownPnl += 1;
      }
      current.wins += row.result === "PROFIT" ? 1 : 0;
      map.set(row.strategy, current);
      return map;
    }, new Map<string, { trades: number; pnl: number; wins: number; knownPnl: number }>()),
  );

  const symbolPerformance = Array.from(
    rows.reduce((map, row) => {
      const current = map.get(row.symbol) || { trades: 0, pnl: 0, knownPnl: 0 };
      current.trades += 1;
      if (row.pnl !== null) {
        current.pnl += row.pnl;
        current.knownPnl += 1;
      }
      map.set(row.symbol, current);
      return map;
    }, new Map<string, { trades: number; pnl: number; knownPnl: number }>()),
  ).sort((a, b) => b[1].pnl - a[1].pnl);

  const sessionPerformance = Array.from(
    rows.reduce((map, row) => {
      const current = map.get(row.session) || { trades: 0, pnl: 0, wins: 0, knownPnl: 0 };
      current.trades += 1;
      if (row.pnl !== null) {
        current.pnl += row.pnl;
        current.knownPnl += 1;
      }
      current.wins += row.result === "PROFIT" ? 1 : 0;
      map.set(row.session, current);
      return map;
    }, new Map<string, { trades: number; pnl: number; wins: number; knownPnl: number }>()),
  );

  const slAnalysis = Array.from(
    knownClosedRows
      .filter((row) => row.result === "LOSS")
      .reduce((map, row) => {
        const key = row.reason || "unknown";
        map.set(key, (map.get(key) || 0) + 1);
        return map;
      }, new Map<string, number>()),
  );

  const accountNetPnl = metrics.today_financial_status === "unavailable" ? null : metrics.today_account_net_pnl;
  const auditStrategies = strategyAudit?.ok ? strategyAudit.strategies : [];
  const auditSummary = strategyAudit?.ok ? strategyAudit.summary : null;
  const auditedTrades = strategyAudit?.ok ? strategyAudit.trades : [];
  const auditedLosses = auditedTrades.filter((trade) => trade.pnl_known && trade.result === "loss");

  const healthCards = [
    {
      title: "Strategy Stability",
      value: totalTrades > 0 ? (winRate !== null ? formatPercent(winRate) : "N/A") : "Insufficient Data",
      hint: "Win-rate based health read.",
      tone: winRate !== null && winRate >= 0.5 ? "good" : "warn",
    },
    {
      title: "Risk Efficiency",
      value: avgRr !== null ? `${avgRr.toFixed(2)}R` : "Insufficient Data",
      hint: "Average realized reward-to-risk profile.",
      tone: avgRr !== null && avgRr >= 1.5 ? "good" : "warn",
    },
    {
      title: "Drawdown Pressure",
      value: maxDrawdown !== null ? formatMoney(maxDrawdown) : "Insufficient Data",
      hint: "Largest equity pullback from persisted closes.",
      tone: maxDrawdown !== null && maxDrawdown <= 2 ? "good" : "warn",
    },
  ];

  return (
    <div className="space-y-6">
      {pnlCoverage < 100 && (
        <div className="bg-amber-500/10 border border-amber-500/20 rounded-2xl p-4 flex items-start gap-3 text-amber-300">
          <ShieldAlert className="w-5 h-5 shrink-0 mt-0.5" />
          <div>
            <h4 className="text-sm font-semibold text-amber-200">Incomplete Financial Data ({pnlCoverage.toFixed(0)}% Coverage)</h4>
            <p className="text-xs text-amber-400/80 mt-1">
              Some closed trades are missing authoritative exchange realized PnL. Incomplete records have been excluded from calculations and win rate/drawdown metrics instead of counting them as zero.
            </p>
          </div>
        </div>
      )}

      <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
        <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-white tracking-tight font-sans">Performance & Strategy</h3>
            <p className="text-xs text-slate-500 mt-1">Account-level Net PnL uses the same Bybit transaction-log truth as Journal and Dashboard. Strategy metrics remain ledger-matched trade analytics.</p>
          </div>
          <div className="text-[10px] font-mono text-slate-500">BDT {BDT_DATE_TIME.format(new Date())}</div>
        </div>
        {error && <div className="mt-4 text-xs font-mono text-rose-300">{error}</div>}
      </div>

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        <KpiCard label="Total Trades" value={totalTrades > 0 ? String(totalTrades) : "Insufficient Data"} />
        <KpiCard label="Open Trades" value={openRows.length > 0 ? String(openRows.length) : "0"} />
        <KpiCard label="Win Rate" value={winRate !== null ? formatPercent(winRate) : "Insufficient Data"} />
        <KpiCard label="Account Net (Bybit)" value={accountNetPnl !== null ? formatMoney(accountNetPnl) : "N/A"} />
        <KpiCard label="Strategy Net (Matched)" value={netPnl !== null ? formatMoney(netPnl) : "Insufficient Data"} />
        <KpiCard label="Profit Factor" value={profitFactor === Infinity ? "Infinity" : profitFactor !== null ? profitFactor.toFixed(2) : "Insufficient Data"} />
        <KpiCard label="Average RR" value={avgRr !== null ? `${avgRr.toFixed(2)}R` : "Insufficient Data"} />
        <KpiCard label="Average Win" value={avgWin !== null ? formatMoney(avgWin) : "Insufficient Data"} />
        <KpiCard label="Average Loss" value={avgLoss !== null ? formatMoney(avgLoss) : "Insufficient Data"} />
        <KpiCard label="Max Drawdown" value={maxDrawdown !== null ? formatMoney(maxDrawdown) : "Insufficient Data"} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <ChartCard title="Equity Curve" icon={<LineChart className="w-4 h-4 text-emerald-400" />}>
          {equityCurve.length > 0 ? <SimpleLineChart data={equityCurve} /> : <EmptyState text="Insufficient Data" />}
        </ChartCard>
        <ChartCard title="Daily PnL" icon={<BarChart3 className="w-4 h-4 text-amber-400" />}>
          {dailyPnl.length > 0 ? <DailyBars data={dailyPnl} /> : <EmptyState text="Insufficient Data" />}
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <DataCard title="Strategy Audit Panel" icon={<Target className="w-4 h-4 text-cyan-300" />}>
          {strategyAudit?.ok ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
                <MiniAuditCard label="Known PnL" value={`${auditSummary?.known_pnl_trades || 0}/${auditSummary?.trade_count || 0}`} />
                <MiniAuditCard label="Bybit Ledger" value={String(auditSummary?.ledger_matched_trades || 0)} />
                <MiniAuditCard label="Journal Fallback" value={String(auditSummary?.journal_fallback_trades || 0)} />
                <MiniAuditCard label="Net PnL" value={formatMoney(auditSummary?.net_pnl ?? null)} tone={(auditSummary?.net_pnl || 0) >= 0 ? "good" : "bad"} />
              </div>
              {auditStrategies.length > 0 ? (
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-slate-800 text-[10px] font-mono uppercase tracking-wider text-slate-500">
                      <th className="py-3 px-3">Strategy</th>
                      <th className="py-3 px-3 text-right">W/L</th>
                      <th className="py-3 px-3 text-right">Ledger</th>
                      <th className="py-3 px-3 text-right">Unknown</th>
                      <th className="py-3 px-3 text-right">Net PnL</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/30 text-xs font-mono">
                    {auditStrategies.map((stats) => (
                      <tr key={stats.strategy}>
                        <td className="py-3 px-3 text-white">{stats.strategy}</td>
                        <td className="py-3 px-3 text-right">
                          <span className="text-emerald-400">{stats.wins}</span>
                          <span className="text-slate-600"> / </span>
                          <span className="text-rose-400">{stats.losses}</span>
                        </td>
                        <td className="py-3 px-3 text-right text-cyan-300">{stats.ledger_matched_trades}</td>
                        <td className="py-3 px-3 text-right text-amber-300">{stats.unmatched_trades}</td>
                        <td className={`py-3 px-3 text-right ${stats.known_pnl_trades === 0 ? "text-slate-500" : stats.net_pnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                          {stats.known_pnl_trades > 0 ? formatMoney(stats.net_pnl) : "N/A"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <EmptyState text="No audited strategy records for selected BDT day" />
              )}
              <div className="space-y-2">
                <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">Recent Audited Trades</div>
                {auditedTrades.slice(0, 5).map((trade) => (
                  <div key={trade.journal_id || `${trade.symbol}-${trade.opened_at}`} className="grid grid-cols-[1fr_auto_auto] gap-3 rounded-xl border border-slate-800 bg-[#0A0B0E] p-3 text-xs">
                    <div>
                      <div className="font-semibold text-white">{trade.symbol}</div>
                      <div className="mt-1 text-[10px] font-mono text-slate-500">{trade.strategy} / {trade.direction.toUpperCase()}</div>
                    </div>
                    <SourceBadge source={trade.pnl_source} />
                    <div className={trade.pnl_known ? (Number(trade.realized_pnl || 0) >= 0 ? "text-emerald-400" : "text-rose-400") : "text-slate-500"}>
                      {trade.pnl_known ? formatMoney(trade.realized_pnl) : "N/A"}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <EmptyState text={strategyAudit?.error || "Strategy audit unavailable"} />
          )}
        </DataCard>

        <DataCard title="Strategy Comparison" icon={<Target className="w-4 h-4 text-violet-400" />}>
          {strategyBreakdown.length > 0 ? (
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-[10px] font-mono uppercase tracking-wider text-slate-500">
                  <th className="py-3 px-3">Strategy</th>
                  <th className="py-3 px-3 text-right">Trades</th>
                  <th className="py-3 px-3 text-right">Win Rate</th>
                  <th className="py-3 px-3 text-right">PnL</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/30 text-xs font-mono">
                {strategyBreakdown.map(([name, stats]) => (
                  <tr key={name}>
                    <td className="py-3 px-3 text-white">{name}</td>
                    <td className="py-3 px-3 text-right">{stats.trades}</td>
                    <td className="py-3 px-3 text-right">{stats.trades > 0 ? formatPercent(stats.wins / stats.trades) : "N/A"}</td>
                    <td className={`py-3 px-3 text-right ${stats.knownPnl === 0 ? "text-slate-500" : stats.pnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>{stats.knownPnl > 0 ? formatMoney(stats.pnl) : "N/A"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <EmptyState text="Insufficient Data" />}
        </DataCard>

        <DataCard title="Symbol / Session Performance" icon={<Activity className="w-4 h-4 text-emerald-400" />}>
          {rows.length > 0 ? (
            <div className="grid grid-cols-1 gap-4">
              <div>
                <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500 mb-2">Symbols</div>
                <div className="space-y-2">
                  {symbolPerformance.slice(0, 6).map(([symbol, stats]) => (
                    <div key={symbol} className="flex items-center justify-between rounded-xl border border-slate-800 bg-[#0A0B0E] p-3 text-xs">
                      <span className="text-white">{symbol}</span>
                      <span className="text-slate-400">{stats.trades} trades</span>
                      <span className={stats.knownPnl === 0 ? "text-slate-500" : stats.pnl >= 0 ? "text-emerald-400" : "text-rose-400"}>{stats.knownPnl > 0 ? formatMoney(stats.pnl) : "N/A"}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500 mb-2">Sessions</div>
                <div className="space-y-2">
                  {sessionPerformance.map(([session, stats]) => (
                    <div key={session} className="flex items-center justify-between rounded-xl border border-slate-800 bg-[#0A0B0E] p-3 text-xs">
                      <span className="text-white">{session}</span>
                      <span className="text-slate-400">{stats.trades} trades</span>
                      <span className={stats.knownPnl === 0 ? "text-slate-500" : stats.pnl >= 0 ? "text-emerald-400" : "text-rose-400"}>{stats.knownPnl > 0 ? formatMoney(stats.pnl) : "N/A"}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : <EmptyState text="Insufficient Data" />}
        </DataCard>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[0.7fr_0.3fr] gap-6">
        <DataCard title="SL-Hit Analysis" icon={<ShieldAlert className="w-4 h-4 text-rose-400" />}>
          {auditedLosses.length > 0 ? (
            <div className="space-y-3">
              {auditedLosses.slice(0, 8).map((trade) => (
                <div key={trade.journal_id || `${trade.symbol}-${trade.opened_at}`} className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-4 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="font-semibold text-white">{trade.symbol} <span className="text-slate-500">/ {trade.strategy}</span></div>
                      <div className="mt-1 text-[10px] font-mono text-slate-500">{trade.direction.toUpperCase()} · {trade.loss_diagnosis?.category || trade.sl_hit_reason || trade.close_reason || "LOSS_EXIT_UNCLASSIFIED"}</div>
                    </div>
                    <div className="text-right">
                      <SourceBadge source={trade.pnl_source} />
                      <div className="mt-2 font-mono text-rose-300">{formatMoney(trade.realized_pnl)}</div>
                    </div>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4">
                    <MiniAuditCard label="Entry" value={formatMoney(trade.loss_diagnosis?.entry ?? trade.entry)} />
                    <MiniAuditCard label="Stop" value={formatMoney(trade.loss_diagnosis?.stop_loss ?? trade.stop_loss ?? null)} tone="bad" />
                    <MiniAuditCard label="Exit" value={formatMoney(trade.loss_diagnosis?.exit_price ?? trade.exit_price)} tone="bad" />
                    <MiniAuditCard label="Exit vs SL" value={trade.loss_diagnosis?.exit_vs_sl == null ? "N/A" : trade.loss_diagnosis.exit_vs_sl.toFixed(6)} />
                  </div>
                  <div className="mt-3 rounded-lg border border-slate-900 bg-slate-950/60 px-3 py-2 text-[11px] leading-5 text-slate-400">
                    {trade.loss_diagnosis?.detail || trade.audit_note || "Loss recorded, but no detailed diagnosis was available."}
                  </div>
                </div>
              ))}
            </div>
          ) : slAnalysis.length > 0 ? (
            <div className="space-y-3">
              {slAnalysis.map(([reason, count]) => (
                <div key={reason} className="flex items-center justify-between rounded-xl border border-slate-800 bg-[#0A0B0E] p-3 text-xs">
                  <span className="text-white">{reason}</span>
                  <span className="text-slate-400">{count} trades</span>
                </div>
              ))}
            </div>
          ) : <EmptyState text="N/A" />}
        </DataCard>

        <div className="space-y-4">
          {healthCards.map((card) => (
            <div key={card.title} className="bg-bento-card border border-slate-800 rounded-2xl p-5 shadow-md">
              <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{card.title}</div>
              <div className={`mt-3 text-lg font-semibold ${card.tone === "good" ? "text-emerald-400" : "text-amber-300"}`}>{card.value}</div>
              <div className="mt-2 text-xs text-slate-500">{card.hint}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function KpiCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-bento-card border border-slate-800 rounded-2xl p-5 shadow-md">
      <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-3 text-lg font-semibold text-white">{value}</div>
    </div>
  );
}

function MiniAuditCard({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "neutral" | "good" | "bad" }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-3">
      <div className="text-[9px] font-mono uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-2 text-sm font-semibold ${tone === "good" ? "text-emerald-400" : tone === "bad" ? "text-rose-400" : "text-white"}`}>{value}</div>
    </div>
  );
}

function SourceBadge({ source }: { source: "bybit_ledger" | "journal" | "unmatched" }) {
  const label = source === "bybit_ledger" ? "BYBIT LEDGER" : source === "journal" ? "JOURNAL" : "UNMATCHED";
  const tone = source === "bybit_ledger" ? "border-cyan-700/60 bg-cyan-950/30 text-cyan-300" : source === "journal" ? "border-amber-700/60 bg-amber-950/30 text-amber-300" : "border-slate-700 bg-slate-950/60 text-slate-500";
  return <span className={`h-fit rounded-full border px-2 py-1 text-[9px] font-mono font-semibold ${tone}`}>{label}</span>;
}

function ChartCard({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
      <div className="flex items-center gap-2 mb-4">
        {icon}
        <h4 className="text-sm font-semibold text-white tracking-tight font-sans">{title}</h4>
      </div>
      {children}
    </div>
  );
}

function DataCard({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
      <div className="flex items-center gap-2 mb-4">
        {icon}
        <h4 className="text-sm font-semibold text-white tracking-tight font-sans">{title}</h4>
      </div>
      {children}
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return <div className="py-12 text-center text-xs font-mono text-slate-500">{text}</div>;
}

function SimpleLineChart({ data }: { data: Array<{ x: string; y: number }> }) {
  const width = 520;
  const height = 220;
  const padding = 16;
  const max = Math.max(...data.map((item) => item.y), 1);
  const min = Math.min(...data.map((item) => item.y), 0);
  const range = Math.max(max - min, 1);
  const path = data
    .map((item, index) => {
      const x = padding + (index / Math.max(data.length - 1, 1)) * (width - padding * 2);
      const y = padding + ((max - item.y) / range) * (height - padding * 2);
      return `${index === 0 ? "M" : "L"} ${x} ${y}`;
    })
    .join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full">
      <path d={path} fill="none" stroke="#10b981" strokeWidth="2" />
    </svg>
  );
}

function DailyBars({ data }: { data: Array<{ date: string; pnl: number }> }) {
  const width = 520;
  const height = 220;
  const padding = 16;
  const maxAbs = Math.max(...data.map((item) => Math.abs(item.pnl)), 1);
  const baseline = height / 2;
  const barWidth = Math.max((width - padding * 2) / data.length - 8, 12);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full">
      <line x1={padding} x2={width - padding} y1={baseline} y2={baseline} stroke="#334155" strokeWidth="1" />
      {data.map((item, index) => {
        const x = padding + index * ((width - padding * 2) / data.length) + 4;
        const barHeight = (Math.abs(item.pnl) / maxAbs) * (height / 2 - padding);
        const y = item.pnl >= 0 ? baseline - barHeight : baseline;
        return (
          <rect key={item.date} x={x} y={y} width={barWidth} height={barHeight} rx="2" fill={item.pnl >= 0 ? "#10b981" : "#f43f5e"} />
        );
      })}
    </svg>
  );
}
