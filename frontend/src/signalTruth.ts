const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export type CanonicalSignalState = "NO_SETUP" | "NEAR_SETUP" | "ACTIVE" | "INVALID" | "EXPIRED";

export type SignalTimeframes = {
  trend?: string;
  setup?: string;
  trigger?: string;
  open_candle_confirmation?: boolean;
};

export interface TruthSignal {
  id: string;
  symbol: string;
  strategyName: string;
  tradeType: "scalping" | "intraday" | null;
  direction: "LONG" | "SHORT" | null;
  entry: number | null;
  stopLoss: number | null;
  takeProfit: number | null;
  riskReward: number | null;
  detectedAt: string | null;
  signalState: CanonicalSignalState;
  rawStatus: string;
  confidenceScore: number | null;
  rejectionReason: string | null;
  trendState: string | null;
  trendStrength: number | null;
  approvedDirection: "LONG" | "SHORT" | null;
  marketRank: number | null;
  signalRank: number | null;
  marketScore: number | null;
  signalScore: number | null;
  primarySignal: boolean;
  geometryValid: boolean;
  isExecutable: boolean;
  monitorOnly: boolean;
  timeframes: SignalTimeframes;
  confirmationCount: number;
  matchedStrategies: string[];
}

export interface TruthSummary {
  symbolsScanned: number | null;
  symbolsRepresented: number;
  rankedMarkets: number;
  strategyChecks: number;
  nearSetups: number;
  activeSignals: number;
  uptrendProfiles: number;
  downtrendProfiles: number;
  sidewaysRejectedProfiles: number | null;
  insufficientOrStaleProfiles: number | null;
  modeAudit: Record<"scalping" | "intraday" | "unknown", TruthModeAudit>;
}

export interface TruthModeAudit {
  checks: number;
  active: number;
  nearSetup: number;
  invalid: number;
  noSetup: number;
  topRejectionReason: string | null;
}

export interface SignalTruthPayload {
  results: TruthSignal[];
  primarySignals: TruthSignal[];
  activeSignals: TruthSignal[];
  marketRows: TruthSignal[];
  summary: TruthSummary;
  capturedAt: string;
  source: "results" | "manual_scan";
}

type RawSignal = Record<string, unknown>;
type RawScanResponse = {
  ok?: boolean;
  symbols_scanned?: number;
  ranked_symbols?: number;
  strategy_checks?: number;
  signals?: RawSignal[];
  results?: RawSignal[];
  rejected_markets?: Array<Record<string, unknown>>;
};

async function requestJson<T>(path: string, token: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(data?.detail || data?.error || `Request failed with status ${response.status}`);
  }
  return data as T;
}

export async function fetchSignalTruth(token: string): Promise<SignalTruthPayload> {
  const [scannerResponse, activeResponse] = await Promise.all([
    requestJson<{ signals?: RawSignal[] }>("/scanner/results", token),
    requestJson<{ signals?: RawSignal[] }>("/signals", token),
  ]);

  const results = (scannerResponse.signals || []).map(normalizeSignal);
  const activeFromEndpoint = (activeResponse.signals || []).map(normalizeSignal);
  return buildPayload(results, activeFromEndpoint, null, "results");
}

export async function runSignalTruthScan(token: string): Promise<SignalTruthPayload> {
  const response = await requestJson<RawScanResponse>("/scanner/run", token, { method: "POST" });
  if (response.ok === false) {
    throw new Error("Scanner reported an unsuccessful result.");
  }

  const results = (response.results || []).map(normalizeSignal);
  const activeSignals = (response.signals || []).map(normalizeSignal);
  return buildPayload(results, activeSignals, response, "manual_scan");
}

function buildPayload(
  results: TruthSignal[],
  activeFromEndpoint: TruthSignal[],
  scan: RawScanResponse | null,
  source: SignalTruthPayload["source"],
): SignalTruthPayload {
  const usefulPrimary = results
    .filter((signal) => signal.primarySignal && ["ACTIVE", "NEAR_SETUP"].includes(signal.signalState))
    .sort(primarySort);

  const activeFallback = dedupeBySymbol(
    activeFromEndpoint.filter((signal) => signal.signalState === "ACTIVE"),
  ).sort(primarySort);

  const primarySignals = usefulPrimary.length > 0 ? dedupeBySymbol(usefulPrimary) : activeFallback;
  const activeSignals = dedupeBySymbol(
    primarySignals.filter((signal) => signal.signalState === "ACTIVE"),
  ).sort(primarySort);
  const marketRows = selectMarketRows(results);
  const summary = summarize(results, primarySignals, activeSignals, marketRows, scan);

  return {
    results: [...results].sort(resultSort),
    primarySignals: primarySignals.sort(primarySort),
    activeSignals,
    marketRows,
    summary,
    capturedAt: new Date().toISOString(),
    source,
  };
}

function normalizeSignal(raw: RawSignal, index: number): TruthSignal {
  const signalState = canonicalState(raw.signal_state ?? raw.status, raw.rejection_reason);
  const direction = normalizeDirection(raw.direction);
  const trendState = stringOrNull(raw.trend_state);
  const timeframes = isRecord(raw.timeframes) ? (raw.timeframes as SignalTimeframes) : {};
  const tradeType = normalizeTradeType(raw.trade_type);
  const strategyName = String(raw.strategy_name || raw.strategy || "unknown");
  const detectedAt = stringOrNull(raw.detected_at);
  const signalKey = stringOrNull(raw.signal_key);

  return {
    id: signalKey || [raw.symbol, tradeType, strategyName, direction, detectedAt, index].join("|"),
    symbol: String(raw.symbol || "UNKNOWN").toUpperCase(),
    strategyName,
    tradeType,
    direction,
    entry: nullableNumber(raw.entry),
    stopLoss: nullableNumber(raw.stop_loss),
    takeProfit: nullableNumber(raw.take_profit),
    riskReward: nullableNumber(raw.risk_reward),
    detectedAt,
    signalState,
    rawStatus: String(raw.raw_status || raw.status || ""),
    confidenceScore: nullableNumber(raw.confidence_score),
    rejectionReason: stringOrNull(raw.rejection_reason),
    trendState,
    trendStrength: nullableNumber(raw.trend_strength),
    approvedDirection: trendState === "UPTREND" ? "LONG" : trendState === "DOWNTREND" ? "SHORT" : null,
    marketRank: nullableInteger(raw.market_rank),
    signalRank: nullableInteger(raw.signal_rank),
    marketScore: nullableNumber(raw.market_score),
    signalScore: nullableNumber(raw.signal_score),
    primarySignal: raw.primary_signal === true,
    geometryValid: raw.geometry_valid === true,
    isExecutable: raw.is_executable === true,
    monitorOnly: raw.monitor_only === true,
    timeframes,
    confirmationCount: nullableInteger(raw.confirmation_count) || 0,
    matchedStrategies: Array.isArray(raw.matched_strategies)
      ? raw.matched_strategies.map((item) => String(item)).filter(Boolean)
      : [],
  };
}

function summarize(
  results: TruthSignal[],
  primarySignals: TruthSignal[],
  activeSignals: TruthSignal[],
  marketRows: TruthSignal[],
  scan: RawScanResponse | null,
): TruthSummary {
  const profileContexts = new Map<string, TruthSignal>();
  results.forEach((signal) => {
    const key = `${signal.symbol}|${signal.tradeType || "unknown"}`;
    if (!profileContexts.has(key)) profileContexts.set(key, signal);
  });

  let uptrendProfiles = 0;
  let downtrendProfiles = 0;
  profileContexts.forEach((signal) => {
    if (signal.trendState === "UPTREND") uptrendProfiles += 1;
    if (signal.trendState === "DOWNTREND") downtrendProfiles += 1;
  });

  let sidewaysRejectedProfiles: number | null = null;
  let insufficientOrStaleProfiles: number | null = null;
  if (scan) {
    sidewaysRejectedProfiles = 0;
    insufficientOrStaleProfiles = 0;
    (scan.rejected_markets || []).forEach((market) => {
      const profiles = isRecord(market.profiles) ? market.profiles : {};
      Object.values(profiles).forEach((profile) => {
        if (!isRecord(profile)) return;
        const reason = String(profile.rejection_reason || "").toLowerCase();
        const trend = isRecord(profile.trend) ? String(profile.trend.state || "") : "";
        if (reason.includes("sideways") || trend === "SIDEWAYS") sidewaysRejectedProfiles! += 1;
        if (reason.includes("insufficient") || reason.includes("stale") || ["INSUFFICIENT_DATA", "STALE_DATA"].includes(trend)) {
          insufficientOrStaleProfiles! += 1;
        }
      });
    });
  }

  const representedSymbols = new Set(results.map((signal) => signal.symbol)).size;

  return {
    symbolsScanned: scan ? finiteInteger(scan.symbols_scanned) : representedSymbols || null,
    symbolsRepresented: representedSymbols,
    rankedMarkets: scan ? finiteInteger(scan.ranked_symbols) : new Set(marketRows.map((signal) => signal.symbol)).size,
    strategyChecks: scan ? finiteInteger(scan.strategy_checks) : results.length,
    nearSetups: primarySignals.filter((signal) => signal.signalState === "NEAR_SETUP").length,
    activeSignals: activeSignals.length,
    uptrendProfiles,
    downtrendProfiles,
    sidewaysRejectedProfiles,
    insufficientOrStaleProfiles,
    modeAudit: summarizeModeAudit(results),
  };
}

function summarizeModeAudit(results: TruthSignal[]): TruthSummary["modeAudit"] {
  const audit: TruthSummary["modeAudit"] = {
    scalping: emptyModeAudit(),
    intraday: emptyModeAudit(),
    unknown: emptyModeAudit(),
  };
  const rejectionCounts: Record<keyof TruthSummary["modeAudit"], Map<string, number>> = {
    scalping: new Map(),
    intraday: new Map(),
    unknown: new Map(),
  };

  results.forEach((signal) => {
    const key = signal.tradeType || "unknown";
    const item = audit[key];
    item.checks += 1;
    if (signal.signalState === "ACTIVE") item.active += 1;
    if (signal.signalState === "NEAR_SETUP") item.nearSetup += 1;
    if (signal.signalState === "INVALID") item.invalid += 1;
    if (signal.signalState === "NO_SETUP") item.noSetup += 1;
    if (signal.rejectionReason) {
      const counts = rejectionCounts[key];
      counts.set(signal.rejectionReason, (counts.get(signal.rejectionReason) || 0) + 1);
    }
  });

  (Object.keys(audit) as Array<keyof TruthSummary["modeAudit"]>).forEach((key) => {
    const top = [...rejectionCounts[key].entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0];
    audit[key].topRejectionReason = top?.[0] || null;
  });

  return audit;
}

function emptyModeAudit(): TruthModeAudit {
  return {
    checks: 0,
    active: 0,
    nearSetup: 0,
    invalid: 0,
    noSetup: 0,
    topRejectionReason: null,
  };
}

function selectMarketRows(results: TruthSignal[]): TruthSignal[] {
  const grouped = new Map<string, TruthSignal[]>();
  results.forEach((signal) => {
    const current = grouped.get(signal.symbol) || [];
    current.push(signal);
    grouped.set(signal.symbol, current);
  });

  return [...grouped.values()]
    .map((signals) => [...signals].sort(marketRowSort)[0])
    .sort((a, b) => (a.marketRank ?? 9999) - (b.marketRank ?? 9999) || a.symbol.localeCompare(b.symbol));
}

function dedupeBySymbol(signals: TruthSignal[]): TruthSignal[] {
  const best = new Map<string, TruthSignal>();
  signals.forEach((signal) => {
    const current = best.get(signal.symbol);
    if (!current || primarySort(signal, current) < 0) best.set(signal.symbol, signal);
  });
  return [...best.values()];
}

function canonicalState(status: unknown, reason: unknown): CanonicalSignalState {
  const normalized = String(status || "").toUpperCase();
  const normalizedReason = String(reason || "").toLowerCase();
  if (["NO_SETUP", "NEAR_SETUP", "ACTIVE", "INVALID", "EXPIRED"].includes(normalized)) {
    return normalized as CanonicalSignalState;
  }
  if (normalized === "READY") return "ACTIVE";
  if (normalized === "NEAR") return "NEAR_SETUP";
  if (normalized === "EXPIRED" || normalizedReason === "signal_expired") return "EXPIRED";
  if (normalized === "INVALID" || normalized === "BLOCKED") return "INVALID";
  return "NO_SETUP";
}

function normalizeDirection(value: unknown): TruthSignal["direction"] {
  const normalized = String(value || "").toUpperCase();
  return normalized === "LONG" || normalized === "SHORT" ? normalized : null;
}

function normalizeTradeType(value: unknown): TruthSignal["tradeType"] {
  const normalized = String(value || "").toLowerCase();
  return normalized === "scalping" || normalized === "intraday" ? normalized : null;
}

function primarySort(a: TruthSignal, b: TruthSignal): number {
  const statePriority: Record<CanonicalSignalState, number> = {
    ACTIVE: 0,
    NEAR_SETUP: 1,
    NO_SETUP: 2,
    INVALID: 3,
    EXPIRED: 4,
  };
  return (
    statePriority[a.signalState] - statePriority[b.signalState] ||
    (b.signalScore ?? -1) - (a.signalScore ?? -1) ||
    (a.marketRank ?? 9999) - (b.marketRank ?? 9999) ||
    a.symbol.localeCompare(b.symbol)
  );
}

function resultSort(a: TruthSignal, b: TruthSignal): number {
  return primarySort(a, b) || a.strategyName.localeCompare(b.strategyName);
}

function marketRowSort(a: TruthSignal, b: TruthSignal): number {
  if (a.primarySignal !== b.primarySignal) return a.primarySignal ? -1 : 1;
  return primarySort(a, b);
}

function nullableNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function nullableInteger(value: unknown): number | null {
  const numeric = nullableNumber(value);
  return numeric === null ? null : Math.trunc(numeric);
}

function finiteInteger(value: unknown): number {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? Math.max(0, Math.trunc(numeric)) : 0;
}

function stringOrNull(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  return String(value);
}

function isRecord(value: unknown): value is Record<string, any> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
