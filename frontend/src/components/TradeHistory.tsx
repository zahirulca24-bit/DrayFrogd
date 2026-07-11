import { useEffect, useMemo, useRef, useState } from "react";
import { Download, FileDown, Filter, RefreshCw } from "lucide-react";
import { api } from "../api";
import { JournalTradeEntry, MarketCandle, TradeHistoryEntry } from "../types";

interface TradeHistoryProps {
  authToken: string | null;
  history: TradeHistoryEntry[];
}

type FinancialJournalTrade = JournalTradeEntry & {
  strategy_name?: string | null;
  strategy?: string | null;
  exit_price?: number | null;
  realized_pnl?: number | null;
  fees?: number | null;
  close_reason?: string | null;
};

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
  if (value === null || value === undefined || Number.isNaN(value)) return "N/A";
  return `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
}

function calcRr(entry: number, stop: number, takeProfit: number) {
  const risk = Math.abs(entry - stop);
  const reward = Math.abs(takeProfit - entry);
  return risk > 0 && reward > 0 ? reward / risk : null;
}

function durationBetween(start?: string | null, end?: string | null) {
  if (!start || !end) return "N/A";
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (!Number.isFinite(ms) || ms <= 0) return "N/A";
  const minutes = Math.floor(ms / 60000);
  const hours = Math.floor(minutes / 60);
  return hours > 0 ? `${hours}h ${minutes % 60}m` : `${minutes}m`;
}

function normalizeDirection(value?: string | null): "LONG" | "SHORT" {
  return String(value || "").toUpperCase() === "SHORT" ? "SHORT" : "LONG";
}

function todayBdtDate() {
  return BDT_DATE.format(new Date());
}

function journalToRow(item: JournalTradeEntry, index: number): JournalRow {
  const financial = item as FinancialJournalTrade;
  const metadata = (item.exchange_metadata || {}) as Record<string, any>;
  const entryPrice = numberValue(item.entry);
  const stopLoss = numberValue(item.stop_loss);
  const takeProfit = numberValue(item.take_profit);
  const isClosed = String(item.status || "").toLowerCase() === "closed";
  const rawResult = String(item.result || "").toLowerCase();
  const realizedPnl = financial.realized_pnl == null ? 0 : numberValue(financial.realized_pnl);
  const outcome =
    realizedPnl > 0 || rawResult === "tp" || rawResult === "profit"
      ? "PROFIT"
      : realizedPnl < 0 || rawResult === "sl" || rawResult === "loss"
      ? "LOSS"
      : "UNKNOWN";
  const exitPrice = financial.exit_price == null ? 0 : numberValue(financial.exit_price);
  const closedAt = item.closed_at || item.opened_at || item.detected_at || new Date().toISOString();
  const leverage = metadata?.order_response?.leverage || metadata?.leverage || null;

  return {
    id: item.order_id || item.journal_id || `${item.symbol}-${index}`,
    pair: item.symbol,
    strategy: String(financial.strategy_name || financial.strategy || "unknown"),
    direction: normalizeDirection(item.direction),
    entryPrice,
    currentPrice: isClosed && exitPrice > 0 ? exitPrice : entryPrice,
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
    exitPrice,
    pnl: isClosed ? realizedPnl : 0,
    result: outcome as TradeHistoryEntry["result"],
    reason: financial.close_reason || item.sl_hit_reason || (isClosed ? "unknown" : "open"),
    side: normalizeDirection(item.direction),
    leverageText: leverage ? `${leverage}x` : "N/A",
    feesText: financial.fees == null ? "N/A" : formatMoney(numberValue(financial.fees)),
    rrValue: calcRr(entryPrice, stopLoss, takeProfit),
    durationText: durationBetween(item.opened_at || item.detected_at, item.closed_at),
    timeline: [
      { label: "Detected", value: item.detected_at || null },
      { label: "Opened", value: item.opened_at || null },
      { label: "Closed", value: item.closed_at || null },
    ],
    executionLog: [
      item.order_id ? `Order linked: ${item.order_id}` : "Order ID unavailable",
      `Execution mode: ${item.execution_mode || "demo"}`,
      isClosed ? `Outcome: ${outcome}; realized PnL: ${formatMoney(realizedPnl)}` : "Outcome: OPEN / active journal trade",
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

  const loadJournal = async () => {
    if (!authToken) return;
    setLoading(true);
    try {
      const response = await api.getJournalTrades(authToken);
      setJournalTrades(response.trades || []);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Failed to load journal trades");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!authToken) return;
    let cancelled = false;
    const refresh = async () => {
      try {
        const response = await api.getJournalTrades(authToken);
        if (!cancelled) {
          setJournalTrades(response.trades || []);
          setError(null);
        }
      } catch (err: any) {
        if (!cancelled) setError(err?.message || "Failed to load journal trades");
      }
    };
    void refresh();
    const interval = setInterval(() => {
      const current = todayBdtDate();
      if (current !== bdtDayRef.current) {
        bdtDayRef.current = current;
        setFilters((prev) => ({ ...prev, dateFrom: current, dateTo: current }));
      }
      void refresh();
    }, 10000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [authToken]);

  const rows = useMemo<JournalRow[]>(() => {
    if (journalTrades.length > 0) return journalTrades.map(journalToRow);
    return history.map((trade) => ({
      ...trade,
      side: normalizeDirection(trade.direction),
      strategy: trade.strategy || "unknown",
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
        `Outcome: ${String(trade.result)}`,
      ],
    }));
  }, [history, journalTrades]);

  const filteredRows = useMemo(() => rows.filter((row) => {
    const date = bdtDate(row.closedAt || row.timestamp);
    return !(filters.dateFrom && date < filters.dateFrom)
      && !(filters.dateTo && date > filters.dateTo)
      && !(filters.symbol && row.pair !== filters.symbol.toUpperCase())
      && !(filters.side !== "ALL" && row.side !== filters.side)
      && !(filters.strategy !== "ALL" && row.strategy !== filters.strategy)
      && !(filters.result !== "ALL" && String(row.result) !== filters.result)
      && !(filters.exitReason !== "ALL" && (row.reason || "N/A") !== filters.exitReason);
  }), [filters, rows]);

  const selectedTrade = useMemo(
    () => filteredRows.find((row) => row.id === selectedId) || filteredRows[0] || null,
    [filteredRows, selectedId],
  );

  useEffect(() => {
    if (!authToken || !selectedTrade) return;
    let cancelled = false;
    const loadCandles = async () => {
      setDetailLoading(true);
      try {
        const response = await api.getMarketCandles(authToken, selectedTrade.pair, "5", 90);
        if (!cancelled) setCandles((response.candles || []).map((item) => ({
          ...item,
          open: numberValue(item.open),
          high: numberValue(item.high),
          low: numberValue(item.low),
          close: numberValue(item.close),
        })));
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    };
    void loadCandles();
    return () => { cancelled = true; };
  }, [authToken, selectedTrade]);

  const symbols = Array.from(new Set(rows.map((row) => row.pair))).sort();
  const strategies = Array.from(new Set(rows.map((row) => row.strategy))).sort();
  const reasons = Array.from(new Set(rows.map((row) => row.reason || "N/A"))).sort();

  const exportCsv = () => {
    const headers = ["BDT Time", "Symbol", "Side", "Strategy", "Entry", "Exit", "Fees", "RealizedPnL", "Result", "ExitReason"];
    const data = filteredRows.map((row) => [bdtDateTime(row.closedAt), row.pair, row.side, row.strategy, row.entryPrice, row.exitPrice, row.feesText, row.pnl, String(row.result), row.reason]);
    const csv = [headers, ...data].map((line) => line.map((cell) => `"${String(cell ?? "").replaceAll('"', '""')}"`).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8;" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `journal-${filters.dateFrom || "all"}-${filters.dateTo || "all"}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const exportPdf = () => {
    const popup = window.open("", "_blank", "width=1100,height=800");
    if (!popup) return;
    popup.document.write(`<html><head><title>Journal Export</title></head><body style="font-family:Arial;padding:24px"><h2>DayFrogd Journal</h2><table border="1" cellspacing="0" cellpadding="6" style="border-collapse:collapse;width:100%;font-size:12px"><thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Strategy</th><th>Exit</th><th>Fees</th><th>PnL</th><th>Result</th></tr></thead><tbody>${filteredRows.map((row) => `<tr><td>${bdtDateTime(row.closedAt)}</td><td>${row.pair}</td><td>${row.side}</td><td>${row.strategy}</td><td>${row.exitPrice || "N/A"}</td><td>${row.feesText}</td><td>${row.pnl}</td><td>${String(row.result)}</td></tr>`).join("")}</tbody></table></body></html>`);
    popup.document.close();
    popup.print();
  };

  return (
    <div className="space-y-6" id="trade-history-section">
      <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
        <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4">
          <div><h3 className="text-sm font-semibold text-white">Journal / Trade History</h3><p className="text-xs text-slate-500 mt-1">Persisted exit, fees and realized PnL. Unknown outcomes are not labelled as losses.</p></div>
          <div className="flex items-center gap-3 text-[10px] font-mono text-slate-500"><span>BDT {bdtDateTime(new Date().toISOString())}</span><button onClick={() => void loadJournal()} className="action-btn"><RefreshCw className="w-3 h-3 inline mr-1" />Refresh</button><button onClick={exportCsv} className="action-btn"><Download className="w-3 h-3 inline mr-1" />CSV</button><button onClick={exportPdf} className="action-btn"><FileDown className="w-3 h-3 inline mr-1" />PDF</button></div>
        </div>
        {error && <div className="mt-4 text-xs font-mono text-rose-300">{error}</div>}
        <div className="grid grid-cols-2 xl:grid-cols-6 gap-3 mt-5">
          <FilterField label="Date From"><input type="date" value={filters.dateFrom} onChange={(e) => setFilters((p) => ({ ...p, dateFrom: e.target.value }))} className="dashboard-input" /></FilterField>
          <FilterField label="Date To"><input type="date" value={filters.dateTo} onChange={(e) => setFilters((p) => ({ ...p, dateTo: e.target.value }))} className="dashboard-input" /></FilterField>
          <FilterField label="Symbol"><select value={filters.symbol} onChange={(e) => setFilters((p) => ({ ...p, symbol: e.target.value }))} className="dashboard-input"><option value="">All</option>{symbols.map((v) => <option key={v}>{v}</option>)}</select></FilterField>
          <FilterField label="Side"><select value={filters.side} onChange={(e) => setFilters((p) => ({ ...p, side: e.target.value }))} className="dashboard-input"><option value="ALL">All</option><option value="LONG">Long</option><option value="SHORT">Short</option></select></FilterField>
          <FilterField label="Strategy"><select value={filters.strategy} onChange={(e) => setFilters((p) => ({ ...p, strategy: e.target.value }))} className="dashboard-input"><option value="ALL">All</option>{strategies.map((v) => <option key={v}>{v}</option>)}</select></FilterField>
          <FilterField label="Result"><select value={filters.result} onChange={(e) => setFilters((p) => ({ ...p, result: e.target.value }))} className="dashboard-input"><option value="ALL">All</option><option value="PROFIT">PROFIT</option><option value="LOSS">LOSS</option><option value="UNKNOWN">UNKNOWN</option></select></FilterField>
          <FilterField label="Exit Reason"><select value={filters.exitReason} onChange={(e) => setFilters((p) => ({ ...p, exitReason: e.target.value }))} className="dashboard-input"><option value="ALL">All</option>{reasons.map((v) => <option key={v}>{v}</option>)}</select></FilterField>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1.45fr_0.55fr] gap-6">
        <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md overflow-hidden">
          <div className="flex justify-between mb-5"><h4 className="text-sm font-semibold text-white">Journal Trades Table</h4><span className="text-[10px] font-mono text-slate-500">{loading ? "Loading..." : `${filteredRows.length} rows`}</span></div>
          <div className="overflow-x-auto"><table className="w-full whitespace-nowrap"><thead><tr className="border-b border-slate-800 text-[10px] font-mono uppercase text-slate-500"><th className="p-3 text-left">Time</th><th className="p-3 text-left">Symbol</th><th className="p-3 text-left">Side</th><th className="p-3 text-left">Strategy</th><th className="p-3 text-right">Entry</th><th className="p-3 text-right">Exit</th><th className="p-3 text-right">Fees</th><th className="p-3 text-right">Realized PnL</th><th className="p-3 text-left">Result</th></tr></thead><tbody className="divide-y divide-slate-800/30 text-xs font-mono">{filteredRows.map((row) => <tr key={row.id} onClick={() => setSelectedId(row.id)} className="cursor-pointer hover:bg-slate-900/20"><td className="p-3">{bdtDateTime(row.closedAt)}</td><td className="p-3 text-white">{row.pair}</td><td className={`p-3 ${row.side === "LONG" ? "text-emerald-400" : "text-rose-400"}`}>{row.side}</td><td className="p-3">{row.strategy}</td><td className="p-3 text-right">{formatMoney(row.entryPrice)}</td><td className="p-3 text-right">{row.exitPrice > 0 ? formatMoney(row.exitPrice) : "N/A"}</td><td className="p-3 text-right">{row.feesText}</td><td className={`p-3 text-right ${row.pnl > 0 ? "text-emerald-400" : row.pnl < 0 ? "text-rose-400" : "text-slate-400"}`}>{formatMoney(row.pnl)}</td><td className="p-3">{String(row.result)}</td></tr>)}</tbody></table></div>
          {filteredRows.length === 0 && <div className="py-10 text-center text-xs font-mono text-slate-500">No journal trades matched the selected filters.</div>}
        </div>

        <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
          {selectedTrade ? <><div className="flex justify-between mb-4"><div><h4 className="text-sm font-semibold text-white">{selectedTrade.pair} Trade Detail</h4><p className="text-xs text-slate-500 mt-1">{selectedTrade.strategy} | {selectedTrade.side}</p></div><span className="text-[10px] font-mono text-slate-500">{detailLoading ? "Loading..." : String(selectedTrade.result)}</span></div><div className="grid grid-cols-2 gap-3 mb-4"><MiniMetric label="Fees" value={selectedTrade.feesText} /><MiniMetric label="Realized PnL" value={formatMoney(selectedTrade.pnl)} /><MiniMetric label="RR" value={selectedTrade.rrValue ? `${selectedTrade.rrValue.toFixed(2)}R` : "N/A"} /><MiniMetric label="Duration" value={selectedTrade.durationText} /></div><div className="panel"><div className="panel-title">Timeline</div>{selectedTrade.timeline.map((item) => <div key={item.label} className="flex justify-between text-xs py-1"><span className="text-slate-500">{item.label}</span><span>{bdtDateTime(item.value)}</span></div>)}</div><div className="panel"><div className="panel-title">Chart Markers</div><JournalChart candles={candles} trade={selectedTrade} /></div><div className="panel"><div className="panel-title">Execution Log</div>{selectedTrade.executionLog.map((line, i) => <div key={i} className="text-xs font-mono py-1">{line}</div>)}</div><div className="text-xs text-slate-300">{String(selectedTrade.result) === "UNKNOWN" ? "Exact close outcome is not available; it has not been counted as a loss." : `Exit reason: ${selectedTrade.reason}`}</div></> : <div className="py-12 text-center text-xs font-mono text-slate-500">Select a row to inspect trade detail.</div>}
        </div>
      </div>
    </div>
  );
}

function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="space-y-2 block"><span className="text-[10px] font-mono uppercase text-slate-500"><Filter className="w-3 h-3 inline mr-1" />{label}</span>{children}</label>;
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3"><div className="text-[10px] font-mono uppercase text-slate-500">{label}</div><div className="mt-2 text-xs font-semibold text-white">{value}</div></div>;
}

function JournalChart({ candles, trade }: { candles: MarketCandle[]; trade: JournalRow }) {
  const width = 420;
  const height = 180;
  const padding = 12;
  if (!candles.length) return <div className="py-10 text-center text-xs font-mono text-slate-500">No backend candles available.</div>;
  const markers = [trade.entryPrice, trade.stopLoss, trade.takeProfit, trade.exitPrice].filter((value) => value > 0);
  const high = Math.max(...candles.map((item) => item.high), ...markers);
  const low = Math.min(...candles.map((item) => item.low), ...markers);
  const range = Math.max(high - low, 1);
  const plotWidth = width - padding * 2;
  const plotHeight = height - padding * 2;
  const candleWidth = Math.max(plotWidth / candles.length - 2, 2);
  const getY = (value: number) => padding + ((high - value) / range) * plotHeight;
  return <svg viewBox={`0 0 ${width} ${height}`} className="w-full">{candles.map((candle, index) => { const x = padding + index * (plotWidth / candles.length); const openY = getY(candle.open); const closeY = getY(candle.close); const highY = getY(candle.high); const lowY = getY(candle.low); const bull = candle.close >= candle.open; return <g key={`${candle.timestamp}-${index}`}><line x1={x + candleWidth / 2} x2={x + candleWidth / 2} y1={highY} y2={lowY} stroke={bull ? "#10b981" : "#f43f5e"} /><rect x={x} y={Math.min(openY, closeY)} width={candleWidth} height={Math.max(Math.abs(closeY - openY), 1.5)} fill={bull ? "#10b981" : "#f43f5e"} /></g>; })}</svg>;
}
