import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  Filter,
  Play,
  RadioTower,
  RefreshCw,
  ShieldAlert,
  Target,
  Zap,
} from "lucide-react";
import { api } from "../api";
import { ExecutableSignal, ExecuteTradeResponse, MarketTicker } from "../types";

interface SignalEngineProps {
  authToken: string | null;
  signals: ExecutableSignal[];
  scanResults: ExecutableSignal[];
  loading: boolean;
  onRunScan: () => Promise<void>;
  onRefresh: () => Promise<void>;
  onExecuteSignal: (signal: {
    symbol: string;
    direction: string;
    entry: number;
    stop_loss: number;
    take_profit: number;
    risk_reward: number;
    detected_at?: string | null;
    status: string;
  }) => Promise<ExecuteTradeResponse>;
}

type SignalFilter = "ALL" | "READY" | "NEAR_SETUP" | "BLOCKED";

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
  if (!value) return "Not available";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Not available";
  return BDT_DATE_TIME.format(parsed);
}

function formatMoney(value: number) {
  return `$${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: value >= 1000 ? 2 : 4,
  })}`;
}

function formatCompact(value: number) {
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(value);
}

function numberValue(value: unknown) {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function statusGroup(signal: ExecutableSignal): SignalFilter {
  if (signal.executionStatus === "READY") return "READY";
  if (signal.executionStatus === "NEAR_SETUP") return "NEAR_SETUP";
  return "BLOCKED";
}

function statusLabel(signal: ExecutableSignal) {
  const labels: Record<string, string> = {
    READY: "Ready",
    NEAR_SETUP: "Near setup",
    BLOCKED: "Blocked",
    EXPIRED: "Expired",
    FAILED: "Failed",
    EXECUTING: "Executing",
    EXECUTED: "Executed",
    VALIDATED: "Validated",
    NEW: "New",
  };
  return labels[signal.executionStatus] || signal.executionStatus.replaceAll("_", " ");
}

function statusTone(signal: ExecutableSignal) {
  if (["READY", "VALIDATED", "EXECUTED"].includes(signal.executionStatus)) {
    return "border-emerald-500/20 bg-emerald-500/10 text-emerald-300";
  }
  if (["NEAR_SETUP", "EXECUTING", "NEW"].includes(signal.executionStatus)) {
    return "border-amber-500/20 bg-amber-500/10 text-amber-300";
  }
  return "border-rose-500/20 bg-rose-500/10 text-rose-300";
}

function gradePriority(grade: string) {
  if (grade === "A+") return 0;
  if (grade === "A") return 1;
  if (grade === "B+") return 2;
  return 9;
}

function normalizeSignals(signals: ExecutableSignal[]) {
  const statusPriority: Record<string, number> = {
    READY: 0,
    EXECUTING: 1,
    NEAR_SETUP: 2,
    VALIDATED: 3,
    NEW: 4,
    BLOCKED: 5,
    FAILED: 6,
    EXPIRED: 7,
    EXECUTED: 8,
  };

  const unique = new Map<string, ExecutableSignal>();
  signals.forEach((signal) => {
    const key = signal.id || `${signal.pair}-${signal.timestamp}-${signal.direction}`;
    const current = unique.get(key);
    if (!current || signal.score > current.score) unique.set(key, signal);
  });

  return [...unique.values()].sort((a, b) => {
    const statusDelta = (statusPriority[a.executionStatus] ?? 99) - (statusPriority[b.executionStatus] ?? 99);
    if (statusDelta !== 0) return statusDelta;
    const gradeDelta = gradePriority(a.grade) - gradePriority(b.grade);
    if (gradeDelta !== 0) return gradeDelta;
    return b.score - a.score;
  });
}

function latestSignalTime(signals: ExecutableSignal[]) {
  const timestamps = signals
    .map((signal) => new Date(signal.timestamp).getTime())
    .filter((value) => Number.isFinite(value));
  if (!timestamps.length) return null;
  return new Date(Math.max(...timestamps));
}

function readableReason(reason?: string) {
  if (!reason) return "No rejection reason recorded.";
  return reason
    .replaceAll("_", " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^./, (character) => character.toUpperCase());
}

function validLevels(signal: ExecutableSignal) {
  const entry = numberValue(signal.entryPrice);
  const stop = numberValue(signal.stopLoss);
  const target = numberValue(signal.takeProfit);
  if (entry <= 0 || stop <= 0 || target <= 0) return false;
  if (signal.direction === "LONG") return stop < entry && entry < target;
  return target < entry && entry < stop;
}

export default function SignalEngine({
  authToken,
  signals,
  scanResults,
  loading,
  onRunScan,
  onRefresh,
  onExecuteSignal,
}: SignalEngineProps) {
  const [overview, setOverview] = useState<{
    top_gainers: MarketTicker[];
    watchlist: MarketTicker[];
  }>({ top_gainers: [], watchlist: [] });
  const [marketError, setMarketError] = useState<string | null>(null);
  const [selectedSignalId, setSelectedSignalId] = useState<string | null>(null);
  const [filter, setFilter] = useState<SignalFilter>("ALL");
  const [executionFeedback, setExecutionFeedback] = useState<Record<string, string>>({});
  const [executingId, setExecutingId] = useState<string | null>(null);

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

  const tickerMap = useMemo(() => {
    const map = new Map<string, MarketTicker>();
    [...overview.top_gainers, ...overview.watchlist].forEach((ticker) => map.set(ticker.symbol, ticker));
    return map;
  }, [overview]);

  const allSignals = useMemo(() => normalizeSignals(scanResults), [scanResults]);
  const filteredSignals = useMemo(
    () => (filter === "ALL" ? allSignals : allSignals.filter((signal) => statusGroup(signal) === filter)),
    [allSignals, filter],
  );

  useEffect(() => {
    if (!filteredSignals.length) {
      setSelectedSignalId(null);
      return;
    }
    if (!filteredSignals.some((signal) => signal.id === selectedSignalId)) {
      setSelectedSignalId(filteredSignals[0].id);
    }
  }, [filteredSignals, selectedSignalId]);

  const selectedSignal = useMemo(
    () => filteredSignals.find((signal) => signal.id === selectedSignalId) || filteredSignals[0] || null,
    [filteredSignals, selectedSignalId],
  );

  const readyCount = allSignals.filter((signal) => signal.executionStatus === "READY").length;
  const nearCount = allSignals.filter((signal) => signal.executionStatus === "NEAR_SETUP").length;
  const blockedCount = allSignals.filter((signal) => statusGroup(signal) === "BLOCKED").length;
  const premiumCount = allSignals.filter((signal) => signal.grade === "A+" || signal.grade === "A").length;
  const latestScanAt = latestSignalTime(allSignals);

  const executeSelected = async (signal: ExecutableSignal) => {
    setExecutingId(signal.id);
    setExecutionFeedback((current) => ({ ...current, [signal.id]: "Submitting demo execution..." }));
    try {
      const result = await onExecuteSignal({
        symbol: signal.pair,
        direction: signal.direction.toLowerCase(),
        entry: signal.entryPrice,
        stop_loss: signal.stopLoss,
        take_profit: signal.takeProfit,
        risk_reward: signal.rr,
        detected_at: signal.timestamp,
        status: "active",
      });
      setExecutionFeedback((current) => ({
        ...current,
        [signal.id]: result.ok
          ? result.warning || "Execution submitted successfully."
          : result.error || "Execution failed.",
      }));
    } finally {
      setExecutingId(null);
    }
  };

  return (
    <div className="space-y-4" id="signal-engine-root">
      <section className="rounded-2xl border border-slate-800/80 bg-bento-card-sec/40 p-5 shadow-lg backdrop-blur-md">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="rounded-xl border border-sky-500/20 bg-sky-500/10 p-2.5 text-sky-300">
                <RadioTower className="h-5 w-5" />
              </div>
              <div>
                <h1 className="text-xl font-bold tracking-tight text-white">Signal Engine</h1>
                <p className="mt-1 text-xs text-slate-400">
                  Review scanner decisions, understand rejection reasons, and inspect trade levels before execution.
                </p>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-2 text-[10px] font-mono text-slate-500">
              <span className="inline-flex items-center gap-1 rounded-lg border border-slate-800 bg-[#0A0B0E] px-2.5 py-1.5">
                <Clock3 className="h-3.5 w-3.5" /> Last result: {formatBdtDateTime(latestScanAt)}
              </span>
              <span className="rounded-lg border border-slate-800 bg-[#0A0B0E] px-2.5 py-1.5">
                Auto queue: {signals.length}
              </span>
            </div>
          </div>

          <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
            <button
              type="button"
              onClick={onRunScan}
              disabled={loading}
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-sky-500/20 bg-sky-500/10 px-5 py-3 text-xs font-semibold text-sky-300 transition-colors hover:bg-sky-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Play className="h-4 w-4" />
              {loading ? "SCANNING..." : "RUN DIAGNOSTIC SCAN"}
            </button>
            <button
              type="button"
              onClick={onRefresh}
              disabled={loading}
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-800 bg-[#0A0B0E] px-5 py-3 text-xs font-semibold text-slate-300 transition-colors hover:border-slate-700 hover:text-white disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> REFRESH
            </button>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <SummaryCard label="Total results" value={allSignals.length} icon={<Filter className="h-4 w-4" />} tone="neutral" />
        <SummaryCard label="Ready" value={readyCount} icon={<CheckCircle2 className="h-4 w-4" />} tone="good" />
        <SummaryCard label="Near setup" value={nearCount} icon={<Target className="h-4 w-4" />} tone="warn" />
        <SummaryCard label="Blocked" value={blockedCount} icon={<ShieldAlert className="h-4 w-4" />} tone="bad" />
        <SummaryCard label="A+ / A grade" value={premiumCount} icon={<Zap className="h-4 w-4" />} tone="accent" />
      </section>

      {marketError && (
        <div className="flex items-start gap-2 rounded-2xl border border-amber-500/20 bg-amber-500/10 p-4 text-xs text-amber-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          Market enrichment unavailable: {marketError}. Scanner results remain visible.
        </div>
      )}

      <section className="rounded-2xl border border-slate-800 bg-bento-card p-4 shadow-md">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-white">Result Filters</h2>
            <p className="mt-1 text-xs text-slate-500">Prioritize executable setups and investigate blocked ones separately.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {(["ALL", "READY", "NEAR_SETUP", "BLOCKED"] as SignalFilter[]).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setFilter(value)}
                className={`rounded-lg border px-3 py-2 text-[10px] font-mono font-semibold transition-colors ${
                  filter === value
                    ? "border-sky-500/20 bg-sky-500/10 text-sky-300"
                    : "border-slate-800 bg-[#0A0B0E] text-slate-500 hover:border-slate-700 hover:text-slate-300"
                }`}
              >
                {value === "ALL" ? "ALL" : value === "NEAR_SETUP" ? "NEAR SETUP" : value}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-[0.42fr_0.58fr]">
        <div className="rounded-2xl border border-slate-800 bg-bento-card p-4 shadow-md">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-white">Scanner Results</h2>
              <p className="mt-1 text-xs text-slate-500">Sorted by readiness, grade, and confidence score.</p>
            </div>
            <span className="rounded-lg border border-slate-800 bg-[#0A0B0E] px-2.5 py-1 text-[10px] font-mono text-slate-500">
              {filteredSignals.length} shown
            </span>
          </div>

          <div className="max-h-[720px] space-y-2 overflow-y-auto pr-1">
            {filteredSignals.map((signal) => (
              <SignalListItem
                key={signal.id}
                signal={signal}
                ticker={tickerMap.get(signal.pair)}
                selected={selectedSignal?.id === signal.id}
                onSelect={() => setSelectedSignalId(signal.id)}
              />
            ))}
            {filteredSignals.length === 0 && (
              <EmptyState
                icon={<RadioTower className="h-5 w-5" />}
                title="No matching results"
                text={allSignals.length ? "Choose another filter to review scanner results." : "Run a diagnostic scan to populate this page."}
              />
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-bento-card p-5 shadow-md">
          {selectedSignal ? (
            <SignalDetail
              signal={selectedSignal}
              ticker={tickerMap.get(selectedSignal.pair)}
              feedback={executionFeedback[selectedSignal.id]}
              executing={executingId === selectedSignal.id}
              onExecute={() => executeSelected(selectedSignal)}
            />
          ) : (
            <EmptyState
              icon={<Target className="h-5 w-5" />}
              title="Select a signal"
              text="Choose a scanner result to inspect setup quality, price levels, and the exact block reason."
            />
          )}
        </div>
      </section>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  icon,
  tone,
}: {
  label: string;
  value: number;
  icon: ReactNode;
  tone: "good" | "warn" | "bad" | "neutral" | "accent";
}) {
  const toneClass =
    tone === "good"
      ? "border-emerald-500/10 bg-emerald-500/10 text-emerald-300"
      : tone === "warn"
        ? "border-amber-500/10 bg-amber-500/10 text-amber-300"
        : tone === "bad"
          ? "border-rose-500/10 bg-rose-500/10 text-rose-300"
          : tone === "accent"
            ? "border-sky-500/10 bg-sky-500/10 text-sky-300"
            : "border-slate-700 bg-slate-800/80 text-slate-300";
  return (
    <div className="rounded-2xl border border-slate-800 bg-bento-card p-4 shadow-md">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[10px] font-mono font-semibold uppercase tracking-wider text-slate-500">{label}</span>
        <span className={`rounded-xl border p-2 ${toneClass}`}>{icon}</span>
      </div>
      <div className="mt-3 text-2xl font-bold text-white">{value}</div>
    </div>
  );
}

function SignalListItem({
  signal,
  ticker,
  selected,
  onSelect,
}: {
  signal: ExecutableSignal;
  ticker?: MarketTicker;
  selected: boolean;
  onSelect: () => void;
}) {
  const price = ticker ? numberValue(ticker.lastPrice) : numberValue(signal.price);
  const change = ticker ? numberValue(ticker.price24hPcnt) * 100 : null;
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full rounded-xl border p-4 text-left transition-colors ${
        selected
          ? "border-sky-500/30 bg-sky-500/10"
          : "border-slate-800 bg-[#0A0B0E] hover:border-slate-700 hover:bg-slate-900/60"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-bold text-white">{signal.pair}</span>
            <span className={`rounded-md border px-2 py-1 text-[10px] font-mono ${signal.direction === "LONG" ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300" : "border-rose-500/20 bg-rose-500/10 text-rose-300"}`}>
              {signal.direction}
            </span>
            <span className="rounded-md border border-slate-700 bg-slate-800/70 px-2 py-1 text-[10px] font-mono text-slate-300">{signal.grade}</span>
          </div>
          <div className="mt-2 text-[10px] font-mono text-slate-500">{signal.indicator || "Strategy setup"}</div>
        </div>
        <span className={`shrink-0 rounded-lg border px-2.5 py-1 text-[10px] font-mono font-semibold ${statusTone(signal)}`}>
          {statusLabel(signal)}
        </span>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-3 text-xs">
        <MiniMetric label="Price" value={formatMoney(price)} />
        <MiniMetric label="Score" value={`${numberValue(signal.score).toFixed(0)}%`} />
        <MiniMetric label="RR" value={`${numberValue(signal.rr).toFixed(2)}R`} />
      </div>

      <div className="mt-3 flex items-center justify-between gap-3 border-t border-slate-800 pt-3 text-[10px] font-mono">
        <span className="truncate text-slate-500">{readableReason(signal.rejectionReason)}</span>
        {change !== null && (
          <span className={`inline-flex shrink-0 items-center gap-1 ${change >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
            {change >= 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
            {Math.abs(change).toFixed(2)}%
          </span>
        )}
      </div>
    </button>
  );
}

function SignalDetail({
  signal,
  ticker,
  feedback,
  executing,
  onExecute,
}: {
  signal: ExecutableSignal;
  ticker?: MarketTicker;
  feedback?: string;
  executing: boolean;
  onExecute: () => Promise<void>;
}) {
  const executable = signal.executionStatus === "READY";
  const levelsValid = validLevels(signal);
  const riskDistance = Math.abs(numberValue(signal.entryPrice) - numberValue(signal.stopLoss));
  const rewardDistance = Math.abs(numberValue(signal.takeProfit) - numberValue(signal.entryPrice));
  const premiumGrade = signal.grade === "A+" || signal.grade === "A";
  const rrPass = numberValue(signal.rr) >= 1.5;

  return (
    <div>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-lg border px-2.5 py-1 text-[10px] font-mono font-semibold ${statusTone(signal)}`}>{statusLabel(signal)}</span>
            <span className={`rounded-lg border px-2.5 py-1 text-[10px] font-mono ${signal.direction === "LONG" ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300" : "border-rose-500/20 bg-rose-500/10 text-rose-300"}`}>{signal.direction}</span>
            <span className="rounded-lg border border-sky-500/20 bg-sky-500/10 px-2.5 py-1 text-[10px] font-mono text-sky-300">GRADE {signal.grade}</span>
          </div>
          <h2 className="mt-3 text-2xl font-bold text-white">{signal.pair}</h2>
          <p className="mt-1 text-xs text-slate-500">{signal.indicator || "Strategy setup"} · {signal.timeframe}</p>
        </div>

        <button
          type="button"
          onClick={() => void onExecute()}
          disabled={!executable || executing}
          className="inline-flex items-center justify-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-5 py-3 text-xs font-semibold text-emerald-300 transition-colors hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Zap className="h-4 w-4" />
          {executing ? "SUBMITTING..." : executable ? "DEMO EXECUTE" : "EXECUTION BLOCKED"}
        </button>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <DetailMetric label="Entry" value={formatMoney(numberValue(signal.entryPrice))} />
        <DetailMetric label="Stop Loss" value={formatMoney(numberValue(signal.stopLoss))} tone="bad" />
        <DetailMetric label="Take Profit" value={formatMoney(numberValue(signal.takeProfit))} tone="good" />
        <DetailMetric label="Risk / Reward" value={`${numberValue(signal.rr).toFixed(2)}R`} tone={rrPass ? "good" : "bad"} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-4">
          <h3 className="text-sm font-semibold text-white">Risk Gate Checklist</h3>
          <p className="mt-1 text-xs text-slate-500">Backend validation remains authoritative.</p>
          <div className="mt-4 space-y-2">
            <GateRow label="A+ or A grade" passed={premiumGrade} />
            <GateRow label="Minimum 1.5R" passed={rrPass} />
            <GateRow label="Entry / SL / TP structure" passed={levelsValid} />
            <GateRow label="Execution status READY" passed={executable} />
          </div>
        </div>

        <div className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-4">
          <h3 className="text-sm font-semibold text-white">Market Context</h3>
          <p className="mt-1 text-xs text-slate-500">Live enrichment when market data is available.</p>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <DetailMetric label="Current Price" value={ticker ? formatMoney(numberValue(ticker.lastPrice)) : "N/A"} />
            <DetailMetric label="24h Change" value={ticker ? `${numberValue(ticker.price24hPcnt) >= 0 ? "+" : ""}${(numberValue(ticker.price24hPcnt) * 100).toFixed(2)}%` : "N/A"} tone={ticker && numberValue(ticker.price24hPcnt) < 0 ? "bad" : "good"} />
            <DetailMetric label="24h Turnover" value={ticker ? formatCompact(numberValue(ticker.turnover24h)) : "N/A"} />
            <DetailMetric label="Confidence" value={`${numberValue(signal.score).toFixed(0)}%`} />
          </div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <DetailMetric label="Risk Distance" value={formatMoney(riskDistance)} />
        <DetailMetric label="Reward Distance" value={formatMoney(rewardDistance)} />
        <DetailMetric label="Detected BDT" value={formatBdtDateTime(signal.timestamp)} />
      </div>

      {signal.rejectionReason && (
        <div className="mt-4 flex items-start gap-3 rounded-xl border border-rose-500/20 bg-rose-500/10 p-4">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-rose-300" />
          <div>
            <div className="text-xs font-semibold text-rose-200">Why this setup is blocked</div>
            <div className="mt-1 text-xs leading-5 text-rose-300/80">{readableReason(signal.rejectionReason)}</div>
          </div>
        </div>
      )}

      {feedback && (
        <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-xs text-slate-300">
          <span className="text-slate-500">Execution response:</span> {feedback}
        </div>
      )}
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[9px] font-mono uppercase tracking-wider text-slate-600">{label}</div>
      <div className="mt-1 truncate font-mono text-slate-300">{value}</div>
    </div>
  );
}

function DetailMetric({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "good" | "bad";
}) {
  const valueClass = tone === "good" ? "text-emerald-400" : tone === "bad" ? "text-rose-400" : "text-white";
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
      <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-2 break-words text-sm font-semibold ${valueClass}`}>{value}</div>
    </div>
  );
}

function GateRow({ label, passed }: { label: string; passed: boolean }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2.5">
      <span className="text-xs text-slate-300">{label}</span>
      <span className={`inline-flex items-center gap-1 text-[10px] font-mono ${passed ? "text-emerald-400" : "text-rose-400"}`}>
        {passed ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}
        {passed ? "PASS" : "FAIL"}
      </span>
    </div>
  );
}

function EmptyState({ icon, title, text }: { icon: ReactNode; title: string; text: string }) {
  return (
    <div className="flex min-h-[280px] flex-col items-center justify-center rounded-xl border border-dashed border-slate-800 bg-[#0A0B0E] px-6 py-10 text-center">
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-3 text-slate-400">{icon}</div>
      <div className="mt-3 text-sm font-semibold text-white">{title}</div>
      <div className="mt-1 max-w-sm text-xs leading-5 text-slate-500">{text}</div>
    </div>
  );
}
