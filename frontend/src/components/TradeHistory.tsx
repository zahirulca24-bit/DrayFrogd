import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Database,
  RefreshCw,
  Search,
  ShieldAlert,
  TimerReset,
} from "lucide-react";
import { api } from "../api";
import { JournalTradeEntry, LedgerAuditResponse, TradeHistoryEntry } from "../types";

interface TradeHistoryProps {
  authToken: string | null;
  history: TradeHistoryEntry[];
}

type TruthJournalTrade = JournalTradeEntry & {
  execution_key?: string | null;
  strategy_name?: string | null;
  strategy?: string | null;
  exit_price?: number | null;
  realized_pnl?: number | null;
  fees?: number | null;
  close_reason?: string | null;
  counts_as_trade?: boolean;
  trade_count_reason?: string | null;
  performance_eligible?: boolean;
  performance_exclusion_reason?: string | null;
  financial_reconciliation_status?: "reconciled" | "pending" | "excluded" | string;
  financial_truth_source?: string | null;
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

function formatBdt(value?: string | null) {
  if (!value) return "N/A";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "N/A" : BDT_DATE_TIME.format(date);
}

function formatMoney(value?: number | null) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "N/A";
  const amount = Number(value);
  return `${amount < 0 ? "-" : ""}$${Math.abs(amount).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  })}`;
}

function readable(value?: string | null, fallback = "Not recorded") {
  const normalized = String(value || "").trim();
  if (!normalized) return fallback;
  return normalized.replaceAll("_", " ").replace(/\s+/g, " ").replace(/^./, (char) => char.toUpperCase());
}

function statusTone(status: string) {
  const value = status.toLowerCase();
  if (value === "closed") return "border-emerald-500/20 bg-emerald-500/10 text-emerald-300";
  if (value.includes("pending") || value.includes("requested")) return "border-amber-500/20 bg-amber-500/10 text-amber-300";
  if (value.includes("uncertain") || value.includes("failed")) return "border-rose-500/20 bg-rose-500/10 text-rose-300";
  if (value === "active" || value === "partial_fill") return "border-sky-500/20 bg-sky-500/10 text-sky-300";
  return "border-slate-700 bg-slate-800/70 text-slate-300";
}

function fallbackRows(history: TradeHistoryEntry[]): TruthJournalTrade[] {
  return history.map((trade) => ({
    journal_id: trade.journalId || trade.id,
    symbol: trade.pair,
    direction: trade.direction.toLowerCase(),
    execution_mode: trade.executionMode || "demo",
    entry: trade.entryPrice,
    stop_loss: trade.stopLoss,
    take_profit: trade.takeProfit,
    quantity: trade.size,
    status: trade.rawStatus || trade.status.toLowerCase(),
    result: trade.result,
    sl_hit_reason: trade.slHitReason || null,
    order_id: trade.orderId || null,
    detected_at: trade.timestamp,
    opened_at: trade.timestamp,
    closed_at: trade.closedAt || null,
    exchange_metadata: {},
    exit_price: trade.exitPrice,
    realized_pnl: trade.pnl,
    fees: null,
    close_reason: trade.reason,
    counts_as_trade: false,
    trade_count_reason: "backend_truth_unavailable",
    performance_eligible: false,
    performance_exclusion_reason: "backend_truth_unavailable",
    financial_reconciliation_status: "excluded",
    financial_truth_source: null,
  }));
}

export default function TradeHistory({ authToken, history }: TradeHistoryProps) {
  const [journalTrades, setJournalTrades] = useState<TruthJournalTrade[]>([]);
  const [ledgerAudit, setLedgerAudit] = useState<LedgerAuditResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    if (!authToken) return;
    setLoading(true);
    try {
      const [journal, ledger] = await Promise.all([
        api.getJournalTrades(authToken),
        api.getLedgerAudit(authToken),
      ]);
      setJournalTrades((journal.trades || []) as TruthJournalTrade[]);
      setLedgerAudit(ledger);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Journal truth synchronization failed");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!authToken) return;
    let cancelled = false;
    const refresh = async () => {
      if (cancelled) return;
      await load();
    };
    void refresh();
    const interval = setInterval(refresh, 10_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [authToken]);

  const rows = useMemo(
    () => (journalTrades.length > 0 ? journalTrades : fallbackRows(history)),
    [history, journalTrades],
  );

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return rows;
    return rows.filter((trade) =>
      [
        trade.symbol,
        trade.strategy_name,
        trade.strategy,
        trade.status,
        trade.result,
        trade.close_reason,
        trade.order_id,
        trade.journal_id,
        trade.execution_key,
        trade.performance_exclusion_reason,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(normalized),
    );
  }, [query, rows]);

  useEffect(() => {
    if (!filtered.length) {
      setSelectedId(null);
      return;
    }
    if (!filtered.some((trade) => trade.journal_id === selectedId)) {
      setSelectedId(filtered[0].journal_id);
    }
  }, [filtered, selectedId]);

  const selected = filtered.find((trade) => trade.journal_id === selectedId) || null;
  const counted = rows.filter((trade) => trade.counts_as_trade === true);
  const active = counted.filter((trade) => ["active", "partial_fill", "close_requested", "close_uncertain"].includes(String(trade.status).toLowerCase()));
  const reconciledClosed = rows.filter((trade) => trade.performance_eligible === true);
  const pending = rows.filter((trade) => trade.financial_reconciliation_status === "pending");
  const excluded = rows.filter((trade) => trade.financial_reconciliation_status === "excluded");

  return (
    <div className="space-y-4" id="trade-history-section">
      <section className="rounded-2xl border border-slate-800/80 bg-bento-card-sec/40 p-5 shadow-lg">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h1 className="text-xl font-bold text-white">Journal / Trade History</h1>
            <p className="mt-1 text-xs text-slate-400">
              Every lifecycle row remains visible. Trade counts and Performance eligibility come only from backend financial truth.
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

      <section className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <SummaryCard label="Counted Trades" value={counted.length} icon={<Database className="h-4 w-4" />} />
        <SummaryCard label="Exchange Active" value={active.length} icon={<Activity className="h-4 w-4" />} tone="good" />
        <SummaryCard label="Reconciled Closed" value={reconciledClosed.length} icon={<CheckCircle2 className="h-4 w-4" />} tone="good" />
        <SummaryCard label="Sync Pending" value={pending.length} icon={<TimerReset className="h-4 w-4" />} tone="warn" />
        <SummaryCard label="Excluded / Audit" value={excluded.length} icon={<ShieldAlert className="h-4 w-4" />} tone="bad" />
      </section>

      <section className="rounded-2xl border border-slate-800 bg-bento-card p-4 shadow-md">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <label className="relative block w-full md:max-w-md">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search symbol, order, status, reason..."
              className="w-full rounded-xl border border-slate-800 bg-[#0A0B0E] py-2.5 pl-10 pr-3 text-xs text-white outline-none focus:border-slate-600"
            />
          </label>
          <div className="text-[10px] font-mono text-slate-500">
            Ledger: {ledgerAudit?.ok ? `${ledgerAudit.summary.trade_count} trade records` : "unavailable"}
          </div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.45fr_0.75fr]">
        <div className="overflow-hidden rounded-2xl border border-slate-800 bg-bento-card shadow-md">
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-xs">
              <thead className="border-b border-slate-800 bg-[#0A0B0E] text-[10px] uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-4 py-3">Trade</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Financial truth</th>
                  <th className="px-4 py-3 text-right">PnL</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/70">
                {filtered.map((trade) => {
                  const strategy = trade.strategy_name || trade.strategy || "unknown";
                  const selectedRow = trade.journal_id === selectedId;
                  return (
                    <tr
                      key={trade.journal_id}
                      onClick={() => setSelectedId(trade.journal_id)}
                      className={`cursor-pointer transition-colors ${selectedRow ? "bg-slate-800/70" : "hover:bg-slate-800/35"}`}
                    >
                      <td className="px-4 py-3">
                        <div className="font-semibold text-white">{trade.symbol} · {String(trade.direction).toUpperCase()}</div>
                        <div className="mt-1 text-[10px] text-slate-500">{strategy} · {formatBdt(trade.closed_at || trade.opened_at || trade.detected_at)}</div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-semibold ${statusTone(String(trade.status))}`}>
                          {readable(trade.status)}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className={trade.performance_eligible ? "text-emerald-300" : trade.financial_reconciliation_status === "pending" ? "text-amber-300" : "text-slate-400"}>
                          {trade.performance_eligible ? "PERFORMANCE ELIGIBLE" : String(trade.financial_reconciliation_status || "excluded").toUpperCase()}
                        </div>
                        <div className="mt-1 text-[10px] text-slate-500">
                          {readable(trade.performance_exclusion_reason || trade.trade_count_reason || trade.financial_truth_source)}
                        </div>
                      </td>
                      <td className={`px-4 py-3 text-right font-mono ${Number(trade.realized_pnl || 0) < 0 ? "text-rose-300" : "text-emerald-300"}`}>
                        {formatMoney(trade.realized_pnl)}
                      </td>
                    </tr>
                  );
                })}
                {!filtered.length && (
                  <tr><td colSpan={4} className="px-4 py-10 text-center text-slate-500">No Journal rows match this filter.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <aside className="rounded-2xl border border-slate-800 bg-bento-card p-4 shadow-md">
          {selected ? (
            <div className="space-y-4">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-slate-500">Selected lifecycle</div>
                <h2 className="mt-1 text-lg font-bold text-white">{selected.symbol}</h2>
                <p className="text-xs text-slate-400">{selected.journal_id}</p>
              </div>
              <Detail label="Counts as trade" value={selected.counts_as_trade ? "YES" : "NO"} />
              <Detail label="Count decision" value={readable(selected.trade_count_reason)} />
              <Detail label="Performance" value={selected.performance_eligible ? "ELIGIBLE" : "EXCLUDED"} />
              <Detail label="Exclusion reason" value={readable(selected.performance_exclusion_reason)} />
              <Detail label="Order ID" value={selected.order_id || "Unavailable"} mono />
              <Detail label="Exit / Fees" value={`${formatMoney(selected.exit_price)} / ${formatMoney(selected.fees)}`} />
              <Detail label="Realized PnL" value={formatMoney(selected.realized_pnl)} />
              <Detail label="Close source" value={readable(selected.financial_truth_source)} />
              <Detail label="Close reason" value={readable(selected.close_reason || selected.sl_hit_reason)} />
            </div>
          ) : (
            <div className="py-12 text-center text-sm text-slate-500">Select a Journal row.</div>
          )}
        </aside>
      </section>
    </div>
  );
}

function SummaryCard({ label, value, icon, tone = "neutral" }: { label: string; value: number; icon: React.ReactNode; tone?: "neutral" | "good" | "warn" | "bad" }) {
  const tones = {
    neutral: "text-slate-300",
    good: "text-emerald-300",
    warn: "text-amber-300",
    bad: "text-rose-300",
  };
  return (
    <div className="rounded-2xl border border-slate-800 bg-bento-card p-4 shadow-md">
      <div className={`flex items-center gap-2 ${tones[tone]}`}>{icon}<span className="text-[10px] uppercase tracking-wider">{label}</span></div>
      <div className="mt-3 text-2xl font-bold text-white">{value}</div>
    </div>
  );
}

function Detail({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-3">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 break-words text-xs text-slate-200 ${mono ? "font-mono" : ""}`}>{value}</div>
    </div>
  );
}
