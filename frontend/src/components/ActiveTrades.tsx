import { useEffect, useMemo, useRef } from "react";
import { AccountResponse, Trade, TradeHistoryEntry } from "../types";

interface ActiveTradesProps {
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

export default function ActiveTrades({ trades, tradeHistory, account, onRefresh }: ActiveTradesProps) {
  const bdtDayRef = useRef(new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Dhaka" }));

  const todayClosedTrades = useMemo(() => tradeHistory.filter((trade) => isTodayInBdt(trade.closedAt)), [tradeHistory]);

  const todaysOpen = useMemo(() => trades.filter((trade) => isTodayInBdt(trade.timestamp)).length, [trades]);
  const todaysClosed = todayClosedTrades.length;
  const todaysSlHit = todayClosedTrades.filter((trade) => trade.result === "LOSS").length;
  const todaysTpHit = todayClosedTrades.filter((trade) => trade.result === "PROFIT").length;
  const todaysRealized = todayClosedTrades.reduce((sum, trade) => sum + numberValue(trade.pnl), 0);
  const todaysUnrealized = (account.positions.data || []).reduce((sum, position) => sum + numberValue(position.unrealisedPnl), 0);
  const totalExposure = trades.reduce((sum, trade) => sum + Math.abs(numberValue(trade.margin) || numberValue(trade.entryPrice) * numberValue(trade.size)), 0);

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
                      <th className="px-4 py-4 text-center">Stop / Management Targets</th>
                      <th className="px-4 py-4 text-center">Floating PnL ($ / %)</th>
                      <th className="px-4 py-4 text-right">Action Executions</th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/80 text-sm">
                  {trades.map((trade) => {
                    const exposure = Math.abs(numberValue(trade.margin) || numberValue(trade.entryPrice) * numberValue(trade.size));
                    const markPrice = numberValue(trade.currentPrice || trade.entryPrice);
                    return (
                      <tr
                        key={trade.id}
                        className="bg-[#0E1116] transition-colors hover:bg-slate-900/60"
                      >
                        <td className="px-4 py-4">
                          <div className="flex items-center gap-3">
                            <div className="text-lg font-bold text-white">{trade.pair.replace("USDT", "/USDT")}</div>
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
                          <div className="mt-1 text-emerald-400">TP1: {trade.managementTp1 ? formatMoney(trade.managementTp1) : formatMoney(trade.takeProfit)}</div>
                          {trade.managementTp2 && <div className="mt-1 text-sky-400">TP2: {formatMoney(trade.managementTp2)}</div>}
                          {trade.managementRunner && <div className="mt-1 text-teal-300">Runner: {formatMoney(trade.managementRunner)}</div>}
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
