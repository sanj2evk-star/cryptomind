import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import { useApi } from "../hooks/useApi";
import { Loading, ErrorBox, EmptyState } from "../components/StatusMessage";
import MetricCard from "../components/MetricCard";

const COLORS = { wins: "#22c55e", losses: "#ef4444" };

export default function Performance() {
  const { data: perf, loading: pLoading, error: pError, retry: pRetry } = useApi("/performance", 30000);
  const { data: stratData, loading: sLoading, error: sError } = useApi("/strategies");
  const { data: tradeData } = useApi("/trades?limit=100");

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

  const metrics = perf || {};
  const strategies = stratData?.strategies || [];
  const trades = tradeData?.trades || [];

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
      const r = t.market_condition || "unknown";
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

  // 4. Success state
  return (
    <>
      <h1>Performance</h1>

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
