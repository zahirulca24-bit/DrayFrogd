import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api";
import {
  AccountResponse,
  BotControlState,
  ExecutableSignal,
  MarketTicker,
  SystemReadiness,
  Trade,
  TradeHistoryEntry,
} from "../types";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Bot,
  CheckCircle2,
  Clock3,
  Coins,
  Gauge,
  Layers3,
  Play,
  RadioTower,
  RefreshCw,
  ShieldCheck,
  Target,
  Wallet,
  XCircle,
  Zap,
} from "lucide-react";

interface DashboardViewProps {
  authToken: string | null;
  readiness: SystemReadiness;
  botStatus: BotControlState;
  account: AccountResponse;
  activeTrades: Trade[];
  signals: ExecutableSignal[];
  tradeHistory: TradeHistoryEntry[];
  lastSync?: Date | null;
  isStale?: boolean;
  actionLoading?: string | null;
  onRefreshAll: () => void;
  onStartEngine: () => Promise<void>;
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

function numberValue(value: unknown) {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function formatMoney(value: number) {
  const sign = value < 0 ? "-" : "";
  return `${sign}$${Math.abs(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatCompact(value: number) {
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(value);
}

function formatMarketChange(value: number) {
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
}

function formatPnlPercent(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function formatBdtDateTime(value?: string | Date | null) {
  if (!value) return "Not synced";
  return BDT_DATE_TIME.format(new Date(value));
}

function isTodayInBdt(value?: string | null) {
  if (!value) return false;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return false;
  const itemDay = parsed.toLocaleDateString("en-CA", { timeZone: "Asia/Dhaka" });
  const currentDay = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Dhaka" });
  return itemDay === currentDay;
}

function resolveUnrealizedPnl(wallet: Record<string, string | number>, account: AccountResponse) {
  const walletUnrealized = numberValue(wallet.totalPerpUPL);
  if (walletUnrealized !== 0) return walletUnrealized;
  return (account.positions.data || []).reduce(
    (sum, position) => sum + numberValue(position.unrealisedPnl),
    0,
  );
}

function resolveExposure(account: AccountResponse) {
  return (account.positions.data || []).reduce((sum, position) => {
    const positionValue = numberValue(position.positionValue);
    if (positionValue !== 0) return sum + Math.abs(positionValue);
    return sum + Math.abs(numberValue(position.size) * numberValue(position.markPrice));
  }, 0);
}

export default function DashboardView({
  authToken,
  readiness,
  botStatus,
  account,
  activeTrades,
  signals,
  tradeHistory,
  lastSync,
  isStale,
  actionLoading,
  onRefreshAll,
  onStartEngine,
}: DashboardViewProps) {
  const wallet = account.wallet.data || {};
  const totalEquity = numberValue(
    wallet.totalEquity || wallet.totalWalletBalance || wallet.totalMarginBalance,
  );
  const availableBalance = numberValue(
    wallet.totalAvailableBalance || wallet.totalAvailableBalanceByMp || wallet.totalWalletBalance,
  );
  const unrealizedPnl = resolveUnrealizedPnl(wallet, account);
  const exposure = resolveExposure(account);

  const todayRealizedPnl = useMemo(
    () =>
      tradeHistory
        .filter((trade) => isTodayInBdt(trade.closedAt))
        .reduce((sum, trade) => sum + numberValue(trade.pnl), 0),
    [tradeHistory],
  );
  const todayNetPnl = todayRealizedPnl + unrealizedPnl;
  const recentTrades = useMemo(() => activeTrades.slice(0, 4), [activeTrades]);
  const recentSignals = useMemo(() => signals.slice(0, 5), [signals]);

  const [overview, setOverview] = useState<{
    top_gainers: MarketTicker[];
    watchlist: MarketTicker[];
    server_time: string | null;
  }>({ top_gainers: [], watchlist: [], server_time: null });
  const [marketError, setMarketError] = useState<string | null>(null);

  useEffect(() => {
    if (!authToken) return;
    let cancelled = false;

    const loadOverview = async () => {
      try {
        const response = await api.getMarketOverview(authToken);
        if (!cancelled) {
          setOverview({
            top_gainers: response.top_gainers || [],
            watchlist: response.watchlist || [],
            server_time: response.server_time,
          });
          setMarketError(response.error || null);
        }
      } catch (error: any) {
        if (!cancelled) setMarketError(error?.message || "Market overview unavailable");
      }
    };

    void loadOverview();
    const interval = setInterval(loadOverview, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [authToken]);

  const running = botStatus.status === "running";
  const ready = readiness.ready_for_execution;
  const mode = (botStatus.execution_mode || readiness.mode || "demo").toUpperCase();
  const syncTime = overview.server_time || lastSync || undefined;

  return (
    <div className="space-y-4" id="dashboard-view-root">
      <section className="rounded-2xl border border-slate-800/80 bg-bento-card-sec/40 p-5 shadow-lg backdrop-blur-md">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <div className={`rounded-xl border p-2.5 ${running ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300" : "border-slate-700 bg-slate-800/70 text-slate-400"}`}>
                <Bot className="h-5 w-5" />
              </div>
              <div>
                <h1 className="text-xl font-bold tracking-tight text-white">DayFrogd Control Dashboard</h1>
                <p className="mt-1 text-xs text-slate-400">
                  {running
                    ? "Engine is running in protected automatic mode."
                    : "Engine is stopped. Start it once to scan, validate and execute in demo mode."}
                </p>
              </div>
              {isStale && (
                <span className="inline-flex items-center gap-1 rounded-full border border-rose-500/20 bg-rose-500/10 px-2.5 py-1 text-[10px] font-semibold text-rose-300">
                  <AlertTriangle className="h-3 w-3" /> STALE DATA
                </span>
              )}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <StatusPill label="Bot" value={running ? "RUNNING" : botStatus.status.toUpperCase()} tone={running ? "good" : "muted"} />
              <StatusPill label="Readiness" value={ready ? "READY" : "BLOCKED"} tone={ready ? "good" : "bad"} />
              <StatusPill label="Mode" value={mode} tone={mode === "LIVE" ? "warn" : "good"} />
              <StatusPill label="Auto" value={botStatus.auto_trading_enabled ? "ENABLED" : "DISABLED"} tone={botStatus.auto_trading_enabled ? "good" : "bad"} />
            </div>
          </div>

          <div className="flex w-full flex-col gap-3 sm:w-auto sm:min-w-[320px]">
            <div className="flex flex-col gap-2 sm:flex-row">
              <button
                type="button"
                onClick={onStartEngine}
                disabled={actionLoading === "bot-start" || running}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-5 py-3 text-xs font-semibold text-emerald-300 transition-colors hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Play className="h-4 w-4" />
                {actionLoading === "bot-start" ? "STARTING..." : running ? "ENGINE RUNNING" : "START ENGINE"}
              </button>
              <button
                type="button"
                onClick={onRefreshAll}
                disabled={actionLoading === "bot-start"}
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-800 bg-[#0A0B0E] px-5 py-3 text-xs font-semibold text-slate-300 transition-colors hover:border-slate-700 hover:text-white disabled:opacity-50"
              >
                <RefreshCw className="h-4 w-4" /> REFRESH
              </button>
            </div>
            <div className="flex items-center justify-end gap-2 text-[10px] font-mono text-slate-500">
              <Clock3 className="h-3.5 w-3.5" />
              BDT {formatBdtDateTime(syncTime)}
            </div>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-2 gap-3 xl:grid-cols-6" id="dashboard-kpi-grid">
        <KpiCard label="Total Equity" value={formatMoney(totalEquity)} icon={<Wallet className="h-4 w-4" />} tone="neutral" helper="Exchange account equity" />
        <KpiCard label="Available" value={formatMoney(availableBalance)} icon={<Coins className="h-4 w-4" />} tone="good" helper="Free trading balance" />
        <KpiCard label="Today's Realized" value={formatMoney(todayRealizedPnl)} icon={todayRealizedPnl >= 0 ? <ArrowUpRight className="h-4 w-4" /> : <ArrowDownRight className="h-4 w-4" />} tone={todayRealizedPnl >= 0 ? "good" : "bad"} helper="Closed trades today" />
        <KpiCard label="Unrealized" value={formatMoney(unrealizedPnl)} icon={<Layers3 className="h-4 w-4" />} tone={unrealizedPnl >= 0 ? "good" : "bad"} helper="Open-position PnL" />
        <KpiCard label="Today's Net" value={formatMoney(todayNetPnl)} icon={<Zap className="h-4 w-4" />} tone={todayNetPnl >= 0 ? "good" : "bad"} helper="Realized + unrealized" />
        <KpiCard label="Exposure" value={formatMoney(exposure)} icon={<ShieldCheck className="h-4 w-4" />} tone="warn" helper={`${activeTrades.length} active trade${activeTrades.length === 1 ? "" : "s"}`} />
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Panel title="Active Trades" subtitle="Live positions that need your attention." badge={`${activeTrades.length} open`}>
            {recentTrades.length > 0 ? (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {recentTrades.map((trade) => (
                  <TradeCard key={trade.id} trade={trade} />
                ))}
              </div>
            ) : (
              <EmptyState icon={<Target className="h-5 w-5" />} title="No active trades" text="Start the engine and wait for a validated signal. New positions will appear here." />
            )}
          </Panel>

          <Panel title="Latest Signals" subtitle="Most recent validated opportunities from the scanner." badge={`${signals.length} active`}>
            {recentSignals.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[680px] text-left">
                  <thead className="border-b border-slate-800 text-[10px] font-mono uppercase tracking-wider text-slate-500">
                    <tr>
                      <th className="px-3 py-3">Symbol</th>
                      <th className="px-3 py-3">Side</th>
                      <th className="px-3 py-3">Strategy</th>
                      <th className="px-3 py-3">Grade</th>
                      <th className="px-3 py-3">RR</th>
                      <th className="px-3 py-3 text-right">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/70">
                    {recentSignals.map((signal) => (
                      <tr key={signal.id} className="text-xs text-slate-300">
                        <td className="px-3 py-3 font-semibold text-white">{signal.pair}</td>
                        <td className={`px-3 py-3 font-mono ${signal.direction === "LONG" ? "text-emerald-400" : "text-rose-400"}`}>{signal.direction}</td>
                        <td className="px-3 py-3 text-slate-400">{signal.indicator || "Strategy signal"}</td>
                        <td className="px-3 py-3"><span className="rounded-md border border-sky-500/20 bg-sky-500/10 px-2 py-1 font-mono text-sky-300">{signal.grade}</span></td>
                        <td className="px-3 py-3 font-mono text-white">{numberValue(signal.rr).toFixed(2)}R</td>
                        <td className="px-3 py-3 text-right font-mono text-[10px] text-slate-400">{signal.executionStatus}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState icon={<RadioTower className="h-5 w-5" />} title="No active signals" text="The scanner is waiting for a setup that passes strategy and risk validation." />
            )}
          </Panel>
        </div>

        <div className="space-y-4">
          <Panel title="Safety & Capacity" subtitle="Current execution gates and limits.">
            <div className="space-y-3">
              <CheckRow label="Admin authentication" passed={readiness.checks.admin_auth_configured} />
              <CheckRow label="Exchange API keys" passed={readiness.checks.api_keys_present} />
              <CheckRow label="Exchange connection" passed={readiness.checks.exchange_reachable} />
              <CheckRow label="Wallet synchronization" passed={readiness.checks.wallet_fetch_success} />
            </div>
            <div className="my-4 border-t border-slate-800" />
            <div className="grid grid-cols-2 gap-3">
              <LimitCard label="Risk / trade" value={`${(numberValue(botStatus.risk_per_trade || 0.01) * 100).toFixed(2)}%`} />
              <LimitCard label="Leverage cap" value={`${numberValue(botStatus.leverage_cap || 5).toFixed(0)}x`} />
              <LimitCard label="Max open" value={String(botStatus.max_open_trades || 3)} />
              <LimitCard label="Daily trades" value={String(botStatus.max_daily_trades || 8)} />
            </div>
            {botStatus.emergency_stop && (
              <div className="mt-4 flex items-start gap-2 rounded-xl border border-rose-500/20 bg-rose-500/10 p-3 text-xs text-rose-300">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> Emergency stop is active. Execution is blocked.
              </div>
            )}
          </Panel>

          <Panel title="Market Pulse" subtitle="Compact market context without the dashboard chart." badge={marketError ? "Unavailable" : "Live"}>
            {marketError && (
              <div className="mb-3 rounded-xl border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-amber-300">{marketError}</div>
            )}
            <div className="space-y-2">
              {overview.top_gainers.slice(0, 5).map((ticker) => (
                <MarketRow key={ticker.symbol} ticker={ticker} />
              ))}
              {!marketError && overview.top_gainers.length === 0 && (
                <div className="py-6 text-center text-xs text-slate-500">Market data is loading.</div>
              )}
            </div>
            {overview.watchlist.length > 0 && (
              <div className="mt-4 border-t border-slate-800 pt-4">
                <div className="mb-2 text-[10px] font-mono uppercase tracking-wider text-slate-500">Watchlist</div>
                <div className="flex flex-wrap gap-2">
                  {overview.watchlist.slice(0, 6).map((ticker) => (
                    <span key={ticker.symbol} className="rounded-lg border border-slate-800 bg-[#0A0B0E] px-2.5 py-1.5 text-[10px] font-mono text-slate-300">
                      {ticker.symbol} <span className={ticker.price24hPcnt >= 0 ? "text-emerald-400" : "text-rose-400"}>{formatMarketChange(ticker.price24hPcnt)}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}
          </Panel>
        </div>
      </section>
    </div>
  );
}

function StatusPill({ label, value, tone }: { label: string; value: string; tone: "good" | "warn" | "muted" | "bad" }) {
  const toneClass =
    tone === "good"
      ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
      : tone === "warn"
        ? "border-amber-500/20 bg-amber-500/10 text-amber-300"
        : tone === "bad"
          ? "border-rose-500/20 bg-rose-500/10 text-rose-300"
          : "border-slate-800 bg-[#0A0B0E] text-slate-300";
  return (
    <div className={`flex items-center gap-2 rounded-xl border px-3 py-1.5 font-mono text-[10px] ${toneClass}`}>
      <span className="text-slate-500">{label.toUpperCase()}</span>
      <span className="font-semibold">{value}</span>
    </div>
  );
}

function KpiCard({ label, value, icon, tone, helper }: { label: string; value: string; icon: ReactNode; tone: "good" | "bad" | "warn" | "neutral"; helper: string }) {
  const toneClass =
    tone === "good"
      ? "border-emerald-500/10 bg-emerald-500/10 text-emerald-300"
      : tone === "bad"
        ? "border-rose-500/10 bg-rose-500/10 text-rose-300"
        : tone === "warn"
          ? "border-amber-500/10 bg-amber-500/10 text-amber-300"
          : "border-slate-700 bg-slate-800/80 text-slate-300";
  return (
    <div className="rounded-2xl border border-slate-800/80 bg-bento-card p-4 shadow-md">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[10px] font-mono font-semibold uppercase tracking-wider text-slate-400">{label}</span>
        <div className={`rounded-xl border p-2 ${toneClass}`}>{icon}</div>
      </div>
      <div className="mt-3 text-xl font-bold tracking-tight text-white">{value}</div>
      <div className="mt-1 text-[10px] text-slate-500">{helper}</div>
    </div>
  );
}

function Panel({ title, subtitle, badge, children }: { title: string; subtitle: string; badge?: string; children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-bento-card p-5 shadow-md">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-white">{title}</h2>
          <p className="mt-1 text-xs text-slate-500">{subtitle}</p>
        </div>
        {badge && <span className="shrink-0 rounded-lg border border-slate-800 bg-[#0A0B0E] px-2.5 py-1 text-[10px] font-mono text-slate-400">{badge}</span>}
      </div>
      {children}
    </div>
  );
}

function TradeCard({ trade }: { trade: Trade }) {
  const pnl = numberValue(trade.unrealizedPnl);
  const pnlPercent = numberValue(trade.pnlPercent);
  return (
    <div className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-sm font-bold text-white">{trade.pair}</div>
          <div className="mt-1 text-[10px] font-mono text-slate-500">{trade.strategy || "Exchange position"}</div>
        </div>
        <span className={`rounded-md border px-2 py-1 text-[10px] font-mono ${trade.direction === "LONG" ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300" : "border-rose-500/20 bg-rose-500/10 text-rose-300"}`}>
          {trade.direction}
        </span>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 text-xs">
        <Metric label="Entry" value={formatMoney(numberValue(trade.entryPrice))} />
        <Metric label="Mark" value={formatMoney(numberValue(trade.currentPrice))} />
        <Metric label="Stop" value={formatMoney(numberValue(trade.stopLoss))} tone="bad" />
        <Metric label="Target" value={formatMoney(numberValue(trade.takeProfit))} tone="good" />
      </div>
      <div className="mt-4 flex items-center justify-between border-t border-slate-800 pt-3">
        <span className="text-[10px] font-mono text-slate-500">UNREALIZED PNL</span>
        <span className={`text-sm font-semibold ${pnl >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
          {formatMoney(pnl)} <span className="text-[10px] font-mono">({formatPnlPercent(pnlPercent)})</span>
        </span>
      </div>
    </div>
  );
}

function CheckRow({ label, passed }: { label: string; passed: boolean }) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-slate-800 bg-[#0A0B0E] px-3 py-2.5">
      <span className="text-xs text-slate-300">{label}</span>
      <span className={`inline-flex items-center gap-1 text-[10px] font-mono ${passed ? "text-emerald-400" : "text-rose-400"}`}>
        {passed ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
        {passed ? "READY" : "BLOCKED"}
      </span>
    </div>
  );
}

function LimitCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-3">
      <div className="flex items-center gap-2 text-[10px] font-mono uppercase text-slate-500">
        <Gauge className="h-3.5 w-3.5" /> {label}
      </div>
      <div className="mt-2 text-lg font-semibold text-white">{value}</div>
    </div>
  );
}

function MarketRow({ ticker }: { ticker: MarketTicker }) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-slate-800 bg-[#0A0B0E] px-3 py-2.5">
      <div>
        <div className="text-xs font-semibold text-white">{ticker.symbol}</div>
        <div className="mt-1 text-[10px] font-mono text-slate-500">Turnover {formatCompact(ticker.turnover24h)}</div>
      </div>
      <div className="text-right">
        <div className="text-xs font-semibold text-white">{formatMoney(ticker.lastPrice)}</div>
        <div className={`mt-1 text-[10px] font-mono ${ticker.price24hPcnt >= 0 ? "text-emerald-400" : "text-rose-400"}`}>{formatMarketChange(ticker.price24hPcnt)}</div>
      </div>
    </div>
  );
}

function Metric({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "neutral" | "good" | "bad" }) {
  const valueClass = tone === "good" ? "text-emerald-400" : tone === "bad" ? "text-rose-400" : "text-white";
  return (
    <div>
      <div className="text-[10px] font-mono uppercase text-slate-500">{label}</div>
      <div className={`mt-1 font-mono ${valueClass}`}>{value}</div>
    </div>
  );
}

function EmptyState({ icon, title, text }: { icon: ReactNode; title: string; text: string }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-800 bg-[#0A0B0E] px-6 py-10 text-center">
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-3 text-slate-400">{icon}</div>
      <div className="mt-3 text-sm font-semibold text-white">{title}</div>
      <div className="mt-1 max-w-md text-xs leading-5 text-slate-500">{text}</div>
    </div>
  );
}
