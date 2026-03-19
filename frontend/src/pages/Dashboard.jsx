import { useState, useCallback, lazy, Suspense } from "react";
import { useApi } from "../hooks/useApi";
import { fmtLocalTime, fmtLocalTimeShort, getTimezoneLabel } from "../hooks/useTime";
import { Loading, ErrorBox, EmptyState } from "../components/StatusMessage";
import MetricCard from "../components/MetricCard";
import TradesTable from "../components/TradesTable";
import SimpleEquityChart from "../components/SimpleEquityChart";
const BTCChart = lazy(() => import("../components/BTCChart"));

const TZ_LABEL = getTimezoneLabel();

function fmt(n) {
  return `$${Number(n ?? 0).toFixed(4)}`;
}

function fmtPrice(n) {
  return `$${Number(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/* Compact market state badge */
function MarketStateBadge({ state, score }) {
  const config = {
    SLEEPING:   { color: "#6b7280", label: "SLEEP",     icon: "💤" },
    WAKING_UP:  { color: "#eab308", label: "WAKING",    icon: "🌅" },
    ACTIVE:     { color: "#22c55e", label: "ACTIVE",    icon: "🟢" },
    BREAKOUT:   { color: "#ef4444", label: "BREAKOUT",  icon: "🔥" },
  };
  const c = config[state] || config.SLEEPING;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 3,
      padding: "2px 7px", borderRadius: 4,
      fontSize: 10, fontWeight: 700, letterSpacing: 0.3,
      background: `${c.color}22`, color: c.color,
      border: `1px solid ${c.color}33`,
    }}>
      <span style={{ fontSize: 10 }}>{c.icon}</span>
      {c.label}
      {score > 0 && <span style={{ opacity: 0.6, fontWeight: 400 }}>({score})</span>}
    </span>
  );
}

/* Ultra-compact signal bar */
function SignalBar({ label, value, weight }) {
  const v = Number(value ?? 50);
  const color = v > 60 ? "var(--green)" : v < 40 ? "var(--red)" : "var(--text-muted)";
  return (
    <div style={{ flex: 1, padding: "3px 6px", background: "var(--bg)", borderRadius: 3 }}>
      <div style={{ fontSize: 9, color: "var(--text-muted)", textTransform: "uppercase", marginBottom: 2 }}>
        {label} <span style={{ opacity: 0.5 }}>{weight}</span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <div style={{ flex: 1, height: 3, background: "var(--border)", borderRadius: 2, overflow: "hidden" }}>
          <div style={{ width: `${v}%`, height: "100%", background: color, borderRadius: 2 }} />
        </div>
        <span style={{ fontSize: 11, fontWeight: 600, color, minWidth: 20, textAlign: "right" }}>
          {v.toFixed(0)}
        </span>
      </div>
    </div>
  );
}

/* Inline metric — ultra compact, single line */
function InlineMetric({ label, value, color }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "3px 0" }}>
      <span style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3 }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 600, color: color || "var(--text)" }}>{value}</span>
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

  // Data extraction
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

  const mktState = live?.market_state || {};
  const mktStateName = mktState.state || "SLEEPING";
  const mktStateScore = mktState.confidence_score ?? 0;
  const mktStateReason = mktState.reason || "";

  const buyThresh = adaptive.buy_threshold ?? 65;
  const sellThresh = adaptive.sell_threshold ?? 35;
  const momBoost = adaptive.momentum_boost ?? 0;
  const whyReasons = decision?.why || [];
  const isEarly = adaptive.is_early_entry ?? false;

  const trades = autoTrades?.trades || [];

  return (
    <>
      {/* ── Header bar ── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, flexWrap: "wrap", gap: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <h1 style={{ margin: 0, fontSize: 17, fontWeight: 700 }}>Dashboard</h1>
          <MarketStateBadge state={mktStateName} score={mktStateScore} />
          <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
            {running ? `#${cycleCount}` : "Stopped"}
          </span>
          <span style={{
            display: "inline-block", width: 6, height: 6, borderRadius: "50%",
            background: running ? "var(--green)" : "var(--red)",
          }} />
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          {lastUpdate && <span style={{ fontSize: 9, color: "var(--text-muted)" }}>{fmtLocalTimeShort(lastUpdate)} {TZ_LABEL}</span>}
          <button onClick={refreshAll} disabled={refreshing} style={{
            padding: "3px 8px", background: "var(--surface)", border: "1px solid var(--border)",
            borderRadius: 4, color: "var(--text)", fontSize: 11, cursor: "pointer",
          }}>
            {refreshing ? "..." : "↻"}
          </button>
        </div>
      </div>

      {/* ── Alerts (compact) ── */}
      {liveError && <div className="error" style={{ marginBottom: 6, fontSize: 11, padding: "6px 10px" }}>⚠ {liveError}</div>}
      {mktStateReason && (
        <div style={{
          marginBottom: 6, padding: "5px 10px", borderRadius: 4, fontSize: 11,
          background: mktStateName === "BREAKOUT" ? "#ef444418" : mktStateName === "ACTIVE" ? "#22c55e18" : mktStateName === "WAKING_UP" ? "#eab30818" : "#6b728018",
          color: mktStateName === "BREAKOUT" ? "#ef4444" : mktStateName === "ACTIVE" ? "#22c55e" : mktStateName === "WAKING_UP" ? "#eab308" : "#9ca3af",
        }}>
          <b>Market:</b> {mktStateReason}
        </div>
      )}

      {/* ── Top metrics strip ── */}
      <div style={{ display: "flex", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
        {[
          { label: "BTC", value: fmtPrice(price) },
          { label: "Equity", value: fmt(equity) },
          { label: "P&L", value: fmt(totalPnl), color: totalPnl >= 0 ? "var(--green)" : "var(--red)" },
          { label: "Trades", value: totalTrades },
          { label: "Cash", value: fmt(cash) },
          { label: "BTC Held", value: btc.toFixed(6) },
        ].map((m) => (
          <div key={m.label} style={{
            flex: "1 1 140px", background: "var(--surface)", border: "1px solid var(--border)",
            borderRadius: 6, padding: "20px 18px",
          }}>
            <div style={{ fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 6 }}>{m.label}</div>
            <div style={{ fontSize: 22, fontWeight: 600, color: m.color || "var(--text)" }}>{m.value}</div>
          </div>
        ))}
      </div>

      {/* ── BTC Chart (HERO — preserved height) ── */}
      <Suspense fallback={<div className="card" style={{ height: 340, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", marginBottom: 8 }}>Loading chart...</div>}>
        <BTCChart
          marketState={mktStateName}
          action={decision?.action}
          confidence={Number(decision?.confidence ?? 0)}
          livePrice={price}
        />
      </Suspense>

      {/* ── AI Decision + Holdings + Indicators — 3 column grid ── */}
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 8, marginBottom: 8 }}>

        {/* AI Decision (wider) */}
        <div className="card" style={{ padding: "8px 10px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
            <span style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3 }}>AI Decision</span>
            {isEarly && <span style={{ fontSize: 9, padding: "1px 4px", borderRadius: 2, background: "#8b5cf633", color: "#a78bfa" }}>EARLY</span>}
          </div>
          {!decision ? (
            <div style={{ color: "var(--text-muted)", fontSize: 11 }}>Waiting...</div>
          ) : (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                <span className={`tag ${(decision.action || "hold").toLowerCase()}`} style={{ fontSize: 12, padding: "2px 8px" }}>
                  {decision.action || "HOLD"}
                </span>
                <span style={{ fontSize: 13, fontWeight: 700 }}>{decision.score ?? "—"}</span>
                <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
                  / 100 · {(Number(decision.confidence ?? 0) * 100).toFixed(0)}% conf
                </span>
                {decision.position_size > 0 && (
                  <span style={{ fontSize: 10, color: "#3b82f6", fontWeight: 600 }}>
                    {(decision.position_size * 100).toFixed(0)}% size
                  </span>
                )}
                {momBoost > 0 && <span style={{ fontSize: 10, color: "#22c55e" }}>+{momBoost.toFixed(0)} boost</span>}
              </div>

              {/* Threshold bar */}
              <div style={{ marginBottom: 4 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 8, color: "var(--text-muted)", marginBottom: 1 }}>
                  <span>S&lt;{sellThresh}</span><span>H</span><span>B&gt;{buyThresh}</span>
                </div>
                <div style={{ position: "relative", height: 4, background: "var(--border)", borderRadius: 2 }}>
                  <div style={{ position: "absolute", left: 0, top: 0, width: `${sellThresh}%`, height: "100%", background: "#ef444433", borderRadius: "2px 0 0 2px" }} />
                  <div style={{ position: "absolute", right: 0, top: 0, width: `${100 - buyThresh}%`, height: "100%", background: "#22c55e33", borderRadius: "0 2px 2px 0" }} />
                  <div style={{
                    position: "absolute", top: -2, left: `${Math.max(0, Math.min(100, decision.score ?? 50))}%`,
                    transform: "translateX(-50%)", width: 8, height: 8, borderRadius: "50%",
                    background: decision.action === "BUY" ? "var(--green)" : decision.action === "SELL" ? "var(--red)" : "var(--text-muted)",
                    border: "1.5px solid var(--surface)",
                  }} />
                </div>
              </div>

              <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.4, marginBottom: 3 }}>
                {decision.reasoning}
              </div>

              {/* Why bullets — compact */}
              {whyReasons.length > 0 && (
                <div style={{ padding: "4px 6px", background: "var(--bg)", borderRadius: 3, borderLeft: "2px solid #8b5cf6" }}>
                  {whyReasons.slice(0, 4).map((r, i) => (
                    <div key={i} style={{ fontSize: 10, color: "var(--text-muted)", lineHeight: 1.4 }}>• {r}</div>
                  ))}
                </div>
              )}

              {/* Signal bars */}
              {decision.signals && typeof decision.signals === "object" && !Array.isArray(decision.signals) && (
                <div style={{ display: "flex", gap: 4, marginTop: 5 }}>
                  <SignalBar label="EMA" value={decision.signals.ema} weight="35%" />
                  <SignalBar label="RSI" value={decision.signals.rsi} weight="25%" />
                  <SignalBar label="Trend" value={decision.signals.trend} weight="25%" />
                  <SignalBar label="Accel" value={decision.signals.momentum} weight="15%" />
                </div>
              )}
            </>
          )}
        </div>

        {/* Holdings (compact) */}
        <div className="card" style={{ padding: "8px 10px" }}>
          <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 4 }}>Holdings</div>
          <InlineMetric label="Cash" value={fmt(cash)} />
          <InlineMetric label="BTC" value={btc.toFixed(6)} />
          <InlineMetric label="Entry" value={avgEntry > 0 ? fmtPrice(avgEntry) : "—"} />
          <InlineMetric label="Unreal." value={fmt(unrealizedPnl)} color={unrealizedPnl >= 0 ? "var(--green)" : "var(--red)"} />
          <div style={{ borderTop: "1px solid var(--border)", marginTop: 4, paddingTop: 4 }}>
            <InlineMetric label="Cooldown" value={cooldown > 0 ? `${cooldown}s` : "Ready"} color={cooldown > 0 ? "var(--red)" : "var(--green)"} />
          </div>
        </div>

        {/* Technical Indicators (compact) */}
        <div className="card" style={{ padding: "8px 10px" }}>
          <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 4 }}>Indicators</div>
          <InlineMetric label="EMA 9" value={indicators.ema_short ? fmtPrice(indicators.ema_short) : "—"} />
          <InlineMetric label="EMA 21" value={indicators.ema_long ? fmtPrice(indicators.ema_long) : "—"} />
          <InlineMetric label="RSI" value={indicators.rsi?.toFixed(1) || "—"} color={indicators.rsi > 70 ? "var(--red)" : indicators.rsi < 30 ? "var(--green)" : undefined} />
          <InlineMetric label="Trend" value={indicators.trend || "—"} />
          <InlineMetric label="Vol" value={`${((indicators.volatility ?? 0) * 100).toFixed(3)}%`} />
          <InlineMetric label="Accel" value={indicators.acceleration?.toFixed(1) ?? "0.0"} color={indicators.acceleration > 10 ? "var(--green)" : indicators.acceleration < -10 ? "var(--red)" : undefined} />
        </div>
      </div>

      {/* ── Session Insight (single compact line) ── */}
      {insightText && (
        <div style={{
          marginBottom: 8, padding: "6px 10px", borderRadius: 4,
          background: "var(--surface)", border: "1px solid var(--border)", borderLeft: "2px solid #8b5cf6",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 3 }}>
            <span style={{ fontSize: 10, fontWeight: 700, color: "#a78bfa", textTransform: "uppercase" }}>Insight</span>
            <div style={{ display: "flex", gap: 10, fontSize: 10, color: "var(--text-muted)" }}>
              <span>{insightStats.cycles ?? 0}c</span>
              <span style={{ color: "var(--green)" }}>{insightStats.trades_taken ?? 0} traded</span>
              <span style={{ color: "#f59e0b" }}>{insightStats.trades_avoided ?? 0} filtered</span>
              <span>{insightStats.holds ?? 0} holds</span>
              {insightTime && <span>{fmtLocalTimeShort(insightTime)}</span>}
            </div>
          </div>
          <div style={{ fontSize: 11, color: "var(--text)", lineHeight: 1.4 }}>{insightText}</div>
        </div>
      )}

      {/* ── Equity + Trades side by side on wide screens ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.5fr", gap: 8, marginBottom: 8 }}>
        {/* Equity chart */}
        <div>
          <SimpleEquityChart equity={autoEquity?.equity} />
        </div>

        {/* Recent trades */}
        <div>
          <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 4 }}>Recent Auto-Trades</div>
          {trades.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Action</th>
                    <th>Price</th>
                    <th>P&L</th>
                    <th>Score</th>
                    <th>Conf</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.slice(0, 10).map((t, i) => {
                    const pnl = parseFloat(t.pnl) || 0;
                    const action = (t.action || "HOLD").toUpperCase();
                    return (
                      <tr key={i}>
                        <td style={{ fontSize: 10 }}>{fmtLocalTimeShort(t.timestamp)}</td>
                        <td><span className={`tag ${action.toLowerCase()}`}>{action}</span></td>
                        <td>{fmtPrice(t.price)}</td>
                        <td style={{ color: pnl >= 0 ? "var(--green)" : "var(--red)" }}>{fmt(pnl)}</td>
                        <td>{t.score ?? "—"}</td>
                        <td>{((parseFloat(t.confidence) || 0) * 100).toFixed(0)}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="Waiting for trades" message="Engine will trade when signals align." />
          )}
        </div>
      </div>
    </>
  );
}
