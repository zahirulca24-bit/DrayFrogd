import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleDot,
  Clock3,
  Database,
  Download,
  FileDown,
  Filter,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  TimerReset,
  WalletCards,
  XCircle,
} from "lucide-react";
import { api } from "../api";
import { JournalTradeEntry, TradeHistoryEntry } from "../types";

interface TradeHistoryProps {
  authToken: string | null;
  history: TradeHistoryEntry[];
}

type FinancialJournalTrade = JournalTradeEntry & {
  strategy_name?: string | null;
  strategy?: string | null;
  exit_price?: number | null;
  realized_pnl?: number | null;
  fees?: number | null;
  close_reason?: string | null;
  execution_key?: string | null;
};

type AuditStatus =
  | "PENDING EXECUTION"
  | "ORDER SUBMITTED"
  | "OPEN"
  | "PROTECTION PENDING"
  | "CLOSE REQUESTED"
  | "SYNC PENDING"
  | "UNCERTAIN"
  | "FAILED"
  | "CLOSED"
  | "UNKNOWN";

type AuditOutcome = "PROFIT" | "LOSS" | "FLAT" | "UNKNOWN";
type TimelineState = "done" | "pending" | "warning" | "missing";

type TimelineStep = {
  label: string;
  value: string | null;
  state: TimelineState;
  detail: string;
};

type JournalRow = TradeHistoryEntry & {
  side: "LONG" | "SHORT";
  strategy: string;
  leverageText: string;
  rrValue: number | null;
  durationText: string;
  executionMode: string;
  auditStatus: AuditStatus;
  outcome: AuditOutcome;
  pnlValue: number | null;
  exitValue: number | null;
  feesValue: number | null;
  quantityValue: number | null;
  closeReason: string;
  executionKey: string | null;
  syncSource: string | null;
  protectionAttached: boolean | null;
  needsAttention: boolean;
  isClosed: boolean;
  metadata: Record<string, any>;
  timeline: TimelineStep[];
  executionLog: string[];
};

const BDT_DATE = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Dhaka",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

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

function bdtDate(value?: string | null) {
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "" : BDT_DATE.format(parsed);
}

function bdtDateTime(value?: string | Date | null) {
  if (!value) return "N/A";
  const parsed = value instanceof Date ? value : new Date(value);
  return Number.isNaN(parsed.getTime()) ? "N/A" : BDT_DATE_TIME.format(parsed);
}

function numberValue(value: unknown) {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function nullableNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function formatMoney(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "N/A";
  const sign = value < 0 ? "-" : "";
  return `${sign}$${Math.abs(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: Math.abs(value) >= 1000 ? 2 : 4,
  })}`;
}

function formatQuantity(value: number | null) {
  if (value === null) return "N/A";
  return value.toLocaleString(undefined, { maximumFractionDigits: 8 });
}

function calcRr(entry: number, stop: number, takeProfit: number) {
  const risk = Math.abs(entry - stop);
  const reward = Math.abs(takeProfit - entry);
  return risk > 0 && reward > 0 ? reward / risk : null;
}

function durationBetween(start?: string | null, end?: string | null) {
  if (!start || !end) return "N/A";
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (!Number.isFinite(ms) || ms <= 0) return "N/A";
  const minutes = Math.floor(ms / 60000);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  if (days > 0) return `${days}d ${hours % 24}h`;
  return hours > 0 ? `${hours}h ${minutes % 60}m` : `${minutes}m`;
}

function normalizeDirection(value?: string | null): "LONG" | "SHORT" {
  return String(value || "").toUpperCase() === "SHORT" ? "SHORT" : "LONG";
}

function todayBdtDate() {
  return BDT_DATE.format(new Date());
}

function defaultFilters() {
  return {
    dateFrom: "",
    dateTo: "",
    symbol: "ALL",
    status: "ALL",
    result: "ALL",
    strategy: "ALL",
    side: "ALL",
    exitReason: "ALL",
    search: "",
  };
}

function readable(value?: string | null, fallback = "Not recorded") {
  if (!value) return fallback;
  return value
    .replaceAll("_", " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^./, (character) => character.toUpperCase());
}

function nestedRecord(value: unknown): Record<string, any> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, any>)
    : {};
}

function auditStatus(rawValue?: string | null): AuditStatus {
  const value = String(rawValue || "").toLowerCase();
  if (value === "closed") return "CLOSED";
  if (value === "close_pending_sync") return "SYNC PENDING";
  if (value === "close_requested") return "CLOSE REQUESTED";
  if (value === "close_uncertain" || value === "execution_uncertain") return "UNCERTAIN";
  if (value.includes("failed") || value === "error") return "FAILED";
  if (value === "protection_pending") return "PROTECTION PENDING";
  if (value === "pending_execution") return "PENDING EXECUTION";
  if (value === "order_submitted") return "ORDER SUBMITTED";
  if (value === "active" || value === "open") return "OPEN";
  return "UNKNOWN";
}

function deriveOutcome(
  realizedPnl: number | null,
  rawResult?: string | null,
  isClosed = false,
): AuditOutcome {
  if (realizedPnl !== null) {
    if (realizedPnl > 0) return "PROFIT";
    if (realizedPnl < 0) return "LOSS";
    return isClosed ? "FLAT" : "UNKNOWN";
  }
  const normalized = String(rawResult || "").toLowerCase();
  if (normalized === "tp" || normalized === "profit") return "PROFIT";
  if (normalized === "sl" || normalized === "loss") return "LOSS";
  if (normalized === "flat" || normalized === "breakeven") return "FLAT";
  return "UNKNOWN";
}

function isPendingSyncStatus(status: AuditStatus) {
  return status === "SYNC PENDING" || status === "CLOSE REQUESTED" || status === "UNCERTAIN";
}

function journalToRow(item: JournalTradeEntry, index: number): JournalRow {
  const financial = item as FinancialJournalTrade;
  const metadata = nestedRecord(item.exchange_metadata);
  const manualClose = nestedRecord(metadata.manual_close);
  const closeSync = nestedRecord(metadata.close_sync);
  const orderResponse = nestedRecord(metadata.order_response);
  const positionSnapshot = nestedRecord(metadata.position_snapshot);

  const entryPrice = numberValue(item.entry);
  const stopLoss = numberValue(item.stop_loss);
  const takeProfit = numberValue(item.take_profit);
  const status = auditStatus(item.status);
  const isClosed = status === "CLOSED";
  const pnlValue = nullableNumber(financial.realized_pnl);
  const exitValue = nullableNumber(financial.exit_price);
  const feesValue = nullableNumber(financial.fees);
  const quantityValue = nullableNumber(item.quantity);
  const outcome = deriveOutcome(pnlValue, item.result, isClosed);
  const strategy = String(financial.strategy_name || financial.strategy || metadata.strategy_name || metadata.strategy || "unknown");
  const leverage = nullableNumber(metadata.leverage ?? orderResponse.leverage ?? positionSnapshot.leverage);
  const executionKey = String(financial.execution_key || metadata.execution_key || "").trim() || null;
  const syncSource = String(closeSync.source || metadata.close_sync_source || "").trim() || null;
  const protectionAttachedAt = String(metadata.protection_attached_at || "").trim() || null;
  const protectionAttached =
    metadata.protection_attached === true || protectionAttachedAt
      ? true
      : item.status === "protection_pending"
        ? false
        : null;
  const closeReason = financial.close_reason || item.sl_hit_reason || (isClosed ? "unknown" : "open");
  const detectedAt = item.detected_at || null;
  const openedAt = item.opened_at || null;
  const closeRequestedAt = String(manualClose.requested_at || "").trim() || null;
  const closeSyncedAt = String(closeSync.synced_at || "").trim() || null;
  const closedAt = item.closed_at || null;
  const adoptedPosition = metadata.source === "exchange_position_only";

  const missingClosedEvidence = isClosed && (exitValue === null || pnlValue === null || feesValue === null);
  const needsAttention =
    ["FAILED", "UNCERTAIN", "UNKNOWN"].includes(status) ||
    (isClosed && outcome === "UNKNOWN") ||
    missingClosedEvidence ||
    strategy.toLowerCase() === "unknown" ||
    (!item.order_id && !adoptedPosition);

  const timeline: TimelineStep[] = [
    {
      label: "Signal detected",
      value: detectedAt,
      state: detectedAt ? "done" : "missing",
      detail: detectedAt ? "Strategy signal timestamp recorded." : "No detected timestamp was saved.",
    },
    {
      label: "Journal reserved",
      value: detectedAt || openedAt,
      state: item.journal_id ? "done" : "missing",
      detail: item.journal_id ? `Journal ID ${item.journal_id}` : "Journal identifier unavailable.",
    },
    {
      label: "Order confirmed",
      value: openedAt,
      state: item.order_id ? "done" : adoptedPosition ? "warning" : "missing",
      detail: item.order_id
        ? `Exchange order ${item.order_id}`
        : adoptedPosition
          ? "Exchange position was adopted without an original local order ID."
          : "Exchange order ID unavailable.",
    },
    {
      label: "Protection attached",
      value: protectionAttachedAt,
      state: protectionAttached === true ? "done" : protectionAttached === false ? "warning" : "missing",
      detail:
        protectionAttached === true
          ? "Stop-loss and take-profit attachment was recorded."
          : protectionAttached === false
            ? "Protection attachment is pending."
            : "Protection evidence was not recorded for this row.",
    },
    {
      label: "Close requested",
      value: closeRequestedAt,
      state: closeRequestedAt ? "done" : isPendingSyncStatus(status) ? "pending" : "missing",
      detail: closeRequestedAt
        ? `Close request ${manualClose.request_id || "recorded"}.`
        : isPendingSyncStatus(status)
          ? "Close workflow is active; request timestamp is unavailable."
          : "No manual close request recorded.",
    },
    {
      label: "Exact PnL synchronized",
      value: closeSyncedAt,
      state: closeSyncedAt ? "done" : status === "SYNC PENDING" ? "pending" : isClosed && pnlValue === null ? "warning" : "missing",
      detail: closeSyncedAt
        ? `Source: ${syncSource || "Bybit closed PnL"}.`
        : status === "SYNC PENDING"
          ? "Awaiting authoritative exchange close records."
          : isClosed && pnlValue === null
            ? "Closed row has no authoritative realized PnL."
            : "Exact close sync not applicable yet.",
    },
    {
      label: "Trade closed",
      value: closedAt,
      state: isClosed ? (closedAt ? "done" : "warning") : "pending",
      detail: isClosed
        ? closedAt
          ? `Close reason: ${readable(closeReason)}.`
          : "Trade is marked closed but close timestamp is unavailable."
        : "Trade remains open or in a close workflow.",
    },
  ];

  const executionLog = [
    `Journal ID: ${item.journal_id || "unavailable"}`,
    item.order_id
      ? `Exchange order ID: ${item.order_id}`
      : adoptedPosition
        ? "Original order ID unavailable because this exchange position was adopted."
        : "Exchange order ID unavailable.",
    executionKey ? `Execution key: ${executionKey}` : "Execution key unavailable.",
    `Execution mode: ${(item.execution_mode || "demo").toUpperCase()}`,
    `Current status: ${status}`,
    protectionAttached === true
      ? "Protection evidence: attached"
      : protectionAttached === false
        ? "Protection evidence: pending"
        : "Protection evidence: not recorded",
    syncSource ? `Close PnL source: ${syncSource}` : "Close PnL source unavailable.",
    isClosed
      ? pnlValue !== null
        ? `Authoritative realized PnL: ${formatMoney(pnlValue)}`
        : "Closed outcome is missing authoritative realized PnL."
      : "Trade has not reached an authoritative closed state.",
  ];

  return {
    id: item.order_id || item.journal_id || `${item.symbol}-${index}`,
    pair: item.symbol,
    strategy,
    direction: normalizeDirection(item.direction),
    entryPrice,
    currentPrice: exitValue ?? entryPrice,
    stopLoss,
    takeProfit,
    size: quantityValue ?? 0,
    margin: 0,
    leverage: leverage ?? 0,
    unrealizedPnl: 0,
    pnlPercent: 0,
    status: isClosed ? "CLOSED" : "OPEN",
    timestamp: openedAt || detectedAt || closedAt || new Date().toISOString(),
    orderConfirmed: Boolean(item.order_id),
    slVerified: protectionAttached === true,
    tpVerified: protectionAttached === true,
    positionSynced: Boolean(positionSnapshot.symbol || closeSync.source),
    orderId: item.order_id || undefined,
    rawStatus: item.status,
    journalId: item.journal_id,
    executionMode: item.execution_mode || "demo",
    closedAt: closedAt || undefined,
    slHitReason: item.sl_hit_reason ?? null,
    exitPrice: exitValue ?? 0,
    pnl: pnlValue ?? 0,
    result: outcome as TradeHistoryEntry["result"],
    reason: closeReason,
    side: normalizeDirection(item.direction),
    leverageText: leverage === null ? "N/A" : `${leverage}x`,
    rrValue: calcRr(entryPrice, stopLoss, takeProfit),
    durationText: durationBetween(openedAt || detectedAt, closedAt),
    auditStatus: status,
    outcome,
    pnlValue,
    exitValue,
    feesValue,
    quantityValue,
    closeReason,
    executionKey,
    syncSource,
    protectionAttached,
    needsAttention,
    isClosed,
    metadata,
    timeline,
    executionLog,
  };
}

function fallbackToRow(trade: TradeHistoryEntry, index: number): JournalRow {
  const rawOutcome = String(trade.result || "UNKNOWN").toUpperCase() as AuditOutcome;
  const pnlValue = trade.pnl !== 0 || rawOutcome === "PROFIT" || rawOutcome === "LOSS" ? trade.pnl : null;
  const exitValue = trade.exitPrice > 0 ? trade.exitPrice : null;
  const isClosed = trade.status === "CLOSED";
  const status: AuditStatus = isClosed ? "CLOSED" : "OPEN";
  const strategy = trade.strategy || "unknown";
  const needsAttention = strategy.toLowerCase() === "unknown" || (isClosed && (pnlValue === null || exitValue === null));

  return {
    ...trade,
    id: trade.id || `${trade.pair}-${index}`,
    side: normalizeDirection(trade.direction),
    strategy,
    leverageText: trade.leverage ? `${trade.leverage}x` : "N/A",
    rrValue: calcRr(trade.entryPrice, trade.stopLoss, trade.takeProfit),
    durationText: durationBetween(trade.timestamp, trade.closedAt),
    executionMode: trade.executionMode || "demo",
    auditStatus: status,
    outcome: ["PROFIT", "LOSS", "FLAT"].includes(rawOutcome) ? rawOutcome : "UNKNOWN",
    pnlValue,
    exitValue,
    feesValue: null,
    quantityValue: trade.size || null,
    closeReason: trade.reason || "unknown",
    executionKey: null,
    syncSource: null,
    protectionAttached: trade.slVerified && trade.tpVerified ? true : null,
    needsAttention,
    isClosed,
    metadata: {},
    timeline: [
      { label: "Signal detected", value: null, state: "missing", detail: "Detected timestamp unavailable in fallback history." },
      { label: "Journal reserved", value: trade.timestamp, state: "done", detail: "Fallback history row loaded." },
      { label: "Order confirmed", value: trade.timestamp, state: trade.orderId ? "done" : "missing", detail: trade.orderId ? `Exchange order ${trade.orderId}` : "Exchange order ID unavailable." },
      { label: "Protection attached", value: null, state: trade.slVerified && trade.tpVerified ? "done" : "missing", detail: trade.slVerified && trade.tpVerified ? "Protection flags recorded." : "Protection evidence unavailable." },
      { label: "Close requested", value: null, state: "missing", detail: "Close request metadata unavailable." },
      { label: "Exact PnL synchronized", value: trade.closedAt || null, state: pnlValue !== null ? "done" : "missing", detail: pnlValue !== null ? "Realized PnL available in fallback history." : "Realized PnL unavailable." },
      { label: "Trade closed", value: trade.closedAt || null, state: isClosed ? "done" : "pending", detail: isClosed ? `Close reason: ${readable(trade.reason)}.` : "Trade remains open." },
    ],
    executionLog: [
      trade.orderId ? `Exchange order ID: ${trade.orderId}` : "Exchange order ID unavailable.",
      `Execution mode: ${(trade.executionMode || "demo").toUpperCase()}`,
      pnlValue === null ? "Authoritative realized PnL unavailable." : `Realized PnL: ${formatMoney(pnlValue)}`,
    ],
  };
}

export default function TradeHistory({ authToken, history }: TradeHistoryProps) {
  const [journalTrades, setJournalTrades] = useState<JournalTradeEntry[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [filters, setFilters] = useState(defaultFilters);

  const loadJournal = async () => {
    if (!authToken) return;
    setLoading(true);
    try {
      const response = await api.getJournalTrades(authToken);
      setJournalTrades(response.trades || []);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Failed to load journal trades");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!authToken) return;
    let cancelled = false;

    const refresh = async () => {
      try {
        const response = await api.getJournalTrades(authToken);
        if (!cancelled) {
          setJournalTrades(response.trades || []);
          setError(null);
        }
      } catch (err: any) {
        if (!cancelled) setError(err?.message || "Failed to load journal trades");
      }
    };

    void refresh();
    const interval = setInterval(refresh, 10000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [authToken]);

  const rows = useMemo<JournalRow[]>(() => {
    if (journalTrades.length > 0) return journalTrades.map(journalToRow);
    return history.map(fallbackToRow);
  }, [history, journalTrades]);

  const symbols = useMemo(() => Array.from(new Set(rows.map((row) => row.pair))).sort(), [rows]);
  const strategies = useMemo(() => Array.from(new Set(rows.map((row) => row.strategy))).sort(), [rows]);
  const reasons = useMemo(() => Array.from(new Set(rows.map((row) => row.closeReason || "unknown"))).sort(), [rows]);
  const statuses = useMemo(() => Array.from(new Set(rows.map((row) => row.auditStatus))).sort(), [rows]);

  const filteredRows = useMemo(() => {
    const query = filters.search.trim().toLowerCase();
    return rows.filter((row) => {
      const date = bdtDate(row.closedAt || row.timestamp);
      const searchText = [
        row.pair,
        row.side,
        row.strategy,
        row.auditStatus,
        row.outcome,
        row.orderId,
        row.journalId,
        row.executionKey,
        row.closeReason,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      return !(filters.dateFrom && date < filters.dateFrom)
        && !(filters.dateTo && date > filters.dateTo)
        && !(filters.symbol !== "ALL" && row.pair !== filters.symbol)
        && !(filters.status !== "ALL" && row.auditStatus !== filters.status)
        && !(filters.result !== "ALL" && row.outcome !== filters.result)
        && !(filters.strategy !== "ALL" && row.strategy !== filters.strategy)
        && !(filters.side !== "ALL" && row.side !== filters.side)
        && !(filters.exitReason !== "ALL" && row.closeReason !== filters.exitReason)
        && !(query && !searchText.includes(query));
    });
  }, [filters, rows]);

  const selectedTrade = useMemo(
    () => filteredRows.find((row) => row.id === selectedId) || filteredRows[0] || null,
    [filteredRows, selectedId],
  );

  useEffect(() => {
    if (!filteredRows.length) {
      setSelectedId(null);
      return;
    }
    if (!filteredRows.some((row) => row.id === selectedId)) {
      setSelectedId(filteredRows[0].id);
    }
  }, [filteredRows, selectedId]);

  useEffect(() => {
    if (!rows.length || filteredRows.length > 0) {
      return;
    }

    const hasOnlyDateFilters =
      (filters.dateFrom || filters.dateTo)
      && filters.symbol === "ALL"
      && filters.status === "ALL"
      && filters.result === "ALL"
      && filters.strategy === "ALL"
      && filters.side === "ALL"
      && filters.exitReason === "ALL"
      && !filters.search.trim();

    if (hasOnlyDateFilters) {
      setFilters((current) => ({
        ...current,
        dateFrom: "",
        dateTo: "",
      }));
    }
  }, [filteredRows.length, filters, rows.length]);

  const summary = useMemo(() => ({
    total: rows.length,
    open: rows.filter((row) => !row.isClosed && !isPendingSyncStatus(row.auditStatus)).length,
    pending: rows.filter((row) => isPendingSyncStatus(row.auditStatus)).length,
    closedToday: rows.filter((row) => row.isClosed && bdtDate(row.closedAt) === todayBdtDate()).length,
    attention: rows.filter((row) => row.needsAttention).length,
  }), [rows]);

  const resetFilters = () => {
    setFilters(defaultFilters());
  };

  const exportCsv = () => {
    const headers = [
      "BDT Time",
      "Symbol",
      "Side",
      "Strategy",
      "Status",
      "Entry",
      "Exit",
      "Fees",
      "Realized PnL",
      "Result",
      "Close Reason",
      "Order ID",
      "Journal ID",
    ];
    const data = filteredRows.map((row) => [
      bdtDateTime(row.closedAt || row.timestamp),
      row.pair,
      row.side,
      row.strategy,
      row.auditStatus,
      row.entryPrice,
      row.exitValue ?? "N/A",
      row.feesValue ?? "N/A",
      row.pnlValue ?? "N/A",
      row.outcome,
      row.closeReason,
      row.orderId || "N/A",
      row.journalId || "N/A",
    ]);
    const csv = [headers, ...data]
      .map((line) => line.map((cell) => `"${String(cell ?? "").replaceAll('"', '""')}"`).join(","))
      .join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8;" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `journal-${filters.dateFrom || "all"}-${filters.dateTo || "all"}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const exportPdf = () => {
    const popup = window.open("", "_blank", "width=1200,height=850");
    if (!popup) return;
    const bodyRows = filteredRows
      .map((row) => `
        <tr>
          <td>${escapeHtml(bdtDateTime(row.closedAt || row.timestamp))}</td>
          <td>${escapeHtml(row.pair)}</td>
          <td>${escapeHtml(row.side)}</td>
          <td>${escapeHtml(row.strategy)}</td>
          <td>${escapeHtml(row.auditStatus)}</td>
          <td>${escapeHtml(formatMoney(row.exitValue))}</td>
          <td>${escapeHtml(formatMoney(row.feesValue))}</td>
          <td>${escapeHtml(formatMoney(row.pnlValue))}</td>
          <td>${escapeHtml(row.outcome)}</td>
        </tr>`)
      .join("");
    popup.document.write(`
      <html>
        <head><title>DayFrogd Journal Export</title></head>
        <body style="font-family:Arial;padding:24px;color:#111">
          <h2>DayFrogd Journal / Trade History</h2>
          <p>Generated BDT ${escapeHtml(bdtDateTime(new Date()))}</p>
          <table border="1" cellspacing="0" cellpadding="6" style="border-collapse:collapse;width:100%;font-size:11px">
            <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Strategy</th><th>Status</th><th>Exit</th><th>Fees</th><th>PnL</th><th>Result</th></tr></thead>
            <tbody>${bodyRows}</tbody>
          </table>
        </body>
      </html>`);
    popup.document.close();
    popup.print();
  };

  return (
    <div className="space-y-4" id="trade-history-section">
      <section className="rounded-2xl border border-slate-800/80 bg-bento-card-sec/40 p-5 shadow-lg backdrop-blur-md">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="flex items-center gap-3">
              <div className="rounded-xl border border-violet-500/20 bg-violet-500/10 p-2.5 text-violet-300">
                <WalletCards className="h-5 w-5" />
              </div>
              <div>
                <h1 className="text-xl font-bold tracking-tight text-white">Journal / Trade History</h1>
                <p className="mt-1 text-xs text-slate-400">Audit-ready trade records with lifecycle evidence, sync status, fees and authoritative realized PnL.</p>
              </div>
            </div>
            <div className="mt-4 inline-flex items-center gap-2 rounded-lg border border-slate-800 bg-[#0A0B0E] px-3 py-2 text-[10px] font-mono text-slate-500">
              <Clock3 className="h-3.5 w-3.5" /> BDT {bdtDateTime(new Date())}
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <ActionButton label={loading ? "REFRESHING..." : "REFRESH"} icon={<RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />} onClick={() => void loadJournal()} disabled={loading} />
            <ActionButton label="EXPORT CSV" icon={<Download className="h-4 w-4" />} onClick={exportCsv} />
            <ActionButton label="EXPORT PDF" icon={<FileDown className="h-4 w-4" />} onClick={exportPdf} />
          </div>
        </div>
        {error && (
          <div className="mt-4 flex items-start gap-2 rounded-xl border border-rose-500/20 bg-rose-500/10 p-3 text-xs text-rose-300">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
          </div>
        )}
      </section>

      <section className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <SummaryCard label="Total Trades" value={summary.total} icon={<Database className="h-4 w-4" />} tone="neutral" />
        <SummaryCard label="Open Trades" value={summary.open} icon={<Activity className="h-4 w-4" />} tone="good" />
        <SummaryCard label="Close / Sync Pending" value={summary.pending} icon={<TimerReset className="h-4 w-4" />} tone="warn" />
        <SummaryCard label="Closed Today" value={summary.closedToday} icon={<CheckCircle2 className="h-4 w-4" />} tone="accent" />
        <SummaryCard label="Needs Attention" value={summary.attention} icon={<ShieldAlert className="h-4 w-4" />} tone="bad" />
      </section>

      <section className="rounded-2xl border border-slate-800 bg-bento-card p-4 shadow-md">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-[1.2fr_0.8fr_0.8fr_0.8fr_auto]">
          <FilterField label="Search" icon={<Search className="h-3.5 w-3.5" />}>
            <input
              type="search"
              autoComplete="off"
              value={filters.search}
              onChange={(event) => setFilters((current) => ({ ...current, search: event.target.value }))}
              placeholder="Symbol, order ID, strategy..."
              className="dashboard-input"
            />
          </FilterField>
          <FilterField label="Date From"><input type="date" autoComplete="off" value={filters.dateFrom} onChange={(event) => setFilters((current) => ({ ...current, dateFrom: event.target.value }))} className="dashboard-input" /></FilterField>
          <FilterField label="Date To"><input type="date" autoComplete="off" value={filters.dateTo} onChange={(event) => setFilters((current) => ({ ...current, dateTo: event.target.value }))} className="dashboard-input" /></FilterField>
          <FilterField label="Status"><select value={filters.status} onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))} className="dashboard-input"><option value="ALL">All statuses</option>{statuses.map((value) => <option key={value} value={value}>{value}</option>)}</select></FilterField>
          <div className="flex items-end gap-2">
            <button type="button" onClick={() => setShowAdvanced((current) => !current)} className="inline-flex h-[42px] flex-1 items-center justify-center gap-2 rounded-xl border border-slate-800 bg-[#0A0B0E] px-4 text-xs font-semibold text-slate-300 hover:border-slate-700">
              <Filter className="h-4 w-4" /> MORE {showAdvanced ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </button>
            <button type="button" onClick={resetFilters} className="inline-flex h-[42px] items-center justify-center rounded-xl border border-slate-800 bg-[#0A0B0E] px-4 text-xs font-semibold text-slate-500 hover:border-slate-700 hover:text-slate-300">RESET</button>
          </div>
        </div>

        {showAdvanced && (
          <div className="mt-4 grid grid-cols-2 gap-3 border-t border-slate-800 pt-4 md:grid-cols-3 xl:grid-cols-5">
            <FilterField label="Symbol"><select value={filters.symbol} onChange={(event) => setFilters((current) => ({ ...current, symbol: event.target.value }))} className="dashboard-input"><option value="ALL">All symbols</option>{symbols.map((value) => <option key={value} value={value}>{value}</option>)}</select></FilterField>
            <FilterField label="Result"><select value={filters.result} onChange={(event) => setFilters((current) => ({ ...current, result: event.target.value }))} className="dashboard-input"><option value="ALL">All results</option><option value="PROFIT">PROFIT</option><option value="LOSS">LOSS</option><option value="FLAT">FLAT</option><option value="UNKNOWN">UNKNOWN</option></select></FilterField>
            <FilterField label="Strategy"><select value={filters.strategy} onChange={(event) => setFilters((current) => ({ ...current, strategy: event.target.value }))} className="dashboard-input"><option value="ALL">All strategies</option>{strategies.map((value) => <option key={value} value={value}>{value}</option>)}</select></FilterField>
            <FilterField label="Side"><select value={filters.side} onChange={(event) => setFilters((current) => ({ ...current, side: event.target.value }))} className="dashboard-input"><option value="ALL">All sides</option><option value="LONG">LONG</option><option value="SHORT">SHORT</option></select></FilterField>
            <FilterField label="Close Reason"><select value={filters.exitReason} onChange={(event) => setFilters((current) => ({ ...current, exitReason: event.target.value }))} className="dashboard-input"><option value="ALL">All reasons</option>{reasons.map((value) => <option key={value} value={value}>{readable(value)}</option>)}</select></FilterField>
          </div>
        )}
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="overflow-hidden rounded-2xl border border-slate-800 bg-bento-card p-4 shadow-md">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-white">Trade Records</h2>
              <p className="mt-1 text-xs text-slate-500">Unknown financial values remain N/A and are never presented as zero.</p>
            </div>
            <span className="rounded-lg border border-slate-800 bg-[#0A0B0E] px-2.5 py-1 text-[10px] font-mono text-slate-500">{loading ? "Loading..." : `${filteredRows.length} rows`}</span>
          </div>

          <div className="overflow-x-auto rounded-xl border border-slate-800">
            <table className="w-full min-w-[1120px] whitespace-nowrap">
              <thead className="bg-[#0A0B0E]">
                <tr className="border-b border-slate-800 text-[10px] font-mono uppercase tracking-wider text-slate-500">
                  <th className="p-3 text-left">Time</th><th className="p-3 text-left">Symbol</th><th className="p-3 text-left">Side</th><th className="p-3 text-left">Strategy</th><th className="p-3 text-left">Status</th><th className="p-3 text-right">Entry</th><th className="p-3 text-right">Exit</th><th className="p-3 text-right">Fees</th><th className="p-3 text-right">Realized PnL</th><th className="p-3 text-left">Result</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/50 text-xs">
                {filteredRows.map((row) => (
                  <tr key={row.id} onClick={() => setSelectedId(row.id)} className={`cursor-pointer transition-colors ${selectedTrade?.id === row.id ? "bg-violet-500/10" : "hover:bg-slate-900/50"}`}>
                    <td className="p-3 font-mono text-slate-400">{bdtDateTime(row.closedAt || row.timestamp)}</td>
                    <td className="p-3 font-semibold text-white">{row.pair}</td>
                    <td className={`p-3 font-mono ${row.side === "LONG" ? "text-emerald-400" : "text-rose-400"}`}>{row.side}</td>
                    <td className="max-w-[170px] truncate p-3 text-slate-400">{row.strategy}</td>
                    <td className="p-3"><StatusBadge status={row.auditStatus} /></td>
                    <td className="p-3 text-right font-mono text-slate-300">{formatMoney(row.entryPrice)}</td>
                    <td className="p-3 text-right font-mono text-slate-300">{formatMoney(row.exitValue)}</td>
                    <td className="p-3 text-right font-mono text-slate-400">{formatMoney(row.feesValue)}</td>
                    <td className={`p-3 text-right font-mono font-semibold ${row.pnlValue === null ? "text-slate-500" : row.pnlValue > 0 ? "text-emerald-400" : row.pnlValue < 0 ? "text-rose-400" : "text-slate-300"}`}>{formatMoney(row.pnlValue)}</td>
                    <td className="p-3"><OutcomeBadge outcome={row.outcome} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {filteredRows.length === 0 && <div className="py-14 text-center text-xs text-slate-500">No journal records match the selected filters.</div>}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-bento-card p-5 shadow-md">
          {selectedTrade ? <TradeAuditDetail trade={selectedTrade} /> : <EmptyState />}
        </div>
      </section>
    </div>
  );
}

function ActionButton({ label, icon, onClick, disabled = false }: { label: string; icon: ReactNode; onClick: () => void; disabled?: boolean }) {
  return <button type="button" onClick={onClick} disabled={disabled} className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-800 bg-[#0A0B0E] px-4 py-3 text-xs font-semibold text-slate-300 transition-colors hover:border-slate-700 hover:text-white disabled:cursor-not-allowed disabled:opacity-50">{icon}{label}</button>;
}

function SummaryCard({ label, value, icon, tone }: { label: string; value: number; icon: ReactNode; tone: "neutral" | "good" | "warn" | "accent" | "bad" }) {
  const toneClass = tone === "good" ? "border-emerald-500/10 bg-emerald-500/10 text-emerald-300" : tone === "warn" ? "border-amber-500/10 bg-amber-500/10 text-amber-300" : tone === "accent" ? "border-violet-500/10 bg-violet-500/10 text-violet-300" : tone === "bad" ? "border-rose-500/10 bg-rose-500/10 text-rose-300" : "border-slate-700 bg-slate-800/80 text-slate-300";
  return <div className="rounded-2xl border border-slate-800 bg-bento-card p-4 shadow-md"><div className="flex items-center justify-between gap-3"><span className="text-[10px] font-mono font-semibold uppercase tracking-wider text-slate-500">{label}</span><span className={`rounded-xl border p-2 ${toneClass}`}>{icon}</span></div><div className="mt-3 text-2xl font-bold text-white">{value}</div></div>;
}

function FilterField({ label, icon, children }: { label: string; icon?: ReactNode; children: ReactNode }) {
  return <label className="block space-y-2"><span className="flex items-center gap-1 text-[10px] font-mono uppercase tracking-wider text-slate-500">{icon || <Filter className="h-3.5 w-3.5" />}{label}</span>{children}</label>;
}

function StatusBadge({ status }: { status: AuditStatus }) {
  const tone = status === "CLOSED" ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300" : status === "OPEN" || status === "ORDER SUBMITTED" ? "border-sky-500/20 bg-sky-500/10 text-sky-300" : status === "SYNC PENDING" || status === "CLOSE REQUESTED" || status === "PENDING EXECUTION" || status === "PROTECTION PENDING" ? "border-amber-500/20 bg-amber-500/10 text-amber-300" : "border-rose-500/20 bg-rose-500/10 text-rose-300";
  return <span className={`inline-flex rounded-md border px-2 py-1 text-[9px] font-mono font-semibold ${tone}`}>{status}</span>;
}

function OutcomeBadge({ outcome }: { outcome: AuditOutcome }) {
  const tone = outcome === "PROFIT" ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300" : outcome === "LOSS" ? "border-rose-500/20 bg-rose-500/10 text-rose-300" : outcome === "FLAT" ? "border-slate-600 bg-slate-800 text-slate-300" : "border-amber-500/20 bg-amber-500/10 text-amber-300";
  return <span className={`inline-flex rounded-md border px-2 py-1 text-[9px] font-mono font-semibold ${tone}`}>{outcome}</span>;
}

function TradeAuditDetail({ trade }: { trade: JournalRow }) {
  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <div><div className="flex flex-wrap items-center gap-2"><StatusBadge status={trade.auditStatus} /><OutcomeBadge outcome={trade.outcome} /></div><h2 className="mt-3 text-xl font-bold text-white">{trade.pair} Trade Audit</h2><p className="mt-1 text-xs text-slate-500">{trade.strategy} · <span className={trade.side === "LONG" ? "text-emerald-400" : "text-rose-400"}>{trade.side}</span> · {trade.executionMode.toUpperCase()}</p></div>
        {trade.needsAttention ? <span className="inline-flex items-center gap-1 rounded-lg border border-rose-500/20 bg-rose-500/10 px-2.5 py-1 text-[9px] font-mono text-rose-300"><ShieldAlert className="h-3.5 w-3.5" /> REVIEW</span> : <span className="inline-flex items-center gap-1 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-[9px] font-mono text-emerald-300"><ShieldCheck className="h-3.5 w-3.5" /> COMPLETE</span>}
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <DetailMetric label="Entry" value={formatMoney(trade.entryPrice)} />
        <DetailMetric label="Stop Loss" value={formatMoney(trade.stopLoss)} tone="bad" />
        <DetailMetric label="Take Profit" value={formatMoney(trade.takeProfit)} tone="good" />
        <DetailMetric label="Exit" value={formatMoney(trade.exitValue)} />
        <DetailMetric label="Quantity" value={formatQuantity(trade.quantityValue)} />
        <DetailMetric label="Leverage" value={trade.leverageText} />
        <DetailMetric label="Fees" value={formatMoney(trade.feesValue)} />
        <DetailMetric label="Realized PnL" value={formatMoney(trade.pnlValue)} tone={trade.pnlValue === null ? "neutral" : trade.pnlValue >= 0 ? "good" : "bad"} />
      </div>

      {(trade.outcome === "UNKNOWN" || trade.pnlValue === null) && trade.isClosed && (
        <div className="mt-4 flex items-start gap-3 rounded-xl border border-amber-500/20 bg-amber-500/10 p-4"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" /><div><div className="text-xs font-semibold text-amber-200">Financial outcome incomplete</div><div className="mt-1 text-xs leading-5 text-amber-300/80">This closed row is missing authoritative exchange close data. Unknown values remain N/A and are not counted as profit or loss.</div></div></div>
      )}

      <div className="mt-5 rounded-xl border border-slate-800 bg-[#0A0B0E] p-4">
        <div className="flex items-center justify-between"><div><h3 className="text-sm font-semibold text-white">Trade Lifecycle</h3><p className="mt-1 text-xs text-slate-500">Recorded evidence only—no synthetic timestamps.</p></div><span className="text-[10px] font-mono text-slate-500">{trade.durationText}</span></div>
        <div className="mt-4 space-y-3">{trade.timeline.map((step) => <TimelineRow key={step.label} step={step} />)}</div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-4"><h3 className="text-sm font-semibold text-white">Protection & Sync Evidence</h3><div className="mt-4 space-y-3"><EvidenceRow label="Order ID" value={trade.orderId || "Unavailable"} warning={!trade.orderId} /><EvidenceRow label="Execution Key" value={trade.executionKey || "Unavailable"} warning={!trade.executionKey} /><EvidenceRow label="Protection" value={trade.protectionAttached === true ? "Attached" : trade.protectionAttached === false ? "Pending" : "Not recorded"} warning={trade.protectionAttached !== true} /><EvidenceRow label="PnL Sync Source" value={trade.syncSource || "Unavailable"} warning={trade.isClosed && !trade.syncSource} /><EvidenceRow label="Close Reason" value={readable(trade.closeReason)} /></div></div>
        <div className="rounded-xl border border-slate-800 bg-[#0A0B0E] p-4"><h3 className="text-sm font-semibold text-white">Execution Log</h3><div className="mt-4 space-y-2">{trade.executionLog.map((line, index) => <div key={`${line}-${index}`} className="flex items-start gap-2 text-xs leading-5 text-slate-400"><CircleDot className="mt-1 h-3 w-3 shrink-0 text-slate-600" /><span className="break-all">{line}</span></div>)}</div></div>
      </div>
    </div>
  );
}

function DetailMetric({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "neutral" | "good" | "bad" }) {
  const valueClass = tone === "good" ? "text-emerald-400" : tone === "bad" ? "text-rose-400" : "text-white";
  return <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3"><div className="text-[10px] font-mono uppercase tracking-wider text-slate-500">{label}</div><div className={`mt-2 break-words text-sm font-semibold ${valueClass}`}>{value}</div></div>;
}

function TimelineRow({ step }: { step: TimelineStep }) {
  const icon = step.state === "done" ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : step.state === "pending" ? <TimerReset className="h-4 w-4 text-amber-400" /> : step.state === "warning" ? <AlertTriangle className="h-4 w-4 text-rose-400" /> : <XCircle className="h-4 w-4 text-slate-600" />;
  return <div className="flex items-start gap-3 rounded-lg border border-slate-800 bg-slate-950/50 p-3">{icon}<div className="min-w-0 flex-1"><div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between"><span className="text-xs font-semibold text-slate-200">{step.label}</span><span className="text-[10px] font-mono text-slate-500">{bdtDateTime(step.value)}</span></div><p className="mt-1 text-xs leading-5 text-slate-500">{step.detail}</p></div></div>;
}

function EvidenceRow({ label, value, warning = false }: { label: string; value: string; warning?: boolean }) {
  return <div className="flex items-start justify-between gap-3 border-b border-slate-800/60 pb-2 last:border-0 last:pb-0"><span className="text-xs text-slate-500">{label}</span><span className={`max-w-[65%] break-all text-right text-xs font-mono ${warning ? "text-amber-300" : "text-slate-300"}`}>{value}</span></div>;
}

function EmptyState() {
  return <div className="flex min-h-[420px] flex-col items-center justify-center rounded-xl border border-dashed border-slate-800 bg-[#0A0B0E] px-6 text-center"><div className="rounded-xl border border-slate-800 bg-slate-900 p-3 text-slate-400"><Database className="h-5 w-5" /></div><div className="mt-3 text-sm font-semibold text-white">Select a trade record</div><div className="mt-1 max-w-sm text-xs leading-5 text-slate-500">Choose a journal row to inspect execution evidence, lifecycle status, close synchronization and financial outcome.</div></div>;
}

function escapeHtml(value: string) {
  return value.replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[character] || character));
}
