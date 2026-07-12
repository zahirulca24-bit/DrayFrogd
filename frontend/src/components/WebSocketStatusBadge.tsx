import { useEffect, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

type Channel = {
  state?: string;
  connected?: boolean;
  authenticated?: boolean;
  last_message_at?: string | null;
  last_health_check_at?: string | null;
  reconnect_count?: number;
  endpoint?: string | null;
  error?: string | null;
};

type Status = {
  running?: boolean;
  private?: Channel;
  public?: Channel;
};

function label(channel: Channel | undefined, privateStream = false) {
  if (!channel) return "WAITING";
  if (channel.connected && (!privateStream || channel.authenticated)) {
    return "CONNECTED";
  }
  return String(channel.state || "OFFLINE").toUpperCase();
}

function channelTitle(name: string, channel: Channel | undefined) {
  const parts = [name];
  if (channel?.endpoint) parts.push(`Endpoint: ${channel.endpoint}`);
  if (channel?.last_message_at) {
    parts.push(`Last message: ${channel.last_message_at}`);
  }
  if (channel?.last_health_check_at) {
    parts.push(`Last health check: ${channel.last_health_check_at}`);
  }
  if (channel?.error) parts.push(`Error: ${channel.error}`);
  return parts.join("\n");
}

function retrySuffix(channel: Channel | undefined) {
  const count = Number(channel?.reconnect_count || 0);
  return count > 0 ? ` · RETRY ${count}` : "";
}

export default function WebSocketStatusBadge() {
  const [status, setStatus] = useState<Status | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const token = localStorage.getItem("scalp_token");
      if (!token) {
        setStatus(null);
        return;
      }
      try {
        const response = await fetch(`${API_BASE_URL}/websocket/status`, {
          headers: {
            Authorization: `Bearer ${token}`,
            Accept: "application/json",
          },
        });
        if (!response.ok) return;
        const payload = (await response.json()) as Status;
        if (!cancelled) setStatus(payload);
      } catch {
        if (!cancelled) setStatus({ running: false });
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  if (!status) return null;
  const privateOk = Boolean(
    status.private?.connected && status.private?.authenticated,
  );
  const publicOk = Boolean(status.public?.connected);
  const errors = [
    status.private?.error ? `PRIVATE: ${status.private.error}` : null,
    status.public?.error ? `PUBLIC: ${status.public.error}` : null,
  ].filter((item): item is string => Boolean(item));

  return (
    <div
      style={{
        position: "fixed",
        right: 18,
        bottom: 18,
        zIndex: 80,
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-end",
        gap: 8,
      }}
    >
      {errors.length > 0 && (
        <div
          role="status"
          style={{
            maxWidth: 720,
            padding: "8px 10px",
            borderRadius: 8,
            background: "rgba(73,42,42,.96)",
            color: "#fff",
            fontSize: 11,
            lineHeight: 1.4,
            border: "1px solid rgba(255,255,255,.18)",
            boxShadow: "0 8px 24px rgba(0,0,0,.35)",
            whiteSpace: "pre-wrap",
            overflowWrap: "anywhere",
          }}
        >
          {errors.join("\n")}
        </div>
      )}
      <div style={{ display: "flex", gap: 8 }}>
        <span
          title={channelTitle("Private account stream", status.private)}
          style={{
            padding: "7px 10px",
            borderRadius: 999,
            background: privateOk ? "#123f31" : "#492a2a",
            color: "#fff",
            fontSize: 11,
            fontWeight: 700,
            border: "1px solid rgba(255,255,255,.15)",
          }}
        >
          PRIVATE WS · {label(status.private, true)}
          {retrySuffix(status.private)}
        </span>
        <span
          title={channelTitle("Public market stream", status.public)}
          style={{
            padding: "7px 10px",
            borderRadius: 999,
            background: publicOk ? "#123f31" : "#492a2a",
            color: "#fff",
            fontSize: 11,
            fontWeight: 700,
            border: "1px solid rgba(255,255,255,.15)",
          }}
        >
          PUBLIC WS · {label(status.public)}
          {retrySuffix(status.public)}
        </span>
      </div>
    </div>
  );
}
