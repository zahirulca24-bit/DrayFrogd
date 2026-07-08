import type { ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  Database,
  Play,
  Radio,
  RefreshCw,
  Server,
  ShieldAlert,
  Square,
  Wallet,
  Zap,
} from "lucide-react";
import {
  AccountResponse,
  BotControlState,
  BotEventEntry,
  ExchangeStatusResponse,
  ExecutableSignal,
  MetricsResponse,
  PortfolioSummary,
  RiskStateResponse,
  SystemReadiness,
  Trade,
  TradeHistoryEntry,
  WatchdogSnapshot,
} from "../types";

interface ControlPanelProps {
  botStatus: BotControlState;
  readiness: SystemReadiness;
  exchangeStatus: ExchangeStatusResponse;
  account: AccountResponse;
  metrics: MetricsResponse;
  portfolio: PortfolioSummary;
  riskState: RiskStateResponse;
  signals: ExecutableSignal[];
  scannerResults: ExecutableSignal[];
  activeTrades: Trade[];
  tradeHistory: TradeHistoryEntry[];
  botEvents: BotEventEntry[];
  watchdog: WatchdogSnapshot;
  healthStatus: "ONLINE" | "OFFLINE";
  loading: boolean;
  actionLoading: string | null;
  onStart: () => Promise<void>;
  onStop: () => Promise<void>;
  onEmergencyStop: () => Promise<void>;
  onResume: () => Promise<void>;
  onRunScanner: () => Promise<void>;
  onRefresh: () => Promise<void>;
  onModeChange: (mode: "demo" | "live") => Promise<void>;
  onAutoTradingToggle: (enabled: boolean) => Promise<void>;
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

function formatTime(value?: string | null) {
  if (!value) {
    return "N/A";
  }
  return BDT_DATE_TIME.format(new Date(value));
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

export default function ControlPanel({
  botStatus,
  readiness,
  exchangeStatus,
  account,
  metrics,
  portfolio,
  riskState,
  signals,
  scannerResults,
  activeTrades,
  tradeHistory,
  botEvents,
  watchdog,
  healthStatus,
  loading,
  actionLoading,
  onStart,
  onStop,
  onEmergencyStop,
  onResume,
  onRunScanner,
  onRefresh,
  onModeChange,
  onAutoTradingToggle,
}: ControlPanelProps) {
  const activityLogs = botEvents.slice(0, 10);
  const queueRows = scannerResults.slice(0, 8);
  const moduleCards = watchdog.modules;
  const latestIncident = watchdog.incidents[0];

  return (
    <div className="space-y-6">
      <div className={`bg-bento-card border ${healthStatus === "ONLINE" ? "border-emerald-500/25" : "border-rose-500/25"} rounded-2xl p-6 shadow-md`}>
        <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-white tracking-tight font-sans">Control Panel</h3>
            <p className="text-xs text-slate-500 mt-1">
              Execution setup, module readiness, reconnect actions, and live runtime evidence from the FastAPI backend.
            </p>
          </div>
          <div className="flex items-center gap-3 text-[10px] font-mono text-slate-500">
            <span>BDT {formatTime(new Date().toISOString())}</span>
            <button
              onClick={onRefresh}
              disabled={loading}
              className="px-3 py-1.5 rounded-lg border border-slate-800 bg-[#0A0B0E] hover:text-white cursor-pointer"
            >
              <RefreshCw className={`w-3 h-3 inline mr-1 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 xl:grid-cols-5 gap-4">
        <SummaryCard label="Backend" value={healthStatus} tone={healthStatus === "ONLINE" ? "good" : "bad"} />
        <SummaryCard label="Bybit" value={exchangeStatus.reachable ? "CONNECTED" : "DEGRADED"} tone={exchangeStatus.reachable ? "good" : "warn"} />
        <SummaryCard label="Wallet" value={account.wallet.ok ? "LIVE" : "FAILED"} tone={account.wallet.ok ? "good" : "warn"} />
        <SummaryCard label="Scanner" value={`${scannerResults.length} results`} tone={scannerResults.length > 0 ? "good" : "neutral"} />
        <SummaryCard label="Worker" value={watchdog.modules.find((item) => item.module === "worker")?.status || "N/A"} tone={watchdog.modules.find((item) => item.module === "worker")?.status === "ONLINE" ? "good" : "warn"} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1.4fr_0.6fr] gap-6">
        <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
          <div className="flex items-center justify-between mb-5">
            <div>
              <h4 className="text-sm font-semibold text-white tracking-tight font-sans">Execution Setup & Status</h4>
              <p className="text-xs text-slate-500 mt-1">Real status for backend, exchange, persistence, worker, and safety modules.</p>
            </div>
            <Server className="w-4 h-4 text-emerald-400" />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {moduleCards.map((module) => (
              <ModuleCard
                key={module.module}
                module={module.module}
                status={module.status}
                reason={module.reason}
                endpoint={module.endpoint}
                errorCode={module.error_code}
                actionLabel={module.module === "scanner" ? "Run Test" : "Retest"}
                onAction={module.module === "scanner" ? onRunScanner : onRefresh}
                loading={actionLoading === "scanner" && module.module === "scanner" ? true : loading}
              />
            ))}
          </div>
        </div>

        <div className="space-y-6">
          <PanelCard title="Latest Failure" icon={<AlertTriangle className="w-4 h-4 text-amber-400" />}>
            {latestIncident ? (
              <div className="space-y-3 text-xs">
                <KeyValue label="Module" value={latestIncident.affected_module} />
                <KeyValue label="Error Code" value={latestIncident.error_code} />
                <KeyValue label="Endpoint" value={latestIncident.endpoint || "N/A"} />
                <KeyValue label="Evidence" value={String(latestIncident.technical_evidence || "Cause Not Confirmed")} />
                <KeyValue label="Root Cause" value={latestIncident.root_cause || "Cause Not Confirmed"} />
              </div>
            ) : (
              <EmptyNote text="No persisted incidents yet." />
            )}
          </PanelCard>

          <PanelCard title="System Gates" icon={<ShieldAlert className="w-4 h-4 text-rose-400" />}>
            <div className="space-y-3 text-xs">
              <KeyValue label="Readiness" value={readiness.ready_for_execution ? "READY" : "BLOCKED"} />
              <KeyValue label="Execution Mode" value={(botStatus.execution_mode || "demo").toUpperCase()} />
              <KeyValue label="Emergency Stop" value={botStatus.emergency_stop ? "ACTIVE" : "CLEAR"} />
              <KeyValue label="Auto Trading" value={botStatus.auto_trading_enabled ? "ENABLED" : "DISABLED"} />
              <KeyValue label="Open Incidents" value={String(watchdog.summary.open_incidents)} />
            </div>
          </PanelCard>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <PanelCard title="Bot Controls" icon={<Bot className="w-4 h-4 text-emerald-400" />}>
          <div className="space-y-4">
            <ActionRow title="Start Bot" description="Set runtime status to running." buttonLabel="START" onClick={onStart} loading={actionLoading === "bot-start"} accent="emerald" icon={<Play className="w-3 h-3" />} />
            <ActionRow title="Stop Bot" description="Set runtime status to stopped." buttonLabel="STOP" onClick={onStop} loading={actionLoading === "bot-stop"} accent="amber" icon={<Square className="w-3 h-3" />} />
            <ActionRow title="Switch To Demo" description="Use demo execution mode." buttonLabel="DEMO" onClick={() => onModeChange("demo")} loading={actionLoading === "bot-config-mode"} accent="emerald" icon={<Play className="w-3 h-3" />} />
            <ActionRow title="Switch To Live" description={botStatus.live_mode_available ? "Live keys detected and mode can be tested." : "Live mode is blocked until real keys exist."} buttonLabel="LIVE" onClick={() => onModeChange("live")} loading={actionLoading === "bot-config-mode"} accent="amber" icon={<AlertTriangle className="w-3 h-3" />} />
            <ActionRow title="Auto Trading" description={botStatus.auto_trading_enabled ? "Disable automated execution." : "Enable automated execution."} buttonLabel={botStatus.auto_trading_enabled ? "DISABLE" : "ENABLE"} onClick={() => onAutoTradingToggle(!(botStatus.auto_trading_enabled ?? true))} loading={actionLoading === "bot-config-auto"} accent="rose" icon={<Zap className="w-3 h-3" />} />
          </div>
        </PanelCard>

        <PanelCard title="Risk Settings" icon={<ShieldAlert className="w-4 h-4 text-amber-400" />}>
          <div className="grid grid-cols-2 gap-3">
            <MiniMetric label="Risk / Trade" value={formatPercent(riskState.risk_per_trade)} />
            <MiniMetric label="Min RR" value={`${riskState.min_risk_reward.toFixed(1)}R`} />
            <MiniMetric label="Max Open Trades" value={String(riskState.max_open_trades)} />
            <MiniMetric label="Trades Today" value={`${riskState.trades_today} / ${riskState.max_trades_per_day}`} />
            <MiniMetric label="Active Symbols" value={riskState.active_symbols.length > 0 ? riskState.active_symbols.join(", ") : "None"} />
            <MiniMetric label="Cooldown" value={riskState.cooldown_until ? formatTime(riskState.cooldown_until) : "CLEAR"} />
          </div>
        </PanelCard>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[0.9fr_1.1fr] gap-6">
        <PanelCard title="Scanner Controls" icon={<Radio className="w-4 h-4 text-violet-400" />}>
          <div className="space-y-4">
            <ActionRow title="Manual Scanner Run" description="Trigger the existing backend scanner job." buttonLabel="RUN SCAN" onClick={onRunScanner} loading={actionLoading === "scanner"} accent="rose" icon={<Play className="w-3 h-3" />} />
            <div className="grid grid-cols-2 gap-3">
              <MiniMetric label="Active Signals" value={String(signals.length)} />
              <MiniMetric label="Latest Results" value={String(scannerResults.length)} />
              <MiniMetric label="Win Rate" value={formatPercent(metrics.win_rate)} />
              <MiniMetric label="Closed Trades" value={String(tradeHistory.length)} />
            </div>
          </div>
        </PanelCard>

        <PanelCard title="Execution Queue" icon={<Activity className="w-4 h-4 text-emerald-400" />}>
          {queueRows.length > 0 ? (
            <div className="space-y-3">
              {queueRows.map((signal) => (
                <div key={signal.id} className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs font-semibold text-white">{signal.pair} {signal.direction}</div>
                      <div className="text-[10px] font-mono text-slate-500 mt-1">
                        {signal.executionStatus} | RR {signal.rr.toFixed(2)} | Score {signal.score}
                      </div>
                    </div>
                    <span className={`text-[10px] font-mono ${signal.executionStatus === "READY" ? "text-emerald-400" : "text-amber-300"}`}>
                      {signal.executionStatus}
                    </span>
                  </div>
                  <div className="mt-2 text-[10px] text-slate-500">
                    {signal.rejectionReason || "No blocking reason from backend."}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyNote text="No queued scan results available." />
          )}
        </PanelCard>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[0.7fr_1.3fr] gap-6">
        <PanelCard title="Emergency Actions" icon={<ShieldAlert className="w-4 h-4 text-rose-400" />}>
          <div className="space-y-4">
            <ActionRow title="Emergency Stop" description="Immediately block all execution." buttonLabel="ACTIVATE" onClick={onEmergencyStop} loading={actionLoading === "bot-emergency"} accent="red" icon={<AlertTriangle className="w-3 h-3" />} />
            <ActionRow title="Resume Bot" description="Clear emergency stop and restore normal mode." buttonLabel="RESUME" onClick={onResume} loading={actionLoading === "bot-resume"} accent="emerald" icon={<Play className="w-3 h-3" />} />
            <MiniMetric label="Available Balance" value={String(account.wallet.data?.totalAvailableBalance ?? account.wallet.data?.totalWalletBalance ?? "N/A")} />
            <MiniMetric label="Open Positions" value={String(activeTrades.length)} />
            <MiniMetric label="Portfolio Mode" value={(portfolio.execution_mode || botStatus.execution_mode || "demo").toUpperCase()} />
          </div>
        </PanelCard>

        <PanelCard title="Live Activity Logs" icon={<Database className="w-4 h-4 text-cyan-400" />}>
          {activityLogs.length > 0 ? (
            <div className="space-y-3 max-h-[420px] overflow-y-auto pr-1">
              {activityLogs.map((event) => (
                <div key={event.id} className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-xs font-semibold text-white">{event.event_type}</div>
                    <span className={`text-[10px] font-mono ${event.level === "error" ? "text-rose-400" : event.level === "warning" ? "text-amber-300" : "text-emerald-400"}`}>
                      {event.level.toUpperCase()}
                    </span>
                  </div>
                  <div className="mt-2 text-xs text-slate-300">{event.message}</div>
                  <div className="mt-2 text-[10px] font-mono text-slate-500">
                    {formatTime(event.created_at)} | {(event.metadata?.["affected_module"] as string) || "backend"} | {(event.metadata?.["endpoint"] as string) || "N/A"}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyNote text="No bot event logs persisted yet." />
          )}
        </PanelCard>
      </div>
    </div>
  );
}

function SummaryCard({ label, value, tone }: { label: string; value: string; tone: "good" | "warn" | "bad" | "neutral" }) {
  const toneClass = {
    good: "text-emerald-400",
    warn: "text-amber-300",
    bad: "text-rose-400",
    neutral: "text-slate-200",
  }[tone];

  return (
    <div className="bg-bento-card border border-slate-800 rounded-2xl p-5 shadow-md">
      <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-3 text-lg font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}

function PanelCard({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return (
    <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
      <div className="flex items-center gap-2 mb-4">
        {icon}
        <h4 className="text-sm font-semibold text-white tracking-tight font-sans">{title}</h4>
      </div>
      {children}
    </div>
  );
}

function ModuleCard({
  module,
  status,
  reason,
  endpoint,
  errorCode,
  actionLabel,
  onAction,
  loading,
}: {
  module: string;
  status: string;
  reason: string;
  endpoint: string | null;
  errorCode: string;
  actionLabel: string;
  onAction: () => Promise<void>;
  loading: boolean;
}) {
  const tone = status === "ONLINE" || status === "READY"
    ? "text-emerald-400"
    : status === "IDLE" || status === "NOT_CONFIGURED"
      ? "text-slate-300"
      : "text-amber-300";

  const icon = module === "backend" ? <Server className="w-4 h-4 text-emerald-400" />
    : module === "wallet" ? <Wallet className="w-4 h-4 text-cyan-400" />
      : <Activity className="w-4 h-4 text-slate-300" />;

  return (
    <div className="rounded-2xl border border-slate-800 bg-[#0A0B0E] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          {icon}
          <div>
            <div className="text-xs font-semibold text-white capitalize">{module}</div>
            <div className={`text-[10px] font-mono mt-1 ${tone}`}>{status}</div>
          </div>
        </div>
        <button
          onClick={onAction}
          disabled={loading}
          className="px-2.5 py-1 text-[10px] font-mono rounded-lg border border-slate-800 bg-slate-950 hover:text-white cursor-pointer"
        >
          {loading ? "..." : actionLabel}
        </button>
      </div>
      <div className="mt-3 text-xs text-slate-400 leading-relaxed">{reason}</div>
      <div className="mt-3 flex items-center justify-between gap-3 text-[10px] font-mono text-slate-500">
        <span>{errorCode}</span>
        <span>{endpoint || "No endpoint"}</span>
      </div>
    </div>
  );
}

function ActionRow({
  title,
  description,
  buttonLabel,
  onClick,
  loading,
  accent,
  icon,
}: {
  title: string;
  description: string;
  buttonLabel: string;
  onClick: () => Promise<void>;
  loading: boolean;
  accent: "emerald" | "amber" | "rose" | "red";
  icon: ReactNode;
}) {
  const styles = {
    emerald: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20 hover:bg-emerald-500/20",
    amber: "bg-amber-500/10 text-amber-400 border-amber-500/20 hover:bg-amber-500/20",
    rose: "bg-rose-500/10 text-rose-400 border-rose-500/20 hover:bg-rose-500/20",
    red: "bg-red-500/10 text-red-400 border-red-500/20 hover:bg-red-500/20",
  }[accent];

  return (
    <div className="p-4 bg-[#0A0B0E] border border-slate-800/65 rounded-xl flex items-center justify-between gap-3">
      <div>
        <h4 className="text-xs font-semibold text-slate-200">{title}</h4>
        <p className="text-[10px] text-slate-500 mt-1">{description}</p>
      </div>
      <button
        onClick={onClick}
        disabled={loading}
        className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all border flex items-center space-x-1.5 ${styles} disabled:opacity-50 cursor-pointer`}
      >
        {icon}
        <span>{loading ? "..." : buttonLabel}</span>
      </button>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
      <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-2 text-xs font-semibold text-white break-words">{value}</div>
    </div>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-slate-500">{label}</span>
      <span className="text-right text-slate-200">{value}</span>
    </div>
  );
}

function EmptyNote({ text }: { text: string }) {
  return <div className="py-10 text-center text-xs font-mono text-slate-500">{text}</div>;
}
