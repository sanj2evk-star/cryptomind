import {
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Cell,
} from "recharts";

/**
 * Scatter chart of trades: price on Y-axis, time on X-axis.
 * Green dots = BUY, Red dots = SELL, size = |P&L|.
 *
 * @param {Array} trades - trade dicts from /trades endpoint
 */
export default function TradeScatter({ trades }) {
  if (!trades || trades.length === 0) {
    return <div className="loading">No trades to chart.</div>;
  }

  const buys = [];
  const sells = [];

  trades.forEach((t, i) => {
    const point = {
      index: i,
      time: (t.timestamp || "").slice(5, 16),
      price: parseFloat(t.price) || 0,
      pnl: parseFloat(t.pnl) || 0,
      size: Math.max(Math.abs(parseFloat(t.pnl) || 0) * 2000 + 30, 30),
    };
    if (t.action === "BUY") buys.push(point);
    else if (t.action === "SELL") sells.push(point);
  });

  if (buys.length === 0 && sells.length === 0) {
    return <div className="loading">No BUY/SELL trades to chart.</div>;
  }

  return (
    <div className="chart-wrap">
      <h3>Trade Map</h3>
      <ResponsiveContainer width="100%" height={300}>
        <ScatterChart margin={{ top: 10, right: 20, bottom: 10, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2a2d3a" />
          <XAxis
            dataKey="index"
            type="number"
            tick={{ fontSize: 10, fill: "#8b8fa3" }}
            label={{ value: "Trade #", position: "bottom", fill: "#8b8fa3", fontSize: 11 }}
          />
          <YAxis
            dataKey="price"
            type="number"
            tick={{ fontSize: 11, fill: "#8b8fa3" }}
            tickFormatter={(v) => `$${v.toLocaleString()}`}
            domain={["auto", "auto"]}
          />
          <Tooltip
            contentStyle={{ background: "#1a1d27", border: "1px solid #2a2d3a", fontSize: 12 }}
            formatter={(value, name) => {
              if (name === "price") return [`$${value.toLocaleString()}`, "Price"];
              return [value, name];
            }}
            labelFormatter={(idx) => {
              const all = [...buys, ...sells].find((p) => p.index === idx);
              return all ? all.time : `#${idx}`;
            }}
          />
          <Scatter name="BUY" data={buys} fill="#22c55e">
            {buys.map((b, i) => (
              <Cell key={i} r={Math.sqrt(b.size)} />
            ))}
          </Scatter>
          <Scatter name="SELL" data={sells} fill="#ef4444">
            {sells.map((s, i) => (
              <Cell key={i} r={Math.sqrt(s.size)} />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
