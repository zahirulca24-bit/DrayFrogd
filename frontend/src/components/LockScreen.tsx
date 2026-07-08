import React, { useEffect, useState } from "react";
import { Lock, Eye, EyeOff, ShieldAlert, ArrowRight, Bot, User } from "lucide-react";


interface LockScreenProps {
  onUnlock: (username: string, password: string) => Promise<void>;
}


export default function LockScreen({ onUnlock }: LockScreenProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    document.title = "DayFrogd-ScalpingEngin | Login";
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) {
      setError("Username and password are required");
      return;
    }

    setLoading(true);
    setError("");

    try {
      await onUnlock(username, password);
    } catch (err: any) {
      setError(err?.message || "Authentication failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col justify-center items-center p-4 selection:bg-rose-500 selection:text-white" id="lock-screen-container">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(244,63,94,0.08)_0%,transparent_60%)] pointer-events-none" />

      <div className="w-full max-w-md" id="lock-card-wrapper">
        <div className="text-center mb-8" id="lock-brand-header">
          <div className="inline-flex items-center justify-center p-3 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl mb-4" id="lock-logo-container">
            <Bot className="w-10 h-10 text-rose-500 animate-pulse" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-white font-sans">DayFrogd-ScalpingEngin</h1>
          <p className="text-xs text-slate-500 mt-1 font-mono uppercase tracking-widest">FastAPI Demo Control Terminal</p>
        </div>

        <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-800 rounded-2xl p-6 shadow-2xl relative overflow-hidden" id="lock-card">
          <div className="absolute top-0 inset-x-0 h-px bg-gradient-to-r from-transparent via-rose-500/50 to-transparent" />

          <div className="flex items-center space-x-3 mb-6" id="lock-title-section">
            <div className="p-2 bg-rose-500/10 text-rose-400 rounded-lg">
              <Lock className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-white">Security Verification</h2>
              <p className="text-xs text-slate-400">Restricted algorithm access</p>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4" id="lock-form">
            <div>
              <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider mb-2 font-mono">
                Username
              </label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                <input
                  id="username-input"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Admin username"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-10 pr-4 py-3 text-slate-200 placeholder-slate-700 text-sm focus:outline-none focus:border-rose-500/50 focus:ring-1 focus:ring-rose-500/30 transition-all font-mono"
                  disabled={loading}
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider mb-2 font-mono">
                Password
              </label>
              <div className="relative">
                <input
                  id="password-input"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter password"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-slate-200 placeholder-slate-700 text-sm focus:outline-none focus:border-rose-500/50 focus:ring-1 focus:ring-rose-500/30 transition-all font-mono"
                  disabled={loading}
                />
                <button
                  id="toggle-password-btn"
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {error && (
              <div className="flex items-start space-x-2 bg-rose-500/10 border border-rose-500/20 rounded-xl p-3 text-xs text-rose-400 font-mono" id="lock-error-msg">
                <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            <button
              id="unlock-submit-btn"
              type="submit"
              disabled={loading}
              className="w-full bg-gradient-to-r from-rose-600 to-rose-500 hover:from-rose-500 hover:to-rose-400 text-white font-medium text-sm py-3 px-4 rounded-xl transition-all shadow-lg shadow-rose-950/40 hover:shadow-rose-900/40 flex items-center justify-center space-x-2 disabled:opacity-50 disabled:cursor-not-allowed group cursor-pointer"
            >
              <span>{loading ? "Signing in..." : "Initialize Session"}</span>
              {!loading && <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />}
            </button>
          </form>

          <div className="mt-6 pt-4 border-t border-slate-800/60 text-center" id="lock-hint-container">
            <p className="text-xs text-slate-500">Use your backend-configured admin username and password.</p>
          </div>
        </div>

        <p className="text-center text-[10px] text-slate-600 mt-8 font-mono">DAYFROGD-SCALPINGENGIN SESSION AUTH</p>
      </div>
    </div>
  );
}
