import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { AccountResponse, Trade, TradeHistoryEntry } from "../types";

interface ActiveTradesProps {
  authToken?: string | null;
  trades: Trade[];
  tradeHistory: TradeHistoryEntry[];
  account: AccountResponse;
  onRefresh: () => Promise<void>;
}

type LiveTrade = Trade & {
  liveMetricsAvailable?: boolean;
  closeAllowed?: boolean;
  closeBlockedReason?: string | null;
  liquidationPrice?: number | null;
  positionValue?: number | null;
};

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
  if (!value) return "N/A";
  return BDT_DATE_TIME.format(new Date(value));
}

function numberValue(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

function hasNumber(value: unknown) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}

function formatMoney(value: number) {
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
}

function formatOptionalMoney(value: unknown) {
  return hasNumber(value) ? formatMoney(Number(value)) : "N/A";
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
  if (!value) return false;
  const left = new Date(value).toLocaleDateString("en-CA", { timeZone: "Asia/Dhaka" });
  const right = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Dhaka" });
  return left === right;
}

function closeButtonLabel(trade: LiveTrade, closing: boolean) {
  if (closing) return "Submitting...";
  const status = String(trade.rawStatus || "").toLowerCase();
  if (status === "close_requested") return "Close Pending";
  if (status === "close_pending_sync") return "Syncing Close";
  if (status === "close_uncertain") return "Close Uncertain";
  return "Market Close";
}

export default function ActiveTrades({ authToken, trades, tradeHistory, account, onRefresh }: ActiveTradesProps) {
  const bdtDayRef = useRef(new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Dhaka" }));
  const [closingId, setClosingId] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [reportedRealized, setReportedRealized] = useState<number | null>(null);

  const todayClosedTrades = useMemo(() => tradeHistory.filter((trade) => isTodayInBdt(trade.closedAt)), [tradeHistory]);
  const liveTrades = trades as LiveTrade[];
  const activeOpenedToday = useMemo(() => liveTrades.filter((trade) => isTodayInBdt(trade.timestamp)), [liveTrades]);
  const todaysOpened = todayClosedTrades.length + activeOpenedToday.length;
  const activeNow = liveTrades.length;
  const todaysClosed = todayClosedTrades.length;
  const todaysSlHit = todayClosedTrades.filter((trade) => trade.result === "LOSS").length;
  const todaysTpHit = todayClosedTrades.filter((trade) => trade.result === "PROFIT").length;
  const closedOnlyRealized = todayClosedTrades.reduce((sum, trade) => sum + numberValue(trade.pnl), 0);
  const todaysRealized = reportedRealized ?? closedOnlyRealized;
  const todaysUnrealized = liveTrades.reduce((sum, trade) => sum + numberValue(trade.unrealizedPnl), 0);
  const totalExposure = liveTrades.reduce(
    (sum, trade) => sum + (hasNumber(trade.positionValue) ? Math.abs(Number(trade.positionValue)) : 0),
    0,
  );
  const liveMetricCount = liveTrades.filter((trade) => trade.liveMetricsAvailable).length;

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
    if (!authToken) return;
    let cancelled = false;

    const loadDailyFinancials = async () => {
      try {
        const response = (await api.getMetrics(authToken)) as { today_realized_pnl?: number };
        const value = Number(response.today_realized_pnl);
        if (!cancelled) setReportedRealized(Number.isFinite(value) ? value : null);
      } catch {
        if (!cancelled) setReportedRealized(null);
      }
    };

    void loadDailyFinancials();
    const interval = setInterval(loadDailyFinancials, 10000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [authToken, trades.length, tradeHistory.length]);

  const handleMarketClose = async (trade: LiveTrade) => {
    setActionMessage(null);
    setActionError(null);
    if (!authToken) {
      setActionError("Session expired. Please log in again.");
      return;
    }
    if (!trade.journalId) {
      setActionError("Trade journal identity is unavailable; close was not sent.");
      return;
    }
    if (!trade.closeAllowed) {
      setActionError(trade.closeBlockedReason || "This trade is not currently safe to close.");
      return;
    }
    const confirmed = window.confirm(`Submit a reduce-only market close for ${trade.pair}?`);
    if (!confirmed) return;

    setClosingId(trade.id);
    try {
      const response = await api.marketCloseTrade(authToken, trade.journalId);
      if (!response.ok) {
        setActionError(response.detail || response.error || "Market close failed.");
      } else {
        setActionMessage(response.message || "Close submitted; waiting for exact exchange fill synchronization.");
      }
      await onRefresh();
    } catch (err: any) {
      setActionError(err?.message || "Market close failed.");
    } finally {
      setClosingId(null);
    }
  };

  return (
    <div className="space-y-6" id="active-trades-root">
      <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
        <div className="flex flex-col xl:flex-row justify-between gap-4">
          <div>
            <h3 className="text-lg font-bold text-white tracking-tight font-sans">Active Trades Monitor</h3>
            <p className="text-xs text-slate-500 mt-1">Authoritative Bybit position metrics and reduce-only close control.</p>
          </div>
          <div className="text-right text-[10px] font-mono text-slate-400">
            <div>BDT {formatBdtDateTime(new Date())}</div>
            <div className="mt-1">Live metrics: {liveMetricCount}/{activeNow}</div>
          </div>
        </div>

        {actionMessage && <div className="mt-4 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-xs text-emerald-300">{actionMessage}</div>}
        {actionError && <div className="mt-4 rounded-lg border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-xs text-rose-300">{actionError}</div>}

        <div className="grid grid-cols-2 xl:grid-cols-7 gap-3 mt-5">
          <SummaryCard label="Opened Today" value={String(todaysOpened)} tone="neutral" />
          <SummaryCard label="Active Now" value={String(activeNow)} tone="neutral" />
          <SummaryCard label="Closed Today" value={String(todaysClosed)} tone="neutral" />
          <SummaryCard label="SL Today" value={String(todaysSlHit)} tone="bad" />
          <SummaryCard label="TP Today" value={String(todaysTpHit)} tone="good" />
          <SummaryCard label="Realized PnL" value={formatMoney(todaysRealized)} tone={todaysRealized >= 0 ? "good" : "bad"} />
          <SummaryCard label="Unrealized PnL" value={formatMoney(todaysUnrealized)} tone={todaysUnrealized >= 0 ? "good" : "bad"} />
        </div>
      </div>

      <div className="bg-bento-card border border-slate-800 rounded-2xl overflow-hidden shadow-md">
        <div className="flex items-center justify-between gap-4 border-b border-slate-800 px-5 py-4">
          <div className="flex items-center gap-3">
            <h3 className="text-sm font-semibold text-white tracking-tight font-sans uppercase">Active Portfolio Positions</h3>
            <span className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-2 py-1 text-[10px] font-mono text-emerald-300">Exchange Synced</span>
          </div>
          <div className="text-right text-[10px] font-mono text-slate-400">
            <div>Total Exposure: <span className="text-white">{totalExposure > 0 ? formatMoney(totalExposure) : "N/A"}</span></div>
          </div>
        </div>

        {liveTrades.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1100px] border-collapse whitespace-nowrap">
              <thead>
                <tr className="border-b border-slate-800 bg-[#111318] text-[10px] font-mono uppercase tracking-wider text-sky-200/80">
                  <th className="px-4 py-4 text-left">Market Symbol</th>
                  <th className="px-4 py-4 text-left">Direction / Status</th>
                  <th className="px-4 py-4 text-center">Margin / Exposure</th>
                  <th className="px-4 py-4 text-center">Entry / Mark Price</th>
                  <th className="px-4 py-4 text-center">Risk Levels</th>
                  <th className="px-4 py-4 text-center">Floating PnL ($ / %)</th>
                  <th className="px-4 py-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80 text-sm">
                {liveTrades.map((trade) => {
                  const closing = closingId === trade.id;
                  const actionDisabled = closing || !trade.closeAllowed || !trade.journalId || !authToken;
                  const leverageText = hasNumber(trade.leverage) && numberValue(trade.leverage) > 0 ? `${numberValue(trade.leverage).toFixed(2)}X` : "N/A";
                  return (
                    <tr key={trade.id} className="bg-[#0E1116] transition-colors hover:bg-slate-900/60">
                      <td className="px-4 py-4">
                        <div className="text-lg font-bold text-white">{trade.pair.replace("USDT", "/USDT")}</div>
                        <div className="mt-1 text-[10px] font-mono text-slate-500">{trade.positionSynced ? "Position confirmed" : "Position unconfirmed"}</div>
                      </td>
                      <td className="px-4 py-4">
                        <span className={`inline-flex rounded-md border px-3 py-1 text-[11px] font-mono ${trade.direction === "LONG" ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300" : "border-rose-500/20 bg-rose-500/10 text-rose-300"}`}>
                          {trade.direction} {leverageText}
                        </span>
                        <div className="mt-2 text-[10px] font-mono uppercase text-slate-500">{trade.rawStatus || trade.status}</div>
                      </td>
                      <td className="px-4 py-4 text-center font-mono">
                        <div className="font-semibold text-white">{trade.liveMetricsAvailable ? formatOptionalMoney(trade.margin) : "N/A"}</div>
                        <div className="mt-1 text-[11px] text-slate-500">Exposure: {hasNumber(trade.positionValue) ? formatCompactMoney(Number(trade.positionValue)) : "N/A"}</div>
                      </td>
                      <td className="px-4 py-4 text-center font-mono">
                        <div className="text-slate-300">{formatOptionalMoney(trade.entryPrice)}</div>
                        <div className="mt-1 text-emerald-400">Mark: {trade.positionSynced ? formatOptionalMoney(trade.currentPrice) : "N/A"}</div>
                      </td>
                      <td className="px-4 py-4 text-center font-mono">
                        <div className="text-rose-400">SL: {formatOptionalMoney(trade.stopLoss)}</div>
                        <div className="mt-1 text-emerald-400">TP1: {formatOptionalMoney(trade.managementTp1 || trade.takeProfit)}</div>
                        <div className="mt-1 text-amber-300">Liq: {formatOptionalMoney(trade.liquidationPrice)}</div>
                      </td>
                      <td className="px-4 py-4 text-center font-mono">
                        {trade.liveMetricsAvailable ? (
                          <>
                            <div className={numberValue(trade.unrealizedPnl) >= 0 ? "text-emerald-400" : "text-rose-400"}>
                              {numberValue(trade.unrealizedPnl) >= 0 ? "+" : ""}{formatMoney(numberValue(trade.unrealizedPnl))}
                            </div>
                            <div className={`mt-1 ${numberValue(trade.pnlPercent) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                              ({numberValue(trade.pnlPercent) >= 0 ? "+" : ""}{formatPercent(numberValue(trade.pnlPercent))})
                            </div>
                          </>
                        ) : <span className="text-slate-500">N/A</span>}
                      </td>
                      <td className="px-4 py-4 text-right">
                        <button
                          type="button"
                          disabled={actionDisabled}
                          title={trade.closeBlockedReason || undefined}
                          onClick={() => void handleMarketClose(trade)}
                          className={`rounded-md border px-4 py-2 text-[11px] font-semibold ${actionDisabled ? "cursor-not-allowed border-slate-700 bg-slate-800/50 text-slate-500" : "cursor-pointer border-rose-500/20 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20"}`}
                        >
                          {closeButtonLabel(trade, closing)}
                        </button>
                        {!trade.closeAllowed && trade.closeBlockedReason && <div className="mt-2 max-w-[180px] whitespace-normal text-[9px] font-mono text-slate-500">{trade.closeBlockedReason}</div>}
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
  const styles = tone === "good"
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
