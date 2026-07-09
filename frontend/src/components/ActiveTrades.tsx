import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, Clock3, ShieldCheck, Target } from "lucide-react";
import { api } from "../api";
import { AccountResponse, MarketCandle, OrderBookResponse, Trade, TradeHistoryEntry } from "../types";

interface ActiveTradesProps {
  authToken: string | null;
  trades: Trade[];
  tradeHistory: TradeHistoryEntry[];
  account: AccountResponse;
  onRefresh: () => Promise<void>;
}

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

function formatBdtDateTime(value?: string | Date | null) {
  if (!value) {
    return "N/A";
  }
  return BDT_DATE_TIME.format(new Date(value));
}

function numberValue(value: unknown) {
  const numeric = Number(value || 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function formatMoney(value: number) {
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
}

function formatPercent(value: number) {
  return `${value.toFixed(2)}%`;
}

function formatCompactMoney(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(value);
}

function isTodayInBdt(value?: string | null) {
  if (!value) {
    return false;
  }
  const left = new Date(value).toLocaleDateString("en-CA", { timeZone: "Asia/Dhaka" });
  const right = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Dhaka" });
  return left === right;
}

export default function ActiveTrades({ authToken, trades, tradeHistory, account, onRefresh }: ActiveTradesProps) {
  const [selectedTradeId, setSelectedTradeId] = useState<string | null>(null);
  const [candles, setCandles] = useState<MarketCandle[]>([]);
  const [orderBook, setOrderBook] = useState<OrderBookResponse["orderbook"]>({ bids: [], asks: [] });
  const [panelLoading, setPanelLoading] = useState(false);
  const [panelError, setPanelError] = useState<string | null>(null);
  const bdtDayRef = useRef(new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Dhaka" }));

  const todayClosedTrades = useMemo(() => tradeHistory.filter((trade) => isTodayInBdt(trade.closedAt)), [tradeHistory]);
  const latestTrade = trades[0] || null;
  const selectedTrade = useMemo(() => {
    const activeMatch = trades.find((trade) => trade.id === selectedTradeId);
    if (activeMatch) {
      return activeMatch;
    }
    const historyMatch = tradeHistory.find((trade) => trade.id === selectedTradeId);
    return historyMatch || latestTrade || tradeHistory[0] || null;
  }, [latestTrade, selectedTradeId, tradeHistory, trades]);

  const todaysOpen = useMemo(() => trades.filter((trade) => isTodayInBdt(trade.timestamp)).length, [trades]);
  const todaysClosed = todayClosedTrades.length;
  const todaysSlHit = todayClosedTrades.filter((trade) => trade.result === "LOSS").length;
  const todaysTpHit = todayClosedTrades.filter((trade) => trade.result === "PROFIT").length;
  const todaysRealized = todayClosedTrades.reduce((sum, trade) => sum + numberValue(trade.pnl), 0);
  const todaysUnrealized = (account.positions.data || []).reduce((sum, position) => sum + numberValue(position.unrealisedPnl), 0);
  const totalExposure = trades.reduce((sum, trade) => sum + Math.abs(numberValue(trade.margin) || numberValue(trade.entryPrice) * numberValue(trade.size)), 0);

  useEffect(() => {
    if (!selectedTrade && (trades.length > 0 || tradeHistory.length > 0)) {
      setSelectedTradeId((trades[0] || tradeHistory[0]).id);
    }
  }, [selectedTrade, tradeHistory, trades]);

  useEffect(() => {
    const interval = setInterval(() => {
      const currentBdtDay = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Dhaka" });
      if (currentBdtDay !== bdtDayRef.current) {
        bdtDayRef.current = currentBdtDay;
        void onRefresh();
      }
    }, 10000);

    return () => clearInterval(interval);
  }, [onRefresh]);

  useEffect(() => {
    if (!authToken || !selectedTrade) {
      return;
    }

    let cancelled = false;

    const loadPanel = async () => {
      setPanelLoading(true);
      try {
        const [candleResponse, orderBookResponse] = await Promise.all([
          api.getMarketCandles(authToken, selectedTrade.pair, "1", 60),
          api.getOrderBook(authToken, selectedTrade.pair, 12),
        ]);
        if (!cancelled) {
          setCandles((candleResponse.candles || []).map((item) => ({
            ...item,
            open: numberValue(item.open),
            high: numberValue(item.high),
            low: numberValue(item.low),
            close: numberValue(item.close),
          })));
          setOrderBook(orderBookResponse.orderbook || { bids: [], asks: [] });
          setPanelError(candleResponse.error || orderBookResponse.error || null);
        }
      } catch (error: any) {
        if (!cancelled) {
          setPanelError(error?.message || "Failed to load selected trade monitor");
        }
      } finally {
        if (!cancelled) {
          setPanelLoading(false);
        }
      }
    };

    loadPanel();
    const interval = setInterval(loadPanel, 10000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [authToken, selectedTrade]);

  return (
    <div className="space-y-6" id="active-trades-root">
      <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
        <div className="flex flex-col xl:flex-row justify-between gap-4">
          <div>
            <h3 className="text-lg font-bold text-white tracking-tight font-sans">Active Trades Monitor</h3>
            <p className="text-xs text-slate-500 mt-1">Live BDT session overview for open and closed trade flow.</p>
          </div>
          <div className="text-[10px] font-mono text-slate-400">BDT {formatBdtDateTime(new Date())}</div>
        </div>

        <div className="grid grid-cols-2 xl:grid-cols-7 gap-3 mt-5">
          <SummaryCard label="Today's Open" value={String(todaysOpen)} tone="neutral" />
          <SummaryCard label="Active" value={String(trades.length)} tone="neutral" />
          <SummaryCard label="Closed" value={String(todaysClosed)} tone="neutral" />
          <SummaryCard label="SL Hit" value={String(todaysSlHit)} tone="bad" />
          <SummaryCard label="TP Hit" value={String(todaysTpHit)} tone="good" />
          <SummaryCard label="Realized PnL" value={formatMoney(todaysRealized)} tone={todaysRealized >= 0 ? "good" : "bad"} />
          <SummaryCard label="Unrealized PnL" value={formatMoney(todaysUnrealized)} tone={todaysUnrealized >= 0 ? "good" : "bad"} />
        </div>
      </div>

      {panelError && (
        <div className="bg-rose-500/10 border border-rose-500/20 text-rose-300 p-4 rounded-2xl text-xs font-mono">
          {panelError}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[0.64fr_0.36fr] gap-6">
        <div className="bg-bento-card border border-slate-800 rounded-2xl overflow-hidden shadow-md">
          <div className="flex items-center justify-between gap-4 border-b border-slate-800 px-5 py-4">
            <div className="flex items-center gap-3">
              <h3 className="text-sm font-semibold text-white tracking-tight font-sans uppercase">Active Portfolio Positions</h3>
              <span className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-2 py-1 text-[10px] font-mono text-emerald-300">Live Streams</span>
            </div>
            <div className="text-right text-[10px] font-mono text-slate-400">
              <div>Total Exposure: <span className="text-white">{formatMoney(totalExposure)}</span></div>
            </div>
          </div>

          {trades.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] border-collapse whitespace-nowrap">
                <thead>
                  <tr className="border-b border-slate-800 bg-[#111318] text-[10px] font-mono uppercase tracking-wider text-sky-200/80">
                    <th className="px-4 py-4 text-left">Market Symbol</th>
                    <th className="px-4 py-4 text-left">Direction</th>
                    <th className="px-4 py-4 text-center">Margin / Exposure</th>
                    <th className="px-4 py-4 text-center">Entry / Mark Price</th>
                    <th className="px-4 py-4 text-center">Stop / Profit Targets</th>
                    <th className="px-4 py-4 text-center">Floating PnL ($ / %)</th>
                    <th className="px-4 py-4 text-right">Action Executions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/80 text-sm">
                  {trades.map((trade) => {
                    const selected = selectedTrade?.id === trade.id;
                    const exposure = Math.abs(numberValue(trade.margin) || numberValue(trade.entryPrice) * numberValue(trade.size));
                    const markPrice = numberValue(trade.currentPrice || trade.entryPrice);
                    return (
                      <tr
                        key={trade.id}
                        onClick={() => setSelectedTradeId(trade.id)}
                        className={`cursor-pointer transition-colors ${selected ? "bg-slate-900/80" : "bg-[#0E1116] hover:bg-slate-900/60"}`}
                      >
                        <td className="px-4 py-4">
                          <div className="flex items-center gap-3">
                            <div className="text-lg font-bold text-white">{trade.pair.replace("USDT", "/USDT")}</div>
                            {selected && <span className="rounded-md border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-mono text-emerald-300">Viewing</span>}
                          </div>
                        </td>
                        <td className="px-4 py-4">
                          <span className={`inline-flex rounded-md border px-3 py-1 text-[11px] font-mono ${trade.direction === "LONG" ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300" : "border-rose-500/20 bg-rose-500/10 text-rose-300"}`}>
                            {trade.direction} {Math.max(1, Math.round(numberValue(trade.leverage)))}X
                          </span>
                        </td>
                        <td className="px-4 py-4 text-center font-mono">
                          <div className="font-semibold text-white">{formatMoney(numberValue(trade.margin))}</div>
                          <div className="mt-1 text-[11px] text-slate-500">Exposure: {formatCompactMoney(exposure)}</div>
                        </td>
                        <td className="px-4 py-4 text-center font-mono">
                          <div className="text-slate-300">{formatMoney(trade.entryPrice)}</div>
                          <div className="mt-1 text-emerald-400">Mark: {formatMoney(markPrice)}</div>
                        </td>
                        <td className="px-4 py-4 text-center font-mono">
                          <div className="text-rose-400">SL: {formatMoney(trade.stopLoss)}</div>
                          <div className="mt-1 text-emerald-400">TP: {formatMoney(trade.takeProfit)}</div>
                        </td>
                        <td className="px-4 py-4 text-center font-mono">
                          <div className={numberValue(trade.unrealizedPnl) >= 0 ? "text-emerald-400" : "text-rose-400"}>
                            {numberValue(trade.unrealizedPnl) >= 0 ? "+" : ""}{formatMoney(numberValue(trade.unrealizedPnl))}
                          </div>
                          <div className={`mt-1 ${numberValue(trade.pnlPercent) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                            ({numberValue(trade.pnlPercent) >= 0 ? "+" : ""}{formatPercent(numberValue(trade.pnlPercent))})
                          </div>
                        </td>
                        <td className="px-4 py-4 text-right">
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              setSelectedTradeId(trade.id);
                            }}
                            className="rounded-md border border-rose-500/20 bg-rose-500/10 px-4 py-2 text-[11px] font-semibold text-rose-300"
                          >
                            Market Close
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="px-6 py-12 text-center text-slate-500 font-mono text-xs">No active positions returned by the backend.</div>
          )}
        </div>

        <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
          {selectedTrade ? (
            <>
              <div className="flex items-center justify-between mb-5">
                <div>
                  <h3 className="text-sm font-semibold text-white tracking-tight font-sans">{selectedTrade.pair} Monitor</h3>
                  <p className="text-xs text-slate-500 mt-1">Selected trade chart, protection levels, and depth snapshot.</p>
                </div>
                <span className="text-[10px] font-mono text-slate-500">{panelLoading ? "Updating..." : selectedTrade.status}</span>
              </div>

              <div className="grid grid-cols-2 gap-3 mb-4">
                <MonitorMetric label="Direction" value={selectedTrade.direction} good={selectedTrade.direction === "LONG"} />
                <MonitorMetric label="Size" value={String(selectedTrade.size)} />
                <MonitorMetric label="Entry" value={formatMoney(selectedTrade.entryPrice)} />
                <MonitorMetric label="SL / TP" value={`${formatMoney(selectedTrade.stopLoss)} / ${formatMoney(selectedTrade.takeProfit)}`} />
                <MonitorMetric label="Mode" value={selectedTrade.executionMode || "demo"} />
                <MonitorMetric label="Timestamp" value={formatBdtDateTime(selectedTrade.closedAt || selectedTrade.timestamp)} />
              </div>

              <div className="rounded-2xl border border-slate-800 bg-[#0A0B0E] p-4">
                <div className="flex items-center justify-between mb-3 text-[10px] font-mono text-slate-500">
                  <span>Live backend chart</span>
                  <span>{candles.length} candles</span>
                </div>
                <MiniTradeChart candles={candles} entry={selectedTrade.entryPrice} stopLoss={selectedTrade.stopLoss} takeProfit={selectedTrade.takeProfit} />
              </div>

              <div className="grid grid-cols-2 gap-4 mt-4">
                <DepthPanel title="Bids" rows={orderBook.bids.slice(0, 6)} side="bid" />
                <DepthPanel title="Asks" rows={orderBook.asks.slice(0, 6)} side="ask" />
              </div>
            </>
          ) : (
            <div className="py-12 text-center text-slate-500 font-mono text-xs">Select a trade card to inspect its live monitor.</div>
          )}
        </div>
      </div>
    </div>
  );
}

function SummaryCard({ label, value, tone }: { label: string; value: string; tone: "good" | "bad" | "neutral" }) {
  const styles =
    tone === "good"
      ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
      : tone === "bad"
      ? "border-rose-500/20 bg-rose-500/10 text-rose-300"
      : "border-slate-800 bg-[#0A0B0E] text-slate-200";
  return (
    <div className={`rounded-xl border p-3 ${styles}`}>
      <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-2 text-sm font-semibold">{value}</div>
    </div>
  );
}

function MonitorMetric({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-3">
      <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-2 text-xs font-semibold ${good === undefined ? "text-white" : good ? "text-emerald-300" : "text-rose-300"}`}>{value}</div>
    </div>
  );
}

function DepthPanel({ title, rows, side }: { title: string; rows: Array<{ price: number; size: number }>; side: "bid" | "ask" }) {
  return (
    <div className="space-y-2">
      <div className={`text-[10px] font-mono uppercase tracking-wider ${side === "bid" ? "text-emerald-400" : "text-rose-400"}`}>{title}</div>
      {rows.map((row, index) => (
        <div
          key={`${title}-${index}`}
          className={`grid grid-cols-2 gap-2 text-[10px] font-mono px-3 py-2 rounded-lg border ${
            side === "bid" ? "bg-emerald-500/8 border-emerald-500/10 text-emerald-300" : "bg-rose-500/8 border-rose-500/10 text-rose-300"
          }`}
        >
          <span>{numberValue(row.price).toFixed(4)}</span>
          <span className="text-right">{numberValue(row.size).toFixed(4)}</span>
        </div>
      ))}
      {rows.length === 0 && <div className="text-[10px] font-mono text-slate-500">No depth rows.</div>}
    </div>
  );
}

function MiniTradeChart({
  candles,
  entry,
  stopLoss,
  takeProfit,
}: {
  candles: MarketCandle[];
  entry: number;
  stopLoss: number;
  takeProfit: number;
}) {
  const width = 480;
  const height = 220;
  const padding = 12;

  if (!candles.length) {
    return <div className="py-12 text-center text-xs font-mono text-slate-500">No live candles available.</div>;
  }

  const high = Math.max(...candles.map((item) => item.high), takeProfit, entry);
  const low = Math.min(...candles.map((item) => item.low), stopLoss, entry);
  const range = Math.max(high - low, 1);
  const plotWidth = width - padding * 2;
  const plotHeight = height - padding * 2;
  const candleWidth = Math.max(plotWidth / candles.length - 2, 2);
  const getY = (value: number) => padding + ((high - value) / range) * plotHeight;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full">
      {[entry, stopLoss, takeProfit].map((level, index) => (
        <line
          key={index}
          x1={padding}
          x2={width - padding}
          y1={getY(level)}
          y2={getY(level)}
          stroke={index === 0 ? "#94a3b8" : index === 1 ? "#f43f5e" : "#10b981"}
          strokeDasharray="5 5"
          strokeWidth="1"
        />
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
            <rect
              x={x}
              y={Math.min(openY, closeY)}
              width={candleWidth}
              height={Math.max(Math.abs(closeY - openY), 1.5)}
              rx="1"
              fill={isBull ? "#10b981" : "#f43f5e"}
            />
          </g>
        );
      })}
    </svg>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-slate-500">{label}</div>
      <div className="mt-1 text-slate-200">{value}</div>
    </div>
  );
}
