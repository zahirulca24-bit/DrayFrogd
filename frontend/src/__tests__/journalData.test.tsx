// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import React, { act } from "react";
import { render, screen, cleanup } from "@testing-library/react";
import { JournalDataProvider, useJournalData } from "../components/JournalDataContext";
import { api } from "../api";

vi.mock("../api", () => {
  return {
    api: {
      getJournalTrades: vi.fn(),
      getLedgerAudit: vi.fn(),
      getStrategyAudit: vi.fn(),
    },
    ApiError: class ApiError extends Error {
      status: number;
      constructor(message: string, status: number) {
        super(message);
        this.status = status;
      }
    },
  };
});

const ConsumerComponent: React.FC = () => {
  const { journalTrades, metadata, refresh } = useJournalData();
  return (
    <div>
      <div data-testid="state">{metadata.state}</div>
      <div data-testid="trade-count">{journalTrades.length}</div>
      <div data-testid="is-stale">{metadata.isStale ? "stale" : "fresh"}</div>
      <div data-testid="error">{metadata.error || "no-error"}</div>
      <div data-testid="last-success">
        {metadata.lastSuccess ? metadata.lastSuccess.toISOString() : "never"}
      </div>
      <button data-testid="refresh-btn" onClick={() => void refresh(true)}>
        Refresh
      </button>
    </div>
  );
};

describe("JournalDataContext & Provider Tests", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.resetAllMocks();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("should sync automatically and handle successful responses", async () => {
    vi.mocked(api.getJournalTrades).mockResolvedValue({ trades: [{ journal_id: "1", status: "active" } as any] });
    vi.mocked(api.getLedgerAudit).mockResolvedValue({ records: [], summary: {} } as any);
    vi.mocked(api.getStrategyAudit).mockResolvedValue({ ok: true, strategies: [], trades: [] } as any);

    render(
      <JournalDataProvider authToken="test-token" activeTab="journal">
        <ConsumerComponent />
      </JournalDataProvider>
    );

    // Initial load starts immediately
    expect(screen.getByTestId("state").textContent).toBe("syncing");

    await act(async () => {
      // Allow the immediate fetch promise to resolve
      await vi.advanceTimersByTimeAsync(1);
    });

    expect(screen.getByTestId("state").textContent).toBe("idle");
    expect(screen.getByTestId("trade-count").textContent).toBe("1");
    expect(screen.getByTestId("error").textContent).toBe("no-error");
    expect(screen.getByTestId("last-success").textContent).not.toBe("never");
  });

  it("should preserve last successful data and continue polling after a transient failure", async () => {
    // 1. Success first
    vi.mocked(api.getJournalTrades).mockResolvedValueOnce({ trades: [{ journal_id: "1", status: "active" } as any] });
    vi.mocked(api.getLedgerAudit).mockResolvedValueOnce({ records: [], summary: {} } as any);
    vi.mocked(api.getStrategyAudit).mockResolvedValueOnce({ ok: true, strategies: [], trades: [] } as any);

    render(
      <JournalDataProvider authToken="test-token" activeTab="journal">
        <ConsumerComponent />
      </JournalDataProvider>
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });

    expect(screen.getByTestId("trade-count").textContent).toBe("1");
    expect(screen.getByTestId("error").textContent).toBe("no-error");

    // 2. Failure on next poll
    vi.mocked(api.getJournalTrades).mockRejectedValue(new Error("Network Error"));
    vi.mocked(api.getLedgerAudit).mockRejectedValue(new Error("Network Error"));
    vi.mocked(api.getStrategyAudit).mockRejectedValue(new Error("Network Error"));

    // Trigger next regular poll after 10 seconds
    await act(async () => {
      vi.advanceTimersByTime(10000);
    });

    // Resolve the retry attempts (exponential backoff: 1s, 2s, 4s)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8000);
    });

    // It should now end up in the error state
    expect(screen.getByTestId("state").textContent).toBe("error");
    expect(screen.getByTestId("error").textContent).toBe("Network Error");
    // Verify it preserved the last successful data!
    expect(screen.getByTestId("trade-count").textContent).toBe("1");

    // 3. Next normal poll interval succeeds again
    vi.mocked(api.getJournalTrades).mockResolvedValue({ trades: [{ journal_id: "1", status: "active" }, { journal_id: "2", status: "closed" }] as any });
    vi.mocked(api.getLedgerAudit).mockResolvedValue({ records: [], summary: {} } as any);
    vi.mocked(api.getStrategyAudit).mockResolvedValue({ ok: true, strategies: [], trades: [] } as any);

    await act(async () => {
      vi.advanceTimersByTime(10000);
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });

    expect(screen.getByTestId("state").textContent).toBe("idle");
    expect(screen.getByTestId("trade-count").textContent).toBe("2");
    expect(screen.getByTestId("error").textContent).toBe("no-error");
  });

  it("should trigger immediate fresh sync when browser tab visibility becomes visible", async () => {
    // Return a delayed promise so we can catch the syncing state
    vi.mocked(api.getJournalTrades).mockImplementation(() => new Promise((r) => setTimeout(() => r({ trades: [] }), 500)));
    vi.mocked(api.getLedgerAudit).mockImplementation(() => new Promise((r) => setTimeout(() => r({ records: [], summary: {} } as any), 500)));
    vi.mocked(api.getStrategyAudit).mockImplementation(() => new Promise((r) => setTimeout(() => r({ ok: true, strategies: [], trades: [] } as any), 500)));

    const visibilitySpy = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");

    render(
      <JournalDataProvider authToken="test-token" activeTab="journal">
        <ConsumerComponent />
      </JournalDataProvider>
    );

    // Initial load starts immediately, wait for it to resolve
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    // Make sure we are in idle
    expect(screen.getByTestId("state").textContent).toBe("idle");

    // Change visibility to visible
    visibilitySpy.mockReturnValue("visible");

    // Check if a simple listener on document receives it
    const fn = vi.fn();
    document.addEventListener("visibilitychange", fn);

    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(fn).toHaveBeenCalled();

    // Should immediately sync (fetch has started, but promise hasn't resolved yet)
    expect(screen.getByTestId("state").textContent).toBe("syncing");

    // Let the promise resolve by advancing time
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(screen.getByTestId("state").textContent).toBe("idle");
  });

  it("should abort previous in-flight request when a newer refresh/sync starts", async () => {
    vi.mocked(api.getJournalTrades).mockResolvedValue({ trades: [] });
    vi.mocked(api.getLedgerAudit).mockResolvedValue({ records: [], summary: {} } as any);
    vi.mocked(api.getStrategyAudit).mockResolvedValue({ ok: true, strategies: [], trades: [] } as any);

    const { getByTestId } = render(
      <JournalDataProvider authToken="test-token" activeTab="journal">
        <ConsumerComponent />
      </JournalDataProvider>
    );

    // Initial sync is running
    expect(getByTestId("state").textContent).toBe("syncing");

    // Trigger a force sync (clicks refresh button)
    await act(async () => {
      getByTestId("refresh-btn").click();
    });

    // Verify first requests were aborted/called with AbortSignal
    const calls = vi.mocked(api.getJournalTrades).mock.calls;
    expect(calls.length).toBeGreaterThan(1);
    expect(calls[0][1]?.signal).toBeDefined();
    expect(calls[0][1]?.signal?.aborted).toBe(true);
  });
});
