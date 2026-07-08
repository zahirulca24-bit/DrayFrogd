import type { ReactNode } from "react";
import { AlertTriangle, Clock3, RefreshCw, SearchCheck, ShieldAlert, Stethoscope } from "lucide-react";
import { BotEventEntry, WatchdogSnapshot } from "../types";

interface WatchdogProps {
  watchdog: WatchdogSnapshot;
  botEvents: BotEventEntry[];
  onRefresh: () => Promise<void>;
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

export default function Watchdog({ watchdog, botEvents, onRefresh }: WatchdogProps) {
  const degradedModules = watchdog.modules.filter((item) => !["ONLINE", "READY", "IDLE", "NOT_CONFIGURED"].includes(item.status));
  const recentEvents = botEvents.slice(0, 10);

  return (
    <div className="space-y-6">
      <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md">
        <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-white tracking-tight font-sans">Watchdog</h3>
            <p className="text-xs text-slate-500 mt-1">
              System health, incident persistence, technical evidence, and recovery guidance from real backend telemetry.
            </p>
          </div>
          <div className="flex items-center gap-3 text-[10px] font-mono text-slate-500">
            <span>Generated {formatTime(watchdog.generated_at)}</span>
            <button onClick={onRefresh} className="px-3 py-1.5 rounded-lg border border-slate-800 bg-[#0A0B0E] hover:text-white cursor-pointer">
              <RefreshCw className="w-3 h-3 inline mr-1" />
              Refresh
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        <SummaryCard label="Overall Health" value={watchdog.summary.overall_status} tone={watchdog.summary.overall_status === "HEALTHY" ? "good" : "warn"} />
        <SummaryCard label="Open Incidents" value={String(watchdog.summary.open_incidents)} tone={watchdog.summary.open_incidents === 0 ? "good" : "warn"} />
        <SummaryCard label="Persisted Incidents" value={String(watchdog.summary.total_incidents)} tone="neutral" />
        <SummaryCard label="Affected Modules" value={watchdog.summary.affected_modules.length > 0 ? watchdog.summary.affected_modules.join(", ") : "None"} tone="neutral" />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[0.8fr_1.2fr] gap-6">
        <PanelCard title="System Health" icon={<Stethoscope className="w-4 h-4 text-emerald-400" />}>
          <div className="space-y-3">
            {watchdog.modules.map((module) => (
              <div key={module.module} className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-xs font-semibold text-white capitalize">{module.module}</div>
                  <span className={`text-[10px] font-mono ${
                    module.status === "ONLINE" || module.status === "READY"
                      ? "text-emerald-400"
                      : module.status === "IDLE" || module.status === "NOT_CONFIGURED"
                        ? "text-slate-300"
                        : "text-amber-300"
                  }`}>
                    {module.status}
                  </span>
                </div>
                <div className="mt-2 text-xs text-slate-400">{module.reason}</div>
                <div className="mt-2 text-[10px] font-mono text-slate-500">
                  {module.error_code} {module.endpoint ? `| ${module.endpoint}` : ""}
                </div>
              </div>
            ))}
          </div>
        </PanelCard>

        <PanelCard title="Incident Timeline" icon={<Clock3 className="w-4 h-4 text-amber-400" />}>
          {watchdog.incidents.length > 0 ? (
            <div className="space-y-3 max-h-[520px] overflow-y-auto pr-1">
              {watchdog.incidents.map((incident) => (
                <div key={incident.id} className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-4">
                  <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-2">
                    <div className="text-xs font-semibold text-white">
                      {incident.affected_module} | {incident.error_code}
                    </div>
                    <div className="text-[10px] font-mono text-slate-500">{formatTime(incident.timestamp)}</div>
                  </div>
                  <div className="mt-2 text-xs text-slate-300">{incident.message}</div>
                  <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3 text-[10px] font-mono text-slate-500">
                    <div>Endpoint: {incident.endpoint || "N/A"}</div>
                    <div>Retry Count: {incident.retry_count}</div>
                    <div>Recovery: {incident.recovery_status}</div>
                    <div>Root Cause: {incident.root_cause || "Cause Not Confirmed"}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyNote text="No persisted incidents available yet." />
          )}
        </PanelCard>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <PanelCard title="Downtime" icon={<AlertTriangle className="w-4 h-4 text-rose-400" />}>
          {degradedModules.length > 0 ? (
            <div className="space-y-3 text-xs">
              {degradedModules.map((module) => (
                <div key={module.module} className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-3">
                  <div className="text-white font-semibold capitalize">{module.module}</div>
                  <div className="mt-1 text-slate-400">{module.reason}</div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyNote text="No active downtime evidence." />
          )}
        </PanelCard>

        <PanelCard title="Technical Evidence" icon={<SearchCheck className="w-4 h-4 text-cyan-400" />}>
          {watchdog.incidents.length > 0 ? (
            <div className="space-y-3 text-xs">
              {watchdog.incidents.slice(0, 5).map((incident) => (
                <div key={incident.id} className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-3">
                  <div className="text-white font-semibold">{incident.error_code}</div>
                  <div className="mt-1 text-slate-400 break-words">{String(incident.technical_evidence || "Cause Not Confirmed")}</div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyNote text="Cause Not Confirmed" />
          )}
        </PanelCard>

        <PanelCard title="Solution Advice" icon={<ShieldAlert className="w-4 h-4 text-emerald-400" />}>
          <div className="space-y-3 text-xs">
            {degradedModules.length > 0 ? degradedModules.map((module) => (
              <div key={module.module} className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-3">
                <div className="text-white font-semibold capitalize">{module.module}</div>
                <div className="mt-1 text-slate-400">{suggestAction(module.module, module.reason)}</div>
              </div>
            )) : (
              <div className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-3 text-slate-400">
                No action required. System evidence is currently stable.
              </div>
            )}
          </div>
        </PanelCard>
      </div>

      <PanelCard title="Recovery Status" icon={<RefreshCw className="w-4 h-4 text-emerald-400" />}>
        {recentEvents.length > 0 ? (
          <div className="space-y-3">
            {recentEvents.map((event) => (
              <div key={event.id} className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-xs font-semibold text-white">{event.event_type}</div>
                  <div className={`text-[10px] font-mono ${event.level === "error" ? "text-rose-400" : event.level === "warning" ? "text-amber-300" : "text-emerald-400"}`}>
                    {event.level.toUpperCase()}
                  </div>
                </div>
                <div className="mt-2 text-xs text-slate-400">{event.message}</div>
                <div className="mt-2 text-[10px] font-mono text-slate-500">{formatTime(event.created_at)}</div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyNote text="No recovery evidence has been recorded yet." />
        )}
      </PanelCard>
    </div>
  );
}

function suggestAction(module: string, reason: string) {
  const combined = `${module} ${reason}`.toLowerCase();
  if (combined.includes("wallet")) {
    return "Retest account connectivity and confirm the selected Bybit mode has a reachable wallet.";
  }
  if (combined.includes("exchange") || combined.includes("bybit")) {
    return "Retest exchange reachability and verify current API key permissions for the active mode.";
  }
  if (combined.includes("database")) {
    return "Inspect database service availability and validate the configured DATABASE_URL.";
  }
  if (combined.includes("worker")) {
    return "Restart the backend service so the background worker loop is recreated cleanly.";
  }
  if (combined.includes("execution")) {
    return "Clear the blocking condition first, then retry execution after readiness becomes READY.";
  }
  return "Inspect the latest incident evidence, then retest the affected module from the Control Panel.";
}

function SummaryCard({ label, value, tone }: { label: string; value: string; tone: "good" | "warn" | "neutral" }) {
  const toneClass = tone === "good" ? "text-emerald-400" : tone === "warn" ? "text-amber-300" : "text-slate-200";
  return (
    <div className="bg-bento-card border border-slate-800 rounded-2xl p-5 shadow-md">
      <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-3 text-lg font-semibold break-words ${toneClass}`}>{value}</div>
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

function EmptyNote({ text }: { text: string }) {
  return <div className="py-10 text-center text-xs font-mono text-slate-500">{text}</div>;
}
