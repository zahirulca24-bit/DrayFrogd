import React from "react";
import { useJournalData } from "./JournalDataContext";
import { Cloud, CloudLightning, CloudOff, RefreshCw, AlertTriangle } from "lucide-react";

export const JournalSyncStatus: React.FC = () => {
  const { metadata, refresh } = useJournalData();
  const { autoSyncEnabled, intervalMs, lastSuccess, state, error, isStale, retryCount } = metadata;

  const getStatusColor = () => {
    if (state === "error") return "border-red-500/20 bg-red-500/10 text-rose-400";
    if (state === "retrying") return "border-amber-500/20 bg-amber-500/10 text-amber-400";
    if (state === "syncing") return "border-blue-500/20 bg-blue-500/10 text-blue-400";
    if (isStale) return "border-yellow-500/20 bg-yellow-500/10 text-yellow-400";
    return "border-emerald-500/20 bg-emerald-500/10 text-emerald-400";
  };

  const getIcon = () => {
    if (state === "syncing" || state === "retrying") {
      return <RefreshCw className="h-3 w-3 animate-spin" />;
    }
    if (state === "error") {
      return <CloudOff className="h-3 w-3" />;
    }
    if (isStale) {
      return <CloudLightning className="h-3 w-3" />;
    }
    return <Cloud className="h-3 w-3" />;
  };

  const formattedTime = lastSuccess
    ? lastSuccess.toLocaleTimeString("en-BD", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: true,
      })
    : "Never";

  return (
    <div className="space-y-2" id="journal-sync-status-container">
      <div className={`flex flex-wrap items-center justify-between gap-3 rounded-xl border p-3 text-xs ${getStatusColor()}`}>
        <div className="flex items-center gap-2">
          {getIcon()}
          <div>
            <span className="font-semibold uppercase tracking-wider">
              {state === "syncing"
                ? "Syncing data..."
                : state === "retrying"
                ? `Retrying sync (${retryCount}/3)...`
                : state === "error"
                ? "Sync failed"
                : isStale
                ? "Data stale"
                : "Synchronized"}
            </span>
            <span className="mx-2 text-slate-500">|</span>
            <span className="text-slate-400 font-mono">
              Auto Sync: {autoSyncEnabled ? `Enabled (${intervalMs / 1000}s)` : "Disabled"}
            </span>
            <span className="mx-2 text-slate-500">|</span>
            <span className="text-slate-400 font-mono">Last Updated: {formattedTime}</span>
          </div>
        </div>

        <button
          type="button"
          onClick={() => void refresh(true)}
          disabled={state === "syncing" || state === "retrying"}
          className="inline-flex items-center gap-1.5 rounded-lg border border-current bg-transparent px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider transition-all hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={`h-2.5 w-2.5 ${state === "syncing" || state === "retrying" ? "animate-spin" : ""}`} />
          Force Sync
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-xl border border-red-500/20 bg-red-500/10 p-3 text-xs text-rose-400" id="journal-sync-error-details">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="font-mono">
            <strong>Latest Error:</strong> {error}
          </div>
        </div>
      )}
    </div>
  );
};
