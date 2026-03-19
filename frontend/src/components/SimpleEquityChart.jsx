import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

/**
 * Simple equity line chart for the dashboard.
 * Renders only if data is available. Returns null otherwise.
 * No internal data fetching — receives data as a prop.
 */
export default function SimpleEquityChart({ equity }) {
  if (!equity || equity.length < 2) return null;

  const points = equity.map((d) => ({
    time: (d.timestamp || "").slice(5, 16),
    value: parseFloat(d.total_equity) || 0,
  }));

  const min = Math.min(...points.map((p) => p.value));
  const max = Math.max(...points.map((p) => p.value));
  const pad = (max - min) * 0.1 || 0.01;

  return (
    <div className="chart-wrap">
      <h3>Equity Curve</h3>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={points} margin={{ top: 5, right: 16, bottom: 5, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2a2d3a" />
          <XAxis
            dataKey="time"
            tick={{ fontSize: 10, fill: "#8b8fa3" }}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fontSize: 11, fill: "#8b8fa3" }}
            domain={[min - pad, max + pad]}
            tickFormatter={(v) => `$${v.toFixed(2)}`}
          />
          <Tooltip
            contentStyle={{ background: "#1a1d27", border: "1px solid #2a2d3a", fontSize: 12 }}
            formatter={(v) => [`$${v.toFixed(4)}`, "Equity"]}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke="#3b82f6"
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
