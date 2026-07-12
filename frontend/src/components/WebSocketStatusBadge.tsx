import { useEffect, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

type Channel = {
  state?: string;
  connected?: boolean;
  authenticated?: boolean;
  last_message_at?: string | null;
  error?: string | null;
};

type Status = {
  running?: boolean;
  private?: Channel;
  public?: Channel;
};

function label(channel: Channel | undefined, privateStream = false) {
  if (!channel) return "WAITING";
  if (channel.connected && (!privateStream || channel.authenticated)) return "CONNECTED";
  return String(channel.state || "OFFLINE").toUpperCase();
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
          headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
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
  const privateOk = Boolean(status.private?.connected && status.private?.authenticated);
  const publicOk = Boolean(status.public?.connected);

  return (
    <div style={{ position: "fixed", right: 18, bottom: 18, zIndex: 80, display: "flex", gap: 8 }}>
      <span title={status.private?.error || status.private?.last_message_at || "Private account stream"}
        style={{ padding: "7px 10px", borderRadius: 999, background: privateOk ? "#123f31" : "#492a2a", color: "#fff", fontSize: 11, fontWeight: 700, border: "1px solid rgba(255,255,255,.15)" }}>
        PRIVATE WS · {label(status.private, true)}
      </span>
      <span title={status.public?.error || status.public?.last_message_at || "Public market stream"}
        style={{ padding: "7px 10px", borderRadius: 999, background: publicOk ? "#123f31" : "#492a2a", color: "#fff", fontSize: 11, fontWeight: 700, border: "1px solid rgba(255,255,255,.15)" }}>
        PUBLIC WS · {label(status.public)}
      </span>
    </div>
  );
}
