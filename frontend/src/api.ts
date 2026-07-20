import {
  AccountResponse,
  BacktestResponse,
  BotControlState,
  BotEventEntry,
  ExchangeStatusResponse,
  ExecuteTradeResponse,
  ExecutableSignal,
  HealthResponse,
  JournalTradeEntry,
  LedgerAuditResponse,
  MarketCandlesResponse,
  MarketOverviewResponse,
  MetricsResponse,
  OrderBookResponse,
  PositionSizeResponse,
  PortfolioSummary,
  RiskValidationResponse,
  RiskStateResponse,
  StrategyAuditResponse,
  SystemReadiness,
  Trade,
  TradeHistoryEntry,
  WatchdogSnapshot,
} from "./types";
import { normalizeTrade, normalizeTradeHistoryEntry } from "./tradeTruth";


const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";


class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}


async function request<T>(path: string, options: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");

  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  const text = await response.text();
  const data = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const message = data?.detail || data?.error || `Request failed with status ${response.status}`;
    throw new ApiError(message, response.status);
  }

  return data as T;
}


type BackendSignal = {
  symbol: string;
  strategy_name?: string | null;
  strategy?: string | null;
  direction: string | null;
  entry: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  risk_reward: number | null;
  detected_at: string | null;
  status: string;
  confidence_score?: number | null;
  rejection_reason?: string | null;
};


type BackendTrade = {
  symbol: string;
  strategy_name?: string | null;
  strategy?: string | null;
  direction: string;
  entry: number;
  stop_loss: number;
  take_profit: number;
  quantity: string | number;
  order_id?: string;
  status: string;
  result?: string | null;
  sl_hit_reason?: string | null;
  close_reason?: string | null;
  closed_at?: string | null;
  opened_at?: string | null;
  detected_at?: string | null;
  execution_mode?: "demo" | "live";
  journal_id?: string;
  exit_price?: number | null;
  realized_pnl?: number | null;
  fees?: number | null;
  mark_price?: number | null;
  leverage?: number | null;
  position_value?: number | null;
  position_margin?: number | null;
  unrealized_pnl?: number | null;
  pnl_percent?: number | null;
  liquidation_price?: number | null;
  position_synced?: boolean;
  live_metrics_available?: boolean;
  close_allowed?: boolean;
  close_blocked_reason?: string | null;
  exchange_metadata?: Record<string, unknown>;
};


type FinancialTrade = Trade & {
  realizedPnl: number | null;
  fees: number | null;
  closeReason: string | null;
  liveMetricsAvailable: boolean;
  closeAllowed: boolean;
  closeBlockedReason: string | null;
  liquidationPrice: number | null;
  positionValue: number | null;
};


type MarketCloseResponse = {
  ok: boolean;
  duplicate?: boolean;
  status?: string;
  request_id?: string;
  message?: string;
  error?: string;
  detail?: string | null;
  trade?: Record<string, unknown>;
  order?: Record<string, unknown>;
};


type RiskPayload = {
  symbol: string;
  strategy_name?: string | null;
  strategy?: string | null;
  trade_type?: "scalping" | "intraday" | null;
  direction: string;
  entry: number;
  stop_loss: number;
  take_profit: number;
  risk_reward: number;
  detected_at?: string | null;
  status: string;
};




function toUiSignal(item: BackendSignal, index: number): ExecutableSignal {
  const direction = item.direction?.toUpperCase() === "SHORT" ? "SHORT" : "LONG";
  const rr = Number(item.risk_reward || 0);
  const confidence = Number(item.confidence_score || 0);
  const backendStatus = String(item.status || "").toLowerCase();
  const strategyName = String(item.strategy_name || item.strategy || "unknown");
  const executionStatus =
    backendStatus === "active"
      ? "READY"
      : backendStatus === "near_setup"
      ? "NEAR_SETUP"
      : backendStatus === "expired"
      ? "EXPIRED"
      : "BLOCKED";
  const grade = executionStatus === "READY" ? "A" : executionStatus === "NEAR_SETUP" ? "B+" : "REJECT";

  return {
    id: `${item.symbol}-${strategyName}-${item.detected_at || index}`,
    pair: item.symbol,
    strategyName,
    tradeType: item.trade_type === "intraday" ? "intraday" : item.trade_type === "scalping" ? "scalping" : null,
    timeframe: "5M bias / 1M trigger",
    direction,
    indicator: strategyName,
    price: Number(item.entry || 0),
    strength: executionStatus === "READY" ? "STRONG" : executionStatus === "NEAR_SETUP" ? "MEDIUM" : "WEAK",
    timestamp: item.detected_at || new Date().toISOString(),
    grade,
    score: confidence || (executionStatus === "READY" ? 80 : executionStatus === "NEAR_SETUP" ? 72 : 35),
    entryPrice: Number(item.entry || 0),
    stopLoss: Number(item.stop_loss || 0),
    takeProfit: Number(item.take_profit || 0),
    rr,
    status: executionStatus === "BLOCKED" || executionStatus === "EXPIRED" ? "REJECTED" : "PENDING",
    executionStatus,
    ageMs: item.detected_at ? Math.max(0, Date.now() - new Date(item.detected_at).getTime()) : 0,
    rejectionReason: item.rejection_reason || (!item.direction ? "Signal unavailable" : undefined),
  };
}


function toUiTrade(item: BackendTrade, index: number): Trade {
  return normalizeTrade(item, index);
}


function toTradeHistoryEntry(trade: Trade): TradeHistoryEntry {
  return normalizeTradeHistoryEntry(trade);
}


export const api = {
  login: (username: string, password: string) =>
    request<{ access_token: string; token_type: string; expires_in: number }>("/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  logout: (token: string) =>
    request<{ ok: boolean }>("/logout", { method: "POST" }, token),

  verifySession: (token: string) =>
    request<{ authenticated: boolean; username: string }>("/session/verify", {}, token),

  getHealth: () => request<HealthResponse>("/health"),
  getExchangeStatus: () => request<ExchangeStatusResponse>("/exchange/status"),
  getReadiness: () => request<SystemReadiness>("/readiness"),
  getAccount: (token: string) => request<AccountResponse>("/account", {}, token),
  getSignals: async (token: string) => {
    const response = await request<{ signals: BackendSignal[] }>("/signals", {}, token);
    return response.signals.map(toUiSignal);
  },
  runScanner: (token: string) => request("/scanner/run", { method: "POST" }, token),
  getScannerResults: async (token: string) => {
    const response = await request<{ signals: BackendSignal[] }>("/scanner/results", {}, token);
    return response.signals.map(toUiSignal);
  },
  getMetrics: (token: string) => request<MetricsResponse>("/metrics", {}, token),
  getPortfolio: (token: string) => request<PortfolioSummary>("/portfolio", {}, token),
  getRiskState: (token: string) => request<RiskStateResponse>("/risk/state", {}, token),
  getMarketOverview: (token: string) => request<MarketOverviewResponse>("/market/overview", {}, token),
  getMarketCandles: (token: string, symbol: string, interval = "1", limit = 120) =>
    request<MarketCandlesResponse>(`/market/candles?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}&limit=${limit}`, {}, token),
  getOrderBook: (token: string, symbol: string, limit = 20) =>
    request<OrderBookResponse>(`/market/orderbook?symbol=${encodeURIComponent(symbol)}&limit=${limit}`, {}, token),
  validateRisk: (token: string, payload: RiskPayload) =>
    request<RiskValidationResponse>("/risk/validate", { method: "POST", body: JSON.stringify(payload) }, token),
  calculatePositionSize: (token: string, payload: RiskPayload) =>
    request<PositionSizeResponse>("/position-size/calculate", { method: "POST", body: JSON.stringify(payload) }, token),
  executeTrade: (token: string, payload: RiskPayload) =>
    request<ExecuteTradeResponse>("/execute", { method: "POST", body: JSON.stringify(payload) }, token),
  getActiveTrades: async (token: string) => {
    const response = await request<{ trades: BackendTrade[] }>("/active-trades", {}, token);
    return response.trades.map(toUiTrade);
  },
  marketCloseTrade: (token: string, journalId: string) =>
    request<MarketCloseResponse>(
      `/active-trades/${encodeURIComponent(journalId)}/market-close`,
      { method: "POST" },
      token,
    ),
  getTradeHistory: async (token: string) => {
    const response = await request<{ trades: BackendTrade[] }>("/trade-history", {}, token);
    return response.trades.map((item, index) => toTradeHistoryEntry(toUiTrade(item, index)));
  },
  getJournalTrades: (token: string, options?: RequestInit) => request<{ trades: JournalTradeEntry[] }>("/journal/trades", options, token),
  getLedgerAudit: (token: string, date?: string, options?: RequestInit) =>
    request<LedgerAuditResponse>(`/account/ledger-audit${date ? `?date=${encodeURIComponent(date)}` : ""}`, options, token),
  getStrategyAudit: (token: string, date?: string, options?: RequestInit) =>
    request<StrategyAuditResponse>(`/strategy-audit${date ? `?date=${encodeURIComponent(date)}` : ""}`, options, token),
  getBotEvents: (token: string, limit = 100) => request<{ events: BotEventEntry[] }>(`/bot/events?limit=${limit}`, {}, token),
  getWatchdogStatus: (token: string) => request<WatchdogSnapshot>("/watchdog/status", {}, token),
  getBotStatus: (token: string) => request<BotControlState>("/bot/status", {}, token),
  startBot: (token: string) => request<BotControlState>("/bot/start", { method: "POST" }, token),
  stopBot: (token: string) => request<BotControlState>("/bot/stop", { method: "POST" }, token),
  updateBotConfig: (token: string, payload: {
    execution_mode?: "demo" | "live";
    auto_trading_enabled?: boolean;
    risk_per_trade?: number;
    leverage_cap?: number;
    exposure_cap?: number;
    max_open_trades?: number;
    max_daily_trades?: number;
  }) =>
    request<BotControlState>("/bot/config", { method: "POST", body: JSON.stringify(payload) }, token),
  emergencyStop: (token: string) => request<BotControlState>("/bot/emergency-stop", { method: "POST" }, token),
  resumeBot: (token: string) => request<BotControlState>("/bot/resume", { method: "POST" }, token),
  runBacktest: (token: string, payload: {
    symbol: string;
    strategy: string;
    trade_type: "scalping" | "intraday";
    candle_limit: number;
    candle_offset: number;
    risk_amount: number;
    fee_bps: number;
    min_risk_reward: number;
    max_hold_candles: number;
  }) =>
    request<BacktestResponse>("/backtest/run", { method: "POST", body: JSON.stringify(payload) }, token),
};


export { ApiError };
