import {
  AccountResponse,
  BotControlState,
  BotEventEntry,
  ExchangeStatusResponse,
  ExecutableSignal,
  HealthResponse,
  JournalTradeEntry,
  MarketCandlesResponse,
  MarketOverviewResponse,
  MetricsResponse,
  OrderBookResponse,
  PositionSizeResponse,
  PortfolioSummary,
  RiskValidationResponse,
  RiskStateResponse,
  SystemReadiness,
  Trade,
  TradeHistoryEntry,
  WatchdogSnapshot,
} from "./types";


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
  direction: string;
  entry: number;
  stop_loss: number;
  take_profit: number;
  quantity: string | number;
  order_id?: string;
  status: string;
  result?: string | null;
  sl_hit_reason?: string | null;
  closed_at?: string | null;
  execution_mode?: "demo" | "live";
  journal_id?: string;
  exit_price?: number | null;
};

type RiskPayload = {
  symbol: string;
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

  return {
    id: `${item.symbol}-${item.detected_at || index}`,
    pair: item.symbol,
    timeframe: "5M bias / 1M trigger",
    direction,
    indicator: "EMA Pullback",
    price: Number(item.entry || 0),
    strength: confidence >= 85 ? "STRONG" : rr >= 2 ? "MEDIUM" : "WEAK",
    timestamp: item.detected_at || new Date().toISOString(),
    grade: confidence >= 90 ? "A+" : rr >= 2 ? "A" : "REJECT",
    score: confidence || (rr >= 2 ? 80 : 40),
    entryPrice: Number(item.entry || 0),
    stopLoss: Number(item.stop_loss || 0),
    takeProfit: Number(item.take_profit || 0),
    rr,
    status: item.status === "active" ? "PENDING" : "REJECTED",
    executionStatus: item.status === "active" ? "READY" : item.status === "expired" ? "EXPIRED" : "BLOCKED",
    ageMs: item.detected_at ? Math.max(0, Date.now() - new Date(item.detected_at).getTime()) : 0,
    rejectionReason: item.rejection_reason || (!item.direction ? "Signal unavailable" : undefined),
  };
}


function toUiTrade(item: BackendTrade, index: number): Trade {
  const entryPrice = Number(item.entry || 0);
  const stopLoss = Number(item.stop_loss || 0);
  const takeProfit = Number(item.take_profit || 0);
  const size = Number(item.quantity || 0);
  const direction = item.direction?.toUpperCase() === "SHORT" ? "SHORT" : "LONG";
  const rawResult = String(item.result || "").toUpperCase();

  return {
    id: item.order_id || item.journal_id || `${item.symbol}-${index}`,
    pair: item.symbol,
    strategy: "EMA Pullback",
    direction,
    entryPrice,
    currentPrice: entryPrice,
    stopLoss,
    takeProfit,
    size,
    margin: 0,
    leverage: 1,
    unrealizedPnl: 0,
    pnlPercent: 0,
    status: item.status === "closed" ? "CLOSED" : "OPEN",
    timestamp: item.closed_at || new Date().toISOString(),
    orderConfirmed: Boolean(item.order_id),
    slVerified: item.status !== "protection_pending",
    tpVerified: item.status !== "protection_pending",
    positionSynced: true,
    orderId: item.order_id,
    rawStatus: item.status,
    journalId: item.journal_id,
    executionMode: item.execution_mode || "demo",
    result: rawResult === "TP" ? "TP" : rawResult === "SL" ? "SL" : "UNKNOWN",
    closedAt: item.closed_at || undefined,
    slHitReason: item.sl_hit_reason ?? null,
    exitPrice: Number(item.exit_price || 0),
  };
}


function toTradeHistoryEntry(trade: Trade): TradeHistoryEntry {
  const isProfit = trade.result === "TP";
  const exitPrice = Number(trade.exitPrice || 0);
  const pnlValue = trade.result === "SL" ? -1 : trade.result === "TP" ? 2 : 0;

  return {
    ...trade,
    exitPrice,
    pnl: pnlValue,
    result: isProfit ? "PROFIT" : "LOSS",
    reason: trade.slHitReason || "n/a",
    closedAt: trade.closedAt || trade.timestamp,
  };
}


export const api = {
  login: (username: string, password: string) =>
    request<{ access_token: string; token_type: string }>("/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

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
    request("/execute", { method: "POST", body: JSON.stringify(payload) }, token),
  getActiveTrades: async (token: string) => {
    const response = await request<{ trades: BackendTrade[] }>("/active-trades", {}, token);
    return response.trades.map(toUiTrade);
  },
  getTradeHistory: async (token: string) => {
    const response = await request<{ trades: BackendTrade[] }>("/trade-history", {}, token);
    return response.trades.map((item, index) => toTradeHistoryEntry(toUiTrade(item, index)));
  },
  getJournalTrades: (token: string) => request<{ trades: JournalTradeEntry[] }>("/journal/trades", {}, token),
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
};


export { ApiError };
