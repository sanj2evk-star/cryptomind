import {
  ResponsiveContainer,
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from "recharts";
import { useApi } from "../hooks/useApi";

/**
 * Equity curve with drawdown shading.
 * Handles: loading (spinner), error (message), empty (hint), success (chart).
 */
export default function EquityChart() {
  const { data, loading, error } = useApi("/equity?limit=500", 30000);

  if (loading) {
    return (
      <div className="chart-wrap" style={{ textAlign: "center", padding: 32 }}>
        <div className="spinner" style={{ margin: "0 auto 8px" }} />
        <p style={{ color: "var(--text-muted)", fontSize: 13 }}>Loading equity chart...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="chart-wrap" style={{ textAlign: "center", padding: 24 }}>
        <p style={{ color: "var(--text-muted)", fontSize: 13 }}>
          {error === "Backend unavailable" ? "Chart unavailable — backend is down." : `Chart error: ${error}`}
        </p>
      </div>
    );
  }

  const raw = data?.equity || [];
  if (raw.length < 2) {
    return (
      <div className="chart-wrap" style={{ textAlign: "center", padding: 24 }}>
        <p style={{ color: "var(--text-muted)", fontSize: 13 }}>
          Equity chart will appear after a few trading cycles.
        </p>
      </div>
    );
  }

  let peak = 0;
  const points = raw.map((d) => {
    const equity = parseFloat(d.total_equity) || 0;
    if (equity > peak) peak = equity;
    return {
      time: d.timestamp?.slice(5, 16) || "",
      equity,
      peak,
      drawdown: -(peak - equity),
    };
  });

  const startEquity = points[0].equity;

  return (
    <div className="chart-wrap">
      <h3>Equity Curve</h3>
      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart data={points} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2a2d3a" />
          <XAxis dataKey="time" tick={{ fontSize: 10, fill: "#8b8fa3" }} interval="preserveStartEnd" />
          <YAxis yAxisId="equity" tick={{ fontSize: 11, fill: "#8b8fa3" }} domain={["auto", "auto"]} tickFormatter={(v) => `$${v.toFixed(2)}`} />
          <YAxis yAxisId="dd" orientation="right" tick={{ fontSize: 11, fill: "#8b8fa3" }} domain={["auto", 0]} tickFormatter={(v) => `$${v.toFixed(3)}`} />
          <Tooltip
            contentStyle={{ background: "#1a1d27", border: "1px solid #2a2d3a", fontSize: 12 }}
            formatter={(value, name) => {
              if (name === "equity") return [`$${value.toFixed(4)}`, "Equity"];
              if (name === "peak") return [`$${value.toFixed(4)}`, "Peak"];
              if (name === "drawdown") return [`$${Math.abs(value).toFixed(4)}`, "Drawdown"];
              return [value, name];
            }}
          />
          <ReferenceLine yAxisId="equity" y={startEquity} stroke="#8b8fa3" strokeDasharray="6 3" />
          <Area yAxisId="dd" type="monotone" dataKey="drawdown" fill="rgba(239, 68, 68, 0.15)" stroke="none" />
          <Line yAxisId="equity" type="monotone" dataKey="peak" stroke="#8b8fa3" strokeWidth={1} strokeDasharray="4 4" dot={false} />
          <Line yAxisId="equity" type="monotone" dataKey="equity" stroke="#3b82f6" strokeWidth={2} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
