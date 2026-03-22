import { useState, useEffect, useCallback, useRef } from "react";
import { Routes, Route, NavLink } from "react-router-dom";
import { getToken, clearToken, BASE } from "./hooks/useApi";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Trades from "./pages/Trades";
import Performance from "./pages/Performance";
import Journal from "./pages/Journal";
import Leaderboard from "./pages/Leaderboard";
import MemoryPage from "./pages/Memory";
import MindPage from "./pages/Mind";
import LabPage from "./pages/Lab";
import ReviewPage from "./pages/Review";

// ---------------------------------------------------------------------------
// Health check states: "checking" | "ok" | "down"
// ---------------------------------------------------------------------------

function useHealthCheck() {
  const [status, setStatus] = useState("checking");
  const retryRef = useRef(0);

  const check = useCallback(async () => {
    setStatus("checking");
    try {
      const res = await fetch(`${BASE}/health`, {
        signal: AbortSignal.timeout(8000),  // increased from 5s for cold starts
      });
      const data = await res.json();
      setStatus(data.status === "ok" ? "ok" : "down");
      retryRef.current = 0;
    } catch {
      // On first failure, retry once after 3s (Render cold start)
      if (retryRef.current < 2) {
        retryRef.current += 1;
        console.debug(`[health] Retry ${retryRef.current}/2 after cold start delay...`);
        setTimeout(() => check(), 3000);
        return;
      }
      setStatus("down");
    }
  }, []);

  useEffect(() => {
    check();
  }, [check]);

  return { status, retry: check };
}

// ---------------------------------------------------------------------------
// Auth bootstrapping: validate token on app load
// ---------------------------------------------------------------------------

function useAuthBootstrap() {
  const [state, setState] = useState("checking"); // checking | valid | invalid
  const checked = useRef(false);

  useEffect(() => {
    if (checked.current) return;
    checked.current = true;

    const token = getToken();
    if (!token) {
      console.debug("[auth] No token found — starting fresh");
      setState("invalid");
      return;
    }

    // Validate token against an auth-protected endpoint
    async function validate() {
      try {
        const res = await fetch(`${BASE}/status`, {
          headers: { "Authorization": `Bearer ${token}` },
          signal: AbortSignal.timeout(8000),
        });
        if (res.ok) {
          console.debug("[auth] Session restored — token validated against /status");
          setState("valid");
        } else if (res.status === 401) {
          console.debug("[auth] Stored token invalid/expired — clearing");
          clearToken();
          setState("invalid");
        } else {
          // Backend error (500, 503, etc.) but not auth-related — keep token
          console.debug(`[auth] Backend returned ${res.status}, keeping token`);
          setState("valid");
        }
      } catch {
        // Network error — can't validate, keep token (benefit of doubt)
        // If token is actually bad, the 3-consecutive-401 guard will catch it later
        console.debug("[auth] Cannot reach backend to validate — keeping stored token");
        setState("valid");
      }
    }

    validate();
  }, []);

  return state;
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
          {BASE || window.location.origin}
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
  const authState = useAuthBootstrap();
  const [authed, setAuthed] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const logoutGuardRef = useRef(false); // prevent logout loops

  // Sync auth state once bootstrap completes
  useEffect(() => {
    if (authState === "valid") setAuthed(true);
    else if (authState === "invalid") setAuthed(false);
  }, [authState]);

  const handleLogout = useCallback(() => {
    // Prevent multiple rapid logouts (e.g., from several useApi hooks firing at once)
    if (logoutGuardRef.current) return;
    logoutGuardRef.current = true;
    setTimeout(() => { logoutGuardRef.current = false; }, 2000);

    console.debug("[auth] Logging out");
    clearToken();
    setAuthed(false);
  }, []);

  // Listen for auth:logout from useApi's auth guard
  useEffect(() => {
    function onUnauth() { handleLogout(); }
    window.addEventListener("auth:logout", onUnauth);
    return () => window.removeEventListener("auth:logout", onUnauth);
  }, [handleLogout]);

  // 1. Checking backend or auth
  if (health === "checking" || authState === "checking") return <StartupCheck />;

  // 2. Backend down
  if (health === "down") return <BackendDown onRetry={retryHealth} />;

  // 3. Backend up, not logged in
  if (!authed) return <Login onLogin={() => setAuthed(true)} />;

  const navItems = [
    { to: "/", icon: "📊", label: "Dashboard" },
    { to: "/trades", icon: "📈", label: "Trades" },
    { to: "/performance", icon: "🏆", label: "Performance" },
    { to: "/journal", icon: "📝", label: "Journal" },
    { to: "/leaderboard", icon: "🏅", label: "Leaderboard" },
    { to: "/memory", icon: "🧠", label: "Memory" },
    { to: "/mind", icon: "◈", label: "Mind" },
    { to: "/lab", icon: "⬡", label: "Lab" },
    { to: "/review", icon: "⬢", label: "Review" },
  ];

  // 4. Backend up, logged in → full app
  return (
    <div className="app">
      <nav
        className={`sidebar ${sidebarOpen ? "sidebar--open" : ""}`}
        onMouseEnter={() => setSidebarOpen(true)}
        onMouseLeave={() => setSidebarOpen(false)}
      >
        <h2 className="sidebar__title">{sidebarOpen ? "CryptoMind" : "CM"}</h2>
        {navItems.map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => (isActive ? "active" : "")}
            onClick={() => setSidebarOpen(false)}
          >
            <span className="sidebar__icon">{item.icon}</span>
            <span className="sidebar__label">{item.label}</span>
          </NavLink>
        ))}
        <div style={{ marginTop: 30, borderTop: "1px solid var(--border)", paddingTop: 8 }}>
          <a
            href="#"
            onClick={(e) => { e.preventDefault(); handleLogout(); }}
            style={{ color: "var(--red)", opacity: 0.6, fontSize: 12 }}
          >
            <span className="sidebar__icon">🚪</span>
            <span className="sidebar__label">Logout</span>
          </a>
        </div>
      </nav>
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/trades" element={<Trades />} />
          <Route path="/performance" element={<Performance />} />
          <Route path="/journal" element={<Journal />} />
          <Route path="/leaderboard" element={<Leaderboard />} />
          <Route path="/memory" element={<MemoryPage />} />
          <Route path="/mind" element={<MindPage />} />
          <Route path="/lab" element={<LabPage />} />
          <Route path="/review" element={<ReviewPage />} />
        </Routes>
      </main>
    </div>
  );
}
