import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Cell,
  ReferenceLine,
} from "recharts";

/**
 * Bar chart of per-trade P&L.
 * Green bars = profit, red bars = loss.
 *
 * @param {Array} trades - trade dicts from /trades endpoint
 */
export default function PnlBarChart({ trades }) {
  if (!trades || trades.length === 0) {
    return <div className="loading">No P&L data to chart.</div>;
  }

  // Only include trades with non-zero P&L (SELLs)
  const bars = trades
    .filter((t) => t.action === "SELL")
    .map((t, i) => ({
      index: i + 1,
      time: (t.timestamp || "").slice(5, 16),
      pnl: parseFloat(t.pnl) || 0,
      strategy: t.strategy || "unknown",
      regime: t.market_condition || "unknown",
    }));

  if (bars.length === 0) {
    return <div className="loading">No completed trades to chart.</div>;
  }

  return (
    <div className="chart-wrap">
      <h3>Per-Trade P&L</h3>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={bars} margin={{ top: 10, right: 20, bottom: 10, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2a2d3a" />
          <XAxis
            dataKey="index"
            tick={{ fontSize: 10, fill: "#8b8fa3" }}
            label={{ value: "Trade #", position: "bottom", fill: "#8b8fa3", fontSize: 11 }}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "#8b8fa3" }}
            tickFormatter={(v) => `$${v.toFixed(3)}`}
          />
          <Tooltip
            contentStyle={{ background: "#1a1d27", border: "1px solid #2a2d3a", fontSize: 12 }}
            formatter={(v) => [`$${v.toFixed(4)}`, "P&L"]}
            labelFormatter={(idx) => {
              const bar = bars[idx - 1];
              return bar ? `${bar.time} | ${bar.strategy} | ${bar.regime}` : `#${idx}`;
            }}
          />
          <ReferenceLine y={0} stroke="#8b8fa3" />
          <Bar dataKey="pnl" radius={[4, 4, 0, 0]}>
            {bars.map((b, i) => (
              <Cell
                key={i}
                fill={b.pnl >= 0 ? "rgba(34, 197, 94, 0.8)" : "rgba(239, 68, 68, 0.8)"}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
