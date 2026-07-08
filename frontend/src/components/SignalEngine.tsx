import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowRight, Clock3, Play, RefreshCw, ShieldCheck, TrendingDown, TrendingUp } from "lucide-react";
import { api } from "../api";
import { ExecutableSignal, MarketCandle, MarketTicker } from "../types";

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
  }) => Promise<void>;
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
  const [selectedSignalId, setSelectedSignalId] = useState<string | null>(null);
  const [marketError, setMarketError] = useState<string | null>(null);
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

  const selectedSignal = useMemo(() => {
    const list = signals.length > 0 ? signals : scanResults;
    if (!list.length) {
      return null;
    }
    const match = list.find((signal) => signal.id === selectedSignalId);
    return match || list[0];
  }, [scanResults, selectedSignalId, signals]);

  useEffect(() => {
    if (!selectedSignal && (signals.length > 0 || scanResults.length > 0)) {
      const first = (signals.length > 0 ? signals : scanResults)[0];
      setSelectedSignalId(first.id);
    }
  }, [scanResults, selectedSignal, signals]);

  return (
    <div className="space-y-6" id="signal-engine-root">
      <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md" id="scanner-banner">
        <div className="flex flex-col xl:flex-row justify-between items-start xl:items-center gap-6">
          <div className="flex items-center space-x-4">
            <div className="p-4 rounded-xl bg-rose-500/10 text-rose-400">
              <Clock3 className={`w-6 h-6 ${loading ? "animate-pulse" : ""}`} />
            </div>
            <div>
              <h3 className="text-lg font-bold text-white tracking-tight font-sans">Signal Engine</h3>
              <div className="flex flex-wrap gap-4 mt-2 text-xs font-mono text-slate-400">
                <span>Scanner Results: {scanResults.length}</span>
                <span>Active Signals: {signals.length}</span>
                <span>BDT {formatBdtDateTime(new Date())}</span>
              </div>
            </div>
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
      </div>

      {marketError && (
        <div className="bg-rose-500/10 border border-rose-500/20 text-rose-300 p-4 rounded-2xl text-xs font-mono">
          {marketError}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[0.45fr_0.55fr] gap-6">
        <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
          <div className="flex items-center justify-between mb-5">
            <div>
              <h3 className="text-sm font-semibold text-white tracking-tight font-sans">Scanner Results</h3>
              <p className="text-xs text-slate-500 mt-1">Real scanner rows enriched with backend market price and volume.</p>
            </div>
            <span className="text-[10px] font-mono text-slate-500">{scanResults.length} rows</span>
          </div>

          <div className="space-y-3 max-h-[980px] overflow-y-auto pr-1">
            {scanResults.map((signal) => (
              <ScannerRow
                key={signal.id}
                signal={signal}
                ticker={tickerMap.get(signal.pair)}
                active={selectedSignal?.id === signal.id}
                onSelect={() => setSelectedSignalId(signal.id)}
              />
            ))}
            {scanResults.length === 0 && (
              <div className="p-12 text-center text-slate-600 font-mono text-xs">
                <AlertTriangle className="w-8 h-8 mx-auto mb-3 text-slate-700" />
                <span>No scanner results available.</span>
              </div>
            )}
          </div>
        </div>

        <div className="space-y-4">
          {selectedSignal ? (
            <SignalCard
              key={selectedSignal.id}
              authToken={authToken}
              signal={selectedSignal}
              ticker={tickerMap.get(selectedSignal.pair)}
              onExecute={onExecuteSignal}
            />
          ) : (
            <div className="bg-bento-card border border-slate-800 rounded-2xl p-12 text-center text-slate-600 font-mono text-xs">
              Select a scanner result to inspect the live signal card.
            </div>
          )}

          {signals.length > 1 && (
            <div className="grid grid-cols-1 2xl:grid-cols-2 gap-4">
              {signals
                .filter((signal) => signal.id !== selectedSignal?.id)
                .slice(0, 3)
                .map((signal) => (
                  <SignalCard
                    key={signal.id}
                    authToken={authToken}
                    signal={signal}
                    ticker={tickerMap.get(signal.pair)}
                    onExecute={onExecuteSignal}
                    compact
                  />
                ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ScannerRow({
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
  const trendUp = numberValue(ticker?.price24hPcnt) >= 0;
  const reason = signal.rejectionReason || (signal.executionStatus === "READY" ? "No block reason" : "Strategy filtered");

  return (
    <button
      onClick={onSelect}
      className={`w-full text-left p-4 rounded-2xl border transition-colors cursor-pointer ${
        active ? "bg-emerald-500/10 border-emerald-500/20" : "bg-[#0A0B0E] border-slate-800 hover:border-slate-700"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-white">{signal.pair}</div>
          <div className="mt-1 text-[10px] font-mono text-slate-500">
            {ticker ? formatMoney(numberValue(ticker.lastPrice)) : formatMoney(numberValue(signal.price))}
          </div>
        </div>
        <span className={`px-2 py-1 rounded-full text-[10px] font-mono ${
          signal.executionStatus === "READY" ? "bg-emerald-500/10 text-emerald-300" : "bg-amber-500/10 text-amber-300"
        }`}>
          {signal.executionStatus}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 mt-4 text-[10px] font-mono">
        <Meta label="Volume" value={ticker ? formatCompact(numberValue(ticker.volume24h)) : "N/A"} />
        <Meta label="Score" value={String(signal.score)} />
        <Meta
          label="Trend"
          value={ticker ? `${trendUp ? "UP" : "DOWN"} ${Math.abs(numberValue(ticker.price24hPcnt) * 100).toFixed(2)}%` : signal.direction}
          good={ticker ? trendUp : signal.direction === "LONG"}
        />
        <Meta label="Status" value={signal.status} />
      </div>

      <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-2 text-[10px] font-mono text-slate-500">
        <span className="text-slate-400">Block / Reject:</span> {reason}
      </div>
    </button>
  );
}

function SignalCard({
  authToken,
  signal,
  ticker,
  onExecute,
  compact = false,
}: {
  authToken: string | null;
  signal: ExecutableSignal;
  ticker?: MarketTicker;
  onExecute: (signal: {
    symbol: string;
    direction: string;
    entry: number;
    stop_loss: number;
    take_profit: number;
    risk_reward: number;
    detected_at?: string | null;
    status: string;
  }) => Promise<void>;
  compact?: boolean;
}) {
  const [candles, setCandles] = useState<MarketCandle[]>([]);
  const [loadingChart, setLoadingChart] = useState(false);

  useEffect(() => {
    if (!authToken) {
      return;
    }

    let cancelled = false;
    const loadChart = async () => {
      setLoadingChart(true);
      try {
        const response = await api.getMarketCandles(authToken, signal.pair, "1", compact ? 24 : 48);
        if (!cancelled) {
          setCandles((response.candles || []).map((item) => ({
            ...item,
            open: numberValue(item.open),
            high: numberValue(item.high),
            low: numberValue(item.low),
            close: numberValue(item.close),
          })));
        }
      } finally {
        if (!cancelled) {
          setLoadingChart(false);
        }
      }
    };

    loadChart();
    return () => {
      cancelled = true;
    };
  }, [authToken, compact, signal.id, signal.pair]);

  const confidence = signal.score;
  const canExecute = signal.executionStatus === "READY" && signal.status === "PENDING";
  const payload = {
    symbol: signal.pair,
    direction: signal.direction.toLowerCase(),
    entry: signal.entryPrice,
    stop_loss: signal.stopLoss,
    take_profit: signal.takeProfit,
    risk_reward: signal.rr,
    detected_at: signal.timestamp,
    status: "active",
  };

  return (
    <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
      <div className="flex flex-col lg:flex-row justify-between gap-4">
        <div>
          <div className="flex items-center gap-3 flex-wrap">
            <h3 className="text-sm font-semibold text-white tracking-tight font-sans">{signal.pair}</h3>
            <span className={`px-2 py-1 rounded-full text-[10px] font-mono ${signal.direction === "LONG" ? "bg-emerald-500/10 text-emerald-300" : "bg-rose-500/10 text-rose-300"}`}>
              {signal.direction}
            </span>
            <span className="px-2 py-1 rounded-full text-[10px] font-mono bg-slate-900 text-slate-300">{signal.timeframe}</span>
          </div>
          <p className="text-xs text-slate-500 mt-2">
            {signal.indicator} | Confidence {confidence}% | BDT {formatBdtDateTime(signal.timestamp)}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className={`px-3 py-1.5 rounded-xl border text-[10px] font-mono ${
            canExecute ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-300" : "bg-amber-500/10 border-amber-500/20 text-amber-300"
          }`}>
            {signal.executionStatus}
          </span>
          <button
            onClick={() => onExecute(payload)}
            disabled={!canExecute}
            className="px-4 py-2 rounded-xl border border-emerald-500/20 bg-emerald-500/10 text-emerald-300 text-xs font-semibold cursor-pointer disabled:opacity-50"
          >
            Execute
          </button>
        </div>
      </div>

      <div className={`grid ${compact ? "grid-cols-2" : "grid-cols-2 xl:grid-cols-4"} gap-3 mt-5`}>
        <MetricCard label="Entry" value={formatMoney(signal.entryPrice)} />
        <MetricCard label="SL" value={formatMoney(signal.stopLoss)} />
        <MetricCard label="TP" value={formatMoney(signal.takeProfit)} />
        <MetricCard label="RR" value={`${signal.rr.toFixed(2)}R`} />
        <MetricCard label="Strategy" value={signal.indicator} />
        <MetricCard label="Trend" value={ticker ? `${numberValue(ticker.price24hPcnt) >= 0 ? "Bullish" : "Bearish"}` : signal.direction} />
        <MetricCard label="Confidence" value={`${confidence}%`} />
        <MetricCard label="Status" value={signal.status} />
      </div>

      <div className="mt-5 rounded-2xl border border-slate-800 bg-[#0A0B0E] p-4">
        <div className="flex items-center justify-between mb-3 text-[10px] font-mono text-slate-500">
          <span>Live backend chart</span>
          <span>{loadingChart ? "Updating..." : `${candles.length} candles`}</span>
        </div>
        <MiniCandlesChart candles={candles} />
      </div>

      <div className="mt-4 flex flex-wrap gap-4 text-[10px] font-mono text-slate-500">
        <span>Last Price: <span className="text-slate-300">{ticker ? formatMoney(numberValue(ticker.lastPrice)) : formatMoney(signal.price)}</span></span>
        <span className={numberValue(ticker?.price24hPcnt) >= 0 ? "text-emerald-400" : "text-rose-400"}>
          24h: {ticker ? `${(numberValue(ticker.price24hPcnt) * 100).toFixed(2)}%` : "N/A"}
        </span>
        {signal.rejectionReason && <span>Reason: {signal.rejectionReason}</span>}
      </div>
    </div>
  );
}

function MiniCandlesChart({ candles }: { candles: MarketCandle[] }) {
  const width = 640;
  const height = 160;
  const padding = 10;

  if (!candles.length) {
    return <div className="py-10 text-center text-xs font-mono text-slate-500">No live candles available.</div>;
  }

  const high = Math.max(...candles.map((item) => item.high));
  const low = Math.min(...candles.map((item) => item.low));
  const range = Math.max(high - low, 1);
  const plotWidth = width - padding * 2;
  const plotHeight = height - padding * 2;
  const candleWidth = Math.max(plotWidth / candles.length - 2, 2);
  const getY = (value: number) => padding + ((high - value) / range) * plotHeight;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full">
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

function Meta({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div>
      <div className="text-slate-500">{label}</div>
      <div className={`mt-1 text-slate-200 ${good === undefined ? "" : good ? "text-emerald-400" : "text-rose-400"}`}>{value}</div>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-3">
      <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-2 text-sm font-semibold text-white">{value}</div>
    </div>
  );
}
