import { useState } from "react";
import { useApi } from "../hooks/useApi";
import { Loading, ErrorBox, EmptyState } from "../components/StatusMessage";

const API = import.meta.env.VITE_API_URL || window.location.origin;

function fmt(n) { return `$${Number(n ?? 0).toFixed(4)}`; }
function Medal({ rank }) {
  const m = { 1: "🥇", 2: "🥈", 3: "🥉" };
  return <span style={{ fontSize: 16 }}>{m[rank] || `#${rank}`}</span>;
}

/* Status badge with colors for all states */
function StatusBadge({ status }) {
  const cfg = {
    LEADING:  { bg: "#eab30822", color: "#eab308", label: "★ LEADING" },
    ACTIVE:   { bg: "#22c55e22", color: "#22c55e", label: "ACTIVE" },
    PAUSED:   { bg: "#f59e0b22", color: "#f59e0b", label: "⏸ PAUSED" },
    INACTIVE: { bg: "#ef444422", color: "#ef4444", label: "☠ KILLED" },
  };
  const c = cfg[status] || cfg.ACTIVE;
  return (
    <span style={{ display: "inline-block", padding: "2px 6px", borderRadius: 3, fontSize: 9, fontWeight: 700, background: c.bg, color: c.color }}>
      {c.label}
    </span>
  );
}

/* Control buttons */
function StrategyControls({ name, status, onAction }) {
  const [busy, setBusy] = useState(false);

  const act = async (action) => {
    setBusy(true);
    try {
      await fetch(`${API}/strategy/${name.toLowerCase()}/${action}`, { method: "POST" });
      onAction();
    } finally {
      setTimeout(() => setBusy(false), 500);
    }
  };

  if (busy) return <span style={{ fontSize: 10, color: "var(--text-muted)" }}>...</span>;

  return (
    <div style={{ display: "flex", gap: 3 }}>
      {status === "ACTIVE" || status === "LEADING" ? (
        <>
          <button onClick={() => act("pause")} style={btnStyle("#f59e0b")}>Pause</button>
          <button onClick={() => act("kill")} style={btnStyle("#ef4444")}>Kill</button>
        </>
      ) : status === "PAUSED" ? (
        <>
          <button onClick={() => act("resume")} style={btnStyle("#22c55e")}>Resume</button>
          <button onClick={() => act("kill")} style={btnStyle("#ef4444")}>Kill</button>
        </>
      ) : (
        <button onClick={() => act("resume")} style={btnStyle("#22c55e")}>Revive</button>
      )}
    </div>
  );
}

const btnStyle = (color) => ({
  padding: "2px 8px", border: `1px solid ${color}44`, borderRadius: 3,
  background: `${color}15`, color, fontSize: 10, fontWeight: 600,
  cursor: "pointer", lineHeight: 1.4,
});

export default function Leaderboard() {
  const { data, loading, error, retry } = useApi("/leaderboard", 8000);

  if (loading && !data) return <><h1>Strategy Lab</h1><Loading message="Loading strategies..." /></>;
  if (error && !data) return <><h1>Strategy Lab</h1><ErrorBox message={error} onRetry={retry} /></>;

  const board = data?.leaderboard || [];
  const strategies = data?.strategies || {};
  const mkt = data?.market_state || {};
  const cycle = data?.cycle ?? 0;
  const primary = data?.primary_strategy || "";
  const allocations = data?.allocations || {};
  const events = data?.event_log || [];

  const gp = data?.global_portfolio || {};
  const activeCount = board.filter(s => s.status === "ACTIVE" || s.status === "LEADING").length;
  const totalStrategies = board.length;

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <h1 style={{ margin: 0, fontSize: 17 }}>Strategy Lab</h1>
          <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
            {activeCount}/{totalStrategies} active · Cycle #{cycle} · Market: {mkt.state || "—"}
          </span>
        </div>
      </div>

      {/* Global Portfolio Strip */}
      <div style={{ display: "flex", gap: 16, marginBottom: 10, fontSize: 12 }}>
        <div><span style={{ color: "var(--text-muted)" }}>Portfolio: </span><b>${(gp.total_equity ?? 100).toFixed(2)}</b></div>
        <div><span style={{ color: "var(--text-muted)" }}>Cash: </span><b>${(gp.cash ?? 100).toFixed(2)}</b></div>
        <div><span style={{ color: "var(--text-muted)" }}>BTC in positions: </span><b>{(gp.btc_in_positions ?? 0).toFixed(6)}</b></div>
        <div style={{ color: "var(--text-muted)", fontSize: 10 }}>
          Single $100 pool · {totalStrategies} strategies · {activeCount} active
        </div>
      </div>

      {/* Leaderboard Table */}
      {board.length > 0 ? (
        <div className="table-wrap" style={{ marginBottom: 12 }}>
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Strategy</th>
                <th>Return</th>
                <th>Capital</th>
                <th>V.Equity</th>
                <th>Trades</th>
                <th>Win%</th>
                <th>DD</th>
                <th>Alloc</th>
                <th>Status</th>
                <th>Controls</th>
              </tr>
            </thead>
            <tbody>
              {board.map((s) => {
                const ret = s.total_return ?? 0;
                const dimmed = s.status === "INACTIVE" || s.status === "PAUSED";
                return (
                  <tr key={s.strategy} style={{
                    background: s.rank === 1 ? "rgba(234, 179, 8, 0.04)" : undefined,
                    opacity: dimmed ? 0.5 : 1,
                  }}>
                    <td><Medal rank={s.rank} /></td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span style={{ width: 3, height: 20, borderRadius: 2, background: s.color, flexShrink: 0 }} />
                        <div>
                          <div style={{ fontWeight: 600, fontSize: 12 }}>{s.label}</div>
                          <div style={{ fontSize: 9, color: "var(--text-muted)" }}>{s.desc || s.strategy}</div>
                        </div>
                      </div>
                    </td>
                    <td style={{ fontWeight: 700, color: ret >= 0 ? "var(--green)" : "var(--red)" }}>
                      {ret >= 0 ? "+" : ""}{ret.toFixed(2)}%
                    </td>
                    <td style={{ color: "var(--text-muted)" }}>${(s.allocated_capital ?? 0).toFixed(2)}</td>
                    <td>{fmt(s.equity)}</td>
                    <td>{s.total_trades}</td>
                    <td>{s.win_rate?.toFixed(0) ?? 0}%</td>
                    <td style={{ color: s.max_drawdown > 5 ? "var(--red)" : "var(--text-muted)" }}>
                      {s.max_drawdown?.toFixed(1) ?? 0}%
                    </td>
                    <td style={{ fontSize: 11 }}>{(s.allocation_pct ?? 0).toFixed(0)}%</td>
                    <td><StatusBadge status={s.status} /></td>
                    <td><StrategyControls name={s.strategy} status={s.status} onAction={retry} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Waiting for data" message="Strategies will appear after the first cycle." />
      )}

      {/* Allocation Chart */}
      {Object.keys(allocations).length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <h3 style={{ color: "var(--text-muted)", marginBottom: 8, fontSize: 13 }}>Capital Allocation</h3>
          <div className="card" style={{ padding: "8px 12px" }}>
            <div style={{ display: "flex", borderRadius: 4, overflow: "hidden", height: 24, marginBottom: 8 }}>
              {board.filter(s => (s.allocation_pct ?? 0) > 0).map((s) => (
                <div key={s.strategy} style={{
                  width: `${s.allocation_pct}%`, background: s.color || "#666",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 9, fontWeight: 700, color: "#fff", transition: "width 0.5s",
                }}>
                  {(s.allocation_pct ?? 0) >= 8 ? `${(s.allocation_pct ?? 0).toFixed(0)}%` : ""}
                </div>
              ))}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10, justifyContent: "center" }}>
              {board.map((s) => (
                <div key={s.strategy} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: s.color || "#666" }} />
                  <span style={{ color: "var(--text-muted)" }}>{s.label}</span>
                  <span style={{ fontWeight: 600 }}>{(s.allocation_pct ?? 0).toFixed(0)}%</span>
                  {s.status === "PAUSED" && <span style={{ fontSize: 8, color: "#f59e0b" }}>⏸</span>}
                  {s.status === "INACTIVE" && <span style={{ fontSize: 8, color: "#ef4444" }}>☠</span>}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Strategy Cards Grid */}
      <h3 style={{ color: "var(--text-muted)", marginBottom: 8, fontSize: 13 }}>Strategy Details</h3>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 8, marginBottom: 12 }}>
        {Object.entries(strategies).map(([name, s]) => {
          const profile = s.profile || {};
          const boardEntry = board.find(b => b.strategy === name) || {};
          const dimmed = s.status === "INACTIVE" || s.status === "PAUSED";
          return (
            <div key={name} className="card" style={{
              borderLeft: `3px solid ${boardEntry.color || "var(--border)"}`,
              padding: "8px 10px", opacity: dimmed ? 0.5 : 1,
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 12 }}>{boardEntry.label || name}</div>
                  <div style={{ fontSize: 9, color: "var(--text-muted)" }}>
                    B&gt;{profile.buy_threshold} S&lt;{profile.sell_threshold} · {((profile.position_pct || 0) * 100).toFixed(0)}% size · CD:{profile.cooldown}s
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <StatusBadge status={s.status} />
                  <Medal rank={boardEntry.rank || "—"} />
                </div>
              </div>

              {/* Regime tags */}
              {boardEntry.regimes && (
                <div style={{ display: "flex", gap: 3, marginBottom: 4 }}>
                  {boardEntry.regimes.map(r => (
                    <span key={r} style={{
                      fontSize: 8, padding: "1px 4px", borderRadius: 2,
                      background: r === "BREAKOUT" ? "#ef444418" : r === "ACTIVE" ? "#22c55e18" : r === "WAKING_UP" ? "#eab30818" : "#6b728018",
                      color: r === "BREAKOUT" ? "#ef4444" : r === "ACTIVE" ? "#22c55e" : r === "WAKING_UP" ? "#eab308" : "#9ca3af",
                    }}>{r}</span>
                  ))}
                </div>
              )}

              {/* Entry condition */}
              <div style={{ marginBottom: 4, fontSize: 10 }}>
                <span style={{ color: "var(--text-muted)" }}>Entry: </span>
                <span style={{
                  fontWeight: 600,
                  color: boardEntry.entry_condition_met ? "var(--green)" : "var(--text-muted)",
                }}>
                  {boardEntry.entry_condition_met ? "✓ YES" : "✗ NO"}
                </span>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 3, fontSize: 11 }}>
                <div><span style={{ color: "var(--text-muted)" }}>Eq: </span><b>{fmt(s.equity)}</b></div>
                <div><span style={{ color: "var(--text-muted)" }}>PnL: </span><span style={{ color: s.realized_pnl >= 0 ? "var(--green)" : "var(--red)", fontWeight: 600 }}>{fmt(s.realized_pnl)}</span></div>
                <div><span style={{ color: "var(--text-muted)" }}>Trades: </span>{s.total_trades}</div>
                <div><span style={{ color: "var(--text-muted)" }}>Last: </span><span className={`tag ${(s.last_action || "hold").toLowerCase()}`}>{s.last_action}</span></div>
              </div>

              {s.last_reason && <div style={{ marginTop: 3, fontSize: 10, color: "var(--text-muted)", fontStyle: "italic" }}>{s.last_reason}</div>}

              {/* Controls */}
              <div style={{ marginTop: 4, borderTop: "1px solid var(--border)", paddingTop: 4 }}>
                <StrategyControls name={name} status={s.status} onAction={retry} />
              </div>
            </div>
          );
        })}
      </div>

      {/* Event Log */}
      {events.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <h3 style={{ color: "var(--text-muted)", marginBottom: 8, fontSize: 13 }}>Engine Events</h3>
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            {events.slice(0, 15).map((e, i) => {
              const colors = {
                strategy_switch: "#eab308", strategy_killed: "#ef4444", strategy_revived: "#22c55e",
                strategy_paused: "#f59e0b", strategy_resumed: "#22c55e", reallocation: "#3b82f6",
              };
              const icons = {
                strategy_switch: "🔄", strategy_killed: "💀", strategy_revived: "🔄",
                strategy_paused: "⏸", strategy_resumed: "▶", reallocation: "📊",
              };
              return (
                <div key={i} style={{
                  padding: "6px 10px", borderBottom: i < 14 ? "1px solid var(--border)" : "none",
                  display: "flex", gap: 8, alignItems: "center", fontSize: 11,
                }}>
                  <span style={{ fontSize: 12 }}>{icons[e.event] || "📋"}</span>
                  <span style={{ color: colors[e.event] || "var(--text-muted)", fontWeight: 600, minWidth: 80, fontSize: 10 }}>
                    {e.event?.replace(/_/g, " ").toUpperCase()}
                  </span>
                  <span style={{ color: "var(--text)" }}>
                    {e.strategy && `${e.strategy} `}
                    {e.from && e.to && `${e.from} → ${e.to} `}
                    {e.reason && `— ${e.reason}`}
                  </span>
                  <span style={{ marginLeft: "auto", color: "var(--text-muted)", fontSize: 9 }}>
                    {e.timestamp?.slice(11, 19)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {primary && (
        <p style={{ fontSize: 10, color: "var(--text-muted)", textAlign: "right" }}>
          Primary: <span style={{ color: "#eab308", fontWeight: 600 }}>{primary}</span> · Cycle #{cycle}
        </p>
      )}
    </>
  );
}
