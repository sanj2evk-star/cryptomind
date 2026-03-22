/**
 * Lab.jsx — CryptoMind v7.8: The Mind Space
 *
 * Not a dashboard. Not a report.
 * A window into a thinking mind.
 *
 * Structure:
 *   1. Identity Line (who am I, how long have I lived)
 *   2. Hero Thought (what am I thinking right now)
 *   3. Glance Grid (4 fields, readable from 5 feet)
 *   4. Thought Stream (cycle-by-cycle decision feed)
 *   5. Expand Mind (deep content behind a door)
 */

import { useState } from "react";
import { useApi } from "../hooks/useApi";
import { fmtLocalTimeShort } from "../hooks/useTime";

const _isTouch = typeof window !== "undefined" &&
  ("ontouchstart" in window || navigator.maxTouchPoints > 0);

/* ── Mood sigil icons (monochrome SVG) ── */
function MoodSigil({ mood, size = 40 }) {
  const s = size;
  const m = {
    calm_observing:      <svg width={s} height={s} viewBox="0 0 48 48"><circle cx="24" cy="24" r="18" fill="none" stroke="#6b7280" strokeWidth="1.5"/><circle cx="24" cy="24" r="4" fill="#6b7280" opacity="0.3"/></svg>,
    focused_selective:   <svg width={s} height={s} viewBox="0 0 48 48"><circle cx="24" cy="24" r="18" fill="none" stroke="#3b82f6" strokeWidth="1.5"/><line x1="24" y1="8" x2="24" y2="16" stroke="#3b82f6" strokeWidth="1.5"/><line x1="24" y1="32" x2="24" y2="40" stroke="#3b82f6" strokeWidth="1.5"/><circle cx="24" cy="24" r="3" fill="#3b82f6" opacity="0.4"/></svg>,
    cautious_defensive:  <svg width={s} height={s} viewBox="0 0 48 48"><path d="M24 6 L42 18 L42 34 L24 42 L6 34 L6 18 Z" fill="none" stroke="#d97706" strokeWidth="1.5"/><circle cx="24" cy="24" r="3" fill="#d97706" opacity="0.25"/></svg>,
    confident_steady:    <svg width={s} height={s} viewBox="0 0 48 48"><circle cx="24" cy="24" r="18" fill="none" stroke="#22c55e" strokeWidth="1.5"/><circle cx="24" cy="24" r="9" fill="none" stroke="#22c55e" strokeWidth="1" opacity="0.4"/><circle cx="24" cy="24" r="3" fill="#22c55e"/></svg>,
    alert_volatile:      <svg width={s} height={s} viewBox="0 0 48 48"><polygon points="24,6 42,38 6,38" fill="none" stroke="#ef4444" strokeWidth="1.5"/><line x1="24" y1="18" x2="24" y2="28" stroke="#ef4444" strokeWidth="2"/><circle cx="24" cy="33" r="1.5" fill="#ef4444"/></svg>,
    skeptical_filtering: <svg width={s} height={s} viewBox="0 0 48 48"><circle cx="24" cy="24" r="18" fill="none" stroke="#8b5cf6" strokeWidth="1.5" strokeDasharray="4 3"/><line x1="14" y1="14" x2="34" y2="34" stroke="#8b5cf6" strokeWidth="1.5"/><line x1="34" y1="14" x2="14" y2="34" stroke="#8b5cf6" strokeWidth="1.5"/></svg>,
    recovering_learning: <svg width={s} height={s} viewBox="0 0 48 48"><circle cx="24" cy="24" r="18" fill="none" stroke="#f59e0b" strokeWidth="1.5"/><path d="M16 28 Q20 18 24 24 Q28 30 32 20" fill="none" stroke="#f59e0b" strokeWidth="1.5"/></svg>,
    idle_waiting:        <svg width={s} height={s} viewBox="0 0 48 48"><circle cx="24" cy="24" r="18" fill="none" stroke="#4b5563" strokeWidth="1" opacity="0.4"/><circle cx="24" cy="24" r="2" fill="#4b5563" opacity="0.2"/></svg>,
  };
  return m[mood] || m.calm_observing;
}

/* ════════════════════════════════════════════════════════════════════════════
   LAB PAGE — THE MIND SPACE
   ════════════════════════════════════════════════════════════════════════════ */

export default function Lab() {
  // Core mind state
  const { data: mindState }    = useApi("/v7/mind/state", 15000);
  const { data: mindOverview } = useApi("/v7/mind", 30000);
  const { data: identityD }    = useApi("/v7/mind/identity", 60000);
  const { data: decisions }    = useApi("/v7/decisions/recent?limit=20", 10000);

  // Deep content (loaded but hidden behind Expand Mind)
  const { data: signalsD }     = useApi("/v7/signals/latest", 30000);
  const { data: crowdD }       = useApi("/v7/crowd/belief-vs-reality", 30000);
  const { data: personalityD } = useApi("/v7/mind/personality", 30000);
  const { data: contextD }     = useApi("/v7/mind/context-summary", 60000);
  const { data: journalD }     = useApi("/v7/mind/journal", 60000);
  const { data: continuityD }  = useApi("/v7/system/continuity-audit", 120000);
  const { data: sigInsightsD } = useApi("/v7/signals/insights", 45000);
  const { data: insightD } = useApi("/v7/system/insight", 15000);

  const [expanded, setExpanded] = useState(false);

  // Extract state
  const mood       = mindState?.mood || "idle_waiting";
  const moodLabel  = mindState?.mood_label || "Starting up...";
  const moodColor  = mindState?.mood_color || "#4b5563";
  const clarity    = mindState?.clarity || 0;
  const thoughts   = mindState?.thoughts || [];
  const concerns   = mindState?.concerns || [];
  const opps       = mindState?.opportunities || [];
  const reasoning  = mindState?.reasoning || "";
  const impulse    = mindState?.action_impulse || "none";

  const evoScore   = mindOverview?.evolution_score || 0;
  const level      = mindOverview?.mind_level?.level || "Seed";
  const confidence = mindOverview?.confidence || {};
  const confLabel  = confidence.label || identityD?.confidence_label || "Very Low";
  const confColor  = { "Very Low": "#6b7280", "Low": "#d97706", "Medium": "#3b82f6", "High": "#22c55e", "Elite": "#8b5cf6" }[confLabel] || "#6b7280";

  const identity   = identityD || {};
  const maturity   = identity.maturity_level || "seed";
  const totalCycles = identity.total_cycles || 0;
  const version    = identity.current_version || "?";
  const contScore  = identity.continuity_score || 0;

  const recentDecs = decisions?.decisions || [];

  // Hero thought — Claude insight first, then session insight, then fallback
  const claudeInsight = (insightD?.text && insightD.source !== "default") ? insightD.text : "";
  const sessionInsight = mindOverview?.system_age?.session_insight || "";
  const latestReason = recentDecs.length > 0 ? (recentDecs[0].short_summary || "") : "";
  const heroThought = claudeInsight || sessionInsight || reasoning || latestReason || "Gathering data. Waiting for signal.";

  // Transition pulse — what changed between last 2 cycles
  const transitionPulse = (() => {
    if (recentDecs.length < 2) return null;
    const curr = recentDecs[0];
    const prev = recentDecs[1];
    const currScore = curr.decision_score || 0;
    const prevScore = prev.decision_score || 0;
    const diff = currScore - prevScore;
    if (Math.abs(diff) < 2) return "No change";
    if (diff > 5) return "Conviction rising";
    if (diff < -5) return "Conviction falling";
    if (diff > 0) return "Signal strengthening";
    return "Signal weakening";
  })();

  // Glance grid values
  const regime = mindState?.context?.regime || recentDecs[0]?.regime || "SLEEPING";
  const edge = clarity > 60 ? "Possible" : clarity > 35 ? "Weak" : "None";
  const edgeColor = clarity > 60 ? "#22c55e" : clarity > 35 ? "#eab308" : "#6b7280";
  const actionLabel = impulse === "buy" ? "ENTER" : impulse === "sell" ? "EXIT" : "HOLD";
  const actionColor = impulse === "buy" ? "#22c55e" : impulse === "sell" ? "#ef4444" : "#6b7280";

  // Deep content
  const signals = signalsD || {};
  const sigComposite = signals.composite || {};
  const sigInsights = sigInsightsD?.insights || [];
  const crowd = crowdD || {};
  const personality = personalityD || {};
  const ctxSummary = contextD || {};
  const journalToday = journalD?.today || {};

  return (
    <div style={{ maxWidth: 800, margin: "0 auto", padding: _isTouch ? "12px 16px" : "16px 20px" }}>

      {/* ═══ 1. IDENTITY LINE ═══ */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
        marginBottom: 16, flexWrap: "wrap",
      }}>
        <MoodSigil mood={mood} size={_isTouch ? 36 : 32} />
        <div>
          <div style={{
            fontSize: _isTouch ? 14 : 13, fontWeight: 700, color: "var(--text)",
            display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
          }}>
            <span>CryptoMind</span>
            <span style={{ fontSize: 10, color: "#8b5cf6", fontWeight: 600 }}>v{version}</span>
            <span style={{
              fontSize: 9, padding: "1px 6px", borderRadius: 3, fontWeight: 600,
              background: `${moodColor}18`, color: moodColor,
              border: `1px solid ${moodColor}33`,
            }}>{moodLabel}</span>
          </div>
          <div style={{
            fontSize: _isTouch ? 11 : 10, color: "var(--text-muted)",
            display: "flex", gap: 12, marginTop: 2, flexWrap: "wrap",
          }}>
            <span>{totalCycles.toLocaleString()} cycles</span>
            <span>Confidence: <b style={{ color: confColor }}>{confLabel}</b></span>
            <span>Clarity: <b>{clarity}%</b></span>
            <span style={{ textTransform: "capitalize" }}>{maturity}</span>
          </div>
        </div>
      </div>

      {/* ═══ 2. HERO THOUGHT ═══ */}
      <div style={{
        padding: _isTouch ? "24px 20px" : "20px 18px",
        marginBottom: 16,
        borderLeft: `3px solid ${moodColor}`,
        background: "var(--surface)",
        borderRadius: "0 8px 8px 0",
      }}>
        <div style={{
          fontSize: _isTouch ? 20 : 18,
          fontWeight: 500,
          color: "var(--text)",
          lineHeight: 1.5,
          letterSpacing: -0.2,
        }}>
          "{heroThought}"
        </div>
        {transitionPulse && (
          <div style={{
            marginTop: 10, fontSize: 11, color: "var(--text-muted)",
            display: "flex", alignItems: "center", gap: 6,
          }}>
            <span style={{
              width: 6, height: 6, borderRadius: "50%",
              background: transitionPulse.includes("rising") || transitionPulse.includes("strengthening")
                ? "#22c55e" : transitionPulse === "No change" ? "#6b7280" : "#ef4444",
              display: "inline-block",
            }} />
            {transitionPulse}
          </div>
        )}
      </div>

      {/* ═══ 3. GLANCE GRID ═══ */}
      <div style={{
        display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr",
        gap: _isTouch ? 10 : 8,
        marginBottom: 20,
      }}>
        {[
          { label: "Regime", value: regime, color: regime === "ACTIVE" ? "#22c55e" : regime === "BREAKOUT" ? "#ef4444" : regime === "WAKING_UP" ? "#eab308" : "#6b7280" },
          { label: "Edge", value: edge, color: edgeColor },
          { label: "Action", value: actionLabel, color: actionColor },
          { label: "Score", value: `${evoScore}`, color: "#8b5cf6" },
        ].map(g => (
          <div key={g.label} style={{ textAlign: "center" }}>
            <div style={{ fontSize: 9, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>
              {g.label}
            </div>
            <div style={{
              fontSize: _isTouch ? 18 : 16, fontWeight: 700, color: g.color,
              textTransform: "uppercase",
            }}>
              {g.value}
            </div>
          </div>
        ))}
      </div>

      {/* ═══ 4. THOUGHT STREAM ═══ */}
      <div style={{ marginBottom: 20 }}>
        <div style={{
          fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase",
          letterSpacing: 0.5, marginBottom: 8,
        }}>
          Thought Stream
        </div>

        {recentDecs.length === 0 && (
          <div style={{
            padding: "20px", textAlign: "center",
            color: "var(--text-muted)", fontSize: 12,
          }}>
            Waiting for first cycle...
          </div>
        )}

        <div style={{ maxHeight: _isTouch ? 320 : 360, overflowY: "auto" }}>
          {recentDecs.map((d, i) => {
            const action = (d.decision_action || "HOLD").toUpperCase();
            const isBuy = action === "BUY";
            const isSell = action === "SELL";
            const isHold = action === "HOLD";
            const summary = d.short_summary || d.regime || "";

            return (
              <div key={i} style={{
                padding: _isTouch ? "8px 0" : "6px 0",
                borderBottom: i < recentDecs.length - 1 ? "1px solid var(--border)" : "none",
                opacity: isHold ? 0.55 : 1,
              }}>
                <div style={{
                  display: "flex", alignItems: "center", gap: 10,
                }}>
                  {/* Time */}
                  <span style={{
                    fontSize: _isTouch ? 11 : 10, color: "var(--text-muted)",
                    minWidth: 44, fontVariantNumeric: "tabular-nums",
                  }}>
                    {fmtLocalTimeShort(d.timestamp)}
                  </span>

                  {/* Action badge */}
                  <span style={{
                    fontSize: _isTouch ? 10 : 9, fontWeight: 700,
                    padding: "2px 6px", borderRadius: 3, minWidth: 36, textAlign: "center",
                    background: isBuy ? "#22c55e22" : isSell ? "#ef444422" : "transparent",
                    color: isBuy ? "#22c55e" : isSell ? "#ef4444" : "#6b7280",
                  }}>
                    {action}
                  </span>

                  {/* Score */}
                  <span style={{ fontSize: 10, color: "var(--text-muted)", minWidth: 24 }}>
                    {d.decision_score?.toFixed(0) || "—"}
                  </span>
                </div>

                {/* Thought text */}
                <div style={{
                  fontSize: _isTouch ? 12 : 11,
                  color: isHold ? "var(--text-muted)" : "var(--text)",
                  marginTop: 2, marginLeft: 54 + 10,
                  lineHeight: 1.4,
                }}>
                  {summary}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ═══ 5. EXPAND MIND ═══ */}
      <div style={{ marginBottom: 20 }}>
        <button
          onClick={() => setExpanded(v => !v)}
          style={{
            width: "100%", padding: "12px 16px",
            background: expanded ? "var(--surface)" : "transparent",
            border: `1px solid ${expanded ? "var(--border)" : "var(--border)"}`,
            borderRadius: expanded ? "8px 8px 0 0" : 8,
            color: "#8b5cf6", fontSize: 12, fontWeight: 600,
            cursor: "pointer", textAlign: "center",
            letterSpacing: 0.3,
          }}
        >
          {expanded ? "▾ Collapse Mind" : "▸ Expand Mind"}
        </button>

        {expanded && (
          <div style={{
            border: "1px solid var(--border)", borderTop: "none",
            borderRadius: "0 0 8px 8px", padding: _isTouch ? "14px 16px" : "12px 14px",
            background: "var(--surface)",
          }}>

            {/* Thoughts, Concerns, Opportunities */}
            {(thoughts.length > 0 || concerns.length > 0 || opps.length > 0) && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 6 }}>Internal State</div>
                {thoughts.map((t, i) => (
                  <div key={`t${i}`} style={{ fontSize: 11, color: "var(--text)", padding: "2px 0", lineHeight: 1.4 }}>
                    {t}
                  </div>
                ))}
                {concerns.map((c, i) => (
                  <div key={`c${i}`} style={{ fontSize: 11, color: "#ef4444", padding: "2px 0", opacity: 0.8 }}>
                    ⚠ {c}
                  </div>
                ))}
                {opps.map((o, i) => (
                  <div key={`o${i}`} style={{ fontSize: 11, color: "#22c55e", padding: "2px 0", opacity: 0.8 }}>
                    ✦ {o}
                  </div>
                ))}
              </div>
            )}

            {/* Signal Layer */}
            {sigInsights.length > 0 && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 6 }}>Signal Insights</div>
                {sigInsights.map((s, i) => (
                  <div key={i} style={{
                    fontSize: 11, color: "var(--text)", padding: "3px 0",
                    borderBottom: i < sigInsights.length - 1 ? "1px solid var(--border)" : "none",
                  }}>
                    <span style={{
                      fontSize: 9, fontWeight: 600, marginRight: 6,
                      color: s.importance === "high" ? "#ef4444" : s.importance === "medium" ? "#eab308" : "#6b7280",
                    }}>
                      {s.importance === "high" ? "!" : s.importance === "medium" ? "~" : "·"}
                    </span>
                    {s.text || s.message || JSON.stringify(s)}
                  </div>
                ))}
              </div>
            )}

            {/* Belief vs Reality */}
            {crowd.crowd && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 6 }}>Belief vs Reality</div>
                <div style={{ display: "flex", gap: 16, fontSize: 11, flexWrap: "wrap" }}>
                  <span>Crowd: <b style={{ color: crowd.crowd?.bias === "bullish" ? "#22c55e" : crowd.crowd?.bias === "bearish" ? "#ef4444" : "var(--text)" }}>{crowd.crowd?.bias || "—"}</b></span>
                  <span>Reality: <b>{crowd.reality?.trend || "—"}</b></span>
                  <span>Alignment: <b>{crowd.comparison?.alignment || "—"}</b></span>
                  {crowd.comparison?.divergence_score > 30 && (
                    <span style={{ color: "#ef4444" }}>Divergence: {crowd.comparison.divergence_score}%</span>
                  )}
                </div>
              </div>
            )}

            {/* Personality */}
            {personality.dominant_trait && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 6 }}>Personality</div>
                <div style={{ fontSize: 12, color: "var(--text)" }}>
                  <b style={{ color: "#8b5cf6" }}>{personality.dominant_trait?.replace(/_/g, " ")}</b>
                  {personality.oneliner && <span style={{ color: "var(--text-muted)", marginLeft: 8 }}>— {personality.oneliner}</span>}
                </div>
              </div>
            )}

            {/* Context */}
            {ctxSummary.summary && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 6 }}>Context</div>
                <div style={{ fontSize: 11, color: "var(--text)", lineHeight: 1.5 }}>
                  {ctxSummary.summary}
                </div>
              </div>
            )}

            {/* Journal */}
            {journalToday.entry && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 6 }}>Today's Journal</div>
                <div style={{ fontSize: 11, color: "var(--text)", lineHeight: 1.5, fontStyle: "italic" }}>
                  "{journalToday.entry}"
                </div>
              </div>
            )}

            {/* Continuity Health */}
            {continuityD && (
              <div style={{ marginBottom: 8 }}>
                <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 6 }}>Continuity</div>
                <div style={{ display: "flex", gap: 16, fontSize: 11, flexWrap: "wrap" }}>
                  <span>Health: <b style={{ color: continuityD.continuity_health === "good" ? "#22c55e" : "#eab308" }}>{continuityD.continuity_health}</b></span>
                  <span>Sessions: <b>{continuityD.lifetime_sessions}</b></span>
                  <span>Trades: <b>{continuityD.lifetime_trades}</b></span>
                  <span>Cycles: <b>{continuityD.lifetime_cycles}</b></span>
                  <span>DB: <b>{continuityD.db_size_kb}KB</b></span>
                  <span>Version: <b style={{ color: "#8b5cf6" }}>{continuityD.current_version}</b></span>
                </div>
                {continuityD.warnings?.length > 0 && (
                  <div style={{ marginTop: 4, fontSize: 10, color: "#ef4444" }}>
                    {continuityD.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
