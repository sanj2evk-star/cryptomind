import { useEffect } from "react";

/**
 * Portfolio Manager — slide-in drawer showing system brain state.
 * Props: open, onClose, leaderboard data, adaptive data, live data
 */
export default function PortfolioDrawer({ open, onClose, leaderboard, adaptive, live }) {
  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  const board = leaderboard?.leaderboard || [];
  const strategies = leaderboard?.strategies || {};
  const primary = leaderboard?.primary_strategy || "—";
  const mktState = leaderboard?.market_state?.state || live?.market_state?.state || "—";
  const adaptiveData = adaptive || {};
  const events = adaptiveData.recent_adaptations || [];
  const bestByRegime = adaptiveData.best_by_regime || {};

  // Top strategies sorted by allocation
  const sorted = [...board].sort((a, b) => (b.allocation_pct || 0) - (a.allocation_pct || 0));
  const top3 = sorted.slice(0, 3);
  const activeCount = board.filter(s => s.status === "ACTIVE" || s.status === "LEADING").length;

  // Concentration: highest alloc / total
  const maxAlloc = Math.max(...board.map(s => s.allocation_pct || 0), 0);
  const concentration = maxAlloc > 30 ? "HIGH" : maxAlloc > 20 ? "MODERATE" : "LOW";
  const diversification = activeCount >= 6 ? "GOOD" : activeCount >= 4 ? "MODERATE" : "LOW";

  return (
    <>
      {/* Backdrop */}
      <div onClick={onClose} style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 999,
        transition: "opacity 0.2s",
      }} />

      {/* Drawer */}
      <div style={{
        position: "fixed", top: 0, right: 0, bottom: 0, width: "min(380px, 85vw)",
        background: "var(--surface, #1e1e2e)", borderLeft: "1px solid var(--border, #333)",
        zIndex: 1000, overflowY: "auto", padding: "20px 16px",
        animation: "slideIn 0.2s ease-out",
      }}>
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Portfolio Manager</h2>
            <span style={{ fontSize: 10, color: "var(--text-muted)" }}>System brain overview</span>
          </div>
          <button onClick={onClose} style={{
            background: "none", border: "none", color: "var(--text-muted)", fontSize: 20,
            cursor: "pointer", padding: "4px 8px",
          }}>&times;</button>
        </div>

        {/* Section 1: System State */}
        <Section title="System State">
          <Row label="Adaptive Learning" value={
            <span style={{
              padding: "2px 8px", borderRadius: 3, fontSize: 10, fontWeight: 700,
              background: adaptiveData.enabled ? "#22c55e18" : "#ef444418",
              color: adaptiveData.enabled ? "#22c55e" : "#ef4444",
            }}>{adaptiveData.enabled ? "ON" : "OFF"}</span>
          } />
          <Row label="Market Regime" value={
            <span style={{ fontWeight: 700, color: regimeColor(mktState) }}>{mktState}</span>
          } />
          <Row label="Dominant Strategy" value={
            <span style={{ fontWeight: 700, color: "#eab308" }}>{primary}</span>
          } />
          <Row label="Active / Total" value={`${activeCount} / ${board.length}`} />
          <Row label="Next Learning" value={`${adaptiveData.next_learn_in || "—"} cycles`} />
        </Section>

        {/* Section 2: Allocation Insight */}
        <Section title="Allocation Insight">
          {top3.map(s => {
            const strat = strategies[s.strategy] || {};
            return (
              <div key={s.strategy} style={{ marginBottom: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ width: 3, height: 16, borderRadius: 2, background: s.color || "#666" }} />
                    <span style={{ fontWeight: 600, fontSize: 12 }}>{s.label}</span>
                  </div>
                  <span style={{ fontWeight: 700, fontSize: 13 }}>{(s.allocation_pct || 0).toFixed(0)}%</span>
                </div>
                <div style={{ fontSize: 10, color: "var(--text-muted)", marginLeft: 9, fontStyle: "italic" }}>
                  {strat.last_reason || s.desc || "Balanced allocation"}
                </div>
                {/* Mini bar */}
                <div style={{ marginLeft: 9, marginTop: 3, height: 3, borderRadius: 2, background: "var(--border)" }}>
                  <div style={{
                    height: "100%", borderRadius: 2, background: s.color || "#666",
                    width: `${Math.min(s.allocation_pct || 0, 100)}%`, transition: "width 0.3s",
                  }} />
                </div>
              </div>
            );
          })}
          {sorted.filter(s => s.status === "INACTIVE" || s.status === "PAUSED").length > 0 && (
            <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>
              {sorted.filter(s => s.status === "INACTIVE").length} killed ·{" "}
              {sorted.filter(s => s.status === "PAUSED").length} paused
            </div>
          )}
        </Section>

        {/* Section 3: Trust Scores */}
        <Section title="Strategy Trust">
          {sorted.map(s => {
            const trust = computeTrust(s);
            return (
              <div key={s.strategy} style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                padding: "3px 0", opacity: s.status === "INACTIVE" ? 0.4 : 1,
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
                  <span style={{ width: 3, height: 12, borderRadius: 2, background: s.color || "#666" }} />
                  <span>{s.label}</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <div style={{ width: 50, height: 4, borderRadius: 2, background: "var(--border)" }}>
                    <div style={{
                      height: "100%", borderRadius: 2, width: `${trust}%`,
                      background: trust > 60 ? "#22c55e" : trust > 35 ? "#eab308" : "#ef4444",
                    }} />
                  </div>
                  <span style={{ fontSize: 10, fontWeight: 600, width: 28, textAlign: "right",
                    color: trust > 60 ? "#22c55e" : trust > 35 ? "#eab308" : "#ef4444",
                  }}>{trust}%</span>
                </div>
              </div>
            );
          })}
        </Section>

        {/* Section 4: Recent Decisions */}
        <Section title="Recent Adaptations">
          {events.length > 0 ? events.slice(0, 6).map((e, i) => (
            <div key={i} style={{
              fontSize: 10, padding: "4px 0",
              borderBottom: i < 5 ? "1px solid var(--border)" : "none",
              color: "var(--text-muted)",
            }}>
              <span style={{ color: adaptColor(e.type), fontWeight: 600 }}>
                {adaptIcon(e.type)} {e.type?.replace(/_/g, " ")}
              </span>
              {e.strategy && <span> · {e.strategy}</span>}
              {e.reason && <div style={{ marginTop: 1, fontStyle: "italic" }}>{e.reason}</div>}
            </div>
          )) : (
            <div style={{ fontSize: 10, color: "var(--text-muted)" }}>No adaptations yet — system is warming up</div>
          )}
        </Section>

        {/* Section 5: Risk */}
        <Section title="Risk Assessment">
          <Row label="Concentration" value={
            <span style={{ fontWeight: 600, color: concentration === "HIGH" ? "#ef4444" : concentration === "MODERATE" ? "#eab308" : "#22c55e" }}>
              {concentration}
            </span>
          } />
          <Row label="Diversification" value={
            <span style={{ fontWeight: 600, color: diversification === "LOW" ? "#ef4444" : diversification === "MODERATE" ? "#eab308" : "#22c55e" }}>
              {diversification}
            </span>
          } />
          <Row label="Max single allocation" value={`${maxAlloc.toFixed(0)}%`} />
          {bestByRegime && Object.keys(bestByRegime).length > 0 && (
            <div style={{ marginTop: 6, fontSize: 10 }}>
              <span style={{ color: "var(--text-muted)" }}>Best per regime:</span>
              {Object.entries(bestByRegime).map(([r, d]) => (
                <div key={r} style={{ marginLeft: 4, marginTop: 2 }}>
                  <span style={{ color: regimeColor(r) }}>{r}</span>: {d.strategy} ({d.win_rate}% win)
                </div>
              ))}
            </div>
          )}
        </Section>

        {/* CSS animation */}
        <style>{`
          @keyframes slideIn {
            from { transform: translateX(100%); }
            to { transform: translateX(0); }
          }
        `}</style>
      </div>
    </>
  );
}

// ── Helpers ──
function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{
        fontSize: 10, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase",
        letterSpacing: 0.5, marginBottom: 6, paddingBottom: 3, borderBottom: "1px solid var(--border)",
      }}>{title}</div>
      {children}
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "3px 0", fontSize: 12 }}>
      <span style={{ color: "var(--text-muted)" }}>{label}</span>
      <span>{value}</span>
    </div>
  );
}

function computeTrust(s) {
  if (s.status === "INACTIVE") return 0;
  if (s.status === "PAUSED") return 10;
  let trust = 50;
  trust += Math.min((s.total_return || 0) * 5, 20);
  trust += Math.min(((s.win_rate || 50) - 50) * 0.5, 15);
  trust -= Math.min((s.max_drawdown || 0) * 2, 20);
  trust += Math.min((s.allocation_pct || 0) * 0.3, 10);
  return Math.max(0, Math.min(100, Math.round(trust)));
}

function regimeColor(r) {
  return { SLEEPING: "#6b7280", WAKING_UP: "#eab308", ACTIVE: "#22c55e", BREAKOUT: "#ef4444" }[r] || "#9ca3af";
}

function adaptColor(type) {
  return {
    allocation_increase: "#22c55e", allocation_decrease: "#ef4444",
    threshold_tighten: "#f59e0b", threshold_loosen: "#3b82f6",
    auto_revive: "#a78bfa", toggle: "#6b7280", reset: "#ef4444",
  }[type] || "#9ca3af";
}

function adaptIcon(type) {
  return {
    allocation_increase: "↑", allocation_decrease: "↓",
    threshold_tighten: "⊖", threshold_loosen: "⊕",
    auto_revive: "♻", toggle: "⚙", reset: "↺",
  }[type] || "•";
}
