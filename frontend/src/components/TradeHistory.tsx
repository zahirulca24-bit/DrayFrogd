import { useEffect, useMemo, useRef, useState } from "react";
import { Download, FileDown, Filter, Info, RefreshCw } from "lucide-react";
import { api } from "../api";
import { JournalTradeEntry, MarketCandle, TradeHistoryEntry } from "../types";

interface TradeHistoryProps {
  authToken: string | null;
  history: TradeHistoryEntry[];
}

type JournalRow = TradeHistoryEntry & {
  side: "LONG" | "SHORT";
  strategy: string;
  leverageText: string;
  feesText: string;
  rrValue: number | null;
  durationText: string;
  executionMode: string;
  timeline: Array<{ label: string; value: string | null }>;
  executionLog: string[];
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

function bdtDate(value?: string | null) {
  return value ? BDT_DATE.format(new Date(value)) : "";
}

function bdtDateTime(value?: string | null) {
  return value ? BDT_DATE_TIME.format(new Date(value)) : "N/A";
}

function numberValue(value: unknown) {
  const numeric = Number(value || 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function formatMoney(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "N/A";
  }
  return `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
}

function calcRr(entry: number, stop: number, takeProfit: number) {
  const risk = Math.abs(entry - stop);
  const reward = Math.abs(takeProfit - entry);
  if (risk <= 0 || reward <= 0) {
    return null;
  }
  return reward / risk;
}

function durationBetween(start?: string | null, end?: string | null) {
  if (!start || !end) {
    return "N/A";
  }
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (!Number.isFinite(ms) || ms <= 0) {
    return "N/A";
  }
  const minutes = Math.floor(ms / 60000);
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  if (hours > 0) {
    return `${hours}h ${remainingMinutes}m`;
  }
  return `${remainingMinutes}m`;
}

function normalizeDirection(value?: string | null) {
  return String(value || "").toUpperCase() === "SHORT" ? "SHORT" : "LONG";
}

function todayBdtDate() {
  return BDT_DATE.format(new Date());
}

function journalToRow(item: JournalTradeEntry, index: number): JournalRow {
  const metadata = (item.exchange_metadata || {}) as Record<string, any>;
  const management = (metadata.management || {}) as Record<string, any>;
  const entryPrice = numberValue(item.entry);
  const stopLoss = numberValue(item.stop_loss);
  const takeProfit = numberValue(item.take_profit);
  const closedAt = item.closed_at || item.opened_at || item.detected_at || new Date().toISOString();
  const isClosed = String(item.status || "").toLowerCase() === "closed";
  const rawResult = String(item.result || "").toLowerCase();
  const result = rawResult === "tp" || rawResult === "profit" ? "PROFIT" : "LOSS";
  const leverage = metadata?.order_response?.leverage || metadata?.leverage || null;
  const fees = metadata?.fees || metadata?.trading_fee || null;
  const rrValue = calcRr(entryPrice, stopLoss, takeProfit);

  return {
    id: item.order_id || item.journal_id || `${item.symbol}-${index}`,
    pair: item.symbol,
    strategy: "EMA Pullback",
    direction: normalizeDirection(item.direction),
    entryPrice,
    currentPrice: entryPrice,
    stopLoss,
    takeProfit,
    size: numberValue(item.quantity),
    margin: 0,
    leverage: 1,
    unrealizedPnl: 0,
    pnlPercent: 0,
    status: isClosed ? "CLOSED" : "OPEN",
    timestamp: item.opened_at || item.detected_at || closedAt,
    orderConfirmed: Boolean(item.order_id),
    slVerified: item.status !== "protection_pending",
    tpVerified: item.status !== "protection_pending",
    positionSynced: true,
    orderId: item.order_id || undefined,
    rawStatus: item.status,
    journalId: item.journal_id,
    executionMode: item.execution_mode || "demo",
    closedAt,
    slHitReason: item.sl_hit_reason ?? null,
    managementTp1: Number(management.tp1 || 0) || undefined,
    managementTp2: Number(management.tp2 || 0) || undefined,
    managementRunner: Number(management.runner_target || 0) || undefined,
    breakEvenSet: Boolean(management.break_even_set),
    tp1Done: Boolean(management.tp1_done),
    tp2Done: Boolean(management.tp2_done),
    exitPrice: isClosed ? numberValue(metadata?.exit_price || item.take_profit) : 0,
    pnl: isClosed ? (result === "PROFIT" ? 2 : -1) : 0,
    result,
    reason: item.sl_hit_reason || (isClosed ? "n/a" : "open"),
    side: normalizeDirection(item.direction),
    leverageText: leverage ? `${leverage}x` : "N/A",
    feesText: fees !== null && fees !== undefined ? formatMoney(numberValue(fees)) : "N/A",
    rrValue,
    durationText: durationBetween(item.opened_at || item.detected_at, item.closed_at),
    timeline: [
      { label: "Detected", value: item.detected_at || null },
      { label: "Opened", value: item.opened_at || null },
      { label: "Closed", value: item.closed_at || null },
    ],
    executionLog: [
      item.order_id ? `Order linked: ${item.order_id}` : "Order ID unavailable",
      `Execution mode: ${item.execution_mode || "demo"}`,
      isClosed ? `Outcome: ${result}` : "Outcome: OPEN / active journal trade",
    ],
  };
}

export default function TradeHistory({ authToken, history }: TradeHistoryProps) {
  const [journalTrades, setJournalTrades] = useState<JournalTradeEntry[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [candles, setCandles] = useState<MarketCandle[]>([]);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState({
    dateFrom: todayBdtDate(),
    dateTo: todayBdtDate(),
    symbol: "",
    side: "ALL",
    strategy: "ALL",
    result: "ALL",
    exitReason: "ALL",
  });
  const bdtDayRef = useRef(todayBdtDate());

  useEffect(() => {
    if (!authToken) {
      return;
    }
    let cancelled = false;

    const loadJournal = async () => {
      setLoading(true);
      try {
        const response = await api.getJournalTrades(authToken);
        if (!cancelled) {
          setJournalTrades(response.trades || []);
          setError(null);
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(err?.message || "Failed to load journal trades");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    loadJournal();
    const interval = setInterval(() => {
      const current = todayBdtDate();
      if (current !== bdtDayRef.current) {
        bdtDayRef.current = current;
        setFilters((prev) => ({ ...prev, dateFrom: current, dateTo: current }));
      }
      void loadJournal();
    }, 10000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [authToken]);

  const rows = useMemo<JournalRow[]>(() => {
    if (journalTrades.length > 0) {
      return journalTrades.map(journalToRow);
    }

    return history.map((trade) => ({
      ...trade,
      side: normalizeDirection(trade.direction),
      strategy: trade.strategy || "EMA Pullback",
      leverageText: "N/A",
      feesText: "N/A",
      rrValue: calcRr(trade.entryPrice, trade.stopLoss, trade.takeProfit),
      durationText: durationBetween(trade.timestamp, trade.closedAt),
      executionMode: trade.executionMode || "demo",
      timeline: [
        { label: "Detected", value: null },
        { label: "Opened", value: trade.timestamp },
        { label: "Closed", value: trade.closedAt || null },
      ],
      executionLog: [
        trade.orderId ? `Order linked: ${trade.orderId}` : "Order ID unavailable",
        `Execution mode: ${trade.executionMode || "demo"}`,
        `Outcome: ${trade.result}`,
      ],
    }));
  }, [history, journalTrades]);

  const filteredRows = useMemo(() => {
    return rows.filter((row) => {
      const closedDate = bdtDate(row.closedAt || row.timestamp);
      if (filters.dateFrom && closedDate < filters.dateFrom) {
        return false;
      }
      if (filters.dateTo && closedDate > filters.dateTo) {
        return false;
      }
      if (filters.symbol && row.pair !== filters.symbol.toUpperCase()) {
        return false;
      }
      if (filters.side !== "ALL" && row.side !== filters.side) {
        return false;
      }
      if (filters.strategy !== "ALL" && row.strategy !== filters.strategy) {
        return false;
      }
      if (filters.result !== "ALL" && row.result !== filters.result) {
        return false;
      }
      if (filters.exitReason !== "ALL" && (row.reason || "N/A") !== filters.exitReason) {
        return false;
      }
      return true;
    });
  }, [filters, rows]);

  const selectedTrade = useMemo(() => filteredRows.find((row) => row.id === selectedId) || filteredRows[0] || null, [filteredRows, selectedId]);

  useEffect(() => {
    if (!authToken || !selectedTrade) {
      return;
    }
    let cancelled = false;

    const loadCandles = async () => {
      setDetailLoading(true);
      try {
        const response = await api.getMarketCandles(authToken, selectedTrade.pair, "5", 90);
        if (!cancelled) {
          setCandles((response.candles || []).map((item) => ({
            ...item,
            open: numberValue(item.open),
            high: numberValue(item.high),
            low: numberValue(item.low),
            close: numberValue(item.close),
          })));
        }
      } finally {
        if (!cancelled) {
          setDetailLoading(false);
        }
      }
    };

    loadCandles();
    return () => {
      cancelled = true;
    };
  }, [authToken, selectedTrade]);

  const symbolOptions = Array.from(new Set(rows.map((row) => row.pair))).sort();
  const strategyOptions = Array.from(new Set(rows.map((row) => row.strategy))).sort();
  const reasonOptions = Array.from(new Set(rows.map((row) => row.reason || "N/A"))).sort();

  const exportCsv = () => {
    const headers = ["BDT Time", "Symbol", "Side", "Strategy", "Entry", "Exit", "SL", "TP", "Size", "Leverage", "RealizedPnL", "RR", "Duration", "Status", "Result", "ExitReason"];
    const lines = filteredRows.map((row) => [
      bdtDateTime(row.closedAt),
      row.pair,
      row.side,
      row.strategy,
      row.entryPrice,
      row.exitPrice,
      row.stopLoss,
      row.takeProfit,
      row.size,
      row.leverageText,
      row.pnl,
      row.rrValue ?? "N/A",
      row.durationText,
      row.rawStatus || row.status,
      row.result,
      row.reason,
    ]);
    const csv = [headers, ...lines].map((line) => line.map((cell) => `"${String(cell ?? "").replaceAll('"', '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `journal-${filters.dateFrom || "all"}-${filters.dateTo || "all"}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const exportPdf = () => {
    const popup = window.open("", "_blank", "width=1100,height=800");
    if (!popup) {
      return;
    }
    popup.document.write(`
      <html>
        <head><title>Journal Export</title></head>
        <body style="font-family: Arial, sans-serif; padding: 24px;">
          <h2>DayFrogd-ScalpingEngin Journal Export</h2>
          <p>Range: ${filters.dateFrom || "All"} to ${filters.dateTo || "All"}</p>
          <table border="1" cellspacing="0" cellpadding="6" style="border-collapse: collapse; width: 100%; font-size: 12px;">
            <thead>
              <tr>
                <th>BDT Time</th><th>Symbol</th><th>Side</th><th>Strategy</th><th>Entry</th><th>Exit</th><th>SL</th><th>TP</th><th>Size</th><th>Leverage</th><th>Realized PnL</th><th>RR</th><th>Duration</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              ${filteredRows.map((row) => `
                <tr>
                  <td>${bdtDateTime(row.closedAt)}</td>
                  <td>${row.pair}</td>
                  <td>${row.side}</td>
                  <td>${row.strategy}</td>
                  <td>${row.entryPrice}</td>
                  <td>${row.exitPrice}</td>
                  <td>${row.stopLoss}</td>
                  <td>${row.takeProfit}</td>
                  <td>${row.size}</td>
                  <td>${row.leverageText}</td>
                  <td>${row.pnl}</td>
                  <td>${row.rrValue ?? "N/A"}</td>
                  <td>${row.durationText}</td>
                  <td>${row.rawStatus || row.status}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </body>
      </html>
    `);
    popup.document.close();
    popup.focus();
    popup.print();
  };

  return (
    <div className="space-y-6" id="trade-history-section">
      <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
        <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-white tracking-tight font-sans">Journal / Trade History</h3>
            <p className="text-xs text-slate-500 mt-1">Default view shows today&apos;s persisted open and closed journal trades, filtered in BDT.</p>
          </div>
          <div className="flex items-center gap-3 text-[10px] font-mono text-slate-500">
            <span>BDT {bdtDateTime(new Date().toISOString())}</span>
            <button onClick={() => void api.getJournalTrades(authToken || "").then((response) => setJournalTrades(response.trades || []))} className="px-3 py-1.5 rounded-lg border border-slate-800 bg-[#0A0B0E] hover:text-white cursor-pointer">
              <RefreshCw className="w-3 h-3 inline mr-1" /> Refresh
            </button>
            <button onClick={exportCsv} className="px-3 py-1.5 rounded-lg border border-slate-800 bg-[#0A0B0E] hover:text-white cursor-pointer">
              <Download className="w-3 h-3 inline mr-1" /> CSV
            </button>
            <button onClick={exportPdf} className="px-3 py-1.5 rounded-lg border border-slate-800 bg-[#0A0B0E] hover:text-white cursor-pointer">
              <FileDown className="w-3 h-3 inline mr-1" /> PDF
            </button>
          </div>
        </div>

        {error && <div className="mt-4 text-xs font-mono text-rose-300">{error}</div>}

        <div className="grid grid-cols-2 xl:grid-cols-6 gap-3 mt-5">
          <FilterField label="Date From"><input type="date" value={filters.dateFrom} onChange={(e) => setFilters((prev) => ({ ...prev, dateFrom: e.target.value }))} className="dashboard-input" /></FilterField>
          <FilterField label="Date To"><input type="date" value={filters.dateTo} onChange={(e) => setFilters((prev) => ({ ...prev, dateTo: e.target.value }))} className="dashboard-input" /></FilterField>
          <FilterField label="Symbol">
            <select value={filters.symbol} onChange={(e) => setFilters((prev) => ({ ...prev, symbol: e.target.value }))} className="dashboard-input">
              <option value="">All</option>
              {symbolOptions.map((symbol) => <option key={symbol}>{symbol}</option>)}
            </select>
          </FilterField>
          <FilterField label="Side">
            <select value={filters.side} onChange={(e) => setFilters((prev) => ({ ...prev, side: e.target.value }))} className="dashboard-input">
              <option value="ALL">All</option>
              <option value="LONG">Long</option>
              <option value="SHORT">Short</option>
            </select>
          </FilterField>
          <FilterField label="Strategy">
            <select value={filters.strategy} onChange={(e) => setFilters((prev) => ({ ...prev, strategy: e.target.value }))} className="dashboard-input">
              <option value="ALL">All</option>
              {strategyOptions.map((strategy) => <option key={strategy}>{strategy}</option>)}
            </select>
          </FilterField>
          <FilterField label="Result">
            <select value={filters.result} onChange={(e) => setFilters((prev) => ({ ...prev, result: e.target.value }))} className="dashboard-input">
              <option value="ALL">All</option>
              <option value="PROFIT">PROFIT</option>
              <option value="LOSS">LOSS</option>
            </select>
          </FilterField>
          <FilterField label="Exit Reason">
            <select value={filters.exitReason} onChange={(e) => setFilters((prev) => ({ ...prev, exitReason: e.target.value }))} className="dashboard-input">
              <option value="ALL">All</option>
              {reasonOptions.map((reason) => <option key={reason}>{reason}</option>)}
            </select>
          </FilterField>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1.45fr_0.55fr] gap-6">
        <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md overflow-hidden">
          <div className="flex items-center justify-between mb-5">
            <h4 className="text-sm font-semibold text-white tracking-tight font-sans">Journal Trades Table</h4>
            <span className="text-[10px] font-mono text-slate-500">{loading ? "Loading..." : `${filteredRows.length} rows`}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse whitespace-nowrap">
              <thead>
                <tr className="border-b border-slate-800 text-[10px] font-mono uppercase tracking-wider text-slate-500">
                  <th className="py-3 px-3">BDT Time</th>
                  <th className="py-3 px-3">Symbol</th>
                  <th className="py-3 px-3">Side</th>
                  <th className="py-3 px-3">Strategy</th>
                  <th className="py-3 px-3 text-right">Entry</th>
                  <th className="py-3 px-3 text-right">Exit</th>
                  <th className="py-3 px-3 text-right">SL</th>
                  <th className="py-3 px-3 text-right">TP</th>
                  <th className="py-3 px-3 text-right">Size</th>
                  <th className="py-3 px-3 text-right">Lev</th>
                  <th className="py-3 px-3 text-right">Realized PnL</th>
                  <th className="py-3 px-3 text-right">RR</th>
                  <th className="py-3 px-3">Duration</th>
                  <th className="py-3 px-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/30 text-xs font-mono">
                {filteredRows.map((row) => (
                  <tr key={row.id} onClick={() => setSelectedId(row.id)} className={`cursor-pointer hover:bg-slate-900/20 ${selectedTrade?.id === row.id ? "bg-emerald-500/5" : ""}`}>
                    <td className="py-3 px-3 text-slate-300">{bdtDateTime(row.closedAt)}</td>
                    <td className="py-3 px-3 font-semibold text-white">{row.pair}</td>
                    <td className={`py-3 px-3 ${row.side === "LONG" ? "text-emerald-400" : "text-rose-400"}`}>{row.side}</td>
                    <td className="py-3 px-3 text-slate-400">{row.strategy}</td>
                    <td className="py-3 px-3 text-right">{formatMoney(row.entryPrice)}</td>
                    <td className="py-3 px-3 text-right">{formatMoney(row.exitPrice)}</td>
                    <td className="py-3 px-3 text-right">{formatMoney(row.stopLoss)}</td>
                    <td className="py-3 px-3 text-right">{formatMoney(row.takeProfit)}</td>
                    <td className="py-3 px-3 text-right">{row.size}</td>
                    <td className="py-3 px-3 text-right">{row.leverageText}</td>
                    <td className={`py-3 px-3 text-right ${numberValue(row.pnl) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>{formatMoney(row.pnl)}</td>
                    <td className="py-3 px-3 text-right">{row.rrValue ? `${row.rrValue.toFixed(2)}R` : "N/A"}</td>
                    <td className="py-3 px-3 text-slate-400">{row.durationText}</td>
                    <td className="py-3 px-3 text-slate-300">{row.rawStatus || row.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {filteredRows.length === 0 && <div className="py-10 text-center text-xs font-mono text-slate-500">No journal trades matched the selected filters.</div>}
        </div>

        <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
          {selectedTrade ? (
            <>
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h4 className="text-sm font-semibold text-white tracking-tight font-sans">{selectedTrade.pair} Trade Detail</h4>
                  <p className="text-xs text-slate-500 mt-1">{selectedTrade.strategy} | {selectedTrade.side} | {selectedTrade.executionMode.toUpperCase()}</p>
                </div>
                <span className="text-[10px] font-mono text-slate-500">{detailLoading ? "Loading..." : selectedTrade.result}</span>
              </div>

              <div className="grid grid-cols-2 gap-3 mb-4">
                <MiniMetric label="Fees" value={selectedTrade.feesText} />
                <MiniMetric label="Leverage" value={selectedTrade.leverageText} />
                <MiniMetric label="RR" value={selectedTrade.rrValue ? `${selectedTrade.rrValue.toFixed(2)}R` : "N/A"} />
                <MiniMetric label="Duration" value={selectedTrade.durationText} />
              </div>

              <div className="rounded-2xl border border-slate-800 bg-[#0A0B0E] p-4 mb-4">
                <div className="text-[10px] font-mono text-slate-500 mb-2">Trade Timeline</div>
                <div className="space-y-2">
                  {selectedTrade.timeline.map((item) => (
                    <div key={item.label} className="flex items-center justify-between text-xs">
                      <span className="text-slate-500">{item.label}</span>
                      <span className="text-slate-200 font-mono">{bdtDateTime(item.value)}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-2xl border border-slate-800 bg-[#0A0B0E] p-4 mb-4">
                <div className="text-[10px] font-mono text-slate-500 mb-2">Chart Markers</div>
                <JournalChart candles={candles} trade={selectedTrade} />
              </div>

              <div className="rounded-2xl border border-slate-800 bg-[#0A0B0E] p-4 mb-4">
                <div className="text-[10px] font-mono text-slate-500 mb-2">Execution Log</div>
                <div className="space-y-2">
                  {selectedTrade.executionLog.map((line, index) => (
                    <div key={index} className="text-xs font-mono text-slate-300">{line}</div>
                  ))}
                </div>
              </div>

              <div className="rounded-2xl border border-slate-800 bg-[#0A0B0E] p-4">
                <div className="text-[10px] font-mono text-slate-500 mb-2">SL / TP Analysis</div>
                <div className="text-xs text-slate-300 leading-relaxed">
                  {selectedTrade.result === "LOSS"
                    ? `Trade closed at stop-loss. Exit reason: ${selectedTrade.reason || "unknown"}.`
                    : selectedTrade.result === "PROFIT"
                    ? "Trade closed in profit. TP target reached based on persisted trade outcome."
                    : "Outcome details are insufficient in the persisted source data."}
                </div>
              </div>
            </>
          ) : (
            <div className="py-12 text-center text-xs font-mono text-slate-500">Select a row to inspect trade detail.</div>
          )}
        </div>
      </div>
    </div>
  );
}

function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="space-y-2 block">
      <span className="text-[10px] font-mono uppercase tracking-wider text-slate-500"><Filter className="w-3 h-3 inline mr-1" />{label}</span>
      {children}
    </label>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
      <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-2 text-xs font-semibold text-white">{value}</div>
    </div>
  );
}

function JournalChart({ candles, trade }: { candles: MarketCandle[]; trade: JournalRow }) {
  const width = 420;
  const height = 180;
  const padding = 12;

  if (!candles.length) {
    return <div className="py-10 text-center text-xs font-mono text-slate-500">No backend candles available.</div>;
  }

  const high = Math.max(...candles.map((item) => item.high), trade.takeProfit, trade.entryPrice, trade.exitPrice);
  const low = Math.min(...candles.map((item) => item.low), trade.stopLoss, trade.entryPrice, trade.exitPrice);
  const range = Math.max(high - low, 1);
  const plotWidth = width - padding * 2;
  const plotHeight = height - padding * 2;
  const candleWidth = Math.max(plotWidth / candles.length - 2, 2);
  const getY = (value: number) => padding + ((high - value) / range) * plotHeight;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full">
      {[
        { value: trade.entryPrice, color: "#94a3b8" },
        { value: trade.stopLoss, color: "#f43f5e" },
        { value: trade.takeProfit, color: "#10b981" },
        { value: trade.exitPrice, color: "#f59e0b" },
      ].map((line, index) => (
        <line key={index} x1={padding} x2={width - padding} y1={getY(line.value)} y2={getY(line.value)} stroke={line.color} strokeDasharray="5 5" strokeWidth="1" />
      ))}
      {candles.map((candle, index) => {
        const x = padding + index * (plotWidth / candles.length);
        const openY = getY(candle.open);
        const closeY = getY(candle.close);
        const highY = getY(candle.high);
        const lowY = getY(candle.low);
        const isBull = candle.close >= candle.open;
        return (
          <g key={`${candle.timestamp}-${index}`}>
            <line x1={x + candleWidth / 2} x2={x + candleWidth / 2} y1={highY} y2={lowY} stroke={isBull ? "#10b981" : "#f43f5e"} strokeWidth="1.1" />
            <rect x={x} y={Math.min(openY, closeY)} width={candleWidth} height={Math.max(Math.abs(closeY - openY), 1.5)} rx="1" fill={isBull ? "#10b981" : "#f43f5e"} />
          </g>
        );
      })}
    </svg>
  );
}
