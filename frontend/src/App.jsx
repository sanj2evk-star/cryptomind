import { useState, useEffect, useCallback } from "react";
import { Routes, Route, NavLink } from "react-router-dom";
import { getToken, clearToken, BASE } from "./hooks/useApi";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Trades from "./pages/Trades";
import Performance from "./pages/Performance";
import Journal from "./pages/Journal";

// ---------------------------------------------------------------------------
// Health check states: "checking" | "ok" | "down"
// ---------------------------------------------------------------------------

function useHealthCheck() {
  const [status, setStatus] = useState("checking");

  const check = useCallback(async () => {
    setStatus("checking");
    try {
      const res = await fetch(`${BASE}/health`, {
        signal: AbortSignal.timeout(5000),
      });
      const data = await res.json();
      setStatus(data.status === "ok" ? "ok" : "down");
    } catch {
      setStatus("down");
    }
  }, []);

  useEffect(() => {
    check();
  }, [check]);

  return { status, retry: check };
}

// ---------------------------------------------------------------------------
// Backend-down screen
// ---------------------------------------------------------------------------

function BackendDown({ onRetry }) {
  return (
    <div style={{
      display: "flex", justifyContent: "center", alignItems: "center",
      minHeight: "100vh", background: "var(--bg)",
    }}>
      <div style={{
        background: "var(--surface)", border: "1px solid var(--border)",
        borderRadius: 12, padding: 40, width: 380, textAlign: "center",
      }}>
        <div style={{ fontSize: 36, marginBottom: 16, opacity: 0.4 }}>!</div>
        <h2 style={{ marginBottom: 12 }}>Backend Unavailable</h2>
        <p style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 8 }}>
          Cannot reach the API server at:
        </p>
        <code style={{
          display: "block", padding: "6px 12px", background: "var(--bg)",
          borderRadius: 6, fontSize: 13, marginBottom: 20, color: "var(--blue)",
        }}>
          {BASE}
        </code>
        <p style={{ color: "var(--text-muted)", fontSize: 12, marginBottom: 20 }}>
          Start it with: <code>python3 run_api.py</code>
        </p>
        <button onClick={onRetry} className="retry-btn" style={{ padding: "8px 24px", fontSize: 14 }}>
          Retry Connection
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Startup spinner
// ---------------------------------------------------------------------------

function StartupCheck() {
  return (
    <div style={{
      display: "flex", flexDirection: "column", justifyContent: "center",
      alignItems: "center", minHeight: "100vh", background: "var(--bg)", gap: 16,
    }}>
      <div className="spinner" />
      <p style={{ color: "var(--text-muted)", fontSize: 14 }}>Connecting to backend...</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  const { status: health, retry: retryHealth } = useHealthCheck();
  const [authed, setAuthed] = useState(!!getToken());

  const handleLogout = useCallback(() => {
    clearToken();
    setAuthed(false);
  }, []);

  // Listen for 401 from any useApi call
  useEffect(() => {
    function onUnauth() { handleLogout(); }
    window.addEventListener("auth:logout", onUnauth);
    return () => window.removeEventListener("auth:logout", onUnauth);
  }, [handleLogout]);

  // 1. Checking backend
  if (health === "checking") return <StartupCheck />;

  // 2. Backend down
  if (health === "down") return <BackendDown onRetry={retryHealth} />;

  // 3. Backend up, not logged in
  if (!authed) return <Login onLogin={() => setAuthed(true)} />;

  // 4. Backend up, logged in → full app
  return (
    <div className="app">
      <nav className="sidebar">
        <h2>CryptoMind</h2>
        <NavLink to="/" className={({ isActive }) => (isActive ? "active" : "")}>
          Dashboard
        </NavLink>
        <NavLink to="/trades" className={({ isActive }) => (isActive ? "active" : "")}>
          Trades
        </NavLink>
        <NavLink to="/performance" className={({ isActive }) => (isActive ? "active" : "")}>
          Performance
        </NavLink>
        <NavLink to="/journal" className={({ isActive }) => (isActive ? "active" : "")}>
          Journal
        </NavLink>
        <a
          href="#"
          onClick={(e) => { e.preventDefault(); handleLogout(); }}
          style={{ marginTop: "auto", color: "var(--red)" }}
        >
          Logout
        </a>
      </nav>
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/trades" element={<Trades />} />
          <Route path="/performance" element={<Performance />} />
          <Route path="/journal" element={<Journal />} />
        </Routes>
      </main>
    </div>
  );
}
