import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Play, RefreshCw } from "lucide-react";
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

function formatMoney(value: number) {
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
}

function formatCompact(value: number) {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(value);
}

function numberValue(value: unknown) {
  const numeric = Number(value || 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function statusLabel(signal: ExecutableSignal) {
  if (signal.executionStatus === "READY") {
    return "Executable";
  }
  if (signal.executionStatus === "NEAR_SETUP") {
    return "Near Setup";
  }
  return "Blocked";
}

function statusTone(signal: ExecutableSignal) {
  if (signal.executionStatus === "READY") {
    return "text-emerald-300 border-emerald-500/20 bg-emerald-500/10";
  }
  if (signal.executionStatus === "NEAR_SETUP") {
    return "text-amber-300 border-amber-500/20 bg-amber-500/10";
  }
  return "text-rose-300 border-rose-500/20 bg-rose-500/10";
}

function trendLabel(ticker?: MarketTicker, direction?: string) {
  if (!ticker) {
    return direction || "N/A";
  }
  const change = numberValue(ticker.price24hPcnt) * 100;
  return `${change >= 0 ? "UP" : "DOWN"} ${Math.abs(change).toFixed(2)}%`;
}

function normalizeSignals(signals: ExecutableSignal[]) {
  const priority = { READY: 0, NEAR_SETUP: 1, BLOCKED: 2, EXPIRED: 3 } as Record<string, number>;
  return [...signals].sort((a, b) => {
    const delta = (priority[a.executionStatus] ?? 9) - (priority[b.executionStatus] ?? 9);
    if (delta !== 0) {
      return delta;
    }
    return b.score - a.score;
  });
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
  const [overview, setOverview] = useState<{ top_gainers: MarketTicker[]; watchlist: MarketTicker[] }>({ top_gainers: [], watchlist: [] });
  const [marketError, setMarketError] = useState<string | null>(null);
  const [selectedSignalId, setSelectedSignalId] = useState<string | null>(null);
  const [autoTradeArmed, setAutoTradeArmed] = useState<Record<string, boolean>>({});
  const [executionFeedback, setExecutionFeedback] = useState<Record<string, string>>({});
  const bdtDayRef = useRef(new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Dhaka" }));

  useEffect(() => {
    if (!authToken) {
      return;
    }

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
        if (!cancelled) {
          setMarketError(error?.message || "Failed to load market overview");
        }
      }
    };

    loadOverview();
    const interval = setInterval(() => {
      loadOverview();
      const currentBdtDay = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Dhaka" });
      if (currentBdtDay !== bdtDayRef.current) {
        bdtDayRef.current = currentBdtDay;
        void onRefresh();
      }
    }, 10000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [authToken, onRefresh]);

  const tickerMap = useMemo(() => {
    const map = new Map<string, MarketTicker>();
    [...overview.top_gainers, ...overview.watchlist].forEach((ticker) => map.set(ticker.symbol, ticker));
    return map;
  }, [overview]);

  const allSignals = useMemo(() => normalizeSignals(scanResults), [scanResults]);

  const selectedSignal = useMemo(() => {
    if (!allSignals.length) {
      return null;
    }
    return allSignals.find((signal) => signal.id === selectedSignalId) || allSignals[0];
  }, [allSignals, selectedSignalId]);

  useEffect(() => {
    if (!selectedSignal && allSignals.length > 0) {
      setSelectedSignalId(allSignals[0].id);
    }
  }, [allSignals, selectedSignal]);

  const executableCount = allSignals.filter((signal) => signal.executionStatus === "READY").length;
  const nearSetupCount = allSignals.filter((signal) => signal.executionStatus === "NEAR_SETUP").length;
  const blockedCount = allSignals.filter((signal) => !["READY", "NEAR_SETUP"].includes(signal.executionStatus)).length;

  return (
    <div className="space-y-5" id="signal-engine-root">
      <div className="bg-bento-card border border-slate-800 rounded-2xl p-5 shadow-md" id="scanner-banner">
        <div className="flex flex-col xl:flex-row justify-between items-start xl:items-center gap-5">
          <div>
            <h3 className="text-lg font-bold text-white tracking-tight font-sans">Signal Engine</h3>
            <p className="mt-2 text-xs text-slate-500">Scanner results on the left, executable signal cards on the right. No chart noise, only decision flow.</p>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            <button
              onClick={onRunScan}
              disabled={loading}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold transition-all border bg-emerald-600/10 text-emerald-400 border-emerald-600/20 hover:bg-emerald-600/20 disabled:opacity-50 cursor-pointer"
            >
              <Play className="w-3 h-3" /> Run Scan
            </button>
            <button
              onClick={onRefresh}
              disabled={loading}
              className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-bold transition-all border border-slate-700 disabled:opacity-50 cursor-pointer"
            >
              <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} /> Refresh
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 mt-5">
          <SummaryBadge label="Executable" value={executableCount} tone="good" />
          <SummaryBadge label="Near Setup" value={nearSetupCount} tone="warn" />
          <SummaryBadge label="Blocked" value={blockedCount} tone="bad" />
          <SummaryBadge label="Total" value={allSignals.length} tone="neutral" />
        </div>
      </div>

      {marketError && (
        <div className="bg-rose-500/10 border border-rose-500/20 text-rose-300 p-4 rounded-2xl text-xs font-mono">
          {marketError}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[0.45fr_0.55fr] gap-5">
        <div className="bg-bento-card border border-slate-800 rounded-2xl p-5 shadow-md">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-semibold text-white tracking-tight font-sans">Scanner Results</h3>
              <p className="text-xs text-slate-500 mt-1">Price and volume are enriched from live backend market data.</p>
            </div>
            <span className="text-[10px] font-mono text-slate-500">{allSignals.length} rows</span>
          </div>

          <div className="overflow-hidden rounded-2xl border border-slate-800 bg-[#0A0B0E]">
            <div className="grid grid-cols-[1.15fr_1fr_1fr_1fr_0.8fr_1fr_1.6fr] gap-3 px-4 py-3 text-[10px] font-mono uppercase tracking-wider text-slate-500 border-b border-slate-800">
              <span>Symbol</span>
              <span>Price</span>
              <span>Volume</span>
              <span>Trend</span>
              <span>Score</span>
              <span>Status</span>
              <span>Block / Reject</span>
            </div>

            <div className="max-h-[720px] overflow-y-auto">
              {allSignals.map((signal) => (
                <ScannerTableRow
                  key={signal.id}
                  signal={signal}
                  ticker={tickerMap.get(signal.pair)}
                  active={selectedSignal?.id === signal.id}
                  onSelect={() => setSelectedSignalId(signal.id)}
                />
              ))}
              {allSignals.length === 0 && (
                <div className="p-12 text-center text-slate-600 font-mono text-xs">
                  <AlertTriangle className="w-8 h-8 mx-auto mb-3 text-slate-700" />
                  <span>No scanner results available.</span>
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="bg-bento-card border border-slate-800 rounded-2xl p-5 shadow-md">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-semibold text-white tracking-tight font-sans">Signals</h3>
              <p className="text-xs text-slate-500 mt-1">Executable cards first, near setups second, blocked setups last.</p>
            </div>
            <span className="text-[10px] font-mono text-slate-500">{signals.length} executable live</span>
          </div>

          <div className="space-y-4 max-h-[720px] overflow-y-auto pr-1">
            {allSignals.map((signal) => (
              <SignalCard
                key={signal.id}
                signal={signal}
                ticker={tickerMap.get(signal.pair)}
                selected={selectedSignal?.id === signal.id}
                autoTradeEnabled={Boolean(autoTradeArmed[signal.id])}
                onToggleAutoTrade={() =>
                  setAutoTradeArmed((current) => ({
                    ...current,
                    [signal.id]: !current[signal.id],
                  }))
                }
                onSelect={() => setSelectedSignalId(signal.id)}
                onExecute={() =>
                  (async () => {
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
                      [signal.id]: result.ok ? (result.warning || "Execution submitted successfully.") : (result.error || "Execution failed."),
                    }));
                  })()
                }
                executionFeedback={executionFeedback[signal.id]}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function SummaryBadge({ label, value, tone }: { label: string; value: number; tone: "good" | "warn" | "bad" | "neutral" }) {
  const toneClass =
    tone === "good"
      ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
      : tone === "warn"
      ? "border-amber-500/20 bg-amber-500/10 text-amber-300"
      : tone === "bad"
      ? "border-rose-500/20 bg-rose-500/10 text-rose-300"
      : "border-slate-800 bg-[#0A0B0E] text-slate-300";
  return (
    <div className={`rounded-xl border px-4 py-3 ${toneClass}`}>
      <div className="text-[10px] font-mono uppercase tracking-wider">{label}</div>
      <div className="mt-2 text-lg font-semibold">{value}</div>
    </div>
  );
}

function ScannerTableRow({
  signal,
  ticker,
  active,
  onSelect,
}: {
  signal: ExecutableSignal;
  ticker?: MarketTicker;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className={`grid w-full grid-cols-[1.15fr_1fr_1fr_1fr_0.8fr_1fr_1.6fr] gap-3 px-4 py-3 text-left text-xs border-b border-slate-900 transition-colors cursor-pointer ${
        active ? "bg-emerald-500/10" : "hover:bg-slate-900/60"
      }`}
    >
      <span className="font-semibold text-white">{signal.pair}</span>
      <span className="text-slate-300">{formatMoney(ticker ? numberValue(ticker.lastPrice) : signal.price)}</span>
      <span className="text-slate-400">{ticker ? formatCompact(numberValue(ticker.volume24h)) : "N/A"}</span>
      <span className={ticker && numberValue(ticker.price24hPcnt) < 0 ? "text-rose-400" : "text-emerald-400"}>{trendLabel(ticker, signal.direction)}</span>
      <span className="text-slate-300">{signal.score}%</span>
      <span className={signal.executionStatus === "READY" ? "text-emerald-300" : signal.executionStatus === "NEAR_SETUP" ? "text-amber-300" : "text-rose-300"}>
        {statusLabel(signal)}
      </span>
      <span className="text-slate-500">{signal.rejectionReason || "None"}</span>
    </button>
  );
}

function SignalCard({
  signal,
  ticker,
  selected,
  autoTradeEnabled,
  onToggleAutoTrade,
  onSelect,
  onExecute,
  executionFeedback,
}: {
  signal: ExecutableSignal;
  ticker?: MarketTicker;
  selected: boolean;
  autoTradeEnabled: boolean;
  onToggleAutoTrade: () => void;
  onSelect: () => void;
  onExecute: () => Promise<void>;
  executionFeedback?: string;
}) {
  const executable = signal.executionStatus === "READY";
  return (
    <div
      className={`rounded-2xl border p-5 shadow-md transition-colors ${
        selected ? "border-emerald-500/20 bg-emerald-500/5" : "border-slate-800 bg-[#0A0B0E]"
      }`}
      onClick={onSelect}
    >
      <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4">
        <div className="space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <span className={`px-3 py-1.5 rounded-xl border text-[10px] font-mono ${statusTone(signal)}`}>{statusLabel(signal)}</span>
            <span className="text-sm font-semibold text-white">{signal.score}%</span>
            <span className={`px-2 py-1 rounded-full text-[10px] font-mono ${signal.direction === "LONG" ? "bg-emerald-500/10 text-emerald-300" : "bg-rose-500/10 text-rose-300"}`}>
              {signal.direction}
            </span>
          </div>

          <div>
            <div className="text-lg font-bold text-white">{signal.pair}</div>
            <div className="mt-1 text-xs text-slate-500">{signal.indicator}</div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-slate-400">
            <input
              type="checkbox"
              checked={autoTradeEnabled}
              onChange={onToggleAutoTrade}
              onClick={(event) => event.stopPropagation()}
              className="rounded border-slate-700 bg-slate-950"
            />
            Auto Trade
          </label>
          <button
            onClick={(event) => {
              event.stopPropagation();
              void onExecute();
            }}
            disabled={!executable}
            className="px-4 py-2 rounded-xl border border-emerald-500/20 bg-emerald-500/10 text-emerald-300 text-xs font-semibold cursor-pointer disabled:opacity-50"
          >
            Demo Execute
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 mt-5">
        <MetricCard label="Entry" value={formatMoney(signal.entryPrice)} />
        <MetricCard label="Stop Loss" value={formatMoney(signal.stopLoss)} />
        <MetricCard label="Target" value={formatMoney(signal.takeProfit)} />
        <MetricCard label="Received" value={formatBdtDateTime(signal.timestamp)} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 mt-4">
        <MetricCard label="Setup Details" value={`${signal.timeframe} | ${signal.grade} | ${signal.rr.toFixed(2)}R`} />
        <MetricCard label="Trend / Volume" value={`${trendLabel(ticker, signal.direction)} | ${ticker ? formatCompact(numberValue(ticker.volume24h)) : "N/A"}`} />
      </div>

      {signal.rejectionReason && (
        <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-[11px] text-slate-400">
          <span className="text-slate-300">Reason:</span> {signal.rejectionReason}
        </div>
      )}

      {executionFeedback && (
        <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-[11px] text-slate-300">
          <span className="text-slate-400">Execution:</span> {executionFeedback}
        </div>
      )}
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
      <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-2 text-sm font-semibold text-white break-words">{value}</div>
    </div>
  );
}
