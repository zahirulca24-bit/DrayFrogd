import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Play, RefreshCw } from "lucide-react";
import { api } from "../api";
import { ExecutableSignal, ExecuteTradeResponse, MarketTicker } from "../types";
import {
  CanonicalSignalState,
  fetchSignalTruth,
  runSignalTruthScan,
  SignalTruthPayload,
  TruthSignal,
} from "../signalTruth";

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
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? "N/A" : BDT_DATE_TIME.format(date);
}

function formatMoney(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "N/A";
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 })}`;
}

function formatNumber(value: number | null, suffix = "") {
  if (value === null || !Number.isFinite(value)) return "N/A";
  return `${value.toFixed(2)}${suffix}`;
}

function formatCompact(value: number) {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(value);
}

function numberValue(value: unknown) {
  const numeric = Number(value || 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function formatAge(value: string | null) {
  if (!value) return "N/A";
  const ageMs = Date.now() - new Date(value).getTime();
  if (!Number.isFinite(ageMs) || ageMs < 0) return "N/A";
  const minutes = Math.floor(ageMs / 60_000);
  if (minutes < 1) return "<1m";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m`;
  return `${Math.floor(hours / 24)}d`;
}

function stateTone(state: CanonicalSignalState) {
  if (state === "ACTIVE") return "text-emerald-300 border-emerald-500/20 bg-emerald-500/10";
  if (state === "NEAR_SETUP") return "text-amber-300 border-amber-500/20 bg-amber-500/10";
  if (state === "NO_SETUP") return "text-slate-300 border-slate-700 bg-slate-800/60";
  if (state === "EXPIRED") return "text-violet-300 border-violet-500/20 bg-violet-500/10";
  return "text-rose-300 border-rose-500/20 bg-rose-500/10";
}

function trendTone(trendState: string | null) {
  if (trendState === "UPTREND") return "text-emerald-400";
  if (trendState === "DOWNTREND") return "text-rose-400";
  return "text-slate-400";
}

export default function SignalEngine(props: SignalEngineProps) {
  const [truth, setTruth] = useState<SignalTruthPayload | null>(null);
  const [truthError, setTruthError] = useState<string | null>(null);
  const [scanLoading, setScanLoading] = useState(false);
  const [selectedSignalId, setSelectedSignalId] = useState<string | null>(null);
  const [overview, setOverview] = useState<{ top_gainers: MarketTicker[]; watchlist: MarketTicker[] }>({
    top_gainers: [],
    watchlist: [],
  });
  const [marketError, setMarketError] = useState<string | null>(null);

  const loadTruth = useCallback(async () => {
    if (!props.authToken) return;
    try {
      const payload = await fetchSignalTruth(props.authToken);
      setTruth(payload);
      setTruthError(null);
    } catch (error: any) {
      setTruthError(error?.message || "Scanner and signal contract data is unavailable.");
    }
  }, [props.authToken]);

  useEffect(() => {
    void loadTruth();
  }, [loadTruth, props.signals.length, props.scanResults.length]);

  useEffect(() => {
    if (!props.authToken) return;
    let cancelled = false;

    const loadOverview = async () => {
      try {
        const response = await api.getMarketOverview(props.authToken as string);
        if (!cancelled) {
          setOverview({
            top_gainers: response.top_gainers || [],
            watchlist: response.watchlist || [],
          });
          setMarketError(response.error || null);
        }
      } catch (error: any) {
        if (!cancelled) setMarketError(error?.message || "Live market enrichment is unavailable.");
      }
    };

    void loadOverview();
    const interval = setInterval(() => {
      void loadOverview();
      void loadTruth();
    }, 10_000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [props.authToken, loadTruth]);

  const tickerMap = useMemo(() => {
    const map = new Map<string, MarketTicker>();
    [...overview.top_gainers, ...overview.watchlist].forEach((ticker) => map.set(ticker.symbol, ticker));
    return map;
  }, [overview]);

  const signalCards = truth?.primarySignals || [];
  const marketRows = truth?.marketRows || [];
  const selectedSignal = signalCards.find((signal) => signal.id === selectedSignalId) || signalCards[0] || null;

  useEffect(() => {
    if (signalCards.length > 0 && !signalCards.some((signal) => signal.id === selectedSignalId)) {
      setSelectedSignalId(signalCards[0].id);
    }
  }, [signalCards, selectedSignalId]);

  const handleRunScan = async () => {
    if (!props.authToken) return;
    setScanLoading(true);
    setTruthError(null);
    try {
      const payload = await runSignalTruthScan(props.authToken);
      setTruth(payload);
      await props.onRefresh();
    } catch (error: any) {
      setTruthError(error?.message || "Scan failed.");
    } finally {
      setScanLoading(false);
    }
  };

  const summary = truth?.summary;
  const loading = props.loading || scanLoading;

  return (
    <div className="space-y-5" id="signal-engine-root">
      <section className="rounded-2xl border border-slate-800 bg-bento-card p-5 shadow-md">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <h1 className="text-lg font-bold tracking-tight text-white">Signal Engine</h1>
            <p className="mt-2 text-xs text-slate-500">
              Canonical backend states, one primary useful signal per symbol, and separate strategy and execution truth.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => void handleRunScan()}
              disabled={loading || !props.authToken}
              className="flex items-center gap-2 rounded-lg border border-emerald-600/20 bg-emerald-600/10 px-4 py-2 text-xs font-bold text-emerald-400 transition-colors hover:bg-emerald-600/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Play className="h-3.5 w-3.5" /> {scanLoading ? "SCANNING..." : "RUN SCAN"}
            </button>
            <button
              type="button"
              onClick={() => {
                void props.onRefresh();
                void loadTruth();
              }}
              disabled={loading}
              className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 text-xs font-bold text-slate-300 transition-colors hover:bg-slate-700 disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> REFRESH
            </button>
          </div>
        </div>

        <div className="mt-4 rounded-xl border border-sky-500/15 bg-sky-500/5 px-4 py-3 text-[11px] text-sky-200">
          <strong>Run Scan is diagnostic only.</strong> It refreshes scanner and signal evidence but does not submit a trade. Automatic execution remains controlled by Start Engine.
        </div>

        <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
          <SummaryBadge label="Symbols checked" value={summary?.symbolsScanned ?? "N/A"} tone="neutral" />
          <SummaryBadge label="Ranked markets" value={summary?.rankedMarkets ?? 0} tone="neutral" />
          <SummaryBadge label="Strategy checks" value={summary?.strategyChecks ?? 0} tone="neutral" />
          <SummaryBadge label="Near setups" value={summary?.nearSetups ?? 0} tone="warn" />
          <SummaryBadge label="Active signals" value={summary?.activeSignals ?? 0} tone="good" />
          <SummaryBadge label="Uptrend profiles" value={summary?.uptrendProfiles ?? 0} tone="good" />
          <SummaryBadge label="Downtrend profiles" value={summary?.downtrendProfiles ?? 0} tone="bad" />
          <SummaryBadge
            label="Sideways / stale"
            value={
              summary?.sidewaysRejectedProfiles === null || summary?.insufficientOrStaleProfiles === null
                ? "N/A"
                : summary.sidewaysRejectedProfiles + summary.insufficientOrStaleProfiles
            }
            tone="bad"
          />
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[10px] font-mono text-slate-500">
          <span>
            Source: {truth?.source === "manual_scan" ? "latest manual scan response" : "current scanner/signal endpoints"}
          </span>
          <span>Captured: {formatBdtDateTime(truth?.capturedAt)}</span>
        </div>
        {truth?.source !== "manual_scan" && (
          <p className="mt-2 text-[10px] text-slate-600">
            Pre-strategy Sideways and stale rejection totals are shown as N/A until Run Scan returns the full scanner summary.
          </p>
        )}
      </section>

      {(truthError || marketError) && (
        <div className="space-y-2">
          {truthError && <ErrorBanner message={truthError} />}
          {marketError && <ErrorBanner message={`Market enrichment: ${marketError}`} />}
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[0.46fr_0.54fr]">
        <section className="rounded-2xl border border-slate-800 bg-bento-card p-5 shadow-md">
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <h2 className="text-sm font-semibold text-white">Ranked Market Results</h2>
              <p className="mt-1 text-xs text-slate-500">One row per represented market. Strategy checks are never shown as symbol rows.</p>
            </div>
            <span className="rounded-lg border border-slate-800 bg-[#0A0B0E] px-2.5 py-1 text-[10px] font-mono text-slate-400">
              {marketRows.length} markets
            </span>
          </div>

          <div className="overflow-hidden rounded-2xl border border-slate-800 bg-[#0A0B0E]">
            <div className="grid grid-cols-[0.55fr_1fr_0.9fr_0.85fr_0.75fr_1fr_1.3fr] gap-3 border-b border-slate-800 px-4 py-3 text-[9px] font-mono uppercase tracking-wider text-slate-500">
              <span>Rank</span>
              <span>Symbol</span>
              <span>Trend</span>
              <span>Profile</span>
              <span>Score</span>
              <span>State</span>
              <span>Reason</span>
            </div>
            <div className="max-h-[720px] overflow-y-auto">
              {marketRows.map((signal) => (
                <MarketResultRow
                  key={signal.symbol}
                  signal={signal}
                  active={selectedSignal?.symbol === signal.symbol}
                  onSelect={() => {
                    const matching = signalCards.find((item) => item.symbol === signal.symbol);
                    if (matching) setSelectedSignalId(matching.id);
                  }}
                />
              ))}
              {marketRows.length === 0 && <EmptyResults text="No ranked scanner results are currently available." />}
            </div>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-800 bg-bento-card p-5 shadow-md">
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <h2 className="text-sm font-semibold text-white">Primary Useful Signals</h2>
              <p className="mt-1 text-xs text-slate-500">ACTIVE first, NEAR_SETUP second. No duplicate primary card for the same symbol.</p>
            </div>
            <span className="rounded-lg border border-slate-800 bg-[#0A0B0E] px-2.5 py-1 text-[10px] font-mono text-slate-400">
              {signalCards.length} primary
            </span>
          </div>

          <div className="max-h-[720px] space-y-4 overflow-y-auto pr-1">
            {signalCards.map((signal) => (
              <TruthSignalCard
                key={signal.id}
                signal={signal}
                ticker={tickerMap.get(signal.symbol)}
                selected={selectedSignal?.id === signal.id}
                onSelect={() => setSelectedSignalId(signal.id)}
              />
            ))}
            {signalCards.length === 0 && <EmptyResults text="No ACTIVE or NEAR_SETUP primary signal is available." />}
          </div>
        </section>
      </div>
    </div>
  );
}

function SummaryBadge({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone: "good" | "warn" | "bad" | "neutral";
}) {
  const toneClass =
    tone === "good"
      ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
      : tone === "warn"
        ? "border-amber-500/20 bg-amber-500/10 text-amber-300"
        : tone === "bad"
          ? "border-rose-500/20 bg-rose-500/10 text-rose-300"
          : "border-slate-800 bg-[#0A0B0E] text-slate-300";
  return (
    <div className={`rounded-xl border px-3 py-3 ${toneClass}`}>
      <div className="text-[9px] font-mono uppercase tracking-wider">{label}</div>
      <div className="mt-2 text-lg font-semibold">{value}</div>
    </div>
  );
}

function MarketResultRow({ signal, active, onSelect }: { signal: TruthSignal; active: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`grid w-full grid-cols-[0.55fr_1fr_0.9fr_0.85fr_0.75fr_1fr_1.3fr] gap-3 border-b border-slate-900 px-4 py-3 text-left text-[11px] transition-colors ${
        active ? "bg-emerald-500/10" : "hover:bg-slate-900/60"
      }`}
    >
      <span className="font-mono text-slate-400">{signal.marketRank ?? "N/A"}</span>
      <span className="font-semibold text-white">{signal.symbol}</span>
      <span className={trendTone(signal.trendState)}>{signal.trendState || "N/A"}</span>
      <span className="capitalize text-slate-300">{signal.tradeType || "N/A"}</span>
      <span className="font-mono text-slate-300">{formatNumber(signal.marketScore)}</span>
      <span className={`font-mono text-[10px] ${stateTone(signal.signalState).split(" ")[0]}`}>{signal.signalState}</span>
      <span className="truncate text-slate-500" title={signal.rejectionReason || "None"}>{signal.rejectionReason || "None"}</span>
    </button>
  );
}

function TruthSignalCard({
  signal,
  ticker,
  selected,
  onSelect,
}: {
  signal: TruthSignal;
  ticker?: MarketTicker;
  selected: boolean;
  onSelect: () => void;
}) {
  const riskGate = signal.signalState === "ACTIVE" ? "NOT EVALUATED" : "NOT APPLICABLE";
  const executionGate = signal.signalState === "ACTIVE" ? "ENGINE CONTROLLED" : "BLOCKED BY STATE";
  const timeframe = [signal.timeframes.trend && `Trend ${signal.timeframes.trend}`, signal.timeframes.setup && `Setup ${signal.timeframes.setup}`, signal.timeframes.trigger && `Trigger ${signal.timeframes.trigger}`]
    .filter(Boolean)
    .join(" · ") || "N/A";

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full rounded-2xl border p-5 text-left shadow-md transition-colors ${
        selected ? "border-emerald-500/20 bg-emerald-500/5" : "border-slate-800 bg-[#0A0B0E] hover:border-slate-700"
      }`}
    >
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-xl border px-3 py-1.5 text-[10px] font-mono ${stateTone(signal.signalState)}`}>{signal.signalState}</span>
            <span className={`rounded-full px-2 py-1 text-[10px] font-mono ${signal.direction === "LONG" ? "bg-emerald-500/10 text-emerald-300" : "bg-rose-500/10 text-rose-300"}`}>
              {signal.direction || "N/A"}
            </span>
            <span className="rounded-lg border border-slate-800 bg-slate-950/60 px-2 py-1 text-[10px] font-mono text-slate-400">
              {signal.tradeType?.toUpperCase() || "PROFILE N/A"}
            </span>
          </div>
          <div className="mt-3 text-lg font-bold text-white">{signal.symbol}</div>
          <div className="mt-1 text-xs text-slate-500">{signal.strategyName}</div>
        </div>
        <div className="grid grid-cols-2 gap-2 text-right text-[10px] font-mono">
          <RankBox label="Market rank" value={signal.marketRank ?? "N/A"} />
          <RankBox label="Signal rank" value={signal.signalRank ?? "N/A"} />
          <RankBox label="Market score" value={formatNumber(signal.marketScore)} />
          <RankBox label="Signal score" value={formatNumber(signal.signalScore)} />
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 xl:grid-cols-4">
        <MetricCard label="Entry" value={formatMoney(signal.entry)} />
        <MetricCard label="Stop Loss" value={formatMoney(signal.stopLoss)} />
        <MetricCard label="Take Profit" value={formatMoney(signal.takeProfit)} />
        <MetricCard label="Risk : Reward" value={formatNumber(signal.riskReward, "R")} />
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-3">
        <MetricCard label="Timeframes" value={timeframe} />
        <MetricCard label="Trend / Approved side" value={`${signal.trendState || "N/A"} / ${signal.approvedDirection || "N/A"}`} />
        <MetricCard label="Signal age / Received" value={`${formatAge(signal.detectedAt)} / ${formatBdtDateTime(signal.detectedAt)}`} />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2 xl:grid-cols-4">
        <GateCard label="Strategy state" value={signal.signalState} good={["ACTIVE", "NEAR_SETUP"].includes(signal.signalState)} />
        <GateCard label="Monitor only" value={signal.monitorOnly ? "YES" : "NO"} good={signal.monitorOnly} neutral={!signal.monitorOnly} />
        <GateCard label="Risk gate" value={riskGate} neutral />
        <GateCard label="Execution" value={executionGate} neutral={signal.signalState === "ACTIVE"} />
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-slate-800 pt-3 text-[10px] text-slate-500">
        <span>
          Confirmation matches: {signal.confirmationCount} · Strategies: {signal.matchedStrategies.length ? signal.matchedStrategies.join(", ") : signal.strategyName}
        </span>
        <span>Volume: {ticker ? formatCompact(numberValue(ticker.volume24h)) : "N/A"}</span>
      </div>

      {signal.rejectionReason && (
        <div className="mt-3 rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-[11px] text-slate-400">
          <span className="text-slate-300">Reason:</span> {signal.rejectionReason}
        </div>
      )}
    </button>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
      <div className="text-[9px] font-mono uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-2 break-words text-sm font-semibold text-white">{value}</div>
    </div>
  );
}

function RankBox({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2">
      <div className="text-slate-600">{label}</div>
      <div className="mt-1 font-semibold text-slate-300">{value}</div>
    </div>
  );
}

function GateCard({ label, value, good = false, neutral = false }: { label: string; value: string; good?: boolean; neutral?: boolean }) {
  const tone = good
    ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
    : neutral
      ? "border-slate-800 bg-slate-950/60 text-slate-300"
      : "border-rose-500/20 bg-rose-500/10 text-rose-300";
  return (
    <div className={`rounded-xl border px-3 py-2 ${tone}`}>
      <div className="text-[9px] font-mono uppercase tracking-wider opacity-70">{label}</div>
      <div className="mt-1 text-[10px] font-semibold">{value}</div>
    </div>
  );
}

function EmptyResults({ text }: { text: string }) {
  return (
    <div className="p-12 text-center text-xs font-mono text-slate-600">
      <AlertTriangle className="mx-auto mb-3 h-8 w-8 text-slate-700" />
      {text}
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-2xl border border-rose-500/20 bg-rose-500/10 p-4 text-xs text-rose-300">
      <div className="flex items-center gap-2">
        <AlertTriangle className="h-4 w-4" /> {message}
      </div>
    </div>
  );
}
