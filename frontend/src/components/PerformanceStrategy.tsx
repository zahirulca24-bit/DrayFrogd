import { useEffect, useMemo, useState, type ReactNode } from "react";
import { AlertTriangle, BarChart3, RefreshCw, ShieldCheck, Target, TrendingUp } from "lucide-react";
import { api } from "../api";
import { JournalTradeEntry, MetricsResponse, StrategyAuditResponse, TradeHistoryEntry } from "../types";

interface PerformanceStrategyProps {
  authToken: string | null;
  history: TradeHistoryEntry[];
  metrics: MetricsResponse;
}

type TruthJournalTrade = JournalTradeEntry & {
  strategy_name?: string | null;
  strategy?: string | null;
  exit_price?: number | null;
  realized_pnl?: number | null;
  fees?: number | null;
  close_reason?: string | null;
  performance_eligible?: boolean;
  performance_exclusion_reason?: string | null;
  financial_truth_source?: string | null;
};

const BDT_DATE_TIME = new Intl.DateTimeFormat("en-BD", {
  timeZone: "Asia/Dhaka",
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: true,
});

function numberValue(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

function formatMoney(value?: number | null) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "N/A";
  const amount = Number(value);
  return `${amount < 0 ? "-" : ""}$${Math.abs(amount).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  })}`;
}

function formatPercent(value?: number | null) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "N/A";
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function formatBdt(value?: string | null) {
  if (!value) return "N/A";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "N/A" : BDT_DATE_TIME.format(date);
}

function resultFromPnl(value: number) {
  if (value > 0) return "PROFIT";
  if (value < 0) return "LOSS";
  return "FLAT";
}

export default function PerformanceStrategy({ authToken, history: _history, metrics }: PerformanceStrategyProps) {
  const [journalTrades, setJournalTrades] = useState<TruthJournalTrade[]>([]);
  const [strategyAudit, setStrategyAudit] = useState<StrategyAuditResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    if (!authToken) return;
    setLoading(true);
    try {
      const [journal, audit] = await Promise.all([
        api.getJournalTrades(authToken),
        api.getStrategyAudit(authToken),
      ]);
      setJournalTrades((journal.trades || []) as TruthJournalTrade[]);
      setStrategyAudit(audit);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Performance truth synchronization failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!authToken) return;
    let cancelled = false;
    const refresh = async () => {
      if (!cancelled) await load();
    };
    void refresh();
    const interval = setInterval(refresh, 10_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [authToken]);

  const eligible = useMemo(
    () => journalTrades.filter((trade) => trade.performance_eligible === true),
    [journalTrades],
  );
  const excluded = useMemo(
    () => journalTrades.filter((trade) => trade.performance_eligible !== true),
    [journalTrades],
  );

  const wins = eligible.filter((trade) => numberValue(trade.realized_pnl) > 0).length;
  const losses = eligible.filter((trade) => numberValue(trade.realized_pnl) < 0).length;
  const netPnl = eligible.reduce((sum, trade) => sum + numberValue(trade.realized_pnl), 0);
  const totalFees = eligible.reduce((sum, trade) => sum + Math.abs(numberValue(trade.fees)), 0);
  const winRate = wins + losses > 0 ? wins / (wins + losses) : null;

  const strategyRows = useMemo(() => {
    const buckets = new Map<string, { strategy: string; tradeCount: number; wins: number; losses: number; netPnl: number; winRate: number | null }>();
    eligible.forEach((trade) => {
      const strategy = String(trade.strategy_name || trade.strategy || "unknown");
      const bucket = buckets.get(strategy) || { strategy, tradeCount: 0, wins: 0, losses: 0, netPnl: 0, winRate: null };
      const pnl = numberValue(trade.realized_pnl);
      bucket.tradeCount += 1;
      bucket.netPnl += pnl;
      if (pnl > 0) bucket.wins += 1;
      if (pnl < 0) bucket.losses += 1;
      bucket.winRate = bucket.wins + bucket.losses > 0 ? bucket.wins / (bucket.wins + bucket.losses) : null;
      buckets.set(strategy, bucket);
    });
    return Array.from(buckets.values()).sort((left, right) => right.tradeCount - left.tradeCount);
  }, [eligible]);

  return (
    <div className="space-y-4" id="performance-strategy-section">
      <section className="rounded-2xl border border-slate-800/80 bg-bento-card-sec/40 p-5 shadow-lg">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-xl font-bold text-white">Performance & Strategy</h1>
            <p className="mt-1 text-xs text-slate-400">
              Only financially reconciled Bybit closes enter trade count, win/loss, PnL and strategy statistics.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-700 bg-[#0A0B0E] px-4 py-2 text-xs font-semibold text-slate-300 hover:text-white disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            {loading ? "SYNCING" : "REFRESH"}
          </button>
        </div>
        {error && (
          <div className="mt-4 flex items-start gap-2 rounded-xl border border-rose-500/20 bg-rose-500/10 p-3 text-xs text-rose-300">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
          </div>
        )}
      </section>

      <section className="grid grid-cols-2 gap-3 xl:grid-cols-6">
        <Kpi label="Eligible Trades" value={String(eligible.length)} icon={<ShieldCheck className="h-4 w-4" />} />
        <Kpi label="Wins" value={String(wins)} icon={<TrendingUp className="h-4 w-4" />} tone="good" />
        <Kpi label="Losses" value={String(losses)} icon={<Target className="h-4 w-4" />} tone="bad" />
        <Kpi label="Win Rate" value={formatPercent(winRate)} icon={<BarChart3 className="h-4 w-4" />} />
        <Kpi label="Net PnL" value={formatMoney(netPnl)} icon={<TrendingUp className="h-4 w-4" />} tone={netPnl >= 0 ? "good" : "bad"} />
        <Kpi label="Excluded Rows" value={String(excluded.length)} icon={<AlertTriangle className="h-4 w-4" />} tone="warn" />
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <div className="rounded-2xl border border-slate-800 bg-bento-card p-4 shadow-md">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-white">Strategy truth</h2>
              <p className="mt-1 text-[10px] text-slate-500">Backend-approved eligible closes only</p>
            </div>
            <span className="text-[10px] font-mono text-slate-500">Fees {formatMoney(totalFees)}</span>
          </div>
          <div className="space-y-2">
            {strategyRows.map((row) => (
              <div key={row.strategy} className="grid grid-cols-[1fr_auto_auto] items-center gap-3 rounded-xl border border-slate-800 bg-[#0A0B0E] p-3 text-xs">
                <div>
                  <div className="font-semibold text-white">{row.strategy}</div>
                  <div className="mt-1 text-[10px] text-slate-500">{row.tradeCount} reconciled trade{row.tradeCount === 1 ? "" : "s"}</div>
                </div>
                <div className="text-right">
                  <div className="text-slate-400">Win rate</div>
                  <div className="font-mono text-white">{formatPercent(row.winRate)}</div>
                </div>
                <div className={`text-right font-mono ${row.netPnl < 0 ? "text-rose-300" : "text-emerald-300"}`}>
                  {formatMoney(row.netPnl)}
                </div>
              </div>
            ))}
            {!strategyRows.length && <div className="py-10 text-center text-sm text-slate-500">No reconciled strategy trades yet.</div>}
          </div>
        </div>

        <div className="overflow-hidden rounded-2xl border border-slate-800 bg-bento-card shadow-md">
          <div className="border-b border-slate-800 p-4">
            <h2 className="font-semibold text-white">Eligible close ledger</h2>
            <p className="mt-1 text-[10px] text-slate-500">Excluded lifecycle rows remain visible on the Journal page.</p>
          </div>
          <div className="max-h-[520px] overflow-auto">
            <table className="min-w-full text-left text-xs">
              <thead className="sticky top-0 bg-[#0A0B0E] text-[10px] uppercase tracking-wider text-slate-500">
                <tr><th className="px-4 py-3">Trade</th><th className="px-4 py-3">Result</th><th className="px-4 py-3 text-right">PnL / Fees</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-800/70">
                {eligible.map((trade) => {
                  const pnl = numberValue(trade.realized_pnl);
                  return (
                    <tr key={trade.journal_id}>
                      <td className="px-4 py-3">
                        <div className="font-semibold text-white">{trade.symbol} · {String(trade.direction).toUpperCase()}</div>
                        <div className="mt-1 text-[10px] text-slate-500">{trade.strategy_name || trade.strategy || "unknown"} · {formatBdt(trade.closed_at)}</div>
                      </td>
                      <td className="px-4 py-3"><span className="rounded-full border border-slate-700 px-2 py-1 text-[10px] text-slate-300">{resultFromPnl(pnl)}</span></td>
                      <td className="px-4 py-3 text-right font-mono">
                        <div className={pnl < 0 ? "text-rose-300" : "text-emerald-300"}>{formatMoney(pnl)}</div>
                        <div className="mt-1 text-[10px] text-slate-500">fee {formatMoney(trade.fees)}</div>
                      </td>
                    </tr>
                  );
                })}
                {!eligible.length && <tr><td colSpan={3} className="px-4 py-12 text-center text-slate-500">No financially reconciled closes available.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-800 bg-bento-card p-4 text-xs text-slate-400 shadow-md">
        <div className="grid gap-2 md:grid-cols-4">
          <TruthLine label="Dashboard daily source" value={metrics.today_financial_source} />
          <TruthLine label="Dashboard account net" value={formatMoney(metrics.today_account_net_pnl)} />
          <TruthLine label="Journal reconciliation gap" value={metrics.reconciliation_gap === null ? "N/A" : formatMoney(metrics.reconciliation_gap)} />
          <TruthLine label="Audit ledger matches" value={String(strategyAudit?.summary.ledger_matched_trades ?? 0)} />
        </div>
      </section>
    </div>
  );
}

function Kpi({ label, value, icon, tone = "neutral" }: { label: string; value: string; icon: ReactNode; tone?: "neutral" | "good" | "warn" | "bad" }) {
  const tones = { neutral: "text-slate-300", good: "text-emerald-300", warn: "text-amber-300", bad: "text-rose-300" };
  return <div className="rounded-2xl border border-slate-800 bg-bento-card p-4 shadow-md"><div className={`flex items-center gap-2 ${tones[tone]}`}>{icon}<span className="text-[10px] uppercase tracking-wider">{label}</span></div><div className="mt-3 text-xl font-bold text-white">{value}</div></div>;
}

function TruthLine({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-3"><div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div><div className="mt-1 font-mono text-slate-200">{value}</div></div>;
}
