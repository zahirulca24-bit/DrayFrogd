import { describe, expect, it } from "vitest";
import { normalizeTrade, normalizeTradeHistoryEntry } from "../tradeTruth";
import { Trade } from "../types";

describe("Authoritative Trade Normalizer Tests", () => {
  // Helper to construct a base minimal raw trade
  const baseRaw = () => ({
    symbol: "BTCUSDT",
    entry: 50000,
    stop_loss: 49000,
    take_profit: 52000,
    quantity: 0.1,
    status: "active",
  });

  // 1. Missing financial values remain null.
  it("1. should keep missing financial values as null", () => {
    const raw = {
      ...baseRaw(),
      position_margin: null,
      leverage: null,
      unrealized_pnl: undefined,
      pnl_percent: "",
      position_value: null,
      liquidation_price: undefined,
      exit_price: null,
      realized_pnl: undefined,
      fees: null,
    };
    const trade = normalizeTrade(raw, 0);

    expect(trade.margin).toBeNull();
    expect(trade.leverage).toBeNull();
    expect(trade.unrealizedPnl).toBeNull();
    expect(trade.pnlPercent).toBeNull();
    expect(trade.positionValue).toBeNull();
    expect(trade.liquidationPrice).toBeNull();
    expect(trade.exitPrice).toBeNull();
    expect(trade.realizedPnl).toBeNull();
    expect(trade.fees).toBeNull();
  });

  // 2. A legitimate numeric zero remains zero.
  it("2. should keep legitimate numeric zeros as zero", () => {
    const raw = {
      ...baseRaw(),
      position_margin: 0,
      leverage: 0,
      unrealized_pnl: 0,
      pnl_percent: 0,
      position_value: 0,
      liquidation_price: 0,
      exit_price: 0,
      realized_pnl: 0,
      fees: 0,
    };
    const trade = normalizeTrade(raw, 0);

    expect(trade.margin).toBe(0);
    expect(trade.leverage).toBe(0);
    expect(trade.unrealizedPnl).toBe(0);
    expect(trade.pnlPercent).toBe(0);
    expect(trade.positionValue).toBe(0);
    expect(trade.liquidationPrice).toBe(0);
    expect(trade.exitPrice).toBe(0);
    expect(trade.realizedPnl).toBe(0);
    expect(trade.fees).toBe(0);
  });

  // 3. Missing execution mode does not become "demo".
  it("3. should not default missing execution mode to 'demo'", () => {
    const raw = {
      ...baseRaw(),
      execution_mode: undefined,
    };
    const trade = normalizeTrade(raw, 0);
    expect(trade.executionMode).toBeNull();
  });

  // 4. Unknown status does not become "OPEN".
  it("4. should not classify unknown/unsupported status as OPEN", () => {
    const raw = {
      ...baseRaw(),
      status: "random_status_123",
    };
    const trade = normalizeTrade(raw, 0);
    expect(trade.status).not.toBe("OPEN");
    expect(trade.status).toBe("UNKNOWN");
  });

  // 5. active is classified correctly.
  it("5. should classify 'active' status as OPEN", () => {
    const raw = {
      ...baseRaw(),
      status: "active",
    };
    const trade = normalizeTrade(raw, 0);
    expect(trade.status).toBe("OPEN");
  });

  // 6. closed is classified correctly.
  it("6. should classify 'closed' status as CLOSED", () => {
    const raw = {
      ...baseRaw(),
      status: "closed",
    };
    const trade = normalizeTrade(raw, 0);
    expect(trade.status).toBe("CLOSED");
  });

  // 7. protection_pending is not protected.
  it("7. should ensure 'protection_pending' is represented as unverified", () => {
    const raw = {
      ...baseRaw(),
      status: "protection_pending",
    };
    const trade = normalizeTrade(raw, 0);
    expect(trade.slVerified).toBe(false);
    expect(trade.tpVerified).toBe(false);
  });

  // 8. execution_uncertain is not shown as a normal protected open trade.
  it("8. should classify 'execution_uncertain' as ATTENTION and unverified/unprotected", () => {
    const raw = {
      ...baseRaw(),
      status: "execution_uncertain",
    };
    const trade = normalizeTrade(raw, 0);
    expect(trade.status).toBe("ATTENTION");
    expect(trade.slVerified).toBe(false);
    expect(trade.tpVerified).toBe(false);
  });

  // 9. emergency_close_failed is visibly unsafe.
  it("9. should represent 'emergency_close_failed' as ATTENTION status", () => {
    const raw = {
      ...baseRaw(),
      status: "emergency_close_failed",
    };
    const trade = normalizeTrade(raw, 0);
    expect(trade.status).toBe("ATTENTION");
  });

  // 10. close_pending_sync is not classified as a normal open trade.
  it("10. should ensure 'close_pending_sync' status is PENDING/ATTENTION rather than OPEN", () => {
    const raw = {
      ...baseRaw(),
      status: "close_pending_sync",
    };
    const trade = normalizeTrade(raw, 0);
    expect(trade.status).toBe("ATTENTION");
  });

  // 11. Active trade without explicit protection evidence remains unverified/unknown.
  it("11. should keep active trade unverified/unknown without explicit protection evidence", () => {
    const raw = {
      ...baseRaw(),
      status: "active",
      exchange_metadata: {},
    };
    const trade = normalizeTrade(raw, 0);
    expect(trade.slVerified).toBeUndefined(); // mapped to undefined for UI (representing null/unknown)
    expect(trade.tpVerified).toBeUndefined();
  });

  // 12. Explicit verified protection evidence is represented correctly.
  it("12. should represent verified protection when explicit metadata is provided", () => {
    const raw = {
      ...baseRaw(),
      status: "active",
      exchange_metadata: {
        protection_attached: true,
        protection_attached_at: "2023-10-01T12:00:00Z",
      },
    };
    const trade = normalizeTrade(raw, 0);
    expect(trade.slVerified).toBe(true);
    expect(trade.tpVerified).toBe(true);
  });

  // 13. Closed trade without realized PnL remains financially unknown.
  it("13. should keep closed trade financially unknown if realized PnL is missing", () => {
    const raw = {
      ...baseRaw(),
      status: "closed",
      realized_pnl: null,
      result: null,
    };
    const trade = normalizeTrade(raw, 0);
    const historyEntry = normalizeTradeHistoryEntry(trade);

    expect(historyEntry.pnl).toBeNull();
    expect(historyEntry.result).toBe("UNKNOWN");
  });

  // 14. Missing timestamps are not replaced with the current time.
  it("14. should not replace missing timestamps with current time", () => {
    const raw = {
      ...baseRaw(),
      opened_at: null,
      detected_at: null,
      closed_at: null,
    };
    const trade = normalizeTrade(raw, 0);
    expect(trade.timestamp).toBeNull();
    expect(trade.closedAt).toBeNull();
  });

  // 15. Aggregates exclude unknown values instead of counting them as zero.
  it("15. should correctly exclude unknown values from aggregates", () => {
    const trades: Trade[] = [
      normalizeTrade({ ...baseRaw(), realized_pnl: 100, status: "closed" }, 1),
      normalizeTrade({ ...baseRaw(), realized_pnl: null, status: "closed" }, 2),
      normalizeTrade({ ...baseRaw(), realized_pnl: -50, status: "closed" }, 3),
      normalizeTrade({ ...baseRaw(), realized_pnl: undefined, status: "closed" }, 4),
    ];

    const validPnlTrades = trades.filter((t) => t.realizedPnl !== null);
    const sumPnl = validPnlTrades.reduce((sum, t) => sum + (t.realizedPnl ?? 0), 0);

    expect(validPnlTrades.length).toBe(2);
    expect(sumPnl).toBe(50);
  });
});
