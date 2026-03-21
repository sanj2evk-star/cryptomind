import { useState, useCallback, useEffect, useRef, lazy, Suspense } from "react";
import { useApi } from "../hooks/useApi";
import { useKeepAlive } from "../hooks/useKeepAlive";
import { useTradeSound } from "../hooks/useTradeSound";
import { fmtLocalTime, fmtLocalTimeShort, getTimezoneLabel } from "../hooks/useTime";
import { Loading, ErrorBox, EmptyState } from "../components/StatusMessage";
import MetricCard from "../components/MetricCard";
import TradesTable from "../components/TradesTable";
import SimpleEquityChart from "../components/SimpleEquityChart";
import PortfolioDrawer from "../components/PortfolioDrawer";
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
    <div style={{ flex: 1, padding: _isTouch ? "5px 8px" : "3px 6px", background: "var(--bg)", borderRadius: 3 }}>
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

/* Inline metric — responsive single line */
const _isTouch = typeof window !== "undefined" && ("ontouchstart" in window || navigator.maxTouchPoints > 0);
function InlineMetric({ label, value, color }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: _isTouch ? "5px 0" : "3px 0" }}>
      <span style={{ fontSize: _isTouch ? 12 : 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3 }}>{label}</span>
      <span style={{ fontSize: _isTouch ? 15 : 13, fontWeight: 600, color: color || "var(--text)" }}>{value}</span>
    </div>
  );
}

export default function Dashboard() {
  const { data: live, loading: lLoad, error: lErr, retry: rLive } = useApi("/live", 5000);
  const { data: autoTrades, retry: rTrades } = useApi("/auto/trades?limit=15", 10000);
  const { data: autoEquity, retry: rEquity } = useApi("/auto/equity?limit=100", 10000);
  const { data: aiPerf } = useApi("/ai-performance", 30000);
  const { data: adaptive } = useApi("/adaptive", 15000);
  const { data: sysAge } = useApi("/v7/system-age", 10000);
  const { data: memStatus } = useApi("/v7/memory", 30000);
  const { data: latestReview } = useApi("/v7/daily-review", 60000);

  const { status: sysStatus, lastPing } = useKeepAlive();
  const { enabled: soundEnabled, toggle: toggleSound, checkTrades: checkTradeSound } = useTradeSound();
  const [refreshing, setRefreshing] = useState(false);
  const [showHolds, setShowHolds] = useState(false);
  const [tradeBanner, setTradeBanner] = useState(null);
  const lastBannerTradeRef = useRef(null);
  const [proMode, setProMode] = useState(() => {
    try { return localStorage.getItem("cryptomind_pro_mode") === "true"; }
    catch { return false; }
  });
  const [highlightRow, setHighlightRow] = useState(null); // timestamp of row to highlight
  const [drawerOpen, setDrawerOpen] = useState(false);
  const { data: lbData } = useApi("/leaderboard", 10000);

  const refreshAll = useCallback(() => {
    setRefreshing(true);
    rLive();
    rTrades();
    rEquity();
    setTimeout(() => setRefreshing(false), 1200);
  }, [rLive, rTrades, rEquity]);

  // Sound notification on new trades (MUST be before early returns)
  useEffect(() => {
    const t = autoTrades?.trades;
    if (t && t.length > 0) checkTradeSound(t);
  }, [autoTrades, checkTradeSound]);

  // Toggle pro mode
  const toggleProMode = useCallback(() => {
    setProMode(prev => {
      const next = !prev;
      try { localStorage.setItem("cryptomind_pro_mode", String(next)); } catch {}
      return next;
    });
  }, []);

  // Trade banner + row highlight for BUY/SELL
  useEffect(() => {
    const t = autoTrades?.trades;
    if (!t || t.length === 0) return;
    const latest = t[0];
    if (!latest || !latest.timestamp) return;
    const action = (latest.action || "").toUpperCase();
    if (action === "HOLD") return;
    if (latest.timestamp === lastBannerTradeRef.current) return;
    lastBannerTradeRef.current = latest.timestamp;
    const price = Number(latest.price || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    setTradeBanner(`${action} @ $${price}`);
    if (proMode) setHighlightRow(latest.timestamp);
    const timer = setTimeout(() => { setTradeBanner(null); setHighlightRow(null); }, 3000);
    return () => clearTimeout(timer);
  }, [autoTrades, proMode]);

  if (lLoad && !live) return <><h1>Dashboard</h1><Loading message="Connecting to auto-trader..." /></>;
  if (lErr && !live) return <><h1>Dashboard</h1><ErrorBox message={lErr} onRetry={refreshAll} /></>;

  // Data extraction
  const running = live?.running ?? false;
  const price = Number(live?.last_price ?? 0);
  const decision = live?.last_decision;
  const indicators = live?.indicators || {};
  const portfolio = live?.portfolio || {};
  const liveAdaptive = live?.adaptive || {};
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
  const isTouch = typeof window !== "undefined" && ("ontouchstart" in window || navigator.maxTouchPoints > 0);
  const maxTradeRows = proMode ? (isTouch ? 14 : 18) : (isTouch ? 12 : 15);
  const buyCount = trades.filter(t => (t.action || "").toUpperCase() === "BUY").length;
  const sellCount = trades.filter(t => (t.action || "").toUpperCase() === "SELL").length;
  const filteredTrades = showHolds ? trades : trades.filter(t => (t.action || "").toUpperCase() !== "HOLD");

  return (
    <>
      {/* ── Header bar ── */}
      <div className="dash-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, flexWrap: "wrap", gap: 6 }}>
        {/* Left: title + market badge */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <h1 style={{ margin: 0, fontSize: 17, fontWeight: 700 }}>Dashboard</h1>
          <MarketStateBadge state={mktStateName} score={mktStateScore} />
        </div>

        {/* Right: status + stats + time + refresh */}
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          {/* System status dot */}
          {(() => {
            const dotCfg = {
              LIVE:       { color: "#22c55e", label: "LIVE" },
              CONNECTING: { color: "#eab308", label: "CONNECTING" },
              SLEEPING:   { color: "#f97316", label: "WAKING" },
              ERROR:      { color: "#ef4444", label: "OFFLINE" },
            };
            const d = dotCfg[sysStatus] || dotCfg.CONNECTING;
            return (
              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{
                  display: "inline-block", width: 7, height: 7, borderRadius: "50%",
                  background: d.color, boxShadow: `0 0 6px ${d.color}66`,
                }} />
                <span style={{ fontSize: 10, fontWeight: 600, color: d.color }}>{d.label}</span>
              </div>
            );
          })()}

          {/* Cycle */}
          <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
            Cycle <b style={{ color: "var(--text)" }}>#{cycleCount}</b>
          </span>

          {/* Trade count */}
          <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
            Trades <b style={{ color: "var(--text)" }}>{totalTrades}</b>
            {(buyCount > 0 || sellCount > 0) && (
              <span style={{ marginLeft: 3 }}>
                (<span style={{ color: "var(--green)" }}>B:{buyCount}</span> / <span style={{ color: "var(--red)" }}>S:{sellCount}</span>)
              </span>
            )}
          </span>

          {/* Active strategies count */}
          <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
            Strategies <b style={{ color: "var(--text)" }}>{running ? "9" : "0"}</b>
          </span>

          {/* Last update time */}
          {lastUpdate && (
            <span style={{ fontSize: 9, color: "var(--text-muted)" }}>
              {fmtLocalTimeShort(lastUpdate)} {TZ_LABEL}
            </span>
          )}

          {/* Simple / Pro toggle */}
          <div style={{ display: "flex", gap: 1, background: "var(--bg)", borderRadius: 4, padding: 1 }}>
            <button onClick={() => proMode && toggleProMode()} style={{
              padding: "3px 8px", border: "none", borderRadius: 3, fontSize: 10, fontWeight: 600, cursor: "pointer",
              background: !proMode ? "var(--surface)" : "transparent",
              color: !proMode ? "var(--text)" : "var(--text-muted)",
            }}>Simple</button>
            <button onClick={() => !proMode && toggleProMode()} style={{
              padding: "3px 8px", border: "none", borderRadius: 3, fontSize: 10, fontWeight: 600, cursor: "pointer",
              background: proMode ? "#3b82f6" : "transparent",
              color: proMode ? "#fff" : "var(--text-muted)",
            }}>Pro</button>
          </div>

          {/* Portfolio Manager */}
          <button onClick={() => setDrawerOpen(true)} style={{
            padding: "3px 8px", background: "var(--surface)", border: "1px solid var(--border)",
            borderRadius: 4, color: "#a78bfa", fontSize: 10, fontWeight: 600, cursor: "pointer",
          }}>Portfolio</button>

          {/* Sound toggle */}
          <button onClick={toggleSound} title={soundEnabled ? "Mute sounds" : "Enable sounds"} style={{
            padding: "3px 8px", background: "var(--surface)", border: "1px solid var(--border)",
            borderRadius: 4, color: soundEnabled ? "var(--text)" : "var(--text-muted)", fontSize: 13, cursor: "pointer",
          }}>
            {soundEnabled ? "🔊" : "🔇"}
          </button>

          {/* Refresh */}
          <button onClick={refreshAll} disabled={refreshing} style={{
            padding: "3px 8px", background: "var(--surface)", border: "1px solid var(--border)",
            borderRadius: 4, color: "var(--text)", fontSize: 11, cursor: "pointer",
          }}>
            {refreshing ? "..." : "↻"}
          </button>
        </div>
      </div>

      {/* ── Trade banner (subtle in Simple, prominent in Pro) ── */}
      {tradeBanner && (
        <div style={{
          marginBottom: 4, padding: proMode ? "6px 14px" : "5px 12px", borderRadius: 4,
          fontSize: proMode ? 13 : 12, fontWeight: proMode ? 600 : 400,
          background: tradeBanner.startsWith("BUY") ? (proMode ? "rgba(34,197,94,0.18)" : "rgba(34,197,94,0.1)") : (proMode ? "rgba(239,68,68,0.18)" : "rgba(239,68,68,0.1)"),
          color: tradeBanner.startsWith("BUY") ? "#22c55e" : "#ef4444",
          opacity: proMode ? 1 : 0.85,
          borderLeft: proMode ? `3px solid ${tradeBanner.startsWith("BUY") ? "#22c55e" : "#ef4444"}` : "none",
          transition: "all 0.3s ease",
        }}>
          {proMode ? `⚡ ${tradeBanner}` : tradeBanner}
        </div>
      )}

      {/* ── Alerts (compact) ── */}
      {liveError && <div className="error" style={{ marginBottom: 6, fontSize: 11, padding: "6px 10px" }}>⚠ {liveError}</div>}
      {mktStateReason && (
        <div className="market-banner" style={{
          marginBottom: 4, padding: "4px 10px", borderRadius: 4, fontSize: 11,
          background: mktStateName === "BREAKOUT" ? "#ef444418" : mktStateName === "ACTIVE" ? "#22c55e18" : mktStateName === "WAKING_UP" ? "#eab30818" : "#6b728018",
          color: mktStateName === "BREAKOUT" ? "#ef4444" : mktStateName === "ACTIVE" ? "#22c55e" : mktStateName === "WAKING_UP" ? "#eab308" : "#9ca3af",
        }}>
          <b>Market:</b> {mktStateReason}
        </div>
      )}

      {/* ── v7: System Age Strip ── */}
      {sysAge && (
        <div style={{
          display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap",
          padding: "6px 10px", marginBottom: isTouch ? 5 : 6,
          background: "var(--surface)", border: "1px solid var(--border)",
          borderRadius: 6, fontSize: 10,
        }}>
          <span style={{ color: "var(--blue)", fontWeight: 700 }}>
            v{sysAge.current_session_version || "7"}
          </span>
          <span style={{ color: "var(--text-muted)" }}>
            System Age: <b style={{ color: "var(--text)" }}>{(sysAge.system_age_cycles || 0).toLocaleString()} cycles</b>
          </span>
          <span style={{ color: "var(--text-muted)" }}>
            Session: <b style={{ color: "var(--text)" }}>{(sysAge.current_session_hours || 0).toFixed(1)}h</b>
          </span>
          <span style={{ color: "var(--text-muted)" }}>
            Lifetime Trades: <b style={{ color: "var(--text)" }}>{sysAge.total_lifetime_trades || 0}</b>
          </span>
          {memStatus && (memStatus.total_memories || 0) > 0 && (
            <span style={{ color: "#8b5cf6" }}>
              Memories: <b>{memStatus.total_memories}</b>
            </span>
          )}
          {latestReview?.review && (
            <span style={{ color: "var(--text-muted)", fontSize: 9 }}>
              Last Review: {latestReview.review.review_date || "—"}
            </span>
          )}
        </div>
      )}

      {/* ── Top metrics strip ── */}
      <div className="metric-strip" style={{ display: "flex", gap: isTouch ? 5 : 6, marginBottom: isTouch ? 5 : 6, flexWrap: "wrap" }}>
        {[
          { label: "BTC", value: fmtPrice(price) },
          { label: "Equity", value: fmt(equity) },
          { label: "P&L", value: `${totalPnl < 0 ? "▼ " : totalPnl > 0 ? "▲ " : ""}${fmt(totalPnl)}`, color: totalPnl >= 0 ? "var(--green)" : "var(--red)", fontWeight: totalPnl < 0 ? 700 : 600 },
          { label: "Trades", value: totalTrades },
          { label: "Cash", value: fmt(cash) },
          { label: "BTC Held", value: btc.toFixed(6) },
        ].map((m) => (
          <div key={m.label} className="metric-card" style={{
            flex: "1 1 130px", background: "var(--surface)", border: "1px solid var(--border)",
            borderRadius: 6, padding: isTouch ? "16px 14px" : "18px 16px",
          }}>
            <div className="metric-label" style={{ fontSize: isTouch ? 11 : 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: isTouch ? 5 : 4 }}>{m.label}</div>
            <div className="metric-value" style={{ fontSize: isTouch ? 20 : 22, fontWeight: 600, color: m.color || "var(--text)" }}>{m.value}</div>
          </div>
        ))}
      </div>

      {/* ── BTC Chart (HERO — preserved height) ── */}
      <Suspense fallback={<div className="card" style={{ height: 340, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", marginBottom: 6 }}>Loading chart...</div>}>
        <BTCChart
          marketState={mktStateName}
          action={decision?.action}
          confidence={Number(decision?.confidence ?? 0)}
          livePrice={price}
        />
      </Suspense>

      {/* ── AI Decision | Holdings | Indicators — 3-col ── */}
      <div className="panel-grid" style={{ display: "grid", gridTemplateColumns: "5fr 3fr 3fr", gap: isTouch ? 6 : 6, marginBottom: isTouch ? 6 : 6 }}>

        {/* Column 1: AI Decision + Insight stacked */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {/* AI Decision — flex:1 to fill gap above Insight */}
          <div className="card" style={{ padding: isTouch ? "14px 16px" : "10px 12px", flex: 1 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
              <span style={{ fontSize: isTouch ? 12 : 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3 }}>AI Decision</span>
              {isEarly && <span style={{ fontSize: 9, padding: "1px 4px", borderRadius: 2, background: "#8b5cf633", color: "#a78bfa" }}>EARLY</span>}
            </div>
            {!decision ? (
              <div style={{ color: "var(--text-muted)", fontSize: 11 }}>Waiting...</div>
            ) : (
              <>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 6 }}>
                  <span className={`tag ${(decision.action || "hold").toLowerCase()}`} style={{ fontSize: 16, padding: "3px 12px", fontWeight: 700 }}>
                    {decision.action || "HOLD"}
                  </span>
                  <span style={{ fontSize: 20, fontWeight: 800 }}>{decision.score ?? "—"}</span>
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>/100</span>
                  <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                    {(Number(decision.confidence ?? 0) * 100).toFixed(0)}% conf
                  </span>
                  {decision.position_size > 0 && (
                    <span style={{ fontSize: 11, color: "#3b82f6", fontWeight: 600 }}>
                      {(decision.position_size * 100).toFixed(0)}% size
                      {price > 0 && ` ($${(decision.position_size * cash).toFixed(2)})`}
                    </span>
                  )}
                </div>

                {/* Threshold bar */}
                <div style={{ marginBottom: 5 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "var(--text-muted)", marginBottom: 1 }}>
                    <span>SELL &lt;{sellThresh}</span><span>HOLD</span><span>BUY &gt;{buyThresh}</span>
                  </div>
                  <div style={{ position: "relative", height: 5, background: "var(--border)", borderRadius: 3 }}>
                    <div style={{ position: "absolute", left: 0, top: 0, width: `${sellThresh}%`, height: "100%", background: "#ef444433", borderRadius: "3px 0 0 3px" }} />
                    <div style={{ position: "absolute", right: 0, top: 0, width: `${100 - buyThresh}%`, height: "100%", background: "#22c55e33", borderRadius: "0 3px 3px 0" }} />
                    <div style={{
                      position: "absolute", top: -3, left: `${Math.max(0, Math.min(100, decision.score ?? 50))}%`,
                      transform: "translateX(-50%)", width: 11, height: 11, borderRadius: "50%",
                      background: decision.action === "BUY" ? "var(--green)" : decision.action === "SELL" ? "var(--red)" : "var(--text-muted)",
                      border: "2px solid var(--surface)",
                    }} />
                  </div>
                </div>

                <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.4, marginBottom: 4 }}>
                  {decision.reasoning}
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                  {whyReasons.length > 0 && (
                    <div style={{ padding: "4px 6px", background: "var(--bg)", borderRadius: 3, borderLeft: "2px solid #8b5cf6" }}>
                      <div style={{ fontSize: 9, color: "#a78bfa", fontWeight: 700, marginBottom: 2 }}>WHY</div>
                      {whyReasons.slice(0, 3).map((r, i) => (
                        <div key={i} style={{ fontSize: 10, color: "var(--text-muted)", lineHeight: 1.3 }}>• {r}</div>
                      ))}
                    </div>
                  )}
                  {decision.signals && typeof decision.signals === "object" && !Array.isArray(decision.signals) && (
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 3 }}>
                      <SignalBar label="EMA" value={decision.signals.ema} weight="35%" />
                      <SignalBar label="RSI" value={decision.signals.rsi} weight="25%" />
                      <SignalBar label="Trend" value={decision.signals.trend} weight="25%" />
                      <SignalBar label="Accel" value={decision.signals.momentum} weight="15%" />
                    </div>
                  )}
                </div>
              </>
            )}
          </div>

        </div>

        {/* Column 2: Holdings */}
        <div className="card" style={{ padding: isTouch ? "10px 14px" : "8px 10px" }}>
          <div style={{ fontSize: isTouch ? 12 : 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 4 }}>Holdings</div>
          <InlineMetric label="Cash" value={fmt(cash)} />
          <InlineMetric label="BTC" value={btc.toFixed(6)} />
          <InlineMetric label="Avg Entry" value={avgEntry > 0 ? fmtPrice(avgEntry) : "—"} />
          <InlineMetric label="Unrealized" value={`${unrealizedPnl < 0 ? "▼ " : unrealizedPnl > 0 ? "▲ " : ""}${fmt(unrealizedPnl)}`} color={unrealizedPnl >= 0 ? "var(--green)" : "var(--red)"} />
          <div style={{ borderTop: "1px solid var(--border)", marginTop: 5, paddingTop: 5 }}>
            <InlineMetric label="Cooldown" value={cooldown > 0 ? `${cooldown}s` : "Ready"} color={cooldown > 0 ? "var(--red)" : "var(--green)"} />
          </div>
        </div>

        {/* Column 3: Indicators */}
        <div className="card" style={{ padding: isTouch ? "10px 14px" : "8px 10px" }}>
          <div style={{ fontSize: isTouch ? 12 : 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 4 }}>Indicators</div>
          <InlineMetric label="EMA 9" value={indicators.ema_short ? fmtPrice(indicators.ema_short) : "—"} />
          <InlineMetric label="EMA 21" value={indicators.ema_long ? fmtPrice(indicators.ema_long) : "—"} />
          <InlineMetric label="RSI(14)" value={indicators.rsi?.toFixed(1) || "—"} color={indicators.rsi > 70 ? "var(--red)" : indicators.rsi < 30 ? "var(--green)" : undefined} />
          <InlineMetric label="Trend" value={indicators.trend || "—"} />
          <InlineMetric label="Volatility" value={`${((indicators.volatility ?? 0) * 100).toFixed(3)}%`} />
          <InlineMetric label="Accel" value={indicators.acceleration?.toFixed(1) ?? "0.0"} color={indicators.acceleration > 10 ? "var(--green)" : indicators.acceleration < -10 ? "var(--red)" : undefined} />
        </div>
      </div>

      {/* ── Insight + Equity (left) | Auto-Trades (right) ── */}
      <div className="bottom-grid" style={{ display: "grid", gridTemplateColumns: "5fr 6fr", gap: 6, marginBottom: 6, alignItems: "start" }}>

        {/* Left: Insight + Equity stacked */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {/* Insight */}
          {insightText && (
            <div className="insight-card" style={{
              padding: isTouch ? "16px 18px" : "14px 16px", borderRadius: 6,
              background: "var(--surface)", border: "1px solid var(--border)", borderLeft: "3px solid #8b5cf6",
              minHeight: isTouch ? 120 : 100,
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: "#a78bfa", textTransform: "uppercase", letterSpacing: 0.5 }}>Session Insight</span>
                <div style={{ display: "flex", gap: 10, fontSize: 11, color: "var(--text-muted)" }}>
                  <span>{insightStats.cycles ?? 0}c</span>
                  <span style={{ color: "var(--green)" }}>{insightStats.trades_taken ?? 0} traded</span>
                  <span style={{ color: "#f59e0b" }}>{insightStats.trades_avoided ?? 0} skip</span>
                  <span>{insightStats.holds ?? 0} hold</span>
                </div>
              </div>
              <div style={{ fontSize: 14, color: "var(--text)", lineHeight: 1.6 }}>{insightText}</div>
            </div>
          )}
          {/* AI Performance — minimal */}
          {aiPerf?.metrics?.total_evaluated > 0 && (
            <div style={{
              padding: "8px 12px", borderRadius: 5,
              background: "var(--surface)", border: "1px solid var(--border)",
            }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", marginBottom: 4 }}>AI Performance</div>
              <div style={{ display: "flex", gap: 12, fontSize: 12 }}>
                <div>
                  <span style={{ color: "var(--text-muted)" }}>Accuracy </span>
                  <span style={{ fontWeight: 700, color: aiPerf.metrics.accuracy_pct >= 50 ? "var(--green)" : "var(--red)" }}>
                    {aiPerf.metrics.accuracy_pct}%
                  </span>
                </div>
                <div>
                  <span style={{ color: "var(--text-muted)" }}>Hi-Conf </span>
                  <span style={{ fontWeight: 700, color: aiPerf.metrics.high_conf_accuracy_pct >= 50 ? "var(--green)" : "var(--red)" }}>
                    {aiPerf.metrics.high_conf_accuracy_pct}%
                  </span>
                </div>
                <div>
                  <span style={{ color: "var(--text-muted)" }}>Overconf </span>
                  <span style={{ fontWeight: 700, color: aiPerf.metrics.overconfidence_pct > 30 ? "var(--red)" : "var(--text-muted)" }}>
                    {aiPerf.metrics.overconfidence_pct}%
                  </span>
                </div>
                <div style={{ color: "var(--text-muted)", fontSize: 10 }}>
                  ({aiPerf.metrics.total_evaluated} eval · {aiPerf.metrics.pending_evaluations} pending)
                </div>
              </div>
            </div>
          )}
          {/* Adaptive Learning */}
          {adaptive && (
            <div className="card" style={{ padding: "6px 10px", marginBottom: 6 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <span style={{ fontSize: 10, color: "#a78bfa", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5 }}>
                  Adaptive Learning
                </span>
                <span style={{
                  fontSize: 9, padding: "1px 6px", borderRadius: 3, fontWeight: 600,
                  background: adaptive.enabled ? "#22c55e18" : "#ef444418",
                  color: adaptive.enabled ? "#22c55e" : "#ef4444",
                }}>{adaptive.enabled ? "ON" : "OFF"}</span>
              </div>
              <div style={{ display: "flex", gap: 12, fontSize: 11, flexWrap: "wrap" }}>
                <div><span style={{ color: "var(--text-muted)" }}>Tracked: </span><b>{adaptive.strategies_tracked || 0}</b></div>
                <div><span style={{ color: "var(--text-muted)" }}>Adaptations: </span><b>{adaptive.total_adaptations || 0}</b></div>
                <div><span style={{ color: "var(--text-muted)" }}>Next in: </span><b>{adaptive.next_learn_in || "—"} cycles</b></div>
              </div>
              {adaptive.best_by_regime && Object.keys(adaptive.best_by_regime).length > 0 && (
                <div style={{ marginTop: 4, fontSize: 10 }}>
                  <span style={{ color: "var(--text-muted)" }}>Best by regime: </span>
                  {Object.entries(adaptive.best_by_regime).map(([regime, d]) => (
                    <span key={regime} style={{ marginRight: 8 }}>
                      <span style={{ color: "#9ca3af" }}>{regime}: </span>
                      <span style={{ fontWeight: 600 }}>{d.strategy}</span>
                      <span style={{ color: "var(--text-muted)" }}> ({d.win_rate}%)</span>
                    </span>
                  ))}
                </div>
              )}
              {adaptive.recent_adaptations?.length > 0 && (
                <div style={{ marginTop: 4, fontSize: 10, color: "var(--text-muted)", fontStyle: "italic" }}>
                  Latest: {adaptive.recent_adaptations[0]?.reason || adaptive.recent_adaptations[0]?.type}
                </div>
              )}
            </div>
          )}
          {/* Equity */}
          <SimpleEquityChart equity={autoEquity?.equity} />
        </div>

        {/* Right: Auto-Trades — fixed height, scrollable */}
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
            <span style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3 }}>Recent Auto-Trades</span>
            <button onClick={() => setShowHolds(h => !h)} style={{
              padding: "2px 8px", border: "none", borderRadius: 3, fontSize: 9, fontWeight: 600, cursor: "pointer",
              background: showHolds ? "var(--surface)" : "var(--bg)",
              color: showHolds ? "var(--text)" : "var(--text-muted)",
            }}>
              {showHolds ? "All" : "Trades Only"}
            </button>
          </div>
          {filteredTrades.length > 0 ? (
            <div className="table-wrap" style={{ maxHeight: proMode ? (isTouch ? 300 : 340) : (isTouch ? 260 : 280), overflowY: "auto" }}>
              <table style={{ fontSize: 11 }}>
                <thead>
                  <tr>
                    <th style={{ padding: isTouch ? "7px 10px" : "3px 6px" }}>Time</th>
                    <th style={{ padding: isTouch ? "7px 10px" : "3px 6px" }}>Action</th>
                    <th style={{ padding: isTouch ? "7px 10px" : "3px 6px" }}>Price</th>
                    <th style={{ padding: isTouch ? "7px 10px" : "3px 6px" }}>Size</th>
                    <th style={{ padding: isTouch ? "7px 10px" : "3px 6px" }}>P&L</th>
                    <th style={{ padding: isTouch ? "7px 10px" : "3px 6px" }}>Score</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTrades.slice(0, maxTradeRows).map((t, i) => {
                    const pnl = parseFloat(t.pnl) || 0;
                    const action = (t.action || "HOLD").toUpperCase();
                    const isHold = action === "HOLD";
                    const isBuy = action === "BUY";
                    const isSell = action === "SELL";
                    const isHighlighted = proMode && highlightRow === t.timestamp;
                    const qty = parseFloat(t.quantity) || 0;
                    const tPrice = parseFloat(t.price) || 0;
                    const posSize = qty * tPrice;
                    const posPct = equity > 0 ? (posSize / equity * 100) : 0;
                    return (
                      <tr key={i} style={{
                        opacity: isHold ? 0.4 : 1,
                        background: isHighlighted
                          ? (isBuy ? "rgba(34,197,94,0.15)" : isSell ? "rgba(239,68,68,0.15)" : "rgba(59,130,246,0.1)")
                          : proMode
                            ? (isBuy ? "rgba(34,197,94,0.08)" : isSell ? "rgba(239,68,68,0.08)" : "transparent")
                            : (isBuy ? "rgba(34,197,94,0.04)" : isSell ? "rgba(239,68,68,0.04)" : "transparent"),
                        transition: "background 0.5s ease",
                      }}>
                        <td style={{ padding: isTouch ? "6px 10px" : "2px 6px", fontSize: 10 }}>{fmtLocalTimeShort(t.timestamp)}</td>
                        <td style={{ padding: isTouch ? "6px 10px" : "2px 6px" }}><span className={`tag ${action.toLowerCase()}`}>{action}</span></td>
                        <td style={{ padding: isTouch ? "6px 10px" : "2px 6px" }}>{fmtPrice(tPrice)}</td>
                        <td style={{ padding: isTouch ? "6px 10px" : "2px 6px" }}>
                          {qty > 0 ? (
                            <span title={`${qty.toFixed(6)} BTC`}>
                              ${posSize.toFixed(2)}
                              <span style={{ fontSize: 9, color: "var(--text-muted)", marginLeft: 2 }}>{posPct.toFixed(1)}%</span>
                            </span>
                          ) : "—"}
                        </td>
                        <td style={{ padding: isTouch ? "6px 10px" : "2px 6px", color: pnl >= 0 ? "var(--green)" : "var(--red)", fontWeight: pnl < 0 ? 700 : 400 }}>
                          {pnl < 0 && "▼ "}{pnl > 0 && "▲ "}{fmt(pnl)}
                        </td>
                        <td style={{ padding: isTouch ? "6px 10px" : "2px 6px" }}>{t.score ?? "—"}</td>
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

      {/* Portfolio Manager Drawer */}
      <PortfolioDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        leaderboard={lbData}
        adaptive={adaptive}
        live={live}
      />
    </>
  );
}
