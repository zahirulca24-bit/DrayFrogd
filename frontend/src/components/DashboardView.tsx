import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api";
import {
  AccountResponse,
  BotControlState,
  ExecutableSignal,
  MarketCandle,
  MarketTicker,
  SystemReadiness,
  Trade,
  TradeHistoryEntry,
} from "../types";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  CandlestickChart,
  Clock3,
  Coins,
  Layers3,
  Play,
  RefreshCw,
  RadioTower,
  ShieldCheck,
  Wallet,
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

const BDT_TIME = new Intl.DateTimeFormat("en-BD", {
  timeZone: "Asia/Dhaka",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

function numberValue(value: unknown) {
  const numeric = Number(value || 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function formatMoney(value: number) {
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatCompact(value: number) {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(value);
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

function formatChartPrice(value: number) {
  if (value >= 1000) {
    return value.toFixed(2);
  }
  if (value >= 1) {
    return value.toFixed(4);
  }
  return value.toFixed(5);
}

function formatBdtDateTime(value?: string | Date | null) {
  if (!value) {
    return "N/A";
  }
  return BDT_DATE_TIME.format(new Date(value));
}

function formatBdtTime(value?: string | Date | null) {
  if (!value) {
    return "--:--:--";
  }
  return BDT_TIME.format(new Date(value));
}

function resolveRealizedPnl(wallet: Record<string, unknown>, tradeHistory: TradeHistoryEntry[]) {
  const coinRows = Array.isArray(wallet.coin) ? wallet.coin : [];
  const walletRealized = coinRows.reduce((sum, coin) => sum + numberValue((coin as Record<string, unknown>).cumRealisedPnl), 0);
  if (walletRealized !== 0) {
    return walletRealized;
  }
  return tradeHistory.reduce((sum, trade) => sum + numberValue(trade.pnl), 0);
}

function resolveUnrealizedPnl(wallet: Record<string, unknown>, account: AccountResponse) {
  const walletUnrealized = numberValue(wallet.totalPerpUPL);
  if (walletUnrealized !== 0) {
    return walletUnrealized;
  }
  return (account.positions.data || []).reduce((sum, position) => sum + numberValue(position.unrealisedPnl), 0);
}

function resolveExposure(account: AccountResponse) {
  return (account.positions.data || []).reduce((sum, position) => {
    const positionValue = numberValue(position.positionValue);
    if (positionValue > 0) {
      return sum + Math.abs(positionValue);
    }
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
  const totalEquity = numberValue(wallet.totalEquity || wallet.totalWalletBalance || wallet.totalMarginBalance);
  const availableBalance = numberValue(wallet.totalAvailableBalance || wallet.totalAvailableBalanceByMp || wallet.totalWalletBalance);
  const realizedPnl = resolveRealizedPnl(wallet, tradeHistory);
  const unrealizedPnl = resolveUnrealizedPnl(wallet, account);
  const sessionPnl = realizedPnl + unrealizedPnl;
  const exposure = resolveExposure(account);

  const [selectedSymbol, setSelectedSymbol] = useState("BTCUSDT");
  const [chartInterval, setChartInterval] = useState("1");
  const [overview, setOverview] = useState<{ top_gainers: MarketTicker[]; watchlist: MarketTicker[]; server_time: string | null }>({
    top_gainers: [],
    watchlist: [],
    server_time: null,
  });
  const [candles, setCandles] = useState<MarketCandle[]>([]);
  const [marketError, setMarketError] = useState<string | null>(null);
  const [marketLoading, setMarketLoading] = useState(false);

  const selectedTicker = useMemo(() => {
    const merged = [...overview.watchlist, ...overview.top_gainers];
    return merged.find((item) => item.symbol === selectedSymbol) || null;
  }, [overview, selectedSymbol]);

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
            server_time: response.server_time,
          });
          setMarketError(response.error);
          if (!selectedTicker && response.watchlist?.[0]?.symbol) {
            setSelectedSymbol(response.watchlist[0].symbol);
          }
        }
      } catch (error: any) {
        if (!cancelled) {
          setMarketError(error?.message || "Failed to load market overview");
        }
      }
    };

    loadOverview();
    const interval = setInterval(loadOverview, 15000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [authToken]);

  useEffect(() => {
    if (!authToken || !selectedSymbol) {
      return;
    }

    let cancelled = false;

    const loadMarketPanels = async () => {
      setMarketLoading(true);
      try {
        const candleResponse = await api.getMarketCandles(authToken, selectedSymbol, chartInterval, 120);
        if (!cancelled) {
          setCandles((candleResponse.candles || []).map((item) => ({
            ...item,
            open: numberValue(item.open),
            high: numberValue(item.high),
            low: numberValue(item.low),
            close: numberValue(item.close),
          })));
          setMarketError(candleResponse.error || null);
        }
      } catch (error: any) {
        if (!cancelled) {
          setMarketError(error?.message || "Failed to load market panels");
        }
      } finally {
        if (!cancelled) {
          setMarketLoading(false);
        }
      }
    };

    loadMarketPanels();
    const interval = setInterval(loadMarketPanels, 10000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [authToken, chartInterval, selectedSymbol]);

  return (
    <div className="space-y-4" id="dashboard-view-root">
      <div className="bg-bento-card-sec/40 border border-slate-800/80 rounded-2xl p-5 flex flex-col xl:flex-row justify-between items-start xl:items-center gap-4 shadow-lg backdrop-blur-md" id="dashboard-banner">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight font-sans flex items-center gap-3">
            DayFrogd-ScalpingEngin
            {isStale && (
              <span className="bg-rose-500/10 text-rose-400 text-[10px] px-2 py-0.5 rounded-full border border-rose-500/20 flex items-center font-mono">
                <AlertTriangle className="w-3 h-3 mr-1" /> STALE DATA
              </span>
            )}
          </h1>
          <p className="text-xs text-slate-400 mt-1 flex items-center gap-3 flex-wrap">
            <span>{botStatus.status === "running" ? "Runtime armed for protected scanning." : "Bot is not running. Execution remains blocked."}</span>
            <span className="flex items-center gap-1 bg-slate-800/50 px-2 py-0.5 rounded-md text-[10px] text-slate-300 font-mono">
              <Clock3 className="w-3 h-3 text-slate-500" />
              BDT {formatBdtDateTime(overview.server_time || lastSync || undefined)}
            </span>
          </p>
        </div>
        <div className="flex w-full flex-col gap-3 xl:w-auto xl:items-end" id="dashboard-status-indicator">
          <div className="flex w-full flex-col gap-2 sm:flex-row xl:w-auto">
            <button
              type="button"
              onClick={onStartEngine}
              disabled={actionLoading === "bot-start"}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-xs font-semibold text-emerald-300 transition-colors hover:bg-emerald-500/20 disabled:opacity-50 sm:w-auto"
            >
              <Play className="h-4 w-4" />
              <span>{actionLoading === "bot-start" ? "STARTING..." : "START ENGINE"}</span>
            </button>
            <button
              type="button"
              onClick={onRefreshAll}
              disabled={actionLoading === "bot-start"}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-slate-800 bg-[#0A0B0E] px-4 py-3 text-xs font-semibold text-slate-300 transition-colors hover:border-slate-700 hover:text-white disabled:opacity-50 sm:w-auto"
            >
              <RefreshCw className="h-4 w-4" />
              <span>REFRESH</span>
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-3 shrink-0">
          <StatusPill label="Bot" value={botStatus.status.toUpperCase()} tone={botStatus.status === "running" ? "good" : "muted"} />
          <StatusPill label="Readiness" value={readiness.ready_for_execution ? "READY" : "BLOCKED"} tone={readiness.ready_for_execution ? "good" : "warn"} />
          <StatusPill label="Mode" value={(botStatus.execution_mode || "demo").toUpperCase()} tone={(botStatus.execution_mode || "demo") === "live" ? "warn" : "good"} />
          <StatusPill label="Symbol" value={selectedSymbol} tone="muted" />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3" id="dashboard-kpi-grid">
        <KpiCard label="Total Equity" value={formatMoney(totalEquity)} icon={<Wallet className="w-4 h-4" />} tone="neutral" />
        <KpiCard label="Available Balance" value={formatMoney(availableBalance)} icon={<Coins className="w-4 h-4" />} tone="good" />
        <KpiCard label="Realized PnL" value={formatMoney(realizedPnl)} icon={realizedPnl >= 0 ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownRight className="w-4 h-4" />} tone={realizedPnl >= 0 ? "good" : "bad"} />
        <KpiCard label="Unrealized PnL" value={formatMoney(unrealizedPnl)} icon={<Layers3 className="w-4 h-4" />} tone={unrealizedPnl >= 0 ? "good" : "bad"} />
        <KpiCard label="Session PnL" value={formatMoney(sessionPnl)} icon={<CandlestickChart className="w-4 h-4" />} tone={sessionPnl >= 0 ? "good" : "bad"} />
        <KpiCard label="Exposure" value={formatMoney(exposure)} icon={<ShieldCheck className="w-4 h-4" />} tone="warn" />
        <KpiCard label="Active Trades" value={String(activeTrades.length)} icon={<BarChart3 className="w-4 h-4" />} tone="neutral" />
        <KpiCard label="Active Signals" value={String(signals.length)} icon={<RadioTower className="w-4 h-4" />} tone="neutral" />
      </div>

      {marketError && (
        <div className="bg-rose-500/10 border border-rose-500/20 text-rose-300 p-4 rounded-2xl text-xs font-mono">
          {marketError}
        </div>
      )}

      <div className="space-y-4" id="dashboard-main-panels">
          <div className="bg-bento-card border border-slate-800 rounded-2xl p-5 shadow-md">
            <div className="flex flex-col lg:flex-row justify-between gap-4 mb-5">
              <div>
                <h2 className="text-sm font-semibold text-white tracking-tight font-sans">Market Structure</h2>
                <p className="text-xs text-slate-500 mt-1">Real backend OHLCV stream for {selectedSymbol} with BDT timestamps.</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {["1", "5", "15", "60"].map((interval) => (
                  <button
                    key={interval}
                    onClick={() => setChartInterval(interval)}
                    className={`px-3 py-1.5 rounded-lg border text-[10px] font-mono transition-colors cursor-pointer ${
                      chartInterval === interval
                        ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/20"
                        : "bg-[#0A0B0E] text-slate-400 border-slate-800 hover:border-slate-700"
                    }`}
                  >
                    {interval === "60" ? "1H" : `${interval}M`}
                  </button>
                ))}
              </div>
            </div>
            <CandlesPanel candles={candles} loading={marketLoading} symbol={selectedSymbol} />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <TickerTable
              title="Top 10 Gainers"
              rows={overview.top_gainers.slice(0, 10)}
              selectedSymbol={selectedSymbol}
              onSelectSymbol={setSelectedSymbol}
            />
            <TickerTable
              title="Watchlist"
              rows={overview.watchlist}
              selectedSymbol={selectedSymbol}
              onSelectSymbol={setSelectedSymbol}
            />
          </div>
      </div>
    </div>
  );
}

function StatusPill({ label, value, tone }: { label: string; value: string; tone: "good" | "warn" | "muted" }) {
  const toneClass = tone === "good" ? "text-emerald-300 border-emerald-500/20 bg-emerald-500/10" : tone === "warn" ? "text-amber-300 border-amber-500/20 bg-amber-500/10" : "text-slate-300 border-slate-800 bg-[#0A0B0E]";
  return (
    <div className={`px-3 py-1.5 rounded-xl border flex items-center gap-2 font-mono text-[10px] ${toneClass}`}>
      <span className="text-slate-500">{label.toUpperCase()}</span>
      <span className="font-semibold">{value}</span>
    </div>
  );
}

function KpiCard({ label, value, icon, tone }: { label: string; value: string; icon: ReactNode; tone: "good" | "bad" | "warn" | "neutral" }) {
  const toneClass =
    tone === "good"
      ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/10"
      : tone === "bad"
      ? "bg-rose-500/10 text-rose-300 border-rose-500/10"
      : tone === "warn"
      ? "bg-amber-500/10 text-amber-300 border-amber-500/10"
      : "bg-slate-800/80 text-slate-300 border-slate-700";

  return (
    <div className="bg-bento-card border border-slate-800/80 rounded-2xl p-5 shadow-md">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-mono text-slate-400 uppercase tracking-wider font-semibold">{label}</span>
        <div className={`p-2 rounded-xl border ${toneClass}`}>{icon}</div>
      </div>
      <div className="mt-4 text-2xl font-bold text-white tracking-tight font-sans">{value}</div>
    </div>
  );
}

function TickerTable({
  title,
  rows,
  selectedSymbol,
  onSelectSymbol,
}: {
  title: string;
  rows: MarketTicker[];
  selectedSymbol: string;
  onSelectSymbol: (symbol: string) => void;
}) {
  return (
    <div className="bg-bento-card border border-slate-800 rounded-2xl p-5 shadow-md">
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-sm font-semibold text-white tracking-tight font-sans">{title}</h2>
        <span className="text-[10px] font-mono text-slate-500">{rows.length} symbols</span>
      </div>
      <div className="space-y-2 max-h-[280px] overflow-y-auto pr-1">
        {rows.map((row) => (
          <button
            key={`${title}-${row.symbol}`}
            onClick={() => onSelectSymbol(row.symbol)}
            className={`w-full text-left p-3 rounded-xl border transition-colors cursor-pointer ${
              selectedSymbol === row.symbol ? "border-emerald-500/20 bg-emerald-500/10" : "border-slate-800 bg-[#0A0B0E] hover:border-slate-700"
            }`}
          >
            <div className="flex items-center justify-between">
              <div>
                <div className="text-xs font-semibold text-white">{row.symbol}</div>
                <div className="text-[10px] font-mono text-slate-500 mt-1">Vol {formatCompact(row.volume24h)} | Turnover {formatCompact(row.turnover24h)}</div>
              </div>
              <div className="text-right">
                <div className="text-xs font-semibold text-white">{formatMoney(row.lastPrice)}</div>
                <div className={`text-[10px] font-mono mt-1 ${row.price24hPcnt >= 0 ? "text-emerald-400" : "text-rose-400"}`}>{formatPercent(row.price24hPcnt)}</div>
              </div>
            </div>
          </button>
        ))}
        {rows.length === 0 && <div className="text-xs font-mono text-slate-500 py-8 text-center">No backend market rows available.</div>}
      </div>
    </div>
  );
}

function CandlesPanel({ candles, loading, symbol }: { candles: MarketCandle[]; loading: boolean; symbol: string }) {
  const width = 920;
  const height = 320;
  const paddingLeft = 16;
  const paddingRight = 68;
  const paddingTop = 16;
  const paddingBottom = 28;
  const plotHeight = height - paddingTop - paddingBottom;
  const plotWidth = width - paddingLeft - paddingRight;
  const candleHighs = candles.map((candle) => candle.high);
  const candleLows = candles.map((candle) => candle.low);
  const rawHigh = candleHighs.length > 0 ? Math.max(...candleHighs) : 1;
  const rawLow = candleLows.length > 0 ? Math.min(...candleLows) : 0;
  const pricePadding = Math.max((rawHigh - rawLow) * 0.08, rawHigh > 1 ? 0.5 : 0.0005);
  const high = rawHigh + pricePadding;
  const low = Math.max(rawLow - pricePadding, 0);
  const range = Math.max(high - low, 1);
  const step = candles.length > 0 ? plotWidth / candles.length : plotWidth;
  const candleWidth = candles.length > 0 ? Math.max(Math.min(step * 0.72, 8), 3) : 4;
  const priceLevels = [0, 0.25, 0.5, 0.75, 1].map((line) => high - range * line);
  const timeLabelStep = Math.max(Math.floor(candles.length / 6), 1);
  const latestClose = candles.length > 0 ? candles[candles.length - 1].close : null;

  const y = (value: number) => paddingTop + ((high - value) / range) * plotHeight;

  return (
    <div>
      <div className="flex items-center justify-between mb-3 text-[10px] font-mono text-slate-500">
        <span>{symbol}</span>
        <span>{loading ? "Updating..." : `${candles.length} candles`}</span>
      </div>
      <div className="rounded-2xl border border-slate-800 bg-[#0A0B0E] p-3 overflow-x-auto">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full min-w-[760px]">
          <defs>
            <linearGradient id="dashboardChartBg" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="#0f172a" stopOpacity="0.55" />
              <stop offset="100%" stopColor="#020617" stopOpacity="0.15" />
            </linearGradient>
          </defs>
          <rect x={paddingLeft} y={paddingTop} width={plotWidth} height={plotHeight} rx="10" fill="url(#dashboardChartBg)" />
          {priceLevels.map((level, index) => (
            <g key={level}>
              <line
                x1={paddingLeft}
                x2={width - paddingRight}
                y1={paddingTop + plotHeight * (index / (priceLevels.length - 1))}
                y2={paddingTop + plotHeight * (index / (priceLevels.length - 1))}
                stroke="#1e293b"
                strokeWidth="1"
                strokeDasharray="3 5"
              />
              <text
                x={width - paddingRight + 8}
                y={paddingTop + plotHeight * (index / (priceLevels.length - 1)) + 4}
                fontSize="10"
                fill="#64748b"
                textAnchor="start"
              >
                {formatChartPrice(level)}
              </text>
            </g>
          ))}
          {candles.filter((_, index) => index % timeLabelStep === 0).map((candle, index) => {
            const sourceIndex = index * timeLabelStep;
            const x = paddingLeft + sourceIndex * step + step / 2;
            return (
              <g key={`grid-${candle.timestamp}-${sourceIndex}`}>
                <line
                  x1={x}
                  x2={x}
                  y1={paddingTop}
                  y2={height - paddingBottom}
                  stroke="#0f172a"
                  strokeWidth="1"
                />
                <text
                  x={x}
                  y={height - 8}
                  fontSize="10"
                  fill="#64748b"
                  textAnchor="middle"
                >
                  {formatBdtTime(candle.timestamp)}
                </text>
              </g>
            );
          })}
          {latestClose !== null && (
            <g>
              <line
                x1={paddingLeft}
                x2={width - paddingRight}
                y1={y(latestClose)}
                y2={y(latestClose)}
                stroke="#38bdf8"
                strokeWidth="1"
                strokeDasharray="2 4"
                opacity="0.9"
              />
              <rect
                x={width - paddingRight + 6}
                y={y(latestClose) - 9}
                width="54"
                height="18"
                rx="6"
                fill="#082f49"
                stroke="#0ea5e9"
                opacity="0.95"
              />
              <text x={width - 35} y={y(latestClose) + 4} fontSize="10" fill="#e0f2fe" textAnchor="middle">
                {formatChartPrice(latestClose)}
              </text>
            </g>
          )}
          {candles.map((candle, index) => {
            const x = paddingLeft + index * step + (step - candleWidth) / 2;
            const openY = y(candle.open);
            const closeY = y(candle.close);
            const highY = y(candle.high);
            const lowY = y(candle.low);
            const isBull = candle.close >= candle.open;
            const bodyY = Math.min(openY, closeY);
            const bodyHeight = Math.max(Math.abs(closeY - openY), 2);
            return (
              <g key={`${candle.timestamp}-${index}`}>
                <line
                  x1={x + candleWidth / 2}
                  x2={x + candleWidth / 2}
                  y1={highY}
                  y2={lowY}
                  stroke={isBull ? "#34d399" : "#fb7185"}
                  strokeWidth="1.1"
                  strokeLinecap="round"
                />
                <rect
                  x={x}
                  y={bodyY}
                  width={candleWidth}
                  height={bodyHeight}
                  rx="1"
                  fill={isBull ? "#0f9f6e" : "#e11d48"}
                  stroke={isBull ? "#6ee7b7" : "#fda4af"}
                  strokeWidth="0.7"
                  opacity="0.96"
                />
              </g>
            );
          })}
        </svg>
        {candles.length === 0 && <div className="py-16 text-center text-xs font-mono text-slate-500">No backend candles available for this symbol yet.</div>}
      </div>
    </div>
  );
}
