import { useState, useMemo } from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  PieChart,
  Pie,
  Cell,
  ReferenceLine,
} from "recharts";
import { useApi } from "../hooks/useApi";
import { fmtLocalTimeShort } from "../hooks/useTime";
import { Loading, ErrorBox, EmptyState } from "../components/StatusMessage";
import MetricCard from "../components/MetricCard";
import ScopeToggle from "../components/ScopeToggle";
import ChartContainer from "../components/ChartContainer";

const _isTouch = typeof window !== "undefined" && ("ontouchstart" in window || navigator.maxTouchPoints > 0);

const COLORS = { wins: "#22c55e", losses: "#ef4444" };

/* Confidence dot: low=grey, medium=amber, high=green */
const CONF_DOT = { low: "#6b7280", medium: "#eab308", high: "#22c55e" };
function ConfDot({ level }) {
  const c = CONF_DOT[level] || CONF_DOT.low;
  return (
    <span title={`${level} confidence`} style={{
      width: 7, height: 7, borderRadius: "50%", background: c,
      flexShrink: 0, display: "inline-block",
    }} />
  );
}

export default function Performance() {
  const [scope, setScope] = useState("session");
  const [showDrawdown, setShowDrawdown] = useState(!_isTouch); // default open on desktop, closed on iPad

  const { data: scopedData, loading: pLoading, error: pError, retry: pRetry } = useApi(`/v7/performance/scoped?scope=${scope}`, 15000);
  const { data: stratData, loading: sLoading, error: sError } = useApi("/strategies");
  const { data: tradeData } = useApi(`/v7/trades/scoped?scope=${scope}&limit=100`, 30000);
  const { data: patternsData } = useApi("/v7/mind/patterns", 60000);
  const { data: equityData } = useApi(`/v7/performance/equity?scope=${scope}&max_points=400`, 15000);

  // 1. Loading state
  if (pLoading || sLoading) return <><h1>Performance</h1><Loading message="Loading performance..." /></>;

  // 2. Error state
  const anyError = pError || sError;
  if (anyError) {
    return (
      <>
        <h1>Performance</h1>
        <ErrorBox message={anyError} onRetry={pRetry} />
      </>
    );
  }

  const scopedStats = scopedData?.stats || {};
  const metrics = {
    total_trades: scopedStats.total || 0,
    wins: scopedStats.wins || 0,
    losses: scopedStats.losses || 0,
    win_rate: scopedStats.win_rate || 0,
    total_pnl: scopedStats.total_pnl || 0,
    max_drawdown: 0,
  };
  const strategies = stratData?.strategies || [];
  const trades = tradeData?.trades || [];
  const patterns = patternsData || {};

  const pieData = [
    { name: "Wins", value: metrics.wins || 0 },
    { name: "Losses", value: metrics.losses || 0 },
  ].filter((d) => d.value > 0);

  const fitnessData = strategies.map((s) => ({
    name: s.name.replace("EMA ", "").replace(" RSI ", " / RSI "),
    fitness: s.fitness || 0,
    live_score: s.live_score || 0,
  }));

  const regimeMap = {};
  trades
    .filter((t) => t.action === "SELL")
    .forEach((t) => {
      const r = t.regime || t.market_condition || "unknown";
      if (!regimeMap[r]) regimeMap[r] = 0;
      regimeMap[r] += parseFloat(t.pnl) || 0;
    });
  const regimeData = Object.entries(regimeMap).map(([name, pnl]) => ({
    name,
    pnl: parseFloat(pnl.toFixed(4)),
  }));

  // 3. Empty state
  const hasData = (metrics.total_trades || 0) > 0 || strategies.length > 0;
  if (!hasData) {
    return (
      <>
        <h1>Performance</h1>
        <div className="card-grid">
          <MetricCard label="Trades Today" value="0" />
          <MetricCard label="Win Rate" value="0%" />
          <MetricCard label="P&L Today" value="$0.0000" />
          <MetricCard label="Max Drawdown" value="$0.0000" />
        </div>
        <EmptyState
          title="No performance data yet"
          message="Run the optimizer or a trading cycle to see metrics."
        />
      </>
    );
  }

  // Scoped stats display
  const sTrades = scopedStats.total || 0;
  const sWins = scopedStats.wins || 0;
  const sLosses = scopedStats.losses || 0;
  const sWinRate = scopedStats.win_rate || 0;
  const sPnl = scopedStats.total_pnl || 0;
  const sBest = scopedStats.best_trade || 0;
  const sWorst = scopedStats.worst_trade || 0;

  // Top strengths + mistakes from pattern engine
  const topStrengths = (patterns.top_strengths || []).slice(0, 3);
  const topMistakes = (patterns.top_mistakes || []).slice(0, 3);

  // 4. Success state
  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ margin: 0 }}>Performance</h1>
        <ScopeToggle value={scope} onChange={setScope} />
      </div>

      {/* Today's metrics (always shown) */}
      <div className="card-grid">
        <MetricCard label="Trades Today" value={metrics.total_trades || 0} />
        <MetricCard
          label="Win Rate"
          value={`${metrics.win_rate || 0}%`}
          color={(metrics.win_rate || 0) >= 50 ? "green" : "red"}
        />
        <MetricCard
          label="P&L Today"
          value={`$${(metrics.total_pnl || 0).toFixed(4)}`}
          color={(metrics.total_pnl || 0) >= 0 ? "green" : "red"}
        />
        <MetricCard
          label="Max Drawdown"
          value={`$${(metrics.max_drawdown || 0).toFixed(4)}`}
          color="red"
        />
      </div>

      {/* Scoped summary bar */}
      {sTrades > 0 && (
        <div style={{
          display: "flex", gap: 16, flexWrap: "wrap", padding: "10px 16px",
          background: "var(--surface)", border: "1px solid var(--border)",
          borderRadius: 8, marginBottom: 16, alignItems: "center",
        }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase" }}>
            {scope}
          </span>
          <span style={{ fontSize: 12 }}>
            <b>{sTrades}</b> <span style={{ color: "var(--text-muted)" }}>closed</span>
          </span>
          <span style={{ fontSize: 12 }}>
            <b style={{ color: sWinRate >= 50 ? "var(--green)" : "var(--red)" }}>{sWinRate}%</b>
            <span style={{ color: "var(--text-muted)" }}> win rate</span>
          </span>
          <span style={{ fontSize: 12 }}>
            P&L: <b style={{ color: sPnl >= 0 ? "var(--green)" : "var(--red)" }}>${sPnl.toFixed(4)}</b>
          </span>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            W: <b style={{ color: "var(--green)" }}>{sWins}</b> / L: <b style={{ color: "var(--red)" }}>{sLosses}</b>
          </span>
          {sBest > 0 && (
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
              Best: <span style={{ color: "var(--green)" }}>${sBest.toFixed(4)}</span>
              {sWorst < 0 && <> · Worst: <span style={{ color: "var(--red)" }}>${sWorst.toFixed(4)}</span></>}
            </span>
          )}
        </div>
      )}

      {/* ── v7.7.3: Equity Curve + Drawdown ── */}
      {equityData && !equityData.warming_up && equityData.points?.length > 2 && (() => {
        const pts = equityData.points;
        const st = equityData.stats || {};
        const refills = equityData.refill_markers || [];
        const versions = equityData.version_markers || [];
        const fmtTick = (ts) => { try { return new Date(ts).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}); } catch { return ""; } };
        const pnlColor = st.pnl_change >= 0 ? "var(--green)" : "var(--red)";
        const organicColor = st.organic_pnl >= 0 ? "var(--green)" : "var(--red)";
        return (
          <>
            {/* Summary cards */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 8, marginBottom: 12 }}>
              {[
                { label: "Start", value: `$${st.start_equity?.toFixed(2)}` },
                { label: "End", value: `$${st.end_equity?.toFixed(2)}` },
                { label: "Peak", value: `$${st.peak_equity?.toFixed(2)}`, color: "var(--green)" },
                { label: "Max DD", value: `${st.max_drawdown_pct?.toFixed(1)}%`, color: "var(--red)" },
                { label: "DD Duration", value: `${st.max_drawdown_duration_hours}h` },
                { label: "Underwater", value: `${st.time_underwater_pct}%` },
                { label: "Capital In", value: `$${st.total_capital_injected?.toFixed(0)}` },
                { label: "Organic P&L", value: `$${st.organic_pnl?.toFixed(4)}`, color: organicColor },
                { label: "Current DD", value: `${st.current_drawdown_pct?.toFixed(1)}%`, color: st.current_drawdown_pct > 0 ? "var(--red)" : "var(--green)" },
              ].map(c => (
                <div key={c.label} style={{
                  padding: "8px 10px", background: "var(--surface)", border: "1px solid var(--border)",
                  borderRadius: 6,
                }}>
                  <div style={{ fontSize: 9, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3 }}>{c.label}</div>
                  <div style={{ fontSize: 15, fontWeight: 600, color: c.color || "var(--text)", marginTop: 2 }}>{c.value}</div>
                </div>
              ))}
            </div>

            {/* Equity curve — Safari-safe via ChartContainer */}
            <ChartContainer height={_isTouch ? 240 : 260} expandable title="Equity Curve">
              {({ width, height }) => (
                <AreaChart width={width} height={height} data={pts} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
                  <defs>
                    <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/>
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.02}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a2d3a" />
                  <XAxis dataKey="timestamp" tickFormatter={fmtTick} tick={{ fontSize: 9, fill: "#8b8fa3" }} interval="preserveStartEnd" minTickGap={60} />
                  <YAxis tick={{ fontSize: 10, fill: "#8b8fa3" }} tickFormatter={v => `$${v.toFixed(1)}`} domain={["auto", "auto"]} />
                  <Tooltip
                    contentStyle={{ background: "#1a1d27", border: "1px solid #2a2d3a", fontSize: 11 }}
                    labelFormatter={ts => { try { return new Date(ts).toLocaleString(); } catch { return ts; } }}
                    formatter={(v, name) => [`$${Number(v).toFixed(4)}`, name === "equity" ? "Equity" : name === "organic_equity" ? "Organic" : name]}
                  />
                  <Area type="monotone" dataKey="equity" stroke="#3b82f6" fill="url(#eqGrad)" strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="organic_equity" stroke="#8b5cf6" strokeWidth={1} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="peak" stroke="#22c55e33" strokeWidth={1} strokeDasharray="2 4" dot={false} isAnimationActive={false} />
                  {refills.map((r, i) => (
                    <ReferenceLine key={`r${i}`} x={r.timestamp} stroke="#f59e0b" strokeDasharray="3 3" label={{ value: "$", fill: "#f59e0b", fontSize: 10, position: "top" }} />
                  ))}
                  {versions.map((v, i) => (
                    <ReferenceLine key={`v${i}`} x={v.timestamp} stroke="#8b5cf644" strokeDasharray="5 5" label={{ value: `v${v.version}`, fill: "#8b5cf6", fontSize: 8, position: "insideTopRight" }} />
                  ))}
                </AreaChart>
              )}
            </ChartContainer>

            {/* Drawdown chart (collapsible) */}
            <div style={{ marginBottom: 12 }}>
              <button onClick={() => setShowDrawdown(v => !v)} style={{
                background: "none", border: "none", cursor: "pointer", fontSize: 12,
                color: "var(--text-muted)", fontWeight: 600, padding: "4px 0", display: "flex", alignItems: "center", gap: 4,
              }}>
                {showDrawdown ? "▼" : "▶"} Drawdown Chart
              </button>
              {showDrawdown && (
                <ChartContainer height={160}>
                  {({ width, height }) => (
                    <AreaChart width={width} height={height} data={pts} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
                      <defs>
                        <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#ef4444" stopOpacity={0.4}/>
                          <stop offset="95%" stopColor="#ef4444" stopOpacity={0.05}/>
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#2a2d3a" />
                      <XAxis dataKey="timestamp" tickFormatter={fmtTick} tick={{ fontSize: 9, fill: "#8b8fa3" }} interval="preserveStartEnd" minTickGap={60} />
                      <YAxis tick={{ fontSize: 10, fill: "#8b8fa3" }} tickFormatter={v => `${v.toFixed(1)}%`} reversed domain={[0, "auto"]} />
                      <Tooltip
                        contentStyle={{ background: "#1a1d27", border: "1px solid #2a2d3a", fontSize: 11 }}
                        formatter={(v) => [`${Number(v).toFixed(2)}%`, "Drawdown"]}
                      />
                      <Area type="monotone" dataKey="drawdown_pct" stroke="#ef4444" fill="url(#ddGrad)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
                    </AreaChart>
                  )}
                </ChartContainer>
              )}
            </div>
          </>
        );
      })()}

      {/* Equity warming up message */}
      {equityData?.warming_up && (
        <div style={{
          padding: "16px 20px", marginBottom: 12, background: "var(--surface)",
          border: "1px solid var(--border)", borderRadius: 8, textAlign: "center",
          color: "var(--text-muted)", fontSize: 12,
        }}>
          {equityData.message || "Not enough equity history yet. Equity curve will appear once more cycles accumulate."}
        </div>
      )}

      {(pieData.length > 0 || regimeData.length > 0) && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 24 }}>
          {pieData.length > 0 && (
            <div className="chart-wrap">
              <h3>Win / Loss</h3>
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie
                    data={pieData} dataKey="value" nameKey="name"
                    cx="50%" cy="50%" outerRadius={80}
                    label={({ name, value }) => `${name}: ${value}`}
                  >
                    <Cell fill={COLORS.wins} />
                    <Cell fill={COLORS.losses} />
                  </Pie>
                  <Tooltip contentStyle={{ background: "#1a1d27", border: "1px solid #2a2d3a" }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}

          {regimeData.length > 0 && (
            <div className="chart-wrap">
              <h3>P&L by Regime</h3>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={regimeData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#2a2d3a" />
                  <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#8b8fa3" }} />
                  <YAxis tick={{ fontSize: 11, fill: "#8b8fa3" }} tickFormatter={(v) => `$${v.toFixed(3)}`} />
                  <Tooltip contentStyle={{ background: "#1a1d27", border: "1px solid #2a2d3a" }} formatter={(v) => [`$${v.toFixed(4)}`, "P&L"]} />
                  <Bar dataKey="pnl" radius={[4, 4, 0, 0]}>
                    {regimeData.map((d, i) => (
                      <Cell key={i} fill={d.pnl >= 0 ? COLORS.wins : COLORS.losses} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {/* Recurring Patterns (from pattern_insight_engine) */}
      {(topStrengths.length > 0 || topMistakes.length > 0) && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 24 }}>
          {topStrengths.length > 0 && (
            <div style={{
              padding: "14px 16px", background: "var(--surface)", border: "1px solid var(--border)",
              borderRadius: 8, borderLeft: "3px solid #22c55e",
            }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: "#22c55e", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 8 }}>
                Top Strengths
              </div>
              {topStrengths.map((s, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "3px 0" }}>
                  <ConfDot level={s.confidence} />
                  <span style={{ fontSize: 12, color: "var(--text)", flex: 1 }}>{s.label}</span>
                  <span style={{ fontSize: 10, color: "var(--text-muted)" }}>(seen {s.count}×)</span>
                </div>
              ))}
            </div>
          )}

          {topMistakes.length > 0 && (
            <div style={{
              padding: "14px 16px", background: "var(--surface)", border: "1px solid var(--border)",
              borderRadius: 8, borderLeft: "3px solid #ef4444",
            }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: "#ef4444", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 8 }}>
                Recurring Mistakes
              </div>
              {topMistakes.map((m, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "3px 0" }}>
                  <ConfDot level={m.confidence} />
                  <span style={{ fontSize: 12, color: "var(--text)", flex: 1 }}>{m.label}</span>
                  <span style={{ fontSize: 10, color: "var(--text-muted)" }}>(seen {m.count}×)</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {fitnessData.length > 0 && (
        <div className="chart-wrap">
          <h3>Strategy Fitness</h3>
          <ResponsiveContainer width="100%" height={Math.max(fitnessData.length * 40, 160)}>
            <BarChart data={fitnessData} layout="vertical" margin={{ left: 100 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2a2d3a" />
              <XAxis type="number" tick={{ fontSize: 11, fill: "#8b8fa3" }} />
              <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: "#8b8fa3" }} width={100} />
              <Tooltip contentStyle={{ background: "#1a1d27", border: "1px solid #2a2d3a" }} />
              <Bar dataKey="fitness" fill="#3b82f6" radius={[0, 4, 4, 0]} name="Fitness" />
              <Bar dataKey="live_score" fill="#8b5cf6" radius={[0, 4, 4, 0]} name="Live Score" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {strategies.length > 0 && (
        <div className="section">
          <h3 style={{ marginBottom: 12, color: "var(--text-muted)" }}>Strategies</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Name</th><th>Fitness</th><th>Live Score</th><th>Win Rate</th><th>Return</th></tr>
              </thead>
              <tbody>
                {strategies.map((s, i) => (
                  <tr key={i}>
                    <td>{s.name}</td>
                    <td>{(s.fitness || 0).toFixed(4)}</td>
                    <td>{(s.live_score || 0).toFixed(4)}</td>
                    <td>{s.metrics?.win_rate || 0}%</td>
                    <td style={{ color: (s.metrics?.return_pct || 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                      {(s.metrics?.return_pct || 0).toFixed(4)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
