import { Trade, TradeHistoryEntry } from "./types";

export function parseNullableNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export type LifecycleStatus = 'OPEN' | 'CLOSED' | 'PENDING' | 'ATTENTION' | 'UNKNOWN';

export function getLifecycleStatus(rawStatus: string | null | undefined): LifecycleStatus {
  const status = String(rawStatus || "").toLowerCase().trim();
  if (!status) return 'UNKNOWN';

  const openStatuses = ['active', 'partial_fill', 'close_requested', 'close_uncertain'];
  if (openStatuses.includes(status)) {
    return 'OPEN';
  }

  if (status === 'closed') {
    return 'CLOSED';
  }

  const pendingStatuses = [
    'pending_execution',
    'order_submitted',
    'fill_confirmation_pending',
    'order_filled',
    'protection_pending',
    'reconciliation_pending'
  ];
  if (pendingStatuses.includes(status)) {
    return 'PENDING';
  }

  const attentionStatuses = [
    'execution_uncertain',
    'emergency_close_failed',
    'close_pending_sync'
  ];
  if (attentionStatuses.includes(status)) {
    return 'ATTENTION';
  }

  return 'UNKNOWN';
}

export function getProtectionVerification(raw: any): { slVerified: boolean | null; tpVerified: boolean | null } {
  const status = String(raw.status || "").toLowerCase().trim();
  const metadata = raw.exchange_metadata || {};

  // Explicit verified evidence
  const hasExplicitVerified = metadata.protection_attached === true ||
                              Boolean(metadata.protection_attached_at) ||
                              metadata.sl_verified === true ||
                              metadata.tp_verified === true;

  // Explicit failed or pending evidence
  const hasFailedOrPending = status === "protection_pending" ||
                             metadata.protection_failed === true ||
                             metadata.protection_pending === true;

  // Unsafe lifecycle state (status is not open/closed or has pending evidence)
  const lifecycle = getLifecycleStatus(raw.status);
  const isUnsafeLifecycle = lifecycle === 'PENDING' || lifecycle === 'ATTENTION' || lifecycle === 'UNKNOWN';

  if (isUnsafeLifecycle) {
    // never show green “protected” status without explicit evidence
    if (hasExplicitVerified && !hasFailedOrPending) {
      return { slVerified: true, tpVerified: true };
    }
    return { slVerified: false, tpVerified: false };
  }

  if (hasExplicitVerified && !hasFailedOrPending) {
    return { slVerified: true, tpVerified: true };
  }

  if (hasFailedOrPending) {
    return { slVerified: false, tpVerified: false };
  }

  // Missing or conflicting evidence
  return { slVerified: null, tpVerified: null };
}

export function normalizeTrade(raw: any, index: number): Trade {
  const entryPrice = parseNullableNumber(raw.entry ?? raw.entryPrice ?? raw.entry_price) ?? 0;
  const stopLoss = parseNullableNumber(raw.stop_loss ?? raw.stopLoss ?? raw.stop_price) ?? 0;
  const takeProfit = parseNullableNumber(raw.take_profit ?? raw.takeProfit ?? raw.take_profit_price) ?? 0;
  const size = parseNullableNumber(raw.quantity ?? raw.size ?? raw.qty) ?? 0;
  const direction = String(raw.direction || "").toUpperCase() === "SHORT" ? "SHORT" : "LONG";
  const rawResult = String(raw.result || "").toUpperCase();
  const exchangeMetadata = (raw.exchange_metadata || {}) as Record<string, any>;
  const management = (exchangeMetadata.management || {}) as Record<string, any>;
  const exitPrice = parseNullableNumber(raw.exit_price ?? raw.exitPrice);
  const markPrice = parseNullableNumber(raw.mark_price ?? exchangeMetadata.mark_price ?? exchangeMetadata.markPrice);
  const realizedPnl = parseNullableNumber(raw.realized_pnl ?? raw.realizedPnl ?? raw.pnl);
  const fees = parseNullableNumber(raw.fees);
  const margin = parseNullableNumber(raw.position_margin ?? raw.margin);

  // leverage might be nested in exchangeMetadata
  const orderResponse = exchangeMetadata.order_response || {};
  const positionSnapshot = exchangeMetadata.position_snapshot || {};
  const rawLeverage = raw.leverage ?? exchangeMetadata.leverage ?? orderResponse.leverage ?? positionSnapshot.leverage;
  const leverage = parseNullableNumber(rawLeverage);

  const unrealizedPnl = parseNullableNumber(raw.unrealized_pnl ?? raw.unrealizedPnl);
  const pnlPercent = parseNullableNumber(raw.pnl_percent ?? raw.pnlPercent ?? raw.pnl_pcnt);
  const positionValue = parseNullableNumber(raw.position_value ?? raw.positionValue);
  const liquidationPrice = parseNullableNumber(raw.liquidation_price ?? raw.liquidationPrice);
  const positionSynced = raw.position_synced !== undefined ? Boolean(raw.position_synced) : undefined;
  const liveMetricsAvailable = raw.live_metrics_available !== undefined ? Boolean(raw.live_metrics_available) : undefined;
  const closeAllowed = raw.close_allowed === true;

  const status = getLifecycleStatus(raw.status);
  const { slVerified, tpVerified } = getProtectionVerification(raw);

  const timestamp = raw.opened_at || raw.openedAt || raw.detected_at || raw.detectedAt || raw.closed_at || raw.closedAt || null;
  const closedAt = raw.closed_at || raw.closedAt || null;

  return {
    id: String(raw.order_id || raw.orderId || raw.journal_id || raw.journalId || `${raw.symbol || raw.pair || 'unknown'}-${index}`),
    pair: String(raw.symbol || raw.pair || "unknown"),
    strategy: String(raw.strategy_name || raw.strategy || exchangeMetadata.strategy_name || exchangeMetadata.strategy || "unknown"),
    direction,
    entryPrice,
    currentPrice: status === "CLOSED" && exitPrice !== null ? exitPrice : (markPrice !== null ? markPrice : entryPrice),
    stopLoss,
    takeProfit,
    size,
    margin,
    leverage,
    unrealizedPnl,
    pnlPercent,
    status,
    timestamp,
    orderConfirmed: Boolean(raw.order_id || raw.orderId),
    slVerified: slVerified ?? undefined,
    tpVerified: tpVerified ?? undefined,
    positionSynced,
    isUnsafe: !closeAllowed,
    orderId: raw.order_id || raw.orderId,
    rawStatus: raw.status,
    journalId: raw.journal_id || raw.journalId,
    executionMode: raw.execution_mode ?? raw.executionMode ?? null,
    result: rawResult === "TP" ? "TP" : rawResult === "SL" ? "SL" : "UNKNOWN",
    closedAt,
    slHitReason: raw.sl_hit_reason ?? null,
    exitPrice,
    realizedPnl,
    fees,
    closeReason: raw.close_reason ?? null,
    managementTp1: parseNullableNumber(management.tp1) ?? undefined,
    managementTp2: parseNullableNumber(management.tp2) ?? undefined,
    managementRunner: parseNullableNumber(management.runner_target) ?? undefined,
    breakEvenSet: Boolean(management.break_even_set),
    tp1Done: Boolean(management.tp1_done),
    tp2Done: Boolean(management.tp2_done),
    liveMetricsAvailable,
    closeAllowed,
    closeBlockedReason: raw.close_blocked_reason ?? null,
    liquidationPrice,
    positionValue,
  };
}

export function normalizeTradeHistoryEntry(trade: Trade): TradeHistoryEntry {
  const pnlValue = trade.realizedPnl;
  let outcome: 'PROFIT' | 'LOSS' | 'FLAT' | 'UNKNOWN' = 'UNKNOWN';
  if (pnlValue !== null) {
    if (pnlValue > 0) outcome = 'PROFIT';
    else if (pnlValue < 0) outcome = 'LOSS';
    else if (trade.status === 'CLOSED') outcome = 'FLAT';
  } else {
    if (trade.result === "TP") outcome = "PROFIT";
    else if (trade.result === "SL") outcome = "LOSS";
    else outcome = "UNKNOWN";
  }

  return {
    ...trade,
    exitPrice: trade.exitPrice ?? null,
    pnl: pnlValue,
    result: outcome,
    reason: trade.closeReason || trade.slHitReason || "n/a",
    closedAt: trade.closedAt || trade.timestamp,
  };
}
