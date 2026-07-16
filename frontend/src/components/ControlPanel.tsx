import { useMemo, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Clock3,
  Database,
  Play,
  RefreshCw,
  Server,
  ShieldAlert,
  ShieldCheck,
  Square,
  Stethoscope,
  Wallet,
  XCircle,
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
  WatchdogIncident,
  WatchdogModuleStatus,
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

const CRITICAL_MODULES = new Set(["backend", "bybit", "database", "worker", "wallet"]);
const HEALTHY_MODULE_STATUSES = new Set(["ONLINE", "READY", "IDLE"]);

function formatTime(value?: string | null) {
  if (!value) return "N/A";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "N/A" : BDT_DATE_TIME.format(parsed);
}

function formatPercent(value: number) {
  return `${(Number(value || 0) * 100).toFixed(2)}%`;
}

function formatMoney(value?: number | null) {
  return Number.isFinite(Number(value)) ? `$${Number(value).toFixed(2)}` : "N/A";
}

function formatDailyTradeLimit(riskState: RiskStateResponse) {
  return riskState.max_trades_per_day > 0
    ? `${riskState.trades_today} / ${riskState.max_trades_per_day}`
    : `${riskState.trades_today} / Unlimited`;
}

function readable(value?: string | null, fallback = "Not confirmed") {
  if (!value) return fallback;
  return value
    .replaceAll("_", " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^./, (character) => character.toUpperCase());
}

function incidentEvidence(value: unknown) {
  if (value === null || value === undefined || value === "") return "No technical evidence recorded.";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export default function ControlPanel({
  botStatus,
  readiness,
  riskState,
  watchdog,
  healthStatus,
  loading,
  actionLoading,
  onStart,
  onStop,
  onEmergencyStop,
  onResume,
  onRefresh,
}: ControlPanelProps) {

  const criticalModules = useMemo(
    () => watchdog.modules.filter((module) => CRITICAL_MODULES.has(module.module)),
    [watchdog.modules],
  );
  const incidents = useMemo(() => watchdog.incidents.slice(0, 20), [watchdog.incidents]);
  const lastIncident = incidents[0] || null;
  const criticalHealthy =
    healthStatus === "ONLINE" &&
    criticalModules.length > 0 &&
    criticalModules.every((module) => HEALTHY_MODULE_STATUSES.has(module.status));
  const localJournal = readiness.persistence?.local_journal_storage;
  const externalAudit = readiness.persistence?.external_audit_sink;

  return (
    <div className="space-y-4" id="control-center-root">
      <section className="rounded-2xl border border-slate-800/80 bg-bento-card-sec/40 p-5 shadow-lg backdrop-blur-md">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="flex items-center gap-3">
              <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/10 p-2.5 text-emerald-300">
                <ShieldCheck className="h-5 w-5" />
              </div>
              <div>
                <h1 className="text-xl font-bold tracking-tight text-white">Control Center</h1>
                <p className="mt-1 text-xs text-slate-400">
                  Engine control, risk configuration, critical health and incident investigation in one page.
                </p>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2 text-[10px] font-mono">
              <StatusPill label="BOT" value={botStatus.status.toUpperCase()} tone={botStatus.status === "running" ? "good" : "neutral"} />
              <StatusPill label="READINESS" value={readiness.ready_for_execution ? "READY" : "BLOCKED"} tone={readiness.ready_for_execution ? "good" : "bad"} />
              <StatusPill label="MODE" value={(botStatus.execution_mode || "demo").toUpperCase()} tone={botStatus.execution_mode === "live" ? "warn" : "good"} />
              <StatusPill label="AUTO" value={botStatus.auto_trading_enabled ? "ENABLED" : "DISABLED"} tone={botStatus.auto_trading_enabled ? "good" : "bad"} />
            </div>
          </div>

          <div className="flex flex-col items-start gap-2 sm:items-end">
            <button
              type="button"
              onClick={onRefresh}
              disabled={loading}
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-800 bg-[#0A0B0E] px-5 py-3 text-xs font-semibold text-slate-300 transition-colors hover:border-slate-700 hover:text-white disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              {loading ? "REFRESHING..." : "REFRESH STATUS"}
            </button>
            <span className="inline-flex items-center gap-1 text-[10px] font-mono text-slate-500">
              <Clock3 className="h-3.5 w-3.5" /> Generated {formatTime(watchdog.generated_at)}
            </span>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <SummaryCard
          label="Operational Health"
          value={criticalHealthy ? "HEALTHY" : "DEGRADED"}
          helper={`${criticalModules.length} critical modules checked`}
          icon={<Stethoscope className="h-4 w-4" />}
          tone={criticalHealthy ? "good" : "warn"}
        />
        <SummaryCard
          label="Open Incidents"
          value={String(watchdog.summary.open_incidents)}
          helper={`${watchdog.summary.total_incidents} persisted incidents`}
          icon={<ShieldAlert className="h-4 w-4" />}
          tone={watchdog.summary.open_incidents === 0 ? "good" : "bad"}
        />
        <SummaryCard
          label="Last Incident"
          value={lastIncident ? formatTime(lastIncident.timestamp) : "NONE"}
          helper={lastIncident ? `${lastIncident.affected_module} · ${lastIncident.error_code}` : "No incident evidence recorded"}
          icon={<Clock3 className="h-4 w-4" />}
          tone={lastIncident ? "warn" : "good"}
        />
      </section>

      <section className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        <SummaryCard
          label="Journal Storage"
          value={localJournal?.configured ? localJournal.backend.toUpperCase() : "UNAVAILABLE"}
          helper={localJournal ? `Primary save target: ${localJournal.target}` : "Persistence status is unavailable"}
          icon={<Database className="h-4 w-4" />}
          tone={localJournal?.configured ? "good" : "bad"}
        />
        <SummaryCard
          label="External Audit"
          value={externalAudit?.configured ? "SUPABASE READY" : "DISABLED"}
          helper={externalAudit?.configured ? `Mirror target: ${externalAudit.target}` : "Supabase env vars are not configured; journal saves only to the app database."}
          icon={<Server className="h-4 w-4" />}
          tone={externalAudit?.configured ? "good" : "warn"}
        />
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="space-y-4">
          <Panel title="Engine Controls" subtitle="Primary controls only—scanner and execution details stay on their own pages." icon={<Bot className="h-4 w-4 text-emerald-400" />}>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <ControlAction
                title="Start Engine"
                description="Starts demo automation, scans and attempts validated execution."
                label={botStatus.status === "running" ? "RUNNING" : "START"}
                icon={<Play className="h-4 w-4" />}
                tone="good"
                onClick={onStart}
                disabled={botStatus.status === "running" || actionLoading === "bot-start"}
                loading={actionLoading === "bot-start"}
              />
              <ControlAction
                title="Stop Engine"
                description="Stops normal automation without setting the emergency lock."
                label="STOP"
                icon={<Square className="h-4 w-4" />}
                tone="warn"
                onClick={onStop}
                disabled={actionLoading === "bot-stop"}
                loading={actionLoading === "bot-stop"}
              />
              <ControlAction
                title="Emergency Stop"
                description="Immediately blocks new execution until manually resumed."
                label={botStatus.emergency_stop ? "ACTIVE" : "ACTIVATE"}
                icon={<AlertTriangle className="h-4 w-4" />}
                tone="bad"
                onClick={onEmergencyStop}
                disabled={botStatus.emergency_stop || actionLoading === "bot-emergency"}
                loading={actionLoading === "bot-emergency"}
              />
              {botStatus.emergency_stop && (
                <ControlAction
                  title="Resume Engine"
                  description="Clears the emergency lock and restores execution eligibility."
                  label="RESUME"
                  icon={<Play className="h-4 w-4" />}
                  tone="good"
                  onClick={onResume}
                  disabled={actionLoading === "bot-resume"}
                  loading={actionLoading === "bot-resume"}
                />
              )}
            </div>
          </Panel>

          <Panel title="System Gates" subtitle="Current execution blockers and operating limits." icon={<ShieldAlert className="h-4 w-4 text-amber-400" />}>
            <div className="space-y-2">
              <GateRow label="Backend service" value={healthStatus} passed={healthStatus === "ONLINE"} />
              <GateRow label="Admin authentication" value={readiness.checks.admin_auth_configured ? "READY" : "BLOCKED"} passed={readiness.checks.admin_auth_configured} />
              <GateRow label="Exchange connection" value={readiness.checks.exchange_reachable ? "CONNECTED" : "BLOCKED"} passed={readiness.checks.exchange_reachable} />
              <GateRow label="Wallet synchronization" value={readiness.checks.wallet_fetch_success ? "READY" : "BLOCKED"} passed={readiness.checks.wallet_fetch_success} />
              <GateRow label="Emergency stop" value={botStatus.emergency_stop ? "ACTIVE" : "CLEAR"} passed={!botStatus.emergency_stop} />
              <GateRow label="Loss cooldown" value={riskState.cooldown_until ? formatTime(riskState.cooldown_until) : "CLEAR"} passed={!riskState.cooldown_until} />
            </div>
          </Panel>
        </div>

        <Panel title="Risk Settings" subtitle="Review the active policy, then save only deliberate changes." icon={<ShieldCheck className="h-4 w-4 text-sky-400" />}>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Metric label="Scalping Risk" value={`${formatMoney(riskState.risk_profiles?.scalping.risk_amount)} · ${riskState.risk_profiles?.scalping.leverage_cap ?? 20}x`} />
            <Metric label="Intraday Risk" value={`${formatMoney(riskState.risk_profiles?.intraday.risk_amount)} · ${riskState.risk_profiles?.intraday.leverage_cap ?? 10}x`} />
            <Metric label="Exposure Cap" value={formatPercent(riskState.exposure_cap)} />
            <Metric label="Authority" value={readable(riskState.risk_policy_authority, "Authoritative Risk Engine")} />
            <Metric label="Max Open" value={String(riskState.max_open_trades)} />
            <Metric label="Trades Today" value={formatDailyTradeLimit(riskState)} />
            <Metric label="Active Symbols" value={riskState.active_symbols.length ? riskState.active_symbols.join(", ") : "None"} />
            <Metric label="Cooldown" value={riskState.cooldown_until ? formatTime(riskState.cooldown_until) : "CLEAR"} />
          </div>

          <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Metric label="Day Start Equity" value={formatMoney(riskState.day_start_equity)} />
            <Metric label="Current Equity" value={formatMoney(riskState.current_account_equity)} />
            <Metric label="Equity Drawdown" value={formatMoney(riskState.equity_drawdown_today)} />
            <Metric
              label="5% Hard Stop"
              value={
                riskState.circuit_breaker_active
                  ? "TRIPPED"
                  : `${formatMoney(riskState.daily_net_loss_limit_amount)} limit`
              }
            />
          </div>
          {riskState.circuit_breaker_reason && (
            <div className="mt-3 rounded-xl border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {riskState.circuit_breaker_reason}
            </div>
          )}

          <div className="mt-5 rounded-xl border border-sky-500/20 bg-sky-500/10 p-3 text-xs text-sky-200">
            Risk budgets, leverage caps, daily limits and fee-aware execution gates are locked by the Authoritative Risk Engine. UI fields cannot override execution policy.
          </div>
        </Panel>
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-[0.75fr_1.25fr]">
        <Panel title="Critical Health" subtitle="Only operational dependencies that can stop the bot." icon={<Server className="h-4 w-4 text-cyan-400" />}>
          <div className="space-y-3">
            {criticalModules.map((module) => <ModuleRow key={module.module} module={module} />)}
            {criticalModules.length === 0 && <EmptyNote text="Critical module telemetry is unavailable." />}
          </div>
        </Panel>

        <Panel title="Incident Center" subtitle="Error, evidence, root cause, recovery state and recommended action in one record." icon={<Database className="h-4 w-4 text-violet-400" />}>
          {incidents.length > 0 ? (
            <div className="max-h-[720px] space-y-3 overflow-y-auto pr-1">
              {incidents.map((incident) => <IncidentCard key={incident.id} incident={incident} />)}
            </div>
          ) : (
            <EmptyNote text="No persisted warning or error incidents are available." />
          )}
        </Panel>
      </section>
    </div>
  );
}

function StatusPill({ label, value, tone }: { label: string; value: string; tone: "good" | "warn" | "bad" | "neutral" }) {
  const toneClass = tone === "good" ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300" : tone === "warn" ? "border-amber-500/20 bg-amber-500/10 text-amber-300" : tone === "bad" ? "border-rose-500/20 bg-rose-500/10 text-rose-300" : "border-slate-800 bg-[#0A0B0E] text-slate-300";
  return <span className={`rounded-lg border px-2.5 py-1.5 ${toneClass}`}><span className="text-slate-500">{label}: </span>{value}</span>;
}

function SummaryCard({ label, value, helper, icon, tone }: { label: string; value: string; helper: string; icon: ReactNode; tone: "good" | "warn" | "bad" }) {
  const toneClass = tone === "good" ? "border-emerald-500/10 bg-emerald-500/10 text-emerald-300" : tone === "warn" ? "border-amber-500/10 bg-amber-500/10 text-amber-300" : "border-rose-500/10 bg-rose-500/10 text-rose-300";
  return <div className="rounded-2xl border border-slate-800 bg-bento-card p-4 shadow-md"><div className="flex items-center justify-between gap-3"><span className="text-[10px] font-mono font-semibold uppercase tracking-wider text-slate-500">{label}</span><span className={`rounded-xl border p-2 ${toneClass}`}>{icon}</span></div><div className="mt-3 text-lg font-bold text-white">{value}</div><div className="mt-1 text-[10px] text-slate-500">{helper}</div></div>;
}

function Panel({ title, subtitle, icon, children }: { title: string; subtitle: string; icon: ReactNode; children: ReactNode }) {
  return <div className="rounded-2xl border border-slate-800 bg-bento-card p-5 shadow-md"><div className="mb-4 flex items-start gap-3">{icon}<div><h2 className="text-sm font-semibold text-white">{title}</h2><p className="mt-1 text-xs text-slate-500">{subtitle}</p></div></div>{children}</div>;
}

function ControlAction({ title, description, label, icon, tone, onClick, disabled, loading }: { title: string; description: string; label: string; icon: ReactNode; tone: "good" | "warn" | "bad"; onClick: () => Promise<void>; disabled: boolean; loading: boolean }) {
  const toneClass = tone === "good" ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20" : tone === "warn" ? "border-amber-500/20 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20" : "border-rose-500/20 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20";
  return <div className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-4"><div className="text-xs font-semibold text-white">{title}</div><p className="mt-1 min-h-[32px] text-[10px] leading-4 text-slate-500">{description}</p><button type="button" onClick={() => void onClick()} disabled={disabled} className={`mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${toneClass}`}>{icon}{loading ? "..." : label}</button></div>;
}

function GateRow({ label, value, passed }: { label: string; value: string; passed: boolean }) {
  return <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-[#0A0B0E] px-3 py-2.5"><span className="text-xs text-slate-300">{label}</span><span className={`inline-flex items-center gap-1 text-[10px] font-mono ${passed ? "text-emerald-400" : "text-rose-400"}`}>{passed ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}{value}</span></div>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-3"><div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{label}</div><div className="mt-2 break-words text-xs font-semibold text-white">{value}</div></div>;
}

function ModuleRow({ module }: { module: WatchdogModuleStatus }) {
  const healthy = HEALTHY_MODULE_STATUSES.has(module.status);
  const Icon = module.module === "backend" ? Server : module.module === "wallet" ? Wallet : module.module === "database" ? Database : Activity;
  return <div className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-4"><div className="flex items-start justify-between gap-3"><div className="flex items-start gap-3"><span className={`rounded-lg border p-2 ${healthy ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300" : "border-rose-500/20 bg-rose-500/10 text-rose-300"}`}><Icon className="h-4 w-4" /></span><div><div className="text-xs font-semibold capitalize text-white">{module.module}</div><div className="mt-1 text-xs leading-5 text-slate-500">{module.reason}</div></div></div><span className={`shrink-0 text-[10px] font-mono ${healthy ? "text-emerald-400" : "text-rose-400"}`}>{module.status}</span></div><div className="mt-3 flex flex-wrap justify-between gap-2 border-t border-slate-800 pt-3 text-[10px] font-mono text-slate-600"><span>{module.error_code}</span><span>{module.endpoint || "Internal check"}</span></div></div>;
}

function IncidentCard({ incident }: { incident: WatchdogIncident }) {
  const error = incident.level === "error";
  return <div className={`rounded-xl border p-4 ${error ? "border-rose-500/20 bg-rose-500/5" : "border-amber-500/20 bg-amber-500/5"}`}><div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between"><div><div className="flex flex-wrap items-center gap-2"><span className={`rounded-md border px-2 py-1 text-[9px] font-mono ${error ? "border-rose-500/20 bg-rose-500/10 text-rose-300" : "border-amber-500/20 bg-amber-500/10 text-amber-300"}`}>{incident.level.toUpperCase()}</span><span className="text-xs font-semibold capitalize text-white">{incident.affected_module}</span><span className="text-[10px] font-mono text-slate-500">{incident.error_code}</span></div><p className="mt-2 text-xs leading-5 text-slate-300">{incident.message}</p></div><span className="shrink-0 text-[10px] font-mono text-slate-500">{formatTime(incident.timestamp)}</span></div><div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2"><IncidentField label="Technical Evidence" value={incidentEvidence(incident.technical_evidence)} /><IncidentField label="Root Cause" value={readable(incident.root_cause)} /><IncidentField label="Recovery Status" value={readable(incident.recovery_status)} /><IncidentField label="Recommended Action" value={suggestAction(incident.affected_module, incident.root_cause || incident.message)} /></div><div className="mt-3 flex flex-wrap gap-4 text-[10px] font-mono text-slate-600"><span>Endpoint: {incident.endpoint || "N/A"}</span><span>Retry count: {incident.retry_count}</span></div></div>;
}

function IncidentField({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-slate-800 bg-[#0A0B0E] p-3"><div className="text-[9px] font-mono uppercase tracking-wider text-slate-600">{label}</div><div className="mt-2 break-words text-xs leading-5 text-slate-400">{value}</div></div>;
}

function suggestAction(module: string, reason: string) {
  const combined = `${module} ${reason}`.toLowerCase();
  if (combined.includes("wallet")) return "Refresh account connectivity and confirm the selected Bybit environment has a reachable wallet.";
  if (combined.includes("exchange") || combined.includes("bybit")) return "Verify exchange reachability and current API-key permissions, then refresh status.";
  if (combined.includes("database")) return "Inspect PostgreSQL availability and validate DATABASE_URL before restarting the service.";
  if (combined.includes("worker")) return "Restart the backend service and confirm the background worker returns ONLINE.";
  if (combined.includes("execution")) return "Resolve the blocking readiness or risk condition before allowing another execution attempt.";
  return "Review the evidence and root cause, correct the affected dependency, then refresh Control Center status.";
}

function EmptyNote({ text }: { text: string }) {
  return <div className="rounded-xl border border-dashed border-slate-800 bg-[#0A0B0E] px-6 py-12 text-center text-xs text-slate-500">{text}</div>;
}
