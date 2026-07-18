import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { api } from "../api";
import { AccountResponse, JournalTradeEntry, Trade, TradeHistoryEntry } from "../types";

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

type TruthJournalTrade = JournalTradeEntry & {
  realized_pnl?: number | null;
  fees?: number | null;
  performance_eligible?: boolean;
  performance_exclusion_reason?: string | null;
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
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

function hasNumber(value: unknown) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}

function formatMoney(value: number) {
  return `${value < 0 ? "-" : ""}$${Math.abs(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  })}`;
}

function formatOptionalMoney(value: unknown) {
  return hasNumber(value) ? formatMoney(Number(value)) : "N/A";
}

function isTodayBdt(value?: string | null) {
  if (!value) return false;
  const date = new Date(value);
  return !Number.isNaN(date.getTime()) && BDT_DATE.format(date) === BDT_DATE.format(new Date());
}

function closeButtonLabel(trade: LiveTrade, closing: boolean) {
  if (closing) return "Submitting...";
  const status = String(trade.rawStatus || "").toLowerCase();
  if (status === "close_requested") return "Close Pending";
  if (status === "close_pending_sync") return "Syncing Close";
  if (status === "close_uncertain") return "Close Uncertain";
  return "Market Close";
}

export default function ActiveTrades({ authToken, trades, tradeHistory: _tradeHistory, account, onRefresh }: ActiveTradesProps) {
  const [journalTrades, setJournalTrades] = useState<TruthJournalTrade[]>([]);
  const [reportedRealized, setReportedRealized] = useState<number | null>(null);
  const [closingId, setClosingId] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [truthError, setTruthError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const liveTrades = trades as LiveTrade[];
  const reconciledToday = useMemo(
    () => journalTrades.filter((trade) => trade.performance_eligible === true && isTodayBdt(trade.closed_at)),
    [journalTrades],
  );
  const todaysWins = reconciledToday.filter((trade) => numberValue(trade.realized_pnl) > 0).length;
  const todaysLosses = reconciledToday.filter((trade) => numberValue(trade.realized_pnl) < 0).length;
  const todaysUnrealized = liveTrades.reduce((sum, trade) => sum + numberValue(trade.unrealizedPnl), 0);
  const totalExposure = liveTrades.reduce((sum, trade) => sum + Math.abs(numberValue(trade.positionValue)), 0);
  const walletEquity = numberValue(account.wallet?.data?.totalEquity);

  const syncTruth = async () => {
    if (!authToken) return;
    setSyncing(true);
    try {
      const [journal, metrics] = await Promise.all([
        api.getJournalTrades(authToken),
        api.getMetrics(authToken),
      ]);
      setJournalTrades((journal.trades || []) as TruthJournalTrade[]);
      const realized = Number(metrics.today_realized_pnl);
      setReportedRealized(Number.isFinite(realized) ? realized : null);
      setTruthError(null);
    } catch (err: any) {
      setTruthError(err?.message || "Daily trade truth unavailable");
      setReportedRealized(null);
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    if (!authToken) return;
    let cancelled = false;
    const refresh = async () => {
      if (!cancelled) await syncTruth();
    };
    void refresh();
    const interval = setInterval(refresh, 10_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [authToken, trades.length]);

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
    if (!window.confirm(`Submit a reduce-only market close for ${trade.pair}?`)) return;

    setClosingId(trade.id);
    try {
      const response = await api.marketCloseTrade(authToken, trade.journalId);
      if (!response.ok) setActionError(response.detail || response.error || "Market close failed.");
      else setActionMessage(response.message || "Close submitted; waiting for exact exchange fill synchronization.");
      await onRefresh();
      await syncTruth();
    } catch (err: any) {
      setActionError(err?.message || "Market close failed.");
    } finally {
      setClosingId(null);
    }
  };

  return (
    <div className="space-y-5" id="active-trades-root">
      <section className="rounded-2xl border border-slate-800 bg-bento-card p-5 shadow-md">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-lg font-bold text-white">Active Trades Monitor</h1>
            <p className="mt-1 text-xs text-slate-500">Open positions come from Bybit; daily closed counts use reconciled Journal truth only.</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-right text-[10px] font-mono text-slate-500">
              <div>BDT {BDT_DATE_TIME.format(new Date())}</div>
              <div>Wallet equity {walletEquity > 0 ? formatMoney(walletEquity) : "N/A"}</div>
            </div>
            <button onClick={() => void syncTruth()} disabled={syncing} className="rounded-lg border border-slate-700 bg-[#0A0B0E] p-2 text-slate-300 disabled:opacity-50">
              <RefreshCw className={`h-4 w-4 ${syncing ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>
        {(truthError || actionError) && <div className="mt-4 flex gap-2 rounded-xl border border-rose-500/20 bg-rose-500/10 p-3 text-xs text-rose-300"><AlertTriangle className="h-4 w-4 shrink-0" />{truthError || actionError}</div>}
        {actionMessage && <div className="mt-4 rounded-xl border border-emerald-500/20 bg-emerald-500/10 p-3 text-xs text-emerald-300">{actionMessage}</div>}

        <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
          <Summary label="Active" value={String(liveTrades.length)} />
          <Summary label="Closed Today" value={String(reconciledToday.length)} />
          <Summary label="Wins Today" value={String(todaysWins)} tone="good" />
          <Summary label="Losses Today" value={String(todaysLosses)} tone="bad" />
          <Summary label="Realized PnL" value={reportedRealized === null ? "N/A" : formatMoney(reportedRealized)} tone={(reportedRealized || 0) >= 0 ? "good" : "bad"} />
          <Summary label="Unrealized PnL" value={formatMoney(todaysUnrealized)} tone={todaysUnrealized >= 0 ? "good" : "bad"} />
          <Summary label="Exposure" value={totalExposure > 0 ? formatMoney(totalExposure) : "N/A"} />
        </div>
      </section>

      <section className="overflow-hidden rounded-2xl border border-slate-800 bg-bento-card shadow-md">
        <div className="border-b border-slate-800 px-5 py-4"><h2 className="text-sm font-semibold uppercase text-white">Exchange Positions</h2></div>
        {liveTrades.length ? (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-xs">
              <thead className="bg-[#0A0B0E] text-[10px] uppercase tracking-wider text-slate-500">
                <tr><th className="px-4 py-3">Position</th><th className="px-4 py-3">Entry / Mark</th><th className="px-4 py-3">SL / TP</th><th className="px-4 py-3">PnL</th><th className="px-4 py-3 text-right">Action</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-800/70">
                {liveTrades.map((trade) => {
                  const closing = closingId === trade.id;
                  const disabled = closing || !trade.closeAllowed || !trade.journalId || !authToken;
                  return (
                    <tr key={trade.id}>
                      <td className="px-4 py-4"><div className="font-bold text-white">{trade.pair}</div><div className="mt-1 text-[10px] text-slate-500">{trade.direction} · {trade.rawStatus || trade.status}</div></td>
                      <td className="px-4 py-4 font-mono"><div>{formatOptionalMoney(trade.entryPrice)}</div><div className="mt-1 text-sky-300">{formatOptionalMoney(trade.currentPrice)}</div></td>
                      <td className="px-4 py-4 font-mono"><div className="text-rose-300">SL {formatOptionalMoney(trade.stopLoss)}</div><div className="mt-1 text-emerald-300">TP {formatOptionalMoney(trade.takeProfit)}</div></td>
                      <td className={`px-4 py-4 font-mono ${numberValue(trade.unrealizedPnl) < 0 ? "text-rose-300" : "text-emerald-300"}`}>{trade.liveMetricsAvailable ? formatMoney(numberValue(trade.unrealizedPnl)) : "N/A"}</td>
                      <td className="px-4 py-4 text-right"><button type="button" onClick={() => void handleMarketClose(trade)} disabled={disabled} title={trade.closeBlockedReason || undefined} className="rounded-lg border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-[10px] font-semibold text-rose-300 disabled:cursor-not-allowed disabled:opacity-40">{closeButtonLabel(trade, closing)}</button></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : <div className="py-14 text-center text-sm text-slate-500">No open Bybit positions.</div>}
      </section>
    </div>
  );
}

function Summary({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "neutral" | "good" | "bad" }) {
  const toneClass = tone === "good" ? "text-emerald-300" : tone === "bad" ? "text-rose-300" : "text-white";
  return <div className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-3"><div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div><div className={`mt-2 font-mono text-lg font-bold ${toneClass}`}>{value}</div></div>;
}
