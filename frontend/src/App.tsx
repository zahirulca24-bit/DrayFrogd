import { useEffect, useRef, useState } from "react";
import { LogOut, RefreshCw, Server } from "lucide-react";
import { api, ApiError } from "./api";
import {
  AccountResponse,
  BotControlState,
  ExchangeStatusResponse,
  ExecutableSignal,
  MetricsResponse,
  PortfolioSummary,
  SystemReadiness,
  Trade,
  TradeHistoryEntry,
} from "./types";
import Sidebar from "./components/Sidebar";
import LockScreen from "./components/LockScreen";
import DashboardView from "./components/DashboardView";
import ControlPanel from "./components/ControlPanel";
import Portfolio from "./components/Portfolio";
import SignalEngine from "./components/SignalEngine";
import ActiveTrades from "./components/ActiveTrades";
import TradeHistory from "./components/TradeHistory";


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


export default function App() {
  const [authToken, setAuthToken] = useState<string | null>(localStorage.getItem("scalp_token"));
  const [activeTab, setActiveTab] = useState("dashboard");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [signals, setSignals] = useState<ExecutableSignal[]>([]);
  const [scannerResults, setScannerResults] = useState<ExecutableSignal[]>([]);
  const [activeTrades, setActiveTrades] = useState<Trade[]>([]);
  const [tradeHistory, setTradeHistory] = useState<TradeHistoryEntry[]>([]);
  const [readiness, setReadiness] = useState<SystemReadiness>(emptyReadiness);
  const [exchangeStatus, setExchangeStatus] = useState<ExchangeStatusResponse>(emptyExchangeStatus);
  const [account, setAccount] = useState<AccountResponse>(emptyAccount);
  const [metrics, setMetrics] = useState<MetricsResponse>(emptyMetrics);
  const [portfolio, setPortfolio] = useState<PortfolioSummary>(emptyPortfolio);
  const [botStatus, setBotStatus] = useState<BotControlState>(emptyBotStatus);
  const [healthStatus, setHealthStatus] = useState<"ONLINE" | "OFFLINE">("OFFLINE");
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const [isStale, setIsStale] = useState(false);
  const isFetchingRef = useRef(false);

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
        tradesRes,
        historyRes,
        signalsRes,
        scannerRes,
        botRes,
      ] = await Promise.all([
        safe(api.getHealth(), { status: "offline" }),
        safe(api.getReadiness(), emptyReadiness),
        safe(api.getExchangeStatus(), emptyExchangeStatus),
        safe(api.getAccount(authToken), emptyAccount),
        safe(api.getMetrics(authToken), emptyMetrics),
        safe(api.getPortfolio(authToken), emptyPortfolio),
        safe(api.getActiveTrades(authToken), [] as Trade[]),
        safe(api.getTradeHistory(authToken), [] as TradeHistoryEntry[]),
        safe(api.getSignals(authToken), [] as ExecutableSignal[]),
        safe(api.getScannerResults(authToken), [] as ExecutableSignal[]),
        safe(api.getBotStatus(authToken), emptyBotStatus),
      ]);

      setHealthStatus(String(health.status).toLowerCase() === "ok" ? "ONLINE" : "OFFLINE");
      setReadiness(readinessRes);
      setExchangeStatus(exchangeRes);
      setAccount(accountRes);
      setMetrics(metricsRes);
      setPortfolio(portfolioRes);
      setActiveTrades(tradesRes);
      setTradeHistory(historyRes);
      setSignals(signalsRes);
      setScannerResults(scannerRes);
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

  const renderTabContent = () => {
    switch (activeTab) {
      case "dashboard":
        return (
          <DashboardView
            readiness={readiness}
            botStatus={botStatus}
            exchangeStatus={exchangeStatus}
            account={account}
            metrics={metrics}
            portfolio={portfolio}
            activeTrades={activeTrades}
            signals={signals}
            tradeHistory={tradeHistory}
            lastSync={lastSync}
            isStale={isStale}
          />
        );
      case "signal-engine":
        return (
          <SignalEngine
            signals={signals}
            scanResults={scannerResults}
            loading={loading || actionLoading === "scanner"}
            onRunScan={() => authToken ? runAction("scanner", () => api.runScanner(authToken)) : Promise.resolve()}
            onRefresh={() => fetchAllData()}
          />
        );
      case "active-trades":
        return (
          <div className="space-y-6">
            <ActiveTrades trades={activeTrades} />
            <TradeHistory history={tradeHistory} />
          </div>
        );
      case "portfolio":
        return (
          <Portfolio
            account={account}
            metrics={metrics}
            portfolio={portfolio}
            activeTrades={activeTrades}
            tradeHistory={tradeHistory}
            loading={loading}
            onRefresh={() => fetchAllData()}
          />
        );
      case "ai-review":
        return (
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 text-slate-400 text-sm">
            AI review endpoint is not available in the current FastAPI backend.
          </div>
        );
      case "control-panel":
        return (
          <ControlPanel
            botStatus={botStatus}
            readiness={readiness}
            exchangeStatus={exchangeStatus}
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
          />
        );
      default:
        return (
          <div className="p-8 text-center text-slate-400 font-mono">
            Tab section '{activeTab}' is unavailable in the current API integration.
          </div>
        );
    }
  };

  if (!authToken) {
    return <LockScreen onUnlock={onUnlock} />;
  }

  return (
    <div className="flex h-screen bg-[#0A0B0E] text-slate-300 font-sans selection:bg-rose-500 selection:text-white overflow-hidden" id="main-app-container">
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        collapsed={sidebarCollapsed}
        setCollapsed={setSidebarCollapsed}
        onLogout={logout}
      />

      <div className="flex-1 flex flex-col min-w-0" id="main-terminal-shell">
        <header className="h-16 bg-[#0A0B0E]/80 backdrop-blur-sm border-b border-slate-800 flex items-center justify-between px-6" id="top-bar-header">
          <div className="flex items-center space-x-3">
            <h2 className="text-sm font-semibold text-slate-400 capitalize tracking-tight font-sans">
              Terminal: <span className="text-white font-bold">{activeTab.replace("-", " ")}</span>
            </h2>
            {(loading || actionLoading) && (
              <span className="flex items-center space-x-1 font-mono text-[9px] text-slate-500 bg-[#12141C] px-2 py-0.5 rounded border border-slate-800">
                <RefreshCw className="w-2.5 h-2.5 animate-spin text-rose-400" />
                <span>SYNCING...</span>
              </span>
            )}
          </div>

          <div className="flex items-center space-x-4" id="top-bar-system-stats">
            <div className="hidden sm:flex items-center space-x-1.5 font-mono text-[10px] text-slate-500">
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

        <main className="flex-1 overflow-y-auto p-6" id="terminal-viewports-wrapper">
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
