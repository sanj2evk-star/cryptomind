import React, { useState, useEffect, useCallback, useMemo } from "react";
import { useApi, BASE, getToken } from "../hooks/useApi";
import { fmtLocalTimeShort } from "../hooks/useTime";
import { Loading, ErrorBox, EmptyState } from "../components/StatusMessage";
import TradeScatter from "../components/TradeScatter";
import CumulativePnl from "../components/CumulativePnl";
import ScopeToggle from "../components/ScopeToggle";

/* ─── Helpers ─── */
const fmt = (n) => `$${Number(n ?? 0).toFixed(4)}`;
const fmtPrice = (n) => `$${Number(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const pct = (n) => `${(Number(n ?? 0) * 100).toFixed(0)}%`;

/* Strategy colors */
const STRAT_COLORS = {
  MONK: "#8b5cf6", HUNTER: "#3b82f6", AGGRESSIVE: "#ef4444", DEFENSIVE: "#22c55e",
  EXPERIMENTAL: "#eab308", SCALPER: "#f97316", INTUITIVE: "#06b6d4",
  MEAN_REVERTER: "#a855f7", BREAKOUT_SNIPER: "#f43f5e", main: "#6b7280",
};

/* ─── P&L Cell with night-mode visibility ─── */
function PnlValue({ pnl, size = "normal" }) {
  const v = Number(pnl ?? 0);
  const isNeg = v < 0;
  const isPos = v > 0;
  const fontSize = size === "large" ? 18 : size === "small" ? 11 : 13;
  return (
    <span style={{
      color: isNeg ? "var(--red)" : isPos ? "var(--green)" : "var(--text-muted)",
      fontWeight: isNeg ? 700 : isPos ? 600 : 400,
      fontSize,
    }}>
      {isNeg && "▼ "}{isPos && "▲ "}{fmt(v)}
    </span>
  );
}

/* ─── Trade Quality Badge ─── */
function QualityBadge({ score, confidence, entryType }) {
  const s = Number(score ?? 0);
  const c = Number(confidence ?? 0);
  const isProbe = (entryType || "").includes("probe");

  if (isProbe) return <span className="trade-badge probe">🧪 Probe</span>;
  if (s >= 65 && c >= 0.25) return <span className="trade-badge high">🔥 High</span>;
  if (s >= 50) return <span className="trade-badge neutral">⚖️ Neutral</span>;
  return <span className="trade-badge low">⚡ Low</span>;
}

/* ─── Entry Type Tag ─── */
function EntryTag({ type }) {
  const t = (type || "full").toLowerCase();
  const cfg = {
    full: { bg: "#3b82f622", color: "#3b82f6", label: "Full" },
    probe: { bg: "#eab30822", color: "#eab308", label: "Probe" },
    trend_probe: { bg: "#8b5cf622", color: "#8b5cf6", label: "Trend" },
    sleeping_probe: { bg: "#6b728022", color: "#9ca3af", label: "Sleep" },
    hold_loop_probe: { bg: "#f9731622", color: "#f97316", label: "Loop" },
  };
  const c = cfg[t] || cfg.full;
  return (
    <span style={{
      display: "inline-block", padding: "1px 5px", borderRadius: 3,
      fontSize: 9, fontWeight: 600, background: c.bg, color: c.color,
    }}>{c.label}</span>
  );
}

/* ─── Expandable Trade Detail ─── */
function TradeDetail({ trade }) {
  const signals = (trade.signals || "").split("|").filter(Boolean);
  return (
    <div style={{
      padding: "8px 12px", background: "var(--bg)", borderTop: "1px solid var(--border)",
      fontSize: 11, color: "var(--text-muted)", display: "grid",
      gridTemplateColumns: "1fr 1fr 1fr", gap: "4px 16px",
    }}>
      <div><strong>Strategy:</strong> {trade.strategy || "—"}</div>
      <div><strong>Regime:</strong> {trade.regime || "—"}</div>
      <div><strong>Entry:</strong> {trade.entry_type || "full"}</div>
      <div><strong>Score:</strong> {trade.score || "—"}</div>
      <div><strong>Confidence:</strong> {pct(trade.confidence)}</div>
      <div><strong>$ Size:</strong> ${Number(trade.dollar_size || 0).toFixed(2)}</div>
      {trade.reason && (
        <div style={{ gridColumn: "1 / -1" }}>
          <strong>Reason:</strong> {trade.reason}
        </div>
      )}
      {signals.length > 0 && (
        <div style={{ gridColumn: "1 / -1" }}>
          <strong>Signals:</strong> {signals.join(" · ")}
        </div>
      )}
    </div>
  );
}

/* ─── Session Summary Panel ─── */
function SessionSummary({ summary }) {
  if (!summary) return null;
  const stats = [
    { label: "Total", value: summary.total_trades },
    { label: "Buys", value: summary.buys, color: "var(--green)" },
    { label: "Sells", value: summary.sells, color: "var(--red)" },
    { label: "Win Rate", value: `${summary.win_rate}%`, color: summary.win_rate >= 50 ? "var(--green)" : "var(--red)" },
    { label: "Net P&L", value: null, pnl: summary.net_pnl },
    { label: "Best", value: null, pnl: summary.best_trade },
    { label: "Worst", value: null, pnl: summary.worst_trade },
  ];
  return (
    <div className="card" style={{ marginBottom: 12, padding: "12px 14px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.5 }}>Session Summary</span>
        <span style={{
          fontSize: 10, padding: "2px 6px", borderRadius: 3, fontWeight: 600,
          background: summary.regime === "ACTIVE" ? "#22c55e22" : summary.regime === "BREAKOUT" ? "#ef444422" : "#6b728022",
          color: summary.regime === "ACTIVE" ? "#22c55e" : summary.regime === "BREAKOUT" ? "#ef4444" : "#9ca3af",
        }}>{summary.regime || "SLEEPING"}</span>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 16px", marginBottom: 8 }}>
        {stats.map((s, i) => (
          <div key={i} style={{ minWidth: 60 }}>
            <div style={{ fontSize: 9, color: "var(--text-muted)", textTransform: "uppercase" }}>{s.label}</div>
            {s.pnl !== undefined ? (
              <PnlValue pnl={s.pnl} size="normal" />
            ) : (
              <div style={{ fontSize: 16, fontWeight: 700, color: s.color || "var(--text)" }}>{s.value}</div>
            )}
          </div>
        ))}
      </div>
      {summary.insight && (
        <div style={{ fontSize: 11, color: "var(--text-muted)", fontStyle: "italic", borderTop: "1px solid var(--border)", paddingTop: 6 }}>
          "{summary.insight}"
        </div>
      )}
    </div>
  );
}

/* ─── Debug Panel ─── */
function DebugPanel() {
  const { data } = useApi("/debug/state", 10000);
  if (!data) return null;
  const items = [
    ["Exposure", `${data.total_exposure_pct}%`],
    ["Cap", data.exposure_cap_active || "—"],
    ["Quality", data.market_quality_score],
    ["Hold Cycles", data.consecutive_hold_cycles],
    ["Probes", data.probe_trades_count],
    ["Blocked", data.blocked_trade_reason || "none"],
    ["Re-entry Buys", data.reentry_state?.consecutive_buys ?? "—"],
    ["Last Score", data.reentry_state?.last_committed_score ?? "—"],
  ];
  return (
    <div className="card" style={{ marginBottom: 12, padding: "10px 12px" }}>
      <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", marginBottom: 6 }}>🧠 Debug State</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "4px 12px", fontSize: 11 }}>
        {items.map(([k, v], i) => (
          <div key={i}>
            <span style={{ color: "var(--text-muted)" }}>{k}: </span>
            <span style={{ fontWeight: 600 }}>{v}</span>
          </div>
        ))}
      </div>
      {data.strategy_status && Object.keys(data.strategy_status).length > 0 && (
        <div style={{ marginTop: 6, fontSize: 10, color: "var(--text-muted)" }}>
          {Object.entries(data.strategy_status).map(([n, s]) => (
            <span key={n} style={{
              display: "inline-block", marginRight: 6, padding: "1px 4px", borderRadius: 2,
              background: s === "ACTIVE" ? "#22c55e22" : s === "LEADING" ? "#eab30822" : s === "PROBATION" ? "#f9731622" : "#ef444422",
              color: s === "ACTIVE" ? "#22c55e" : s === "LEADING" ? "#eab308" : s === "PROBATION" ? "#f97316" : "#ef4444",
            }}>{n.slice(0, 4)}:{s.slice(0, 3)}</span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   MAIN TRADES PAGE
   ═══════════════════════════════════════════════════════════════════ */
export default function Trades() {
  // State
  const [viewMode, setViewMode] = useState("table"); // table | feed
  const [showHold, setShowHold] = useState(false);
  const [scope, setScope] = useState("session"); // session | version | lifetime | today | yesterday | weekly | monthly | range
  const [debugMode, setDebugMode] = useState(false);
  const [expandedRow, setExpandedRow] = useState(null);
  const [trades, setTrades] = useState([]);
  const [hasMore, setHasMore] = useState(false);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [offset, setOffset] = useState(0);

  // Filters
  const [filterAction, setFilterAction] = useState("");
  const [filterStrategy, setFilterStrategy] = useState("");
  const [filterRegime, setFilterRegime] = useState("");
  const [filterEntry, setFilterEntry] = useState("");
  const [filterResult, setFilterResult] = useState(""); // win / loss

  // Time-based filter state (v7.7.2)
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [activePreset, setActivePreset] = useState(""); // today | yesterday | weekly | monthly
  const scopeUrl = useMemo(() => {
    if (scope === "range" && startDate && endDate) {
      return `/v7/trades/scoped?scope=range&start=${startDate}&end=${endDate}&limit=5`;
    }
    return `/v7/trades/scoped?scope=${scope}&limit=5`;
  }, [scope, startDate, endDate]);

  // Summary — from v7 scoped stats (single source of truth)
  const { data: sysAge } = useApi("/v7/system-age", 30000);
  const { data: scopedStats, retry: rScoped } = useApi(scopeUrl, 15000);

  // Build the fetch URL using v7 scoped endpoint (DB-backed, not CSV)
  const tradesUrl = useMemo(() => {
    const params = new URLSearchParams({ scope, limit: "200" });
    if (scope === "range" && startDate && endDate) {
      params.set("start", startDate);
      params.set("end", endDate);
    }
    return `${BASE}/v7/trades/scoped?${params}`;
  }, [scope, startDate, endDate]);

  // Fetch trades from v7 DB (single source of truth)
  const fetchTrades = useCallback(async (reset = false) => {
    try {
      setLoading(true);
      const token = getToken();
      const headers = {};
      if (token) headers["Authorization"] = `Bearer ${token}`;
      const res = await fetch(tradesUrl, { headers });
      if (!res.ok) throw new Error(`Server error (${res.status})`);
      const data = await res.json();

      let newTrades = data.trades || [];

      // Client-side filters (action, strategy, regime, entry_type, win/loss)
      if (filterAction) newTrades = newTrades.filter(t => (t.action || "").toUpperCase() === filterAction);
      if (filterStrategy) newTrades = newTrades.filter(t => t.strategy === filterStrategy);
      if (filterRegime) newTrades = newTrades.filter(t => t.regime === filterRegime);
      if (filterEntry) newTrades = newTrades.filter(t => (t.entry_type || "").includes(filterEntry));
      if (filterResult === "win") newTrades = newTrades.filter(t => t.action === "SELL" && Number(t.pnl) > 0);
      else if (filterResult === "loss") newTrades = newTrades.filter(t => t.action === "SELL" && Number(t.pnl) < 0);

      setTrades(newTrades);
      setTotal(data.total || 0);
      setHasMore(false);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [tradesUrl, filterAction, filterStrategy, filterRegime, filterEntry, filterResult]);

  // Initial load + auto-refresh
  useEffect(() => {
    fetchTrades(true);
    const iv = setInterval(() => fetchTrades(true), 30000);
    return () => clearInterval(iv);
  }, [fetchTrades]);

  const filteredTrades = useMemo(() => {
    if (showHold) return trades;
    return trades.filter(t => t.action !== "HOLD");
  }, [trades, showHold]);

  // Unique strategies/regimes for filter dropdowns
  const uniqueStrategies = useMemo(() => {
    const set = new Set(trades.map(t => t.strategy).filter(Boolean));
    return Array.from(set);
  }, [trades]);

  const uniqueRegimes = useMemo(() => {
    const set = new Set(trades.map(t => t.regime).filter(Boolean));
    return Array.from(set);
  }, [trades]);

  // Group trades by local date (v7.7.2)
  const groupedByDay = useMemo(() => {
    const groups = {};
    for (const t of filteredTrades) {
      const ts = t.timestamp || t.time || "";
      let dateKey = "Unknown";
      try {
        const d = new Date(ts);
        dateKey = d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
      } catch {}
      if (!groups[dateKey]) groups[dateKey] = [];
      groups[dateKey].push(t);
    }
    return Object.entries(groups);
  }, [filteredTrades]);

  if (loading && trades.length === 0) {
    return <><h1>Trade History</h1><Loading message="Loading trade ledger..." /></>;
  }
  if (error && trades.length === 0) {
    return <><h1>Trade History</h1><ErrorBox message={error} onRetry={() => fetchTrades(true)} /></>;
  }

  return (
    <>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
        <h1 style={{ margin: 0 }}>Trade History</h1>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          {/* View mode toggle */}
          <button onClick={() => setViewMode("table")} style={toggleBtn(viewMode === "table")}>📋 Table</button>
          <button onClick={() => setViewMode("feed")} style={toggleBtn(viewMode === "feed")}>⚡ Feed</button>
          <span style={{ width: 1, height: 16, background: "var(--border)" }} />
          {/* Show HOLD */}
          <button onClick={() => setShowHold(!showHold)} style={toggleBtn(showHold)}>
            {showHold ? "Hide" : "Show"} HOLD
          </button>
          {/* Debug toggle */}
          <button onClick={() => setDebugMode(!debugMode)} style={toggleBtn(debugMode)}>🧠 Debug</button>
          <span style={{ width: 1, height: 16, background: "var(--border)" }} />
          <ScopeToggle value={scope} onChange={setScope} compact/>
        </div>
      </div>

      {/* ── v7.7.2: Time Filter Bar ── */}
      <div style={{
        display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap",
        padding: "6px 10px", marginBottom: 6,
        background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6,
      }}>
        {/* Preset buttons */}
        {[
          { key: "today", label: "Today" },
          { key: "yesterday", label: "Yesterday" },
          { key: "weekly", label: "7D" },
          { key: "monthly", label: "30D" },
          { key: "lifetime", label: "Lifetime" },
        ].map(p => (
          <button key={p.key} onClick={() => {
            setScope(p.key); setActivePreset(p.key); setStartDate(""); setEndDate("");
          }} style={{
            padding: "3px 10px", fontSize: 10, fontWeight: 600, cursor: "pointer",
            borderRadius: 4, border: "1px solid var(--border)",
            background: scope === p.key ? "#3b82f6" : "var(--bg)",
            color: scope === p.key ? "#fff" : "var(--text-muted)",
          }}>{p.label}</button>
        ))}

        {/* Separator */}
        <span style={{ width: 1, height: 18, background: "var(--border)", margin: "0 4px" }} />

        {/* Date range inputs */}
        <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)}
          style={{ padding: "2px 6px", fontSize: 10, borderRadius: 4, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--text)", outline: "none" }}
        />
        <span style={{ fontSize: 10, color: "var(--text-muted)" }}>→</span>
        <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)}
          style={{ padding: "2px 6px", fontSize: 10, borderRadius: 4, border: "1px solid var(--border)", background: "var(--bg)", color: "var(--text)", outline: "none" }}
        />
        <button onClick={() => {
          if (startDate && endDate) { setScope("range"); setActivePreset("range"); }
        }} disabled={!startDate || !endDate} style={{
          padding: "3px 10px", fontSize: 10, fontWeight: 600, cursor: "pointer",
          borderRadius: 4, border: "none",
          background: scope === "range" ? "#3b82f6" : "#3b82f644",
          color: "#fff", opacity: (!startDate || !endDate) ? 0.4 : 1,
        }}>Apply</button>

        {/* Reset */}
        {scope !== "session" && (
          <button onClick={() => { setScope("session"); setActivePreset(""); setStartDate(""); setEndDate(""); }}
            style={{ padding: "3px 8px", fontSize: 9, color: "var(--text-muted)", background: "none", border: "none", cursor: "pointer", textDecoration: "underline" }}>
            Reset
          </button>
        )}
      </div>

      {/* Scoped Stats + Range Label */}
      {scopedStats?.stats && (
        <div style={{
          display: "flex", gap: 16, padding: "4px 10px", marginBottom: 6,
          background: "var(--surface)", border: "1px solid var(--border)",
          borderRadius: 6, fontSize: 10, flexWrap: "wrap",
        }}>
          <span>Scope: <b style={{color:"var(--text)"}}>{scope === "range" && startDate && endDate ? `${startDate} → ${endDate}` : scope}</b></span>
          <span>Trades: <b>{scopedStats.stats.total||0}</b></span>
          <span>Wins: <b style={{color:"var(--green)"}}>{scopedStats.stats.wins||0}</b></span>
          <span>Losses: <b style={{color:"var(--red)"}}>{scopedStats.stats.losses||0}</b></span>
          <span>Win Rate: <b>{scopedStats.stats.win_rate||0}%</b></span>
          <span>PnL: <b style={{color:(scopedStats.stats.total_pnl||0)>=0?"var(--green)":"var(--red)"}}>{(scopedStats.stats.total_pnl||0).toFixed(4)}</b></span>
        </div>
      )}

      {/* v7: Session strip */}
      {sysAge && (
        <div style={{
          display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap",
          padding: "5px 10px", marginBottom: 6,
          background: "var(--surface)", border: "1px solid var(--border)",
          borderRadius: 6, fontSize: 10,
        }}>
          <span style={{ color: "var(--blue)", fontWeight: 700 }}>
            v{sysAge.current_session_version || "7"} Session #{sysAge.current_session_id || "—"}
          </span>
          <span style={{ color: "var(--text-muted)" }}>
            Lifetime: <b style={{ color: "var(--text)" }}>{(sysAge.total_lifetime_trades || 0)} trades</b>
          </span>
          <span style={{ color: "var(--text-muted)" }}>
            {(sysAge.system_age_cycles || 0).toLocaleString()} cycles
          </span>
        </div>
      )}

      {/* Session Summary */}
      <SessionSummary summary={scopedStats?.stats ? {
        total_trades: scopedStats.stats.total || 0,
        buys: scopedStats.stats.buys || 0,
        sells: scopedStats.stats.sells || 0,
        win_rate: scopedStats.stats.win_rate || 0,
        net_pnl: scopedStats.stats.total_pnl || 0,
        best_trade: scopedStats.stats.best_trade || 0,
        worst_trade: scopedStats.stats.worst_trade || 0,
        regime: "—",
      } : null} />

      {/* Debug Panel */}
      {debugMode && <DebugPanel />}

      {/* Filters */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
        <FilterPill label="All" active={!filterAction} onClick={() => setFilterAction("")} />
        <FilterPill label="BUY" active={filterAction === "BUY"} onClick={() => setFilterAction(filterAction === "BUY" ? "" : "BUY")} color="var(--green)" />
        <FilterPill label="SELL" active={filterAction === "SELL"} onClick={() => setFilterAction(filterAction === "SELL" ? "" : "SELL")} color="var(--red)" />
        <FilterPill label="Win" active={filterResult === "win"} onClick={() => setFilterResult(filterResult === "win" ? "" : "win")} color="var(--green)" />
        <FilterPill label="Loss" active={filterResult === "loss"} onClick={() => setFilterResult(filterResult === "loss" ? "" : "loss")} color="var(--red)" />
        <FilterPill label="Probe" active={filterEntry === "probe"} onClick={() => setFilterEntry(filterEntry === "probe" ? "" : "probe")} color="#eab308" />
        <FilterPill label="Full" active={filterEntry === "full"} onClick={() => setFilterEntry(filterEntry === "full" ? "" : "full")} color="#3b82f6" />
        {uniqueStrategies.length > 1 && (
          <select value={filterStrategy} onChange={e => setFilterStrategy(e.target.value)}
            style={selectStyle}>
            <option value="">All Strategies</option>
            {uniqueStrategies.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        )}
        {uniqueRegimes.length > 1 && (
          <select value={filterRegime} onChange={e => setFilterRegime(e.target.value)}
            style={selectStyle}>
            <option value="">All Regimes</option>
            {uniqueRegimes.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        )}
      </div>

      {/* Trade count */}
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 8 }}>
        Showing {filteredTrades.length} of {total} trades
      </div>

      {/* Empty state */}
      {filteredTrades.length === 0 && !loading && (
        <EmptyState title="No trades yet" message="System waiting for edge. No trades executed yet." />
      )}

      {/* Charts (only show in table mode with enough data) */}
      {viewMode === "table" && filteredTrades.length >= 2 && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 12 }}>
          <TradeScatter trades={filteredTrades} />
          <CumulativePnl trades={filteredTrades} />
        </div>
      )}

      {/* ═══ TABLE VIEW ═══ */}
      {viewMode === "table" && filteredTrades.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Action</th>
                <th>Price</th>
                <th>Size</th>
                <th>P&L</th>
                <th>Strategy</th>
                <th>Score</th>
                <th>Type</th>
                <th>Badge</th>
              </tr>
            </thead>
            <tbody>
              {filteredTrades.map((t, i) => {
                const pnl = parseFloat(t.pnl) || 0;
                const action = (t.action || "HOLD").toUpperCase();
                const isHold = action === "HOLD";
                const isBuy = action === "BUY";
                const isSell = action === "SELL";
                const qty = parseFloat(t.quantity) || 0;
                const tPrice = parseFloat(t.price) || 0;
                const dollarSize = parseFloat(t.dollar_size) || qty * tPrice;
                const isExpanded = expandedRow === i;
                const stratColor = STRAT_COLORS[(t.strategy || "").toUpperCase()] || "#6b7280";

                return (
                  <React.Fragment key={i}>
                    <tr
                      onClick={() => setExpandedRow(isExpanded ? null : i)}
                      style={{
                        cursor: "pointer",
                        opacity: isHold ? 0.4 : 1,
                        background: isSell && pnl < 0
                          ? "rgba(239, 68, 68, 0.04)"
                          : isSell && pnl > 0
                            ? "rgba(34, 197, 94, 0.04)"
                            : isBuy
                              ? "rgba(59, 130, 246, 0.03)"
                              : "transparent",
                        borderLeft: isExpanded ? "2px solid var(--blue)" : "2px solid transparent",
                      }}
                    >
                      <td style={{ fontSize: 10 }}>{fmtLocalTimeShort(t.timestamp)}</td>
                      <td><span className={`tag ${action.toLowerCase()}`}>{action}</span></td>
                      <td>{fmtPrice(tPrice)}</td>
                      <td>
                        {qty > 0 ? (
                          <span title={`${qty.toFixed(6)} BTC`} style={{ fontSize: 11 }}>
                            ${dollarSize.toFixed(2)}
                          </span>
                        ) : "—"}
                      </td>
                      <td>
                        {isSell ? <PnlValue pnl={pnl} size="small" /> : "—"}
                      </td>
                      <td>
                        <span style={{
                          display: "inline-block", padding: "1px 5px", borderRadius: 3,
                          fontSize: 9, fontWeight: 600,
                          background: `${stratColor}22`, color: stratColor,
                        }}>{(t.strategy || "—").slice(0, 8)}</span>
                      </td>
                      <td style={{ fontSize: 11 }}>
                        {t.score || "—"}
                        <span style={{ fontSize: 9, color: "var(--text-muted)", marginLeft: 2 }}>
                          {pct(t.confidence)}
                        </span>
                      </td>
                      <td><EntryTag type={t.entry_type} /></td>
                      <td><QualityBadge score={t.score} confidence={t.confidence} entryType={t.entry_type} /></td>
                    </tr>
                    {isExpanded && (
                      <tr><td colSpan={9} style={{ padding: 0 }}><TradeDetail trade={t} /></td></tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ═══ LIVE FEED VIEW (grouped by day) ═══ */}
      {viewMode === "feed" && filteredTrades.length > 0 && (
        <div className="card" style={{ padding: "8px 12px", maxHeight: 500, overflowY: "auto" }}>
          {groupedByDay.map(([dateLabel, dayTrades]) => (
            <div key={dateLabel}>
              {/* Day header */}
              <div style={{
                padding: "6px 0 3px", fontSize: 11, fontWeight: 700,
                color: "#8b5cf6", borderBottom: "1px solid var(--border)",
                marginTop: 4,
              }}>
                {dateLabel} <span style={{ fontWeight: 400, color: "var(--text-muted)", fontSize: 10 }}>({dayTrades.length} trades)</span>
              </div>
              {dayTrades.map((t, i) => {
                const action = (t.action || "HOLD").toUpperCase();
                const pnl = parseFloat(t.pnl) || 0;
                const stratColor = STRAT_COLORS[(t.strategy || "").toUpperCase()] || "#6b7280";
                const isHold = action === "HOLD";
                return (
                  <div key={i} style={{
                    padding: "5px 0",
                    borderBottom: "1px solid var(--border)",
                    opacity: isHold ? 0.5 : 1,
                    fontSize: 12,
                    display: "flex", gap: 8, alignItems: "center",
                  }}>
                    <span style={{ fontSize: 10, color: "var(--text-muted)", minWidth: 45 }}>
                      {fmtLocalTimeShort(t.timestamp)}
                    </span>
                    <span className={`tag ${action.toLowerCase()}`} style={{ minWidth: 32, textAlign: "center" }}>{action}</span>
                    <span>{fmtPrice(t.price)}</span>
                    {action !== "HOLD" && (
                      <span style={{ color: stratColor, fontSize: 10, fontWeight: 600 }}>
                        {(t.strategy || "").slice(0, 6)}
                      </span>
                    )}
                    <EntryTag type={t.entry_type} />
                    {action === "SELL" && <PnlValue pnl={pnl} size="small" />}
                    {isHold && t.reason && (
                      <span style={{ fontSize: 10, color: "var(--text-muted)", fontStyle: "italic" }}>
                        — {(t.reason || "no edge").slice(0, 40)}
                      </span>
                    )}
                    <span style={{ fontSize: 9, color: "var(--text-muted)", marginLeft: "auto" }}>
                      S:{t.score || "—"}
                    </span>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}

      {/* Load More */}
      {hasMore && (
        <div style={{ textAlign: "center", marginTop: 12 }}>
          <button
            onClick={() => fetchTrades(false)}
            disabled={loading}
            style={{
              padding: "8px 24px", background: "var(--surface)", border: "1px solid var(--border)",
              borderRadius: 5, color: "var(--text)", fontSize: 12, cursor: "pointer",
            }}
          >
            {loading ? "Loading..." : `Load More (${total - trades.length} remaining)`}
          </button>
        </div>
      )}
    </>
  );
}

/* ─── Reusable style helpers ─── */
function toggleBtn(active) {
  return {
    padding: "4px 10px", borderRadius: 4, border: `1px solid ${active ? "var(--blue)" : "var(--border)"}`,
    background: active ? "rgba(59,130,246,0.15)" : "var(--surface)",
    color: active ? "var(--blue)" : "var(--text-muted)",
    fontSize: 11, fontWeight: 600, cursor: "pointer",
  };
}

function FilterPill({ label, active, onClick, color }) {
  return (
    <button onClick={onClick} style={{
      padding: "3px 10px", borderRadius: 12, fontSize: 10, fontWeight: 600, cursor: "pointer",
      border: `1px solid ${active ? (color || "var(--blue)") : "var(--border)"}`,
      background: active ? `${color || "var(--blue)"}22` : "transparent",
      color: active ? (color || "var(--blue)") : "var(--text-muted)",
    }}>
      {label}
    </button>
  );
}

const selectStyle = {
  padding: "3px 8px", borderRadius: 4, fontSize: 10, fontWeight: 600,
  border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)",
  cursor: "pointer",
};
