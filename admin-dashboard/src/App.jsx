import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  ShieldAlert, Activity, Search,
  Settings, LogOut, Clock, Download, RefreshCw,
  ClipboardList, CheckCircle, XCircle, Bell, User
} from 'lucide-react';

const API = "http://localhost:8000";

// ── Auth helpers ──────────────────────────────────────────────────────────────

function getToken() { return localStorage.getItem("fg_token"); }
function setToken(t) { localStorage.setItem("fg_token", t); }
function clearToken() { localStorage.removeItem("fg_token"); }

function authHeaders(extra = {}) {
  return { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}`, ...extra };
}

function decodeUsername(token) {
  try {
    return JSON.parse(atob(token.split('.')[1])).sub || "Officer";
  } catch { return "Officer"; }
}

// ── Login Page ────────────────────────────────────────────────────────────────

function LoginPage({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError]       = useState("");
  const [loading, setLoading]   = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true); setError("");
    try {
      const res = await fetch(`${API}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) { setError("Invalid credentials. Please try again."); return; }
      const data = await res.json();
      setToken(data.access_token);
      onLogin();
    } catch {
      setError("Cannot reach server. Ensure the backend is running.");
    } finally { setLoading(false); }
  }

  return (
    <div className="min-h-screen bg-[#0f1115] flex items-center justify-center">
      <div className="bg-[#161920] border border-[#2a2e39] rounded-2xl p-10 w-full max-w-md shadow-2xl">
        <div className="flex items-center gap-3 text-red-500 font-bold text-2xl mb-8">
          <ShieldAlert size={32} />
          <span>FraudGuard AI</span>
        </div>
        <h2 className="text-white text-xl font-bold mb-1">Compliance Login</h2>
        <p className="text-gray-500 text-sm mb-8">Fraud Monitoring Dashboard — Authorised Personnel Only</p>
        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="text-gray-400 text-sm font-semibold block mb-2">Username</label>
            <input
              type="text" value={username} onChange={e => setUsername(e.target.value)} required
              autoComplete="username"
              className="w-full bg-[#0f1115] border border-[#2a2e39] rounded-lg px-4 py-3 text-white focus:outline-none focus:border-red-500/50 transition-all"
            />
          </div>
          <div>
            <label className="text-gray-400 text-sm font-semibold block mb-2">Password</label>
            <input
              type="password" value={password} onChange={e => setPassword(e.target.value)} required
              autoComplete="current-password"
              className="w-full bg-[#0f1115] border border-[#2a2e39] rounded-lg px-4 py-3 text-white focus:outline-none focus:border-red-500/50 transition-all"
            />
          </div>
          {error && <p className="text-red-400 text-sm font-semibold">{error}</p>}
          <button
            type="submit" disabled={loading}
            className="w-full bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-bold py-3 rounded-lg transition-all"
          >
            {loading ? "Authenticating…" : "Sign In"}
          </button>
        </form>
        <p className="text-gray-700 text-xs mt-6 text-center">
          Access restricted to authorised compliance officers only.
        </p>
      </div>
    </div>
  );
}

// ── Risk badge ────────────────────────────────────────────────────────────────

function RiskBadge({ level }) {
  const styles = {
    HIGH:   "bg-red-500/10 text-red-500 border border-red-500/20",
    MEDIUM: "bg-yellow-500/10 text-yellow-500 border border-yellow-500/20",
    LOW:    "bg-emerald-500/10 text-emerald-500 border border-emerald-500/20",
  };
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-black tracking-widest ${styles[level] || styles.LOW}`}>
      {level}
    </span>
  );
}

// ── Toast notification ────────────────────────────────────────────────────────

function Toast({ message, type, onDismiss }) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 5000);
    return () => clearTimeout(t);
  }, [onDismiss]);

  const colors = {
    success: "bg-emerald-900/90 border-emerald-500/30 text-emerald-300",
    error:   "bg-red-900/90 border-red-500/30 text-red-300",
    info:    "bg-blue-900/90 border-blue-500/30 text-blue-300",
  };

  return (
    <div className={`fixed bottom-6 right-6 z-50 flex items-start gap-3 px-5 py-4 rounded-xl border shadow-2xl text-sm font-semibold max-w-sm backdrop-blur ${colors[type]}`}>
      <Bell size={16} className="mt-0.5 shrink-0" />
      <span>{message}</span>
      <button onClick={onDismiss} className="ml-2 opacity-50 hover:opacity-100 text-xs">✕</button>
    </div>
  );
}

function useToast() {
  const [toast, setToast] = useState(null);
  const show = useCallback((message, type = "info") => setToast({ message, type }), []);
  const dismiss = useCallback(() => setToast(null), []);
  return { toast, show, dismiss };
}

// ── Live Monitor Tab ──────────────────────────────────────────────────────────

function LiveMonitorTab() {
  const [alerts, setAlerts]       = useState([]);
  const [riskFilter, setRiskFilter] = useState("");
  const [search, setSearch]       = useState("");
  const [exporting, setExporting] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [secondsAgo, setSecondsAgo]   = useState(0);

  const fetchAlerts = useCallback(() => {
    const params = new URLSearchParams({ limit: 100 });
    if (riskFilter) params.append("risk_level", riskFilter);
    if (search)     params.append("search", search);
    fetch(`${API}/api/admin/alerts?${params}`, { headers: authHeaders() })
      .then(r => r.json())
      .then(data => { 
        if (Array.isArray(data)) {
          setAlerts(data); 
          setLastUpdated(Date.now()); 
          setSecondsAgo(0); 
        }
      })
      .catch(() => {});
  }, [riskFilter, search]);

  useEffect(() => {
    fetchAlerts();
    const poll = setInterval(fetchAlerts, 3000);
    return () => clearInterval(poll);
  }, [fetchAlerts]);

  // Tick seconds-ago counter
  useEffect(() => {
    const tick = setInterval(() => {
      if (lastUpdated) setSecondsAgo(Math.floor((Date.now() - lastUpdated) / 1000));
    }, 1000);
    return () => clearInterval(tick);
  }, [lastUpdated]);

  async function handleExport() {
    setExporting(true);
    const params = new URLSearchParams();
    if (riskFilter) params.append("risk_level", riskFilter);
    if (search)     params.append("search", search);
    try {
      const res  = await fetch(`${API}/api/admin/alerts/export?${params}`, { headers: authHeaders() });
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "fraud_alerts.csv"; a.click();
    } finally { setExporting(false); }
  }

  const safeAlerts = Array.isArray(alerts) ? alerts : [];
  const highCount  = safeAlerts.filter(a => a.riskLevel === "HIGH" || a.riskLevel === "MEDIUM").length;
  const avgLatency = safeAlerts.length
    ? (safeAlerts.reduce((s, a) => s + (a.latencyMs || 0), 0) / safeAlerts.length).toFixed(1)
    : 0;

  const staleness = secondsAgo > 10
    ? "text-red-400"
    : secondsAgo > 5 ? "text-yellow-400" : "text-emerald-400";

  return (
    <div>
      {/* Metrics */}
      <div className="grid grid-cols-3 gap-6 mb-8">
        {[
          { label: "TOTAL SCANNED",        value: alerts.length, color: "blue" },
          { label: "FLAGGED DETECTIONS",   value: highCount,     color: "red"  },
          { label: "AVG RESPONSE LATENCY", value: `${avgLatency}ms`, color: "emerald" },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-[#161920] border border-[#2a2e39] rounded-2xl p-6 transition-all">
            <h3 className="text-gray-400 font-semibold mb-1 text-sm tracking-wide">{label}</h3>
            <div className={`text-4xl font-bold ${color === "red" ? "text-red-400" : "text-white"}`}>{value}</div>
          </div>
        ))}
      </div>

      {/* Filters + Export */}
      <div className="flex items-center gap-4 mb-4">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
          <input
            value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search value or field…"
            className="w-full bg-[#0f1115] border border-[#2a2e39] rounded-lg py-2 pl-9 pr-4 text-sm text-white focus:outline-none focus:border-red-500/50"
          />
        </div>
        <select
          value={riskFilter} onChange={e => setRiskFilter(e.target.value)}
          className="bg-[#0f1115] border border-[#2a2e39] rounded-lg px-4 py-2 text-sm text-white focus:outline-none"
        >
          <option value="">All Risk Levels</option>
          <option value="HIGH">HIGH</option>
          <option value="MEDIUM">MEDIUM</option>
          <option value="LOW">LOW</option>
        </select>
        <button
          onClick={handleExport} disabled={exporting}
          className="flex items-center gap-2 bg-[#161920] border border-[#2a2e39] hover:border-emerald-500/40 text-gray-300 hover:text-emerald-400 px-4 py-2 rounded-lg text-sm font-semibold transition-all"
        >
          <Download size={15} /> {exporting ? "Exporting…" : "Export CSV"}
        </button>
      </div>

      {/* Table */}
      <div className="bg-[#161920] border border-[#2a2e39] rounded-2xl overflow-hidden">
        <div className="p-5 border-b border-[#2a2e39] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
            <h2 className="text-lg font-bold text-gray-100">Live Alert Feed</h2>
          </div>
          <span className={`text-xs font-semibold ${staleness}`}>
            {lastUpdated ? `Updated ${secondsAgo}s ago` : "Loading…"}
          </span>
        </div>
        <table className="w-full text-left">
          <thead className="text-xs bg-[#0f1115] text-gray-400 font-bold tracking-wider">
            <tr>
              <th className="px-6 py-4 uppercase">Value</th>
              <th className="px-6 py-4 uppercase">Field</th>
              <th className="px-6 py-4 uppercase">Risk</th>
              <th className="px-6 py-4 uppercase">Similarity</th>
              <th className="px-6 py-4 uppercase">Time</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#2a2e39]">
            {alerts.length === 0 && (
              <tr><td colSpan={5} className="px-6 py-8 text-center text-gray-500">No entries yet…</td></tr>
            )}
            {alerts.map(a => (
              <tr key={a.id} className="hover:bg-[#1a1d24] transition-colors">
                <td className="px-6 py-4 font-bold text-gray-200">{a.value || "—"}</td>
                <td className="px-6 py-4 text-xs text-gray-500">{a.fieldName}</td>
                <td className="px-6 py-4"><RiskBadge level={a.riskLevel} /></td>
                <td className="px-6 py-4">
                  <div className="flex items-center gap-2">
                    <div className="w-20 h-1.5 bg-[#2a2e39] rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${(a.similarityScore || 0) > 80 ? "bg-red-500" : (a.similarityScore || 0) > 50 ? "bg-yellow-500" : "bg-emerald-500"}`}
                        style={{ width: `${a.similarityScore || 0}%` }}
                      />
                    </div>
                    <span className="text-sm text-gray-300">{(a.similarityScore || 0).toFixed(1)}%</span>
                  </div>
                </td>
                <td className="px-6 py-4 text-sm text-gray-400">
                  {a.timestamp ? new Date(a.timestamp * 1000).toLocaleTimeString() : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Review Queue Tab ──────────────────────────────────────────────────────────

function ReviewQueueTab() {
  const [cases, setCases]           = useState([]);
  const [statusFilter, setStatusFilter] = useState("pending");
  const [loading, setLoading]       = useState(false);
  const [note, setNote]             = useState({});
  const [notification, setNotification] = useState(null); // { caseId, action, ref }
  const { toast, show: showToast, dismiss: dismissToast } = useToast();

  const fetchQueue = useCallback(() => {
    fetch(`${API}/api/admin/review-queue?status=${statusFilter}`, { headers: authHeaders() })
      .then(r => r.json())
      .then(setCases)
      .catch(() => {});
  }, [statusFilter]);

  useEffect(() => { fetchQueue(); }, [fetchQueue]);

  async function decide(caseId, action) {
    setLoading(true);
    setNotification(null);
    try {
      await fetch(`${API}/api/admin/review-queue/${caseId}/${action}`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ officer_note: note[caseId] || "" }),
      });
      const ref = caseId.slice(0, 8).toUpperCase();
      if (action === "approve") {
        showToast(`Case ${ref} approved. Applicant notification dispatched via registered contact.`, "success");
        setNotification({ caseId, action: "approved", ref });
      } else {
        showToast(`Case ${ref} rejected. Rejection notice dispatched to applicant.`, "error");
        setNotification({ caseId, action: "rejected", ref });
      }
      fetchQueue();
    } finally { setLoading(false); }
  }

  return (
    <div>
      {toast && <Toast message={toast.message} type={toast.type} onDismiss={dismissToast} />}

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white mb-1">Compliance Review Queue</h1>
          <p className="text-gray-500 text-sm">Cases the AI flagged for manual verification (Edtech, Job, Retail, Insurance)</p>
        </div>
        <div className="flex items-center gap-3">
          <select value={statusFilter} onChange={e => { setStatusFilter(e.target.value); setNotification(null); }}
            className="bg-[#0f1115] border border-[#2a2e39] rounded-lg px-4 py-2 text-sm text-white focus:outline-none">
            <option value="pending">Pending</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </select>
          <button onClick={fetchQueue} className="p-2 bg-[#161920] border border-[#2a2e39] rounded-lg text-gray-400 hover:text-white transition-all">
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      {/* Notification confirmation inline banner */}
      {notification && (
        <div className={`mb-5 flex items-center gap-3 px-5 py-3 rounded-xl border text-sm font-semibold
          ${notification.action === "approved"
            ? "bg-emerald-900/30 border-emerald-500/30 text-emerald-300"
            : "bg-red-900/30 border-red-500/30 text-red-300"}`}>
          {notification.action === "approved"
            ? <CheckCircle size={16} className="shrink-0" />
            : <XCircle size={16} className="shrink-0" />}
          <span>
            Case <span className="font-black">{notification.ref}</span> {notification.action}.
            {notification.action === "approved"
              ? " Identity committed to registry. Applicant notified via registered contact details."
              : " Identity NOT added to registry. Rejection notice sent to applicant."}
          </span>
          <button onClick={() => setNotification(null)} className="ml-auto opacity-50 hover:opacity-100 text-xs">✕</button>
        </div>
      )}

      <div className="space-y-4">
        {cases.length === 0 && (
          <div className="bg-[#161920] border border-[#2a2e39] rounded-2xl p-10 text-center text-gray-500">
            No {statusFilter} cases
          </div>
        )}
        {cases.map(c => (
          <div key={c.id} className="bg-[#161920] border border-[#2a2e39] rounded-2xl p-6">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <div className="flex items-center gap-3 mb-2">
                  <RiskBadge level={c.riskLevel} />
                  <span className="text-xs text-gray-600 font-mono">REF: {c.id?.slice(0, 8).toUpperCase()}</span>
                  <span className="text-xs text-gray-500">{c.timestamp ? new Date(c.timestamp * 1000).toLocaleString() : ""}</span>
                  <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-violet-500/10 text-violet-400 border border-violet-500/20">🤖 AI Escalated</span>
                </div>
                <p className="text-white font-bold mb-1">
                  {c.value || "—"} <span className="text-gray-500 font-normal text-sm">({c.fieldName})</span>
                </p>
                <p className="text-yellow-400 text-sm mb-2">{c.explanation}</p>
                {c.aiReason && (
                  <div className="flex items-start gap-2 bg-violet-500/5 border border-violet-500/20 rounded-lg px-3 py-2 mb-2">
                    <span className="text-violet-400 text-xs font-bold shrink-0 mt-0.5">AI:</span>
                    <p className="text-violet-300 text-xs">{c.aiReason}</p>
                  </div>
                )}
                {c.identityDetails && (
                  <div className="flex gap-4 text-xs text-gray-500 mb-2">
                    {c.identityDetails.FullName     && <span>Name: <span className="text-gray-300">{c.identityDetails.FullName}</span></span>}
                    {c.identityDetails.EmailAddress && <span>Email: <span className="text-gray-300">{c.identityDetails.EmailAddress}</span></span>}
                    {c.identityDetails.PhoneNumber  && <span>Phone: <span className="text-gray-300">{c.identityDetails.PhoneNumber}</span></span>}
                  </div>
                )}
                {c.officerNote && <p className="text-gray-400 text-xs italic">Officer note: {c.officerNote}</p>}
              </div>

              {statusFilter === "pending" && (
                <div className="flex flex-col gap-2 min-w-[220px]">
                  <input
                    placeholder="Officer note (optional)"
                    value={note[c.id] || ""}
                    onChange={e => setNote(n => ({ ...n, [c.id]: e.target.value }))}
                    className="bg-[#0f1115] border border-[#2a2e39] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-red-500/50"
                  />
                  <div className="flex gap-2">
                    <button onClick={() => decide(c.id, "approve")} disabled={loading}
                      className="flex-1 flex items-center justify-center gap-2 bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-400 border border-emerald-500/30 rounded-lg py-2 text-sm font-bold transition-all disabled:opacity-50">
                      <CheckCircle size={14} /> Approve
                    </button>
                    <button onClick={() => decide(c.id, "reject")} disabled={loading}
                      className="flex-1 flex items-center justify-center gap-2 bg-red-600/20 hover:bg-red-600/30 text-red-400 border border-red-500/30 rounded-lg py-2 text-sm font-bold transition-all disabled:opacity-50">
                      <XCircle size={14} /> Reject
                    </button>
                  </div>
                </div>
              )}

              {statusFilter !== "pending" && (
                <span className={`text-sm font-bold px-3 py-1 rounded-full border ${statusFilter === "approved" ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" : "bg-red-500/10 text-red-400 border-red-500/20"}`}>
                  {statusFilter.toUpperCase()}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Thresholds Tab ────────────────────────────────────────────────────────────

function ThresholdsTab() {
  const [high, setHigh]     = useState(85);
  const [medium, setMedium] = useState(60);
  const [saved, setSaved]   = useState(false);
  const [error, setError]   = useState("");
  const { toast, show: showToast, dismiss: dismissToast } = useToast();

  useEffect(() => {
    fetch(`${API}/api/admin/thresholds`, { headers: authHeaders() })
      .then(r => r.json())
      .then(d => { setHigh(d.high_risk_threshold); setMedium(d.medium_risk_threshold); })
      .catch(() => {});
  }, []);

  function handleHighChange(val) {
    const v = Number(val);
    // HIGH must always be above MEDIUM — enforce client-side
    if (v <= medium) return;
    setHigh(v);
  }

  function handleMediumChange(val) {
    const v = Number(val);
    // MEDIUM must always be below HIGH — enforce client-side
    if (v >= high) return;
    setMedium(v);
  }

  const gap = high - medium;
  const gapWarning = gap < 10;

  async function handleSave() {
    setError("");
    if (medium >= high) {
      setError("HIGH threshold must be greater than MEDIUM threshold.");
      return;
    }
    const res = await fetch(`${API}/api/admin/thresholds`, {
      method: "PUT",
      headers: authHeaders(),
      body: JSON.stringify({ high_risk_threshold: high, medium_risk_threshold: medium }),
    });
    if (res.ok) {
      setSaved(true);
      showToast(`Thresholds updated — HIGH: ${high}%, MEDIUM: ${medium}%`, "success");
      setTimeout(() => setSaved(false), 2500);
    } else {
      const d = await res.json();
      setError(d.detail || "Error saving thresholds.");
    }
  }

  return (
    <div className="max-w-xl">
      {toast && <Toast message={toast.message} type={toast.type} onDismiss={dismissToast} />}

      <h1 className="text-2xl font-bold text-white mb-1">Risk Thresholds</h1>
      <p className="text-gray-500 text-sm mb-8">Configurable similarity thresholds for fraud classification (FR-20, BR-2)</p>

      <div className="bg-[#161920] border border-[#2a2e39] rounded-2xl p-8 space-y-8">

        {/* HIGH slider */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-gray-300 font-semibold">HIGH Risk Threshold</label>
            <span className="text-red-400 font-black text-xl">{high}%</span>
          </div>
          <input
            type="range" min={1} max={99} value={high}
            onChange={e => handleHighChange(e.target.value)}
            className="w-full accent-red-500"
          />
          <p className="text-gray-500 text-xs mt-1">Above this similarity % → flagged for officer review</p>
        </div>

        {/* MEDIUM slider */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-gray-300 font-semibold">MEDIUM Risk Threshold</label>
            <span className="text-yellow-400 font-black text-xl">{medium}%</span>
          </div>
          <input
            type="range" min={1} max={99} value={medium}
            onChange={e => handleMediumChange(e.target.value)}
            className="w-full accent-yellow-500"
          />
          <p className="text-gray-500 text-xs mt-1">Above this similarity % → warning shown, caution advised</p>
        </div>

        {/* Visual gap indicator */}
        <div className="bg-[#0f1115] rounded-xl p-4">
          <p className="text-gray-400 text-xs font-semibold mb-3 uppercase tracking-wide">Threshold Range Preview</p>
          <div className="relative h-4 bg-[#2a2e39] rounded-full overflow-hidden">
            <div className="absolute h-full bg-emerald-500/60 rounded-full" style={{ width: `${medium}%` }} />
            <div className="absolute h-full bg-yellow-500/60" style={{ left: `${medium}%`, width: `${high - medium}%` }} />
            <div className="absolute h-full bg-red-500/60" style={{ left: `${high}%`, width: `${100 - high}%` }} />
          </div>
          <div className="flex justify-between text-xs text-gray-500 mt-1">
            <span>0% — LOW</span>
            <span>{medium}% — MEDIUM</span>
            <span>{high}% — HIGH</span>
            <span>100%</span>
          </div>
          {gapWarning && (
            <p className="text-yellow-400 text-xs mt-2 font-semibold">
              ⚠ Gap between thresholds is only {gap}%. A wider gap reduces false positives.
            </p>
          )}
        </div>

        {error && <p className="text-red-400 text-sm font-semibold">{error}</p>}

        <button onClick={handleSave}
          className="w-full bg-red-600 hover:bg-red-500 text-white font-bold py-3 rounded-lg transition-all">
          {saved ? "✓ Thresholds Saved" : "Save Thresholds"}
        </button>
      </div>
    </div>
  );
}

// ── Audit Log Tab ─────────────────────────────────────────────────────────────

function AuditLogTab() {
  const [logs, setLogs] = useState([]);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [secondsAgo, setSecondsAgo]   = useState(0);

  const fetchLogs = useCallback(() => {
    fetch(`${API}/api/admin/audit-log?limit=100`, { headers: authHeaders() })
      .then(r => r.json())
      .then(data => { setLogs(data); setLastUpdated(Date.now()); setSecondsAgo(0); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchLogs();
    const poll = setInterval(fetchLogs, 5000);
    return () => clearInterval(poll);
  }, [fetchLogs]);

  useEffect(() => {
    const tick = setInterval(() => {
      if (lastUpdated) setSecondsAgo(Math.floor((Date.now() - lastUpdated) / 1000));
    }, 1000);
    return () => clearInterval(tick);
  }, [lastUpdated]);

  const actionStyles = {
    approve:           "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20",
    reject:            "bg-red-500/10 text-red-400 border border-red-500/20",
    update_thresholds: "bg-blue-500/10 text-blue-400 border border-blue-500/20",
    bulk_import:       "bg-purple-500/10 text-purple-400 border border-purple-500/20",
  };

  function describeLog(log) {
    if (log.action === "approve")           return `Approved case ${log.case_id?.slice(0, 8).toUpperCase()}${log.note ? ` — "${log.note}"` : ""}`;
    if (log.action === "reject")            return `Rejected case ${log.case_id?.slice(0, 8).toUpperCase()}${log.note ? ` — "${log.note}"` : ""}`;
    if (log.action === "update_thresholds") return `Thresholds updated — HIGH: ${log.high}%, MEDIUM: ${log.medium}%`;
    if (log.action === "bulk_import")       return `Bulk import — ${log.count} identities seeded into registry`;
    return log.action;
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white mb-1">Audit Log</h1>
          <p className="text-gray-500 text-sm">Immutable record of all officer actions (FR-28, BR-6)</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500">
            {lastUpdated ? `Updated ${secondsAgo}s ago` : "Loading…"}
          </span>
          <button onClick={fetchLogs} className="p-2 bg-[#161920] border border-[#2a2e39] rounded-lg text-gray-400 hover:text-white transition-all">
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      <div className="bg-[#161920] border border-[#2a2e39] rounded-2xl overflow-hidden">
        <table className="w-full text-left">
          <thead className="text-xs bg-[#0f1115] text-gray-400 font-bold tracking-wider">
            <tr>
              <th className="px-6 py-4 uppercase">Action</th>
              <th className="px-6 py-4 uppercase">Officer</th>
              <th className="px-6 py-4 uppercase">Details</th>
              <th className="px-6 py-4 uppercase">Time</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#2a2e39]">
            {logs.length === 0 && (
              <tr><td colSpan={4} className="px-6 py-8 text-center text-gray-500">No audit entries yet…</td></tr>
            )}
            {logs.map(log => (
              <tr key={log.id} className="hover:bg-[#1a1d24] transition-colors">
                <td className="px-6 py-4">
                  <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-black tracking-widest ${actionStyles[log.action] || "bg-gray-500/10 text-gray-400 border border-gray-500/20"}`}>
                    {log.action?.toUpperCase().replace("_", " ")}
                  </span>
                </td>
                <td className="px-6 py-4 text-sm text-gray-300 font-semibold">{log.officer || "—"}</td>
                <td className="px-6 py-4 text-sm text-gray-400">{describeLog(log)}</td>
                <td className="px-6 py-4 text-sm text-gray-500">
                  {log.timestamp ? new Date(log.timestamp * 1000).toLocaleString() : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────────────────────

export default function App() {
  const [loggedIn, setLoggedIn] = useState(!!getToken());
  const [activeTab, setActiveTab] = useState("dashboard");

  const username = loggedIn ? decodeUsername(getToken()) : "";

  function handleLogout() { clearToken(); setLoggedIn(false); }

  if (!loggedIn) return <LoginPage onLogin={() => setLoggedIn(true)} />;

  const tabs = [
    { id: "dashboard", label: "Live Monitor", icon: Activity      },
    { id: "review",    label: "Review Queue", icon: Clock         },
    { id: "settings",  label: "Thresholds",   icon: Settings      },
    { id: "audit",     label: "Audit Log",    icon: ClipboardList },
  ];

  return (
    <div className="flex h-screen bg-[#0f1115] text-white overflow-hidden font-sans">
      {/* Sidebar */}
      <aside className="w-64 bg-[#161920] border-r border-[#2a2e39] flex flex-col justify-between">
        <div className="p-6">
          <div className="flex items-center gap-3 text-red-500 font-bold text-xl tracking-wide mb-10">
            <ShieldAlert size={28} />
            <span>FraudGuard AI</span>
          </div>
          <nav className="space-y-3">
            {tabs.map(({ id, label, icon: Icon }) => (
              <button key={id} onClick={() => setActiveTab(id)}
                className={`w-full flex items-center gap-4 px-4 py-3 rounded-lg transition-all ${activeTab === id ? "bg-red-500/10 text-red-500 border border-red-500/20" : "text-gray-400 hover:bg-[#2a2e39] hover:text-white"}`}>
                <Icon size={20} />
                <span className="font-semibold">{label}</span>
              </button>
            ))}
          </nav>
        </div>

        {/* Logged-in officer info */}
        <div className="p-6 border-t border-[#2a2e39] space-y-3">
          <div className="flex items-center gap-3 px-4 py-3 bg-[#0f1115] rounded-lg">
            <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-red-700 to-red-500 flex items-center justify-center font-bold text-sm">
              {username.slice(0, 2).toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-white text-sm font-semibold truncate">{username}</p>
              <p className="text-gray-500 text-xs">Compliance Manager</p>
            </div>
          </div>
          <button onClick={handleLogout}
            className="w-full flex items-center gap-4 px-4 py-3 text-gray-400 hover:text-red-500 hover:bg-red-500/10 rounded-lg transition-all">
            <LogOut size={20} />
            <span className="font-semibold">Sign Out</span>
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col h-full bg-[#0a0c10]">
        <header className="h-16 border-b border-[#2a2e39] flex items-center justify-between px-10 bg-[#161920]">
          <h2 className="font-bold text-gray-300 text-lg">
            {tabs.find(t => t.id === activeTab)?.label}
          </h2>
          <div className="flex items-center gap-3 text-sm text-gray-400">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <span>System Active</span>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-8">
          {activeTab === "dashboard" && <LiveMonitorTab />}
          {activeTab === "review"    && <ReviewQueueTab />}
          {activeTab === "settings"  && <ThresholdsTab />}
          {activeTab === "audit"     && <AuditLogTab />}
        </div>
      </main>
    </div>
  );
}
