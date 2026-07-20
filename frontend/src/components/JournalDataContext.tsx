import React, { createContext, useContext, useState, useEffect, useRef, useCallback } from "react";
import { api } from "../api";
import { JournalTradeEntry, LedgerAuditResponse, StrategyAuditResponse } from "../types";

export type JournalSyncState = "idle" | "syncing" | "error" | "retrying";

export interface JournalSyncMetadata {
  autoSyncEnabled: boolean;
  intervalMs: number;
  lastSuccess: Date | null;
  state: JournalSyncState;
  error: string | null;
  isStale: boolean;
  retryCount: number;
}

interface JournalDataContextType {
  journalTrades: JournalTradeEntry[];
  ledgerAudit: LedgerAuditResponse | null;
  strategyAudit: StrategyAuditResponse | null;
  metadata: JournalSyncMetadata;
  refresh: (force?: boolean) => Promise<void>;
}

const JournalDataContext = createContext<JournalDataContextType | undefined>(undefined);

const BDT_DATE = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Dhaka",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const DEFAULT_POLL_INTERVAL_MS = 10000;
const STALE_THRESHOLD_MS = 25000;

export const JournalDataProvider: React.FC<{
  authToken: string | null;
  activeTab: string;
  children: React.ReactNode;
}> = ({ authToken, activeTab, children }) => {
  const [journalTrades, setJournalTrades] = useState<JournalTradeEntry[]>([]);
  const [ledgerAudit, setLedgerAudit] = useState<LedgerAuditResponse | null>(null);
  const [strategyAudit, setStrategyAudit] = useState<StrategyAuditResponse | null>(null);

  const [state, setState] = useState<JournalSyncState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [lastSuccess, setLastSuccess] = useState<Date | null>(null);
  const [isStale, setIsStale] = useState<boolean>(false);
  const [retryCount, setRetryCount] = useState<number>(0);

  const activeTabRef = useRef(activeTab);
  const authTokenRef = useRef(authToken);
  const timeoutIdRef = useRef<NodeJS.Timeout | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const isRefreshingRef = useRef(false);

  // Keep references fresh
  useEffect(() => {
    activeTabRef.current = activeTab;
  }, [activeTab]);

  useEffect(() => {
    authTokenRef.current = authToken;
  }, [authToken]);

  // Is sync tab active?
  const isJournalTabActive = activeTab === "journal" || activeTab === "performance-strategy";

  // Check staleness
  useEffect(() => {
    const checkStale = () => {
      if (!lastSuccess) {
        setIsStale(true);
      } else {
        setIsStale(Date.now() - lastSuccess.getTime() > STALE_THRESHOLD_MS);
      }
    };
    checkStale();
    const interval = setInterval(checkStale, 2000);
    return () => clearInterval(interval);
  }, [lastSuccess]);

  const clearTimer = () => {
    if (timeoutIdRef.current) {
      clearTimeout(timeoutIdRef.current);
      timeoutIdRef.current = null;
    }
  };

  const cancelInFlight = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  };

  // Authoritative fetch logic
  const fetchOnce = useCallback(async (token: string, signal: AbortSignal) => {
    const todayBdt = BDT_DATE.format(new Date());

    const [journalRes, ledgerRes, strategyRes] = await Promise.all([
      api.getJournalTrades(token, { signal }),
      api.getLedgerAudit(token, undefined, { signal }),
      api.getStrategyAudit(token, todayBdt, { signal }),
    ]);

    return { journalRes, ledgerRes, strategyRes };
  }, []);

  const performSync = useCallback(async (force = false) => {
    const token = authTokenRef.current;
    if (!token) return;

    if (isRefreshingRef.current && !force) {
      return;
    }

    clearTimer();
    cancelInFlight();

    isRefreshingRef.current = true;
    setState("syncing");

    const controller = new AbortController();
    abortControllerRef.current = controller;

    let success = false;
    let attempt = 0;
    const maxRetries = 3;
    const delays = [1000, 2000, 4000];
    let latestErr: any = null;

    while (attempt <= maxRetries && !controller.signal.aborted) {
      if (attempt > 0) {
        setState("retrying");
        setRetryCount(attempt);
        // wait before next retry
        await new Promise((resolve) => {
          const tid = setTimeout(resolve, delays[attempt - 1]);
          controller.signal.addEventListener("abort", () => clearTimeout(tid));
        });
        if (controller.signal.aborted) break;
      }

      try {
        const data = await fetchOnce(token, controller.signal);
        if (!controller.signal.aborted) {
          setJournalTrades(data.journalRes.trades || []);
          setLedgerAudit(data.ledgerRes);
          setStrategyAudit(data.strategyRes);
          setLastSuccess(new Date());
          setError(null);
          setState("idle");
          setRetryCount(0);
          success = true;
          break;
        }
      } catch (err: any) {
        if (err?.name === "AbortError") {
          // Request was deliberately aborted, ignore error
          isRefreshingRef.current = false;
          return;
        }
        latestErr = err;
        attempt++;
      }
    }

    if (controller.signal.aborted) {
      isRefreshingRef.current = false;
      return;
    }

    if (!success) {
      // Failed all retries or single attempt, preserve old data
      const errMsg = latestErr?.message || "Transient sync failure.";
      setError(errMsg);
      setState("error");
      setRetryCount(0);
    }

    isRefreshingRef.current = false;

    // Reschedule next regular poll only if we are still active
    if (authTokenRef.current && (activeTabRef.current === "journal" || activeTabRef.current === "performance-strategy")) {
      timeoutIdRef.current = setTimeout(() => {
        void performSync();
      }, DEFAULT_POLL_INTERVAL_MS);
    }
  }, [fetchOnce]);

  // Main coordinator effect
  useEffect(() => {
    if (!authToken) {
      setJournalTrades([]);
      setLedgerAudit(null);
      setStrategyAudit(null);
      setError(null);
      setState("idle");
      setLastSuccess(null);
      clearTimer();
      cancelInFlight();
      return;
    }

    if (isJournalTabActive) {
      // Trigger immediate refresh on tab change/mount
      void performSync(true);
    } else {
      // Pause polling/cancel in-flight if tab changes away
      clearTimer();
      cancelInFlight();
      setState("idle");
    }

    return () => {
      clearTimer();
      cancelInFlight();
    };
  }, [authToken, isJournalTabActive, performSync]);

  // Immediate sync on tab visibility visible
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible" && authTokenRef.current && (activeTabRef.current === "journal" || activeTabRef.current === "performance-strategy")) {
        void performSync(true);
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [performSync]);

  const metadata: JournalSyncMetadata = {
    autoSyncEnabled: isJournalTabActive,
    intervalMs: DEFAULT_POLL_INTERVAL_MS,
    lastSuccess,
    state,
    error,
    isStale,
    retryCount,
  };

  return (
    <JournalDataContext.Provider
      value={{
        journalTrades,
        ledgerAudit,
        strategyAudit,
        metadata,
        refresh: (force = true) => performSync(force),
      }}
    >
      {children}
    </JournalDataContext.Provider>
  );
};

export const useJournalData = () => {
  const context = useContext(JournalDataContext);
  if (context === undefined) {
    throw new Error("useJournalData must be used within a JournalDataProvider");
  }
  return context;
};
