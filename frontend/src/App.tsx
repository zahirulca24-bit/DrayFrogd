import { useEffect, useRef, useState } from "react";
import { LogOut, Menu, RefreshCw, Server } from "lucide-react";
import { api, ApiError } from "./api";
import {
  AccountResponse,
  BotControlState,
  BotEventEntry,
  ExecuteTradeResponse,
  ExchangeStatusResponse,
  ExecutableSignal,
  MetricsResponse,
  PortfolioSummary,
  RiskStateResponse,
  SystemReadiness,
  Trade,
  TradeHistoryEntry,
  WatchdogSnapshot,
} from "./types";
import Sidebar from "./components/Sidebar";
import LockScreen from "./components/LockScreen";
import DashboardView from "./components/DashboardView";
import ControlPanel from "./components/ControlPanel";
import SignalEngine from "./components/SignalEngine";
import ActiveTrades from "./components/ActiveTrades";
import TradeHistory from "./components/TradeHistory";
import PerformanceStrategy from "./components/PerformanceStrategy";
import PageShell from "./components/PageShell";
import Watchdog from "./components/Watchdog";


const emptyReadiness: SystemReadiness = {
  mode: "demo",
  checks: {
    admin_auth_configured: false,
    api_keys_present: false,
    exchange_reachable: false,
    wallet_fetch_success: false,
  },
  errors: {
    exchange: null,
    wallet: null,
  },
  ready_for_execution: false,
};

const emptyExchangeStatus: ExchangeStatusResponse = {
  mode: "demo",
  demo_only: true,
  base_url: "http://localhost:8000",
  api_keys_present: false,
  reachable: false,
  error: null,
};

const emptyAccount: AccountResponse = {
  ok: false,
  mode: "demo",
  wallet: { ok: false, data: null, error: null },
  positions: { ok: false, data: [], error: null },
};

const emptyMetrics: MetricsResponse = {
  total_trades: 0,
  active_trades_count: 0,
  closed_trades_count: 0,
  win_trades: 0,
  loss_trades: 0,
  win_rate: 0,
  pnl_r: 0,
};

const emptyPortfolio: PortfolioSummary = {
  active_trades: 0,
  closed_trades: 0,
  total_trades: 0,
  win_rate: 0,
  pnl_r: 0,
  execution_mode: "demo",
};

const emptyBotStatus: BotControlState = {
  status: "idle",
  emergency_stop: false,
  execution_mode: "demo",
  auto_trading_enabled: true,
  live_mode_available: false,
};

const emptyRiskState: RiskStateResponse = {
  risk_per_trade: 0.01,
  leverage_cap: 5,
  exposure_cap: 0.3,
  max_open_trades: 3,
  max_trades_per_day: 8,
  min_risk_reward: 2,
  active_symbols: [],
  trades_today: 0,
  cooldown_until: null,
};

const emptyWatchdog: WatchdogSnapshot = {
  generated_at: new Date(0).toISOString(),
  mode: "demo",
  admin_auth_configured: false,
  modules: [],
  incidents: [],
  summary: {
    overall_status: "DEGRADED",
    open_incidents: 0,
    total_incidents: 0,
    affected_modules: [],
  },
};


export default function App() {
  const [authToken, setAuthToken] = useState<string | null>(localStorage.getItem("scalp_token"));
  const [activeTab, setActiveTab] = useState("dashboard");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [signals, setSignals] = useState<ExecutableSignal[]>([]);
  const [scannerResults, setScannerResults] = useState<ExecutableSignal[]>([]);
  const [activeTrades, setActiveTrades] = useState<Trade[]>([]);
  const [tradeHistory, setTradeHistory] = useState<TradeHistoryEntry[]>([]);
  const [readiness, setReadiness] = useState<SystemReadiness>(emptyReadiness);
  const [exchangeStatus, setExchangeStatus] = useState<ExchangeStatusResponse>(emptyExchangeStatus);
  const [account, setAccount] = useState<AccountResponse>(emptyAccount);
  const [metrics, setMetrics] = useState<MetricsResponse>(emptyMetrics);
  const [portfolio, setPortfolio] = useState<PortfolioSummary>(emptyPortfolio);
  const [riskState, setRiskState] = useState<RiskStateResponse>(emptyRiskState);
  const [botEvents, setBotEvents] = useState<BotEventEntry[]>([]);
  const [watchdog, setWatchdog] = useState<WatchdogSnapshot>(emptyWatchdog);
  const [botStatus, setBotStatus] = useState<BotControlState>(emptyBotStatus);
  const [healthStatus, setHealthStatus] = useState<"ONLINE" | "OFFLINE">("OFFLINE");
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const [isStale, setIsStale] = useState(false);
  const isFetchingRef = useRef(false);

  useEffect(() => {
    const pageNameMap: Record<string, string> = {
      dashboard: "Dashboard",
      "signal-engine": "Signal Engine",
      "active-trades": "Active Trades",
      journal: "Journal / Trade History",
      "performance-strategy": "Performance & Strategy",
      "control-panel": "Control Panel",
      watchdog: "Watchdog",
      settings: "Settings",
    };

    document.title = `DayFrogd-ScalpingEngin | ${pageNameMap[activeTab] || "Terminal"}`;
  }, [activeTab]);

  useEffect(() => {
    setMobileSidebarOpen(false);
  }, [activeTab]);

  const logout = () => {
    localStorage.removeItem("scalp_token");
    setAuthToken(null);
    setSignals([]);
    setScannerResults([]);
    setActiveTrades([]);
    setTradeHistory([]);
    setReadiness(emptyReadiness);
    setExchangeStatus(emptyExchangeStatus);
    setAccount(emptyAccount);
    setMetrics(emptyMetrics);
    setPortfolio(emptyPortfolio);
    setRiskState(emptyRiskState);
    setBotEvents([]);
    setWatchdog(emptyWatchdog);
    setBotStatus(emptyBotStatus);
  };

  const onUnlock = async (username: string, password: string) => {
    const response = await api.login(username, password);
    localStorage.setItem("scalp_token", response.access_token);
    setAuthToken(response.access_token);
  };

  const fetchAllData = async (silent = false) => {
    if (!authToken || isFetchingRef.current) {
      return;
    }

    isFetchingRef.current = true;
    if (!silent) {
      setLoading(true);
    }
    setErrorMsg(null);

    const safe = async <T,>(promise: Promise<T>, fallback: T): Promise<T> => {
      try {
        return await promise;
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          throw err;
        }
        return fallback;
      }
    };

    try {
      await api.verifySession(authToken);

      const [
        health,
        readinessRes,
        exchangeRes,
        accountRes,
        metricsRes,
        portfolioRes,
        riskRes,
        tradesRes,
        historyRes,
        signalsRes,
        scannerRes,
        botEventsRes,
        watchdogRes,
        botRes,
      ] = await Promise.all([
        safe(api.getHealth(), { status: "offline" }),
        safe(api.getReadiness(), emptyReadiness),
        safe(api.getExchangeStatus(), emptyExchangeStatus),
        safe(api.getAccount(authToken), emptyAccount),
        safe(api.getMetrics(authToken), emptyMetrics),
        safe(api.getPortfolio(authToken), emptyPortfolio),
        safe(api.getRiskState(authToken), emptyRiskState),
        safe(api.getActiveTrades(authToken), [] as Trade[]),
        safe(api.getTradeHistory(authToken), [] as TradeHistoryEntry[]),
        safe(api.getSignals(authToken), [] as ExecutableSignal[]),
        safe(api.getScannerResults(authToken), [] as ExecutableSignal[]),
        safe(api.getBotEvents(authToken), { events: [] as BotEventEntry[] }),
        safe(api.getWatchdogStatus(authToken), emptyWatchdog),
        safe(api.getBotStatus(authToken), emptyBotStatus),
      ]);

      setHealthStatus(String(health.status).toLowerCase() === "ok" ? "ONLINE" : "OFFLINE");
      setReadiness(readinessRes);
      setExchangeStatus(exchangeRes);
      setAccount(accountRes);
      setMetrics(metricsRes);
      setPortfolio(portfolioRes);
      setRiskState(riskRes);
      setActiveTrades(tradesRes);
      setTradeHistory(historyRes);
      setSignals(signalsRes);
      setScannerResults(scannerRes);
      setBotEvents(botEventsRes.events || []);
      setWatchdog(watchdogRes);
      setBotStatus(botRes);
      setLastSync(new Date());
      setIsStale(false);
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        setErrorMsg("Session expired. Please log in again.");
      } else {
        setErrorMsg(err?.message || "Failed to synchronize with FastAPI backend.");
        setIsStale(true);
      }
    } finally {
      isFetchingRef.current = false;
      if (!silent) {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    if (!authToken) {
      return;
    }

    fetchAllData();
    const interval = setInterval(() => {
      fetchAllData(true);
    }, 10000);

    return () => clearInterval(interval);
  }, [authToken]);

  const runAction = async (name: string, action: () => Promise<unknown>) => {
    setActionLoading(name);
    setErrorMsg(null);

    try {
      await action();
      if (name === "scanner") {
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }
      await fetchAllData(true);
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        setErrorMsg("Session expired. Please log in again.");
      } else {
        setErrorMsg(err?.message || "Action failed.");
      }
    } finally {
      setActionLoading(null);
    }
  };

  const executeSignalFromUi = async (signal: {
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
  }): Promise<ExecuteTradeResponse> => {
    if (!authToken) {
      return { ok: false, error: "Session expired. Please log in again." };
    }

    setActionLoading("execute-signal");
    setErrorMsg(null);
    try {
      const result = await api.executeTrade(authToken, signal);
      await fetchAllData(true);
      return result;
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 401) {
        logout();
        setErrorMsg("Session expired. Please log in again.");
        return { ok: false, error: "Session expired. Please log in again." };
      }
      const message = err?.message || "Action failed.";
      setErrorMsg(message);
      return { ok: false, error: message };
    } finally {
      setActionLoading(null);
    }
  };

  const renderTabContent = () => {
    switch (activeTab) {
      case "dashboard":
        return (
          <DashboardView
            authToken={authToken}
            readiness={readiness}
            botStatus={botStatus}
            account={account}
            activeTrades={activeTrades}
            signals={signals}
            tradeHistory={tradeHistory}
            lastSync={lastSync}
            isStale={isStale}
            actionLoading={actionLoading}
            onRefreshAll={() => fetchAllData()}
            onStartEngine={() => authToken ? runAction("bot-start", () => api.startBot(authToken)) : Promise.resolve()}
          />
        );
      case "signal-engine":
        return (
          <SignalEngine
            authToken={authToken}
            signals={signals}
            scanResults={scannerResults}
            loading={loading || actionLoading === "scanner"}
            onRunScan={() => authToken ? runAction("scanner", () => api.runScanner(authToken)) : Promise.resolve()}
            onRefresh={() => fetchAllData()}
            onExecuteSignal={executeSignalFromUi}
          />
        );
      case "active-trades":
        return (
          <div className="space-y-6">
            <ActiveTrades
              authToken={authToken}
              trades={activeTrades}
              tradeHistory={tradeHistory}
              account={account}
              onRefresh={() => fetchAllData()}
            />
          </div>
        );
      case "journal":
        return (
          <TradeHistory
            authToken={authToken}
            history={tradeHistory}
          />
        );
      case "performance-strategy":
        return (
          <PerformanceStrategy
            authToken={authToken}
            history={tradeHistory}
          />
        );
      case "watchdog":
        return (
          <Watchdog
            watchdog={watchdog}
            botEvents={botEvents}
            onRefresh={() => fetchAllData()}
          />
        );
      case "settings":
        return (
          <PageShell
            title="Settings"
            subtitle="Administrative settings, session controls, and future platform preferences will appear here once the backend exposes them."
          />
        );
      case "control-panel":
        return (
          <ControlPanel
            botStatus={botStatus}
            readiness={readiness}
            exchangeStatus={exchangeStatus}
            account={account}
            metrics={metrics}
            portfolio={portfolio}
            riskState={riskState}
            signals={signals}
            scannerResults={scannerResults}
            activeTrades={activeTrades}
            tradeHistory={tradeHistory}
            botEvents={botEvents}
            watchdog={watchdog}
            healthStatus={healthStatus}
            loading={loading}
            actionLoading={actionLoading}
            onStart={() => authToken ? runAction("bot-start", () => api.startBot(authToken)) : Promise.resolve()}
            onStop={() => authToken ? runAction("bot-stop", () => api.stopBot(authToken)) : Promise.resolve()}
            onEmergencyStop={() => authToken ? runAction("bot-emergency", () => api.emergencyStop(authToken)) : Promise.resolve()}
            onResume={() => authToken ? runAction("bot-resume", () => api.resumeBot(authToken)) : Promise.resolve()}
            onRunScanner={() => authToken ? runAction("scanner", () => api.runScanner(authToken)) : Promise.resolve()}
            onRefresh={() => fetchAllData()}
            onModeChange={(mode) => authToken ? runAction("bot-config-mode", () => api.updateBotConfig(authToken, { execution_mode: mode })) : Promise.resolve()}
            onAutoTradingToggle={(enabled) => authToken ? runAction("bot-config-auto", () => api.updateBotConfig(authToken, { auto_trading_enabled: enabled })) : Promise.resolve()}
            onRiskSettingsChange={(settings) => authToken ? runAction("bot-config-risk", () => api.updateBotConfig(authToken, settings)) : Promise.resolve()}
          />
        );
      default:
        return (
          <PageShell
            title="Unavailable Section"
            subtitle={`Tab section '${activeTab}' is not available in the current API integration.`}
          />
        );
    }
  };

  if (!authToken) {
    return <LockScreen onUnlock={onUnlock} />;
  }

  return (
    <div className="flex min-h-screen bg-[#0A0B0E] text-slate-300 font-sans selection:bg-rose-500 selection:text-white overflow-hidden" id="main-app-container">
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        collapsed={sidebarCollapsed}
        setCollapsed={setSidebarCollapsed}
        mobileOpen={mobileSidebarOpen}
        setMobileOpen={setMobileSidebarOpen}
        onLogout={logout}
      />

      <div className="flex-1 flex flex-col min-w-0 min-h-screen" id="main-terminal-shell">
        <header className="sticky top-0 z-20 bg-[#0A0B0E]/90 backdrop-blur-sm border-b border-slate-800 px-4 py-3 sm:px-6" id="top-bar-header">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              <button
                type="button"
                onClick={() => setMobileSidebarOpen(true)}
                className="inline-flex items-center justify-center rounded-lg border border-slate-800 bg-[#12141C] p-2 text-slate-300 md:hidden"
                aria-label="Open navigation"
              >
                <Menu className="h-4 w-4" />
              </button>
            </div>
            <h2 className="min-w-0 text-sm font-semibold text-slate-400 capitalize tracking-tight font-sans">
              Terminal: <span className="text-white font-bold">{activeTab.replace("-", " ")}</span>
            </h2>
            {(loading || actionLoading) && (
              <span className="hidden sm:flex items-center space-x-1 font-mono text-[9px] text-slate-500 bg-[#12141C] px-2 py-0.5 rounded border border-slate-800">
                <RefreshCw className="w-2.5 h-2.5 animate-spin text-rose-400" />
                <span>SYNCING...</span>
              </span>
            )}
          </div>

          <div className="flex flex-wrap items-center justify-end gap-2 sm:gap-4" id="top-bar-system-stats">
            <div className="hidden lg:flex items-center space-x-1.5 font-mono text-[10px] text-slate-500">
              <Server className="w-3.5 h-3.5 text-slate-600" />
              <span>FASTAPI:</span>
              <strong className="text-slate-300">8000</strong>
            </div>

            <div className="hidden sm:flex items-center space-x-2 font-mono text-[10px] text-slate-500">
              <span>MODE:</span>
              <strong className={botStatus.execution_mode === "live" ? "text-amber-400" : "text-emerald-400"}>
                {(botStatus.execution_mode || "demo").toUpperCase()}
              </strong>
            </div>

            <div className="hidden sm:flex items-center space-x-2 font-mono text-[10px] text-slate-500">
              <span>BOT:</span>
              <strong className={botStatus.status === "running" ? "text-emerald-400" : "text-slate-300"}>
                {botStatus.status.toUpperCase()}
              </strong>
            </div>

            <button
              id="top-bar-manual-sync-btn"
              onClick={() => fetchAllData()}
              disabled={loading}
              className="p-1.5 hover:bg-slate-850 rounded-lg text-slate-400 hover:text-rose-400 border border-slate-850 transition-colors cursor-pointer"
              title="Manual telemetry sync"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            </button>

            <button
              id="top-bar-logout-btn"
              onClick={logout}
              className="p-1.5 hover:bg-slate-850 rounded-lg text-slate-400 hover:text-rose-400 border border-slate-850 transition-colors cursor-pointer"
              title="Logout"
            >
              <LogOut className="w-3.5 h-3.5" />
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-4 sm:p-6" id="terminal-viewports-wrapper">
          {errorMsg && (
            <div className="mb-6 bg-red-500/10 border border-red-500/20 text-rose-400 p-4 rounded-2xl flex items-center space-x-3 font-mono text-xs" id="app-sync-error">
              <span className="w-2 h-2 rounded-full bg-red-500 animate-ping" />
              <span>{errorMsg}</span>
            </div>
          )}

          {renderTabContent()}
        </main>
      </div>
    </div>
  );
}
