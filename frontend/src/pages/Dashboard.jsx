import { useState, useCallback } from "react";
import { useApi } from "../hooks/useApi";
import { fmtLocalTime, fmtLocalTimeShort, getTimezoneLabel } from "../hooks/useTime";
import { Loading, ErrorBox, EmptyState } from "../components/StatusMessage";
import MetricCard from "../components/MetricCard";
import TradesTable from "../components/TradesTable";
import SimpleEquityChart from "../components/SimpleEquityChart";

const TZ_LABEL = getTimezoneLabel();

function fmt(n) {
  return `$${Number(n ?? 0).toFixed(4)}`;
}

function fmtPrice(n) {
  return `$${Number(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/* Volatility regime badge */
function VolBadge({ regime }) {
  const colors = { high: "#ef4444", low: "#6b7280", normal: "#3b82f6" };
  const labels = { high: "HIGH VOL", low: "LOW VOL", normal: "NORMAL" };
  return (
    <span style={{
      display: "inline-block", padding: "2px 8px", borderRadius: 4,
      fontSize: 10, fontWeight: 700, letterSpacing: 0.5,
      background: `${colors[regime] || colors.normal}22`,
      color: colors[regime] || colors.normal,
      border: `1px solid ${colors[regime] || colors.normal}44`,
    }}>
      {labels[regime] || regime?.toUpperCase() || "—"}
    </span>
  );
}

/* Signal bar: visual score bar 0-100 */
function SignalBar({ label, value, weight }) {
  const v = Number(value ?? 50);
  const color = v > 60 ? "var(--green)" : v < 40 ? "var(--red)" : "var(--text-muted)";
  return (
    <div style={{ flex: 1, padding: "6px 8px", background: "var(--bg)", borderRadius: 4 }}>
      <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", marginBottom: 4 }}>
        {label} ({weight})
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <div style={{ flex: 1, height: 4, background: "var(--border)", borderRadius: 2, overflow: "hidden" }}>
          <div style={{ width: `${v}%`, height: "100%", background: color, borderRadius: 2, transition: "width 0.3s" }} />
        </div>
        <span style={{ fontSize: 13, fontWeight: 600, color, minWidth: 24, textAlign: "right" }}>
          {v.toFixed(0)}
        </span>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { data: live, loading: lLoad, error: lErr, retry: rLive } = useApi("/live", 5000);
  const { data: autoTrades, retry: rTrades } = useApi("/auto/trades?limit=15", 10000);
  const { data: autoEquity, retry: rEquity } = useApi("/auto/equity?limit=100", 10000);

  const [refreshing, setRefreshing] = useState(false);

  const refreshAll = useCallback(() => {
    setRefreshing(true);
    rLive();
    rTrades();
    rEquity();
    setTimeout(() => setRefreshing(false), 1200);
  }, [rLive, rTrades, rEquity]);

  if (lLoad && !live) return <><h1>Dashboard</h1><Loading message="Connecting to auto-trader..." /></>;
  if (lErr && !live) return <><h1>Dashboard</h1><ErrorBox message={lErr} onRetry={refreshAll} /></>;

  // Data
  const running = live?.running ?? false;
  const price = Number(live?.last_price ?? 0);
  const decision = live?.last_decision;
  const indicators = live?.indicators || {};
  const portfolio = live?.portfolio || {};
  const adaptive = live?.adaptive || {};
  const sessionInsight = live?.session_insight || {};
  const cycleCount = live?.cycle_count ?? 0;
  const lastUpdate = live?.last_update || "";
  const liveError = live?.error;
  const cooldown = live?.cooldown_remaining ?? 0;

  const cash = Number(portfolio.cash ?? 0);
  const btc = Number(portfolio.btc_holdings ?? 0);
  const equity = Number(portfolio.total_equity ?? 0);
  const realizedPnl = Number(portfolio.realized_pnl ?? 0);
  const totalTrades = Number(portfolio.total_trades ?? 0);
  const avgEntry = Number(portfolio.avg_entry_price ?? 0);
  const unrealizedPnl = btc > 0 && avgEntry > 0 ? (price - avgEntry) * btc : 0;
  const totalPnl = realizedPnl + unrealizedPnl;

  const insightText = sessionInsight.insight || "";
  const insightStats = sessionInsight.session_stats || {};
  const insightTime = sessionInsight.generated_at || "";

  const volRegime = adaptive.vol_regime || indicators.vol_regime || "unknown";
  const buyThresh = adaptive.buy_threshold ?? 65;
  const sellThresh = adaptive.sell_threshold ?? 35;
  const momBoost = adaptive.momentum_boost ?? 0;
  const isSpike = adaptive.is_spike ?? false;
  const emergingTrend = adaptive.emerging_trend || "none";
  const isEarly = adaptive.is_early_entry ?? false;

  const trades = autoTrades?.trades || [];

  return (
    <>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <h1 style={{ margin: 0 }}>Dashboard</h1>
          <VolBadge regime={volRegime} />
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{
            display: "inline-block", width: 8, height: 8, borderRadius: "50%",
            background: running ? "var(--green)" : "var(--red)",
          }} />
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            {running ? `Auto-trading (cycle #${cycleCount})` : "Stopped"}
          </span>
          <button
            onClick={refreshAll}
            disabled={refreshing}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 14px", background: "var(--surface)",
              border: "1px solid var(--border)", borderRadius: 6,
              color: refreshing ? "var(--text-muted)" : "var(--text)",
              fontSize: 13, cursor: refreshing ? "wait" : "pointer",
            }}
          >
            {refreshing && <span className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} />}
            {refreshing ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {/* Alerts */}
      {liveError && (
        <div className="error" style={{ marginBottom: 16, fontSize: 13 }}>Auto-trader error: {liveError}</div>
      )}
      {lErr && live && (
        <div className="error" style={{ marginBottom: 16, fontSize: 13 }}>Refresh failed — showing last known data.</div>
      )}
      {isSpike && (
        <div style={{ marginBottom: 16, padding: "8px 14px", background: "#f59e0b22", border: "1px solid #f59e0b44", borderRadius: 6, fontSize: 13, color: "#f59e0b" }}>
          Spike detected — trades paused until price stabilizes.
        </div>
      )}
      {emergingTrend !== "none" && (
        <div style={{ marginBottom: 16, padding: "8px 14px", background: "#8b5cf622", border: "1px solid #8b5cf644", borderRadius: 6, fontSize: 13, color: "#a78bfa" }}>
          {emergingTrend === "emerging_bull" ? "Emerging bullish trend detected" : "Emerging bearish trend detected"} — watching for confirmation.
        </div>
      )}

      {/* Row 1: Metrics */}
      <div className="card-grid">
        <MetricCard label="BTC Price (Live)" value={fmtPrice(price)} />
        <MetricCard label="Portfolio Value" value={fmt(equity)} />
        <MetricCard label="Total P&L" value={fmt(totalPnl)} color={totalPnl >= 0 ? "green" : "red"} />
        <MetricCard label="Trades" value={`${totalTrades} total`} />
      </div>

      {/* Row 2: AI Decision + Holdings */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 24 }}>

        {/* AI Decision */}
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div className="label">AI Decision (Adaptive)</div>
            {isEarly && (
              <span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 3, background: "#8b5cf633", color: "#a78bfa" }}>
                EARLY ENTRY
              </span>
            )}
          </div>
          {!decision ? (
            <div style={{ color: "var(--text-muted)", fontSize: 13, marginTop: 8 }}>Waiting for first cycle...</div>
          ) : (
            <div style={{ marginTop: 8 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span className={`tag ${(decision.action || "hold").toLowerCase()}`} style={{ fontSize: 14, padding: "4px 12px" }}>
                  {decision.action || "HOLD"}
                </span>
                <span style={{ fontSize: 14, fontWeight: 600 }}>
                  Score: {decision.score ?? "—"}/100
                </span>
                <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  ({(Number(decision.confidence ?? 0) * 100).toFixed(0)}% conf)
                </span>
                {decision.position_size > 0 && (
                  <span style={{
                    fontSize: 11, padding: "2px 8px", borderRadius: 4, fontWeight: 700,
                    background: decision.position_size >= 0.5 ? "#22c55e22" : decision.position_size >= 0.25 ? "#3b82f622" : "#6b728022",
                    color: decision.position_size >= 0.5 ? "#22c55e" : decision.position_size >= 0.25 ? "#3b82f6" : "#9ca3af",
                    border: `1px solid ${decision.position_size >= 0.5 ? "#22c55e44" : decision.position_size >= 0.25 ? "#3b82f644" : "#6b728044"}`,
                  }}>
                    Size: {(decision.position_size * 100).toFixed(0)}%
                  </span>
                )}
                {momBoost > 0 && (
                  <span style={{ fontSize: 11, color: "#22c55e", fontWeight: 600 }}>
                    +{momBoost.toFixed(1)} boost
                  </span>
                )}
              </div>

              {/* Dynamic threshold indicator */}
              <div style={{ marginBottom: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--text-muted)", marginBottom: 2 }}>
                  <span>SELL &lt;{sellThresh}</span>
                  <span>HOLD</span>
                  <span>BUY &gt;{buyThresh}</span>
                </div>
                <div style={{ position: "relative", height: 6, background: "var(--border)", borderRadius: 3, overflow: "visible" }}>
                  {/* Sell zone */}
                  <div style={{ position: "absolute", left: 0, top: 0, width: `${sellThresh}%`, height: "100%", background: "#ef444433", borderRadius: "3px 0 0 3px" }} />
                  {/* Buy zone */}
                  <div style={{ position: "absolute", right: 0, top: 0, width: `${100 - buyThresh}%`, height: "100%", background: "#22c55e33", borderRadius: "0 3px 3px 0" }} />
                  {/* Score marker */}
                  <div style={{
                    position: "absolute", top: -3, left: `${Math.max(0, Math.min(100, decision.score ?? 50))}%`,
                    transform: "translateX(-50%)", width: 12, height: 12, borderRadius: "50%",
                    background: decision.action === "BUY" ? "var(--green)" : decision.action === "SELL" ? "var(--red)" : "var(--text-muted)",
                    border: "2px solid var(--surface)",
                  }} />
                </div>
              </div>

              <div style={{ fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }}>
                {decision.reasoning}
              </div>

              {/* Signal bars */}
              {decision.signals && typeof decision.signals === "object" && !Array.isArray(decision.signals) && (
                <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                  <SignalBar label="EMA" value={decision.signals.ema} weight="35%" />
                  <SignalBar label="RSI" value={decision.signals.rsi} weight="25%" />
                  <SignalBar label="Trend" value={decision.signals.trend} weight="25%" />
                  <SignalBar label="Accel" value={decision.signals.momentum} weight="15%" />
                </div>
              )}
            </div>
          )}
        </div>

        {/* Holdings */}
        <div className="card">
          <div className="label">Holdings</div>
          <div style={{ marginTop: 8 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <div>
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>Cash</div>
                <div style={{ fontSize: 16, fontWeight: 600 }}>{fmt(cash)}</div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>BTC</div>
                <div style={{ fontSize: 16, fontWeight: 600 }}>{btc.toFixed(6)}</div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>Avg Entry</div>
                <div style={{ fontSize: 14 }}>{avgEntry > 0 ? fmtPrice(avgEntry) : "—"}</div>
              </div>
              <div>
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>Unrealized</div>
                <div style={{ fontSize: 14, color: unrealizedPnl >= 0 ? "var(--green)" : "var(--red)" }}>
                  {fmt(unrealizedPnl)}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Row 3: Technical Indicators */}
      {indicators.ema_short && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 16, marginBottom: 24 }}>
          <MetricCard label="EMA(9) / EMA(21)" value={`${fmtPrice(indicators.ema_short)} / ${fmtPrice(indicators.ema_long)}`} />
          <MetricCard
            label="RSI(14)"
            value={indicators.rsi?.toFixed(1) || "—"}
            color={indicators.rsi > 70 ? "red" : indicators.rsi < 30 ? "green" : undefined}
          />
          <MetricCard label="Trend" value={indicators.trend || "—"} />
          <MetricCard
            label="Acceleration"
            value={indicators.acceleration?.toFixed(1) ?? "0.0"}
            color={indicators.acceleration > 10 ? "green" : indicators.acceleration < -10 ? "red" : undefined}
          />
          <MetricCard
            label="Volatility"
            value={`${((indicators.volatility ?? 0) * 100).toFixed(3)}%`}
          />
          <MetricCard
            label="Cooldown"
            value={cooldown > 0 ? `${cooldown}s` : "Ready"}
            color={cooldown > 0 ? "red" : "green"}
          />
        </div>
      )}

      {/* Row 4: Session Insight */}
      {insightText && (
        <div className="card" style={{ marginBottom: 24, borderLeft: "3px solid #8b5cf6" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: "#a78bfa" }}>Session Insight</span>
              {insightStats.dominant_trend && (
                <span style={{
                  fontSize: 10, padding: "2px 6px", borderRadius: 3,
                  background: insightStats.dominant_trend === "bullish" ? "#22c55e22" : insightStats.dominant_trend === "bearish" ? "#ef444422" : "#6b728022",
                  color: insightStats.dominant_trend === "bullish" ? "#22c55e" : insightStats.dominant_trend === "bearish" ? "#ef4444" : "#9ca3af",
                  fontWeight: 600,
                }}>
                  {insightStats.dominant_trend}
                </span>
              )}
            </div>
            {insightTime && (
              <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
                {fmtLocalTimeShort(insightTime)} {TZ_LABEL}
              </span>
            )}
          </div>
          <div style={{ fontSize: 13, color: "var(--text)", lineHeight: 1.6, marginBottom: 10 }}>
            {insightText}
          </div>
          <div style={{ display: "flex", gap: 16, fontSize: 11, color: "var(--text-muted)" }}>
            <span>{insightStats.cycles ?? 0} cycles</span>
            <span style={{ color: "var(--green)" }}>{insightStats.trades_taken ?? 0} traded</span>
            <span style={{ color: "#f59e0b" }}>{insightStats.trades_avoided ?? 0} filtered</span>
            <span>{insightStats.holds ?? 0} holds</span>
            <span>avg score: {insightStats.avg_score?.toFixed(0) ?? "—"}</span>
          </div>
        </div>
      )}

      {/* Row 5: Equity chart */}
      <SimpleEquityChart equity={autoEquity?.equity} />

      {/* Row 5: Recent trades */}
      <div className="section">
        <h3 style={{ marginBottom: 12, color: "var(--text-muted)" }}>Recent Auto-Trades</h3>
        {trades.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Time <span style={{ fontWeight: 400, opacity: 0.5 }}>({TZ_LABEL})</span></th>
                  <th>Action</th>
                  <th>Price</th>
                  <th>Qty</th>
                  <th>P&L</th>
                  <th>Score</th>
                  <th>Confidence</th>
                  <th>Signals</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => {
                  const pnl = parseFloat(t.pnl) || 0;
                  const action = (t.action || "HOLD").toUpperCase();
                  return (
                    <tr key={i}>
                      <td>{fmtLocalTime(t.timestamp)}</td>
                      <td><span className={`tag ${action.toLowerCase()}`}>{action}</span></td>
                      <td>{fmtPrice(t.price)}</td>
                      <td>{parseFloat(t.quantity || 0).toFixed(6)}</td>
                      <td style={{ color: pnl >= 0 ? "var(--green)" : "var(--red)" }}>{fmt(pnl)}</td>
                      <td>{t.score ?? "—"}</td>
                      <td>{((parseFloat(t.confidence) || 0) * 100).toFixed(0)}%</td>
                      <td style={{ fontSize: 11, color: "var(--text-muted)" }}>{t.signals || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="Waiting for trades" message="The adaptive engine will trade only when multiple signals align with high confidence." />
        )}
      </div>

      {/* Footer */}
      {lastUpdate && (
        <p style={{ fontSize: 11, color: "var(--text-muted)", textAlign: "right" }}>
          Last update: {fmtLocalTime(lastUpdate)} {TZ_LABEL}
        </p>
      )}
    </>
  );
}
