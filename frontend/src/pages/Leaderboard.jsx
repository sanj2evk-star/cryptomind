import { useApi } from "../hooks/useApi";
import { fmtLocalTime, getTimezoneLabel } from "../hooks/useTime";
import { Loading, ErrorBox, EmptyState } from "../components/StatusMessage";

const TZ = getTimezoneLabel();

function fmt(n) {
  return `$${Number(n ?? 0).toFixed(4)}`;
}

/* Rank medal */
function Medal({ rank }) {
  const medals = { 1: "🥇", 2: "🥈", 3: "🥉" };
  return <span style={{ fontSize: 18 }}>{medals[rank] || `#${rank}`}</span>;
}

/* Strategy status dot */
function StatusDot({ action }) {
  const colors = { BUY: "var(--green)", SELL: "var(--red)", HOLD: "var(--text-muted)" };
  return (
    <span style={{
      display: "inline-block", width: 8, height: 8, borderRadius: "50%",
      background: colors[action] || "var(--text-muted)",
    }} />
  );
}

export default function Leaderboard() {
  const { data, loading, error, retry } = useApi("/leaderboard", 10000);

  if (loading && !data) return <><h1>Strategy Leaderboard</h1><Loading message="Loading strategies..." /></>;
  if (error && !data) return <><h1>Strategy Leaderboard</h1><ErrorBox message={error} onRetry={retry} /></>;

  const board = data?.leaderboard || [];
  const strategies = data?.strategies || {};
  const mkt = data?.market_state || {};
  const cycle = data?.cycle ?? 0;

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20, flexWrap: "wrap", gap: 10 }}>
        <h1 style={{ margin: 0 }}>Strategy Leaderboard</h1>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          Cycle #{cycle} | Market: {mkt.state || "—"}
        </span>
      </div>

      <p style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 20 }}>
        5 strategies compete in parallel. Same market, different rules. Best performer wins.
      </p>

      {/* Leaderboard Table */}
      {board.length > 0 ? (
        <div className="table-wrap" style={{ marginBottom: 24 }}>
          <table>
            <thead>
              <tr>
                <th>Rank</th>
                <th>Strategy</th>
                <th>Return</th>
                <th>Equity</th>
                <th>Trades</th>
                <th>Win Rate</th>
                <th>Drawdown</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {board.map((s) => {
                const ret = s.total_return ?? 0;
                return (
                  <tr key={s.strategy} style={s.rank === 1 ? { background: "rgba(234, 179, 8, 0.05)" } : {}}>
                    <td><Medal rank={s.rank} /></td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ width: 4, height: 24, borderRadius: 2, background: s.color, flexShrink: 0 }} />
                        <div>
                          <div style={{ fontWeight: 600, fontSize: 13 }}>{s.label}</div>
                          <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{s.strategy}</div>
                        </div>
                      </div>
                    </td>
                    <td style={{ fontWeight: 700, color: ret >= 0 ? "var(--green)" : "var(--red)" }}>
                      {ret >= 0 ? "+" : ""}{ret.toFixed(2)}%
                    </td>
                    <td>{fmt(s.equity)}</td>
                    <td>{s.total_trades}</td>
                    <td>{s.win_rate.toFixed(0)}%</td>
                    <td style={{ color: s.max_drawdown > 5 ? "var(--red)" : "var(--text-muted)" }}>
                      {s.max_drawdown.toFixed(1)}%
                    </td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <StatusDot action={s.last_action} />
                        <span style={{ fontSize: 11 }}>{s.last_action}</span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="Waiting for data" message="Strategies will appear after the first cycle." />
      )}

      {/* Strategy Detail Cards */}
      <h3 style={{ color: "var(--text-muted)", marginBottom: 12 }}>Strategy Details</h3>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14 }}>
        {Object.entries(strategies).map(([name, s]) => {
          const profile = s.profile || {};
          const boardEntry = board.find(b => b.strategy === name) || {};
          return (
            <div key={name} className="card" style={{ borderLeft: `3px solid ${PROFILES_COLORS[name] || "var(--border)"}` }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 14 }}>{boardEntry.label || name}</div>
                  <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
                    BUY &gt;{profile.buy_threshold} | SELL &lt;{profile.sell_threshold} | Size: {((profile.position_pct || 0) * 100).toFixed(0)}%
                  </div>
                </div>
                <Medal rank={boardEntry.rank || "—"} />
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, fontSize: 12 }}>
                <div>
                  <span style={{ color: "var(--text-muted)" }}>Equity: </span>
                  <span style={{ fontWeight: 600 }}>{fmt(s.equity)}</span>
                </div>
                <div>
                  <span style={{ color: "var(--text-muted)" }}>P&L: </span>
                  <span style={{ fontWeight: 600, color: s.realized_pnl >= 0 ? "var(--green)" : "var(--red)" }}>
                    {fmt(s.realized_pnl)}
                  </span>
                </div>
                <div>
                  <span style={{ color: "var(--text-muted)" }}>Trades: </span>{s.total_trades}
                </div>
                <div>
                  <span style={{ color: "var(--text-muted)" }}>Last: </span>
                  <span className={`tag ${(s.last_action || "hold").toLowerCase()}`}>{s.last_action}</span>
                </div>
              </div>

              {s.last_reason && (
                <div style={{ marginTop: 6, fontSize: 11, color: "var(--text-muted)", fontStyle: "italic" }}>
                  {s.last_reason}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

// Color map for strategy cards
const PROFILES_COLORS = {
  MONK: "#8b5cf6",
  HUNTER: "#3b82f6",
  AGGRESSIVE: "#ef4444",
  DEFENSIVE: "#22c55e",
  EXPERIMENTAL: "#eab308",
};
