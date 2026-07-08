import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api";
import {
  AccountResponse,
  BotControlState,
  ExchangeStatusResponse,
  ExecutableSignal,
  MarketCandle,
  MarketTicker,
  MetricsResponse,
  OrderBookLevel,
  PositionSizeResponse,
  PortfolioSummary,
  RiskValidationResponse,
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
  RadioTower,
  ShieldCheck,
  Wallet,
} from "lucide-react";

interface DashboardViewProps {
  authToken: string | null;
  readiness: SystemReadiness;
  botStatus: BotControlState;
  exchangeStatus: ExchangeStatusResponse;
  account: AccountResponse;
  metrics: MetricsResponse;
  portfolio: PortfolioSummary;
  activeTrades: Trade[];
  signals: ExecutableSignal[];
  tradeHistory: TradeHistoryEntry[];
  lastSync?: Date | null;
  isStale?: boolean;
  onRefreshAll: () => void;
}

type ManualTradeState = {
  symbol: string;
  side: "Buy" | "Sell";
  orderType: "Market" | "Limit";
  limitPrice: string;
  stopLoss: string;
  takeProfit: string;
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

function buildRiskReward(entry: number, stopLoss: number, takeProfit: number) {
  const risk = Math.abs(entry - stopLoss);
  const reward = Math.abs(takeProfit - entry);
  if (risk <= 0 || reward <= 0) {
    return 0;
  }
  return reward / risk;
}

export default function DashboardView({
  authToken,
  readiness,
  botStatus,
  exchangeStatus,
  account,
  metrics,
  portfolio,
  activeTrades,
  signals,
  tradeHistory,
  lastSync,
  isStale,
  onRefreshAll,
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
  const [orderBook, setOrderBook] = useState<{ bids: OrderBookLevel[]; asks: OrderBookLevel[] }>({ bids: [], asks: [] });
  const [marketError, setMarketError] = useState<string | null>(null);
  const [marketLoading, setMarketLoading] = useState(false);
  const [manualLoading, setManualLoading] = useState(false);
  const [manualResult, setManualResult] = useState<RiskValidationResponse | { ok?: boolean; error?: string; warning?: string } | null>(null);
  const [manualSizing, setManualSizing] = useState<PositionSizeResponse | null>(null);
  const [manualTrade, setManualTrade] = useState<ManualTradeState>({
    symbol: "BTCUSDT",
    side: "Buy",
    orderType: "Market",
    limitPrice: "",
    stopLoss: "",
    takeProfit: "",
  });

  const selectedTicker = useMemo(() => {
    const merged = [...overview.watchlist, ...overview.top_gainers];
    return merged.find((item) => item.symbol === selectedSymbol) || null;
  }, [overview, selectedSymbol]);

  useEffect(() => {
    setManualTrade((current) => ({ ...current, symbol: selectedSymbol }));
  }, [selectedSymbol]);

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
        const [candleResponse, orderBookResponse] = await Promise.all([
          api.getMarketCandles(authToken, selectedSymbol, chartInterval, 120),
          api.getOrderBook(authToken, selectedSymbol, 18),
        ]);
        if (!cancelled) {
          setCandles((candleResponse.candles || []).map((item) => ({
            ...item,
            open: numberValue(item.open),
            high: numberValue(item.high),
            low: numberValue(item.low),
            close: numberValue(item.close),
          })));
          setOrderBook(orderBookResponse.orderbook || { bids: [], asks: [] });
          setMarketError(candleResponse.error || orderBookResponse.error || null);
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

  const submitRiskValidation = async (executeAfterValidation: boolean) => {
    if (!authToken) {
      return;
    }

    const entry = manualTrade.orderType === "Limit" ? numberValue(manualTrade.limitPrice) : numberValue(selectedTicker?.lastPrice);
    const stopLoss = numberValue(manualTrade.stopLoss);
    const takeProfit = numberValue(manualTrade.takeProfit);
    const riskReward = buildRiskReward(entry, stopLoss, takeProfit);
    const direction = manualTrade.side === "Buy" ? "long" : "short";

    setManualLoading(true);
    setManualResult(null);
    setManualSizing(null);

    try {
      const payload = {
        symbol: manualTrade.symbol,
        direction,
        entry,
        stop_loss: stopLoss,
        take_profit: takeProfit,
        risk_reward: riskReward,
        detected_at: new Date().toISOString(),
        status: "active",
      };

      const validation = await api.validateRisk(authToken, payload);
      if (!validation.allowed) {
        setManualResult(validation);
        return;
      }

      const sizing = await api.calculatePositionSize(authToken, payload);
      setManualSizing(sizing);
      if (!executeAfterValidation || !sizing.allowed) {
        setManualResult(sizing.allowed ? validation : { allowed: false, reason: sizing.reason });
        return;
      }

      if (manualTrade.orderType === "Limit") {
        setManualResult({ allowed: false, reason: "Limit execution is not available in the backend yet" });
        return;
      }

      const execution = await api.executeTrade(authToken, payload);
      setManualResult({ ok: true, ...(execution as Record<string, unknown>) });
      onRefreshAll();
    } catch (error: any) {
      setManualResult({ ok: false, error: error?.message || "Manual trade action failed" });
    } finally {
      setManualLoading(false);
    }
  };

  return (
    <div className="space-y-6" id="dashboard-view-root">
      <div className="bg-bento-card-sec/40 border border-slate-800/80 rounded-2xl p-6 flex flex-col xl:flex-row justify-between items-start xl:items-center gap-4 shadow-lg backdrop-blur-md" id="dashboard-banner">
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
        <div className="flex flex-wrap items-center gap-3 shrink-0" id="dashboard-status-indicator">
          <StatusPill label="Bot" value={botStatus.status.toUpperCase()} tone={botStatus.status === "running" ? "good" : "muted"} />
          <StatusPill label="Readiness" value={readiness.ready_for_execution ? "READY" : "BLOCKED"} tone={readiness.ready_for_execution ? "good" : "warn"} />
          <StatusPill label="Mode" value={(botStatus.execution_mode || "demo").toUpperCase()} tone={(botStatus.execution_mode || "demo") === "live" ? "warn" : "good"} />
          <StatusPill label="Symbol" value={selectedSymbol} tone="muted" />
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4" id="dashboard-kpi-grid">
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

      <div className="grid grid-cols-1 xl:grid-cols-[1.8fr_1fr] gap-6" id="dashboard-main-panels">
        <div className="space-y-6">
          <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
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

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <TickerTable
              title="Top 20 Gainers"
              rows={overview.top_gainers}
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

        <div className="space-y-6">
          <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="text-sm font-semibold text-white tracking-tight font-sans">Live Order Book</h2>
                <p className="text-xs text-slate-500 mt-1">{selectedSymbol} depth snapshot via backend relay.</p>
              </div>
              <span className="text-[10px] font-mono text-slate-500">BDT {formatBdtTime(overview.server_time || lastSync || undefined)}</span>
            </div>
            <OrderBookPanel asks={orderBook.asks} bids={orderBook.bids} />
          </div>

          <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="text-sm font-semibold text-white tracking-tight font-sans">Manual Trade</h2>
                <p className="text-xs text-slate-500 mt-1">Quantity is calculated only by the backend position sizing engine.</p>
              </div>
              <button
                onClick={onRefreshAll}
                className="px-3 py-1.5 rounded-lg border border-slate-800 bg-[#0A0B0E] text-[10px] font-mono text-slate-400 hover:text-white cursor-pointer"
              >
                Refresh
              </button>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Symbol">
                <input
                  value={manualTrade.symbol}
                  onChange={(event) => {
                    const symbol = event.target.value.toUpperCase();
                    setManualTrade((current) => ({ ...current, symbol }));
                    setSelectedSymbol(symbol);
                  }}
                  className="dashboard-input"
                />
              </Field>
              <Field label="Side">
                <select
                  value={manualTrade.side}
                  onChange={(event) => setManualTrade((current) => ({ ...current, side: event.target.value as "Buy" | "Sell" }))}
                  className="dashboard-input"
                >
                  <option>Buy</option>
                  <option>Sell</option>
                </select>
              </Field>
              <Field label="Order Type">
                <select
                  value={manualTrade.orderType}
                  onChange={(event) => setManualTrade((current) => ({ ...current, orderType: event.target.value as "Market" | "Limit" }))}
                  className="dashboard-input"
                >
                  <option>Market</option>
                  <option>Limit</option>
                </select>
              </Field>
              <Field label={manualTrade.orderType === "Limit" ? "Limit Price" : "Reference Price"}>
                <input
                  value={manualTrade.orderType === "Limit" ? manualTrade.limitPrice : String(selectedTicker?.lastPrice || "")}
                  onChange={(event) => setManualTrade((current) => ({ ...current, limitPrice: event.target.value }))}
                  disabled={manualTrade.orderType === "Market"}
                  className="dashboard-input disabled:opacity-50"
                />
              </Field>
              <Field label="Stop Loss">
                <input
                  value={manualTrade.stopLoss}
                  onChange={(event) => setManualTrade((current) => ({ ...current, stopLoss: event.target.value }))}
                  className="dashboard-input"
                />
              </Field>
              <Field label="Take Profit">
                <input
                  value={manualTrade.takeProfit}
                  onChange={(event) => setManualTrade((current) => ({ ...current, takeProfit: event.target.value }))}
                  className="dashboard-input"
                />
              </Field>
            </div>

            <div className="mt-4 p-3 rounded-xl bg-[#0A0B0E] border border-slate-800 text-[10px] font-mono text-slate-500">
              Selected last price: <span className="text-slate-200">{selectedTicker ? formatMoney(selectedTicker.lastPrice) : "N/A"}</span> | 24h change:{" "}
              <span className={selectedTicker && selectedTicker.price24hPcnt >= 0 ? "text-emerald-400" : "text-rose-400"}>
                {selectedTicker ? formatPercent(selectedTicker.price24hPcnt) : "N/A"}
              </span>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3">
              <SizingMetric label="Backend Quantity" value={manualSizing?.quantity || "Calculate first"} good={manualSizing?.allowed} />
              <SizingMetric label="Risk Amount" value={manualSizing?.risk_amount !== undefined ? formatMoney(manualSizing.risk_amount) : "N/A"} good={manualSizing?.allowed} />
              <SizingMetric label="Notional" value={manualSizing?.notional !== undefined ? formatMoney(manualSizing.notional) : "N/A"} />
              <SizingMetric label="Required Margin" value={manualSizing?.required_margin !== undefined ? formatMoney(manualSizing.required_margin) : "N/A"} />
              <SizingMetric label="Equity" value={manualSizing?.equity !== undefined ? formatMoney(manualSizing.equity) : "N/A"} />
              <SizingMetric label="Leverage Cap" value={manualSizing?.leverage_cap !== undefined ? `${manualSizing.leverage_cap}x` : "N/A"} />
            </div>

            <div className="mt-4 flex gap-3">
              <button
                onClick={() => submitRiskValidation(false)}
                disabled={manualLoading}
                className="flex-1 px-4 py-2 rounded-xl border border-amber-500/20 bg-amber-500/10 text-amber-300 text-xs font-semibold cursor-pointer disabled:opacity-50"
              >
                {manualLoading ? "Checking..." : "Calculate Size"}
              </button>
              <button
                onClick={() => submitRiskValidation(true)}
                disabled={manualLoading || manualTrade.orderType === "Limit"}
                className="flex-1 px-4 py-2 rounded-xl border border-emerald-500/20 bg-emerald-500/10 text-emerald-300 text-xs font-semibold cursor-pointer disabled:opacity-50"
              >
                {manualLoading ? "Processing..." : "Place Market Order"}
              </button>
            </div>

            {manualTrade.orderType === "Limit" && (
              <p className="mt-3 text-[10px] font-mono text-slate-500">Limit order execution is not exposed by the backend yet. Risk validation still works.</p>
            )}

            {manualResult && (
              <div className={`mt-4 p-4 rounded-xl border text-xs font-mono ${
                "allowed" in manualResult
                  ? manualResult.allowed
                    ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-300"
                    : "bg-amber-500/10 border-amber-500/20 text-amber-300"
                  : manualResult.ok
                  ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-300"
                  : "bg-rose-500/10 border-rose-500/20 text-rose-300"
              }`}>
                {"allowed" in manualResult ? (
                  <span>{manualResult.allowed ? "Risk and sizing validation passed." : manualResult.reason || "Risk validation failed."}</span>
                ) : (
                  <span>{manualResult.error || manualResult.warning || "Trade request completed."}</span>
                )}
              </div>
            )}
          </div>
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
    <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-sm font-semibold text-white tracking-tight font-sans">{title}</h2>
        <span className="text-[10px] font-mono text-slate-500">{rows.length} symbols</span>
      </div>
      <div className="space-y-2 max-h-[420px] overflow-y-auto pr-1">
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

function OrderBookPanel({ asks, bids }: { asks: OrderBookLevel[]; bids: OrderBookLevel[] }) {
  const askRows = [...asks].slice(0, 10).reverse();
  const bidRows = [...bids].slice(0, 10);
  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="space-y-2">
        <div className="text-[10px] font-mono text-rose-400 uppercase tracking-wider">Asks</div>
        {askRows.map((row, index) => (
          <DepthRow key={`ask-${index}`} level={row} side="ask" />
        ))}
      </div>
      <div className="space-y-2">
        <div className="text-[10px] font-mono text-emerald-400 uppercase tracking-wider">Bids</div>
        {bidRows.map((row, index) => (
          <DepthRow key={`bid-${index}`} level={row} side="bid" />
        ))}
      </div>
    </div>
  );
}

function DepthRow({ level, side }: { level: OrderBookLevel; side: "bid" | "ask" }) {
  return (
    <div className={`grid grid-cols-2 gap-2 text-[10px] font-mono px-3 py-2 rounded-lg border ${
      side === "bid" ? "bg-emerald-500/8 border-emerald-500/10 text-emerald-300" : "bg-rose-500/8 border-rose-500/10 text-rose-300"
    }`}>
      <span>{numberValue(level.price).toFixed(4)}</span>
      <span className="text-right">{numberValue(level.size).toFixed(4)}</span>
    </div>
  );
}

function CandlesPanel({ candles, loading, symbol }: { candles: MarketCandle[]; loading: boolean; symbol: string }) {
  const width = 920;
  const height = 340;
  const paddingX = 16;
  const paddingTop = 20;
  const paddingBottom = 32;
  const plotHeight = height - paddingTop - paddingBottom;
  const plotWidth = width - paddingX * 2;

  const high = Math.max(...candles.map((candle) => candle.high), 1);
  const low = Math.min(...candles.map((candle) => candle.low), 0);
  const range = Math.max(high - low, 1);
  const candleWidth = candles.length > 0 ? Math.max(plotWidth / candles.length - 2, 2) : 4;

  const y = (value: number) => paddingTop + ((high - value) / range) * plotHeight;

  return (
    <div>
      <div className="flex items-center justify-between mb-3 text-[10px] font-mono text-slate-500">
        <span>{symbol}</span>
        <span>{loading ? "Updating..." : `${candles.length} candles`}</span>
      </div>
      <div className="rounded-2xl border border-slate-800 bg-[#0A0B0E] p-3 overflow-x-auto">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full min-w-[760px]">
          {[0, 0.25, 0.5, 0.75, 1].map((line) => (
            <line
              key={line}
              x1={paddingX}
              x2={width - paddingX}
              y1={paddingTop + plotHeight * line}
              y2={paddingTop + plotHeight * line}
              stroke="#1f2937"
              strokeWidth="1"
              strokeDasharray="4 6"
            />
          ))}
          {candles.map((candle, index) => {
            const x = paddingX + index * (plotWidth / Math.max(candles.length, 1)) + 1;
            const openY = y(candle.open);
            const closeY = y(candle.close);
            const highY = y(candle.high);
            const lowY = y(candle.low);
            const isBull = candle.close >= candle.open;
            const bodyY = Math.min(openY, closeY);
            const bodyHeight = Math.max(Math.abs(closeY - openY), 1.5);
            return (
              <g key={`${candle.timestamp}-${index}`}>
                <line
                  x1={x + candleWidth / 2}
                  x2={x + candleWidth / 2}
                  y1={highY}
                  y2={lowY}
                  stroke={isBull ? "#10b981" : "#f43f5e"}
                  strokeWidth="1.2"
                />
                <rect
                  x={x}
                  y={bodyY}
                  width={candleWidth}
                  height={bodyHeight}
                  rx="1"
                  fill={isBull ? "#10b981" : "#f43f5e"}
                  opacity="0.9"
                />
              </g>
            );
          })}
          {candles.filter((_, index) => index % Math.max(Math.floor(candles.length / 5), 1) === 0).map((candle, index) => (
            <text
              key={`label-${candle.timestamp}-${index}`}
              x={paddingX + index * Math.max(plotWidth / 5, 1)}
              y={height - 10}
              fontSize="10"
              fill="#64748b"
            >
              {formatBdtTime(candle.timestamp)}
            </text>
          ))}
        </svg>
        {candles.length === 0 && <div className="py-16 text-center text-xs font-mono text-slate-500">No backend candles available for this symbol yet.</div>}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="space-y-2 block">
      <span className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{label}</span>
      {children}
    </label>
  );
}

function SizingMetric({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
      <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-2 text-xs font-semibold ${good === undefined ? "text-white" : good ? "text-emerald-300" : "text-amber-300"}`}>
        {value}
      </div>
    </div>
  );
}
