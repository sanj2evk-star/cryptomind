import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from "recharts";

/**
 * Cumulative P&L area chart.
 * Shows running total of realized P&L over time.
 * Green fill when positive, red when negative.
 *
 * @param {Array} trades - trade dicts from /trades endpoint
 */
export default function CumulativePnl({ trades }) {
  if (!trades || trades.length === 0) {
    return <div className="loading">No data for cumulative P&L.</div>;
  }

  let cumulative = 0;
  const points = trades
    .filter((t) => t.action === "SELL")
    .map((t, i) => {
      cumulative += parseFloat(t.pnl) || 0;
      return {
        trade: i + 1,
        time: (t.timestamp || "").slice(5, 16),
        cumPnl: parseFloat(cumulative.toFixed(4)),
      };
    });

  if (points.length < 2) {
    return <div className="loading">Need at least 2 completed trades.</div>;
  }

  const final = points[points.length - 1].cumPnl;

  return (
    <div className="chart-wrap">
      <h3>Cumulative P&L</h3>
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={points} margin={{ top: 10, right: 20, bottom: 10, left: 10 }}>
          <defs>
            <linearGradient id="cumGreen" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#22c55e" stopOpacity={0.3} />
              <stop offset="100%" stopColor="#22c55e" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="cumRed" x1="0" y1="1" x2="0" y2="0">
              <stop offset="0%" stopColor="#ef4444" stopOpacity={0.3} />
              <stop offset="100%" stopColor="#ef4444" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#2a2d3a" />
          <XAxis
            dataKey="trade"
            tick={{ fontSize: 10, fill: "#8b8fa3" }}
            label={{ value: "Trade #", position: "bottom", fill: "#8b8fa3", fontSize: 11 }}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "#8b8fa3" }}
            tickFormatter={(v) => `$${v.toFixed(3)}`}
          />
          <Tooltip
            contentStyle={{ background: "#1a1d27", border: "1px solid #2a2d3a", fontSize: 12 }}
            formatter={(v) => [`$${v.toFixed(4)}`, "Cumulative P&L"]}
            labelFormatter={(idx) => {
              const pt = points[idx - 1];
              return pt ? pt.time : `#${idx}`;
            }}
          />
          <ReferenceLine y={0} stroke="#8b8fa3" strokeDasharray="6 3" />
          <Area
            type="monotone"
            dataKey="cumPnl"
            stroke={final >= 0 ? "#22c55e" : "#ef4444"}
            strokeWidth={2}
            fill={final >= 0 ? "url(#cumGreen)" : "url(#cumRed)"}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
