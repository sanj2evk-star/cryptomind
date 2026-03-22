import { useState, useCallback, useRef } from "react";
import { useApi, BASE, getToken } from "../hooks/useApi";
import { Loading, ErrorBox, EmptyState } from "../components/StatusMessage";

/* ------------------------------------------------------------------ */
/* Selector Pill Group                                                */
/* ------------------------------------------------------------------ */
function PillGroup({ label, options, value, onChange }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{ fontSize: 10, color: "var(--text-muted)", fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.3, minWidth: 44 }}>
        {label}
      </span>
      <div style={{ display: "flex", gap: 2, padding: 2, background: "var(--bg)", borderRadius: 5, border: "1px solid var(--border)" }}>
        {options.map(opt => (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            style={{
              padding: "4px 10px", border: "none", borderRadius: 3,
              fontSize: 11, fontWeight: 600, cursor: "pointer",
              background: value === opt.value ? "var(--surface)" : "transparent",
              color: value === opt.value ? "var(--text)" : "var(--text-muted)",
              transition: "all 0.15s ease",
            }}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Section Card                                                       */
/* ------------------------------------------------------------------ */
function Section({ title, color, children }) {
  return (
    <div style={{
      padding: "14px 16px", background: "var(--surface)", border: "1px solid var(--border)",
      borderRadius: 8, borderLeft: `3px solid ${color || "var(--border)"}`,
    }}>
      <div style={{ fontSize: 10, fontWeight: 600, color: color || "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.4, marginBottom: 8 }}>
        {title}
      </div>
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Key-Value Row                                                      */
/* ------------------------------------------------------------------ */
function KV({ label, value, color }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "2px 0", fontSize: 12 }}>
      <span style={{ color: "var(--text-muted)" }}>{label}</span>
      <span style={{ fontWeight: 600, color: color || "var(--text)" }}>{value ?? "—"}</span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* PnL Color                                                          */
/* ------------------------------------------------------------------ */
function pnlColor(v) {
  const n = Number(v);
  if (n > 0) return "var(--green)";
  if (n < 0) return "var(--red)";
  return "var(--text-muted)";
}

/* ------------------------------------------------------------------ */
/* Review Page                                                        */
/* ------------------------------------------------------------------ */
export default function ReviewPage() {
  const [reviewType, setReviewType] = useState("daily");
  const [scope, setScope] = useState("session");
  const [mode, setMode] = useState("summary");
  const [exportData, setExportData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);
  const textRef = useRef(null);

  const generateExport = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ review_type: reviewType, scope, mode });
      const res = await fetch(`${BASE}/v7/review/export?${params}`, {
        headers: { "Authorization": `Bearer ${getToken()}` },
        signal: AbortSignal.timeout(15000),
      });
      const data = await res.json();
      if (data.error) {
        setError(data.error);
      }
      setExportData(data);
    } catch (e) {
      setError(e.message || "Failed to generate export");
    } finally {
      setLoading(false);
    }
  }, [reviewType, scope, mode]);

  const copyToClipboard = useCallback(() => {
    const text = exportData?.text_export;
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [exportData]);

  const downloadText = useCallback(() => {
    const text = exportData?.text_export;
    if (!text) return;
    const h = exportData?.header || {};
    const filename = `cryptomind_review_${h.review_type || "daily"}_${h.start_date || "unknown"}.txt`;
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }, [exportData]);

  const downloadJSON = useCallback(() => {
    if (!exportData) return;
    const h = exportData?.header || {};
    const filename = `cryptomind_review_${h.review_type || "daily"}_${h.start_date || "unknown"}.json`;
    const clean = { ...exportData };
    delete clean.text_export; // Remove text from JSON export to keep it clean
    const blob = new Blob([JSON.stringify(clean, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }, [exportData]);

  const h = exportData?.header || {};
  const ms = exportData?.mind_state || {};
  const mc = exportData?.market_context || {};
  const act = exportData?.activity_summary || {};
  const perf = exportData?.performance_summary || {};
  const strats = exportData?.strategy_breakdown || [];
  const dq = exportData?.decision_quality || {};
  const rl = exportData?.reflection_learning || {};
  const ad = exportData?.adaptation_discipline || {};
  const obs = exportData?.observer_summary || {};
  const cc = exportData?.continuity_comparison || {};
  const warning = exportData?.low_data_warning;

  return (
    <div style={{ maxWidth: 900 }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ margin: 0, fontSize: 17, fontWeight: 700 }}>Review Export</h1>
        <span style={{ fontSize: 10, color: "var(--text-muted)" }}>Black Box System v7.5.2</span>
      </div>

      <p style={{ color: "var(--text-muted)", fontSize: 12, marginBottom: 16, lineHeight: 1.5 }}>
        Generate a full review of system behavior, decisions, learning, and evolution.
        Same mind, same memory — reviewed over different windows.
      </p>

      {/* Controls */}
      <div style={{
        display: "flex", flexWrap: "wrap", gap: 12, padding: "12px 16px",
        background: "var(--surface)", border: "1px solid var(--border)",
        borderRadius: 8, marginBottom: 16, alignItems: "center",
      }}>
        <PillGroup
          label="Type"
          options={[
            { value: "daily", label: "Daily" },
            { value: "weekly", label: "Weekly" },
            { value: "monthly", label: "Monthly" },
          ]}
          value={reviewType}
          onChange={setReviewType}
        />
        <PillGroup
          label="Scope"
          options={[
            { value: "session", label: "Session" },
            { value: "version", label: "Version" },
            { value: "lifetime", label: "Lifetime" },
          ]}
          value={scope}
          onChange={setScope}
        />
        <PillGroup
          label="Mode"
          options={[
            { value: "summary", label: "Summary" },
            { value: "detailed", label: "Detailed" },
          ]}
          value={mode}
          onChange={setMode}
        />

        <button
          onClick={generateExport}
          disabled={loading}
          style={{
            padding: "7px 20px", background: "#8b5cf6", color: "#fff",
            border: "none", borderRadius: 6, fontSize: 12, fontWeight: 700,
            cursor: loading ? "wait" : "pointer", opacity: loading ? 0.6 : 1,
            marginLeft: "auto",
          }}
        >
          {loading ? "Generating..." : "Generate Review"}
        </button>
      </div>

      {/* Error */}
      {error && <ErrorBox message={error} />}

      {/* Loading */}
      {loading && <Loading message="Generating review export..." />}

      {/* No data yet */}
      {!exportData && !loading && !error && (
        <EmptyState
          title="No review generated yet"
          message="Select review type, scope, and mode, then click Generate Review."
        />
      )}

      {/* Low data warning */}
      {warning && (
        <div style={{
          padding: "10px 14px", background: "#f59e0b12", border: "1px solid #f59e0b33",
          borderRadius: 6, marginBottom: 12, fontSize: 12, color: "#f59e0b",
          borderLeft: "3px solid #f59e0b",
        }}>
          {warning}
        </div>
      )}

      {/* Export sections */}
      {exportData && !loading && (
        <>
          {/* Action buttons */}
          <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
            <button onClick={copyToClipboard} style={{
              padding: "6px 14px", background: "var(--surface)", border: "1px solid var(--border)",
              borderRadius: 6, fontSize: 11, fontWeight: 600, cursor: "pointer",
              color: copied ? "var(--green)" : "var(--text)",
            }}>
              {copied ? "Copied!" : "Copy Text"}
            </button>
            <button onClick={downloadText} style={{
              padding: "6px 14px", background: "var(--surface)", border: "1px solid var(--border)",
              borderRadius: 6, fontSize: 11, fontWeight: 600, cursor: "pointer", color: "var(--text)",
            }}>
              Download .txt
            </button>
            <button onClick={downloadJSON} style={{
              padding: "6px 14px", background: "var(--surface)", border: "1px solid var(--border)",
              borderRadius: 6, fontSize: 11, fontWeight: 600, cursor: "pointer", color: "var(--text)",
            }}>
              Download .json
            </button>
          </div>

          {/* Header info bar */}
          <div style={{
            display: "flex", gap: 16, flexWrap: "wrap", padding: "8px 14px",
            background: "var(--bg)", border: "1px solid var(--border)",
            borderRadius: 6, marginBottom: 12, fontSize: 11, alignItems: "center",
          }}>
            <span style={{ fontWeight: 700, color: "#8b5cf6" }}>v{h.version}</span>
            <span>Session #{h.session_id}</span>
            <span>{h.review_type} review</span>
            <span>{h.start_date} &rarr; {h.end_date}</span>
            <span style={{ color: "var(--text-muted)" }}>{h.total_cycles_lifetime} lifetime cycles</span>
          </div>

          {/* Section Grid */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
            {/* Mind State */}
            <Section title="Mind State" color="#8b5cf6">
              <KV label="Level" value={ms.current_level} color="#8b5cf6" />
              <KV label="Score" value={`${ms.evolution_score} / 1000`} />
              <KV label="Confidence" value={`${ms.confidence_label} (${ms.confidence_score}%)`} />
              <KV label="Evidence" value={`${ms.evidence_strength_pct}%`} />
              <KV label="Intent" value={ms.session_intent} />
              <KV label="Identity" value={ms.identity_status} />
              <KV label="Continuity" value={ms.continuity_score} />
            </Section>

            {/* Market Context */}
            <Section title="Market Context" color="#3b82f6">
              <KV label="Regime" value={mc.dominant_regime} />
              <KV label="Quality" value={mc.market_quality} />
              <KV label="Fear/Greed" value={mc.fear_greed_value != null ? `${mc.fear_greed_value} (${mc.fear_greed_class})` : "N/A"} />
              <KV label="Noise" value={mc.noise_level} />
              <KV label="Crowd" value={mc.crowd_bias} />
              <KV label="Alignment" value={mc.crowd_alignment} />
            </Section>

            {/* Activity Summary */}
            <Section title="Activity" color="#22c55e">
              <KV label="Trades" value={act.trades_taken} />
              <KV label="Buys / Sells" value={`${act.buys} / ${act.sells}`} />
              <KV label="Holds" value={act.holds} />
              <KV label="Probes" value={act.probes} />
              <KV label="Full / Re-entry" value={`${act.full_entries} / ${act.reentries}`} />
              <KV label="Avg Exposure" value={`${act.average_exposure}%`} />
              <KV label="Max Exposure" value={`${act.max_exposure}%`} />
            </Section>

            {/* Performance */}
            <Section title="Performance" color={pnlColor(perf.realized_pnl)}>
              <KV label="Realized PnL" value={`$${perf.realized_pnl}`} color={pnlColor(perf.realized_pnl)} />
              <KV label="Win Rate" value={`${perf.win_rate}%`} color={perf.win_rate >= 50 ? "var(--green)" : "var(--red)"} />
              <KV label="Wins / Losses" value={`${perf.wins} / ${perf.losses}`} />
              <KV label="Best Trade" value={`$${perf.best_trade}`} color="var(--green)" />
              <KV label="Worst Trade" value={`$${perf.worst_trade}`} color="var(--red)" />
              <KV label="Max Drawdown" value={`$${perf.max_drawdown}`} color="var(--red)" />
              <KV label="Avg Win / Loss" value={`$${perf.avg_win} / $${perf.avg_loss}`} />
            </Section>
          </div>

          {/* Strategy Breakdown */}
          {strats.length > 0 && (
            <Section title="Strategy Breakdown" color="#6366f1">
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--border)" }}>
                      <th style={{ textAlign: "left", padding: "4px 8px", color: "var(--text-muted)", fontWeight: 600 }}>Strategy</th>
                      <th style={{ textAlign: "right", padding: "4px 8px", color: "var(--text-muted)", fontWeight: 600 }}>Trades</th>
                      <th style={{ textAlign: "right", padding: "4px 8px", color: "var(--text-muted)", fontWeight: 600 }}>Win Rate</th>
                      <th style={{ textAlign: "right", padding: "4px 8px", color: "var(--text-muted)", fontWeight: 600 }}>PnL</th>
                      <th style={{ textAlign: "right", padding: "4px 8px", color: "var(--text-muted)", fontWeight: 600 }}>Avg PnL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {strats.map((s, i) => (
                      <tr key={i} style={{ borderBottom: "1px solid var(--border)" }}>
                        <td style={{ padding: "4px 8px", fontWeight: 600 }}>{s.name}</td>
                        <td style={{ padding: "4px 8px", textAlign: "right" }}>{s.trades}</td>
                        <td style={{ padding: "4px 8px", textAlign: "right", color: s.win_rate >= 50 ? "var(--green)" : "var(--red)" }}>{s.win_rate}%</td>
                        <td style={{ padding: "4px 8px", textAlign: "right", color: pnlColor(s.pnl) }}>${s.pnl}</td>
                        <td style={{ padding: "4px 8px", textAlign: "right", color: pnlColor(s.avg_pnl) }}>${s.avg_pnl}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          )}

          <div style={{ height: 12 }} />

          {/* Decision Quality + Reflection side by side */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
            <Section title="Decision Quality" color="#f59e0b">
              <KV label="Reflections" value={dq.total_reflections} />
              <KV label="Timing Issues" value={dq.timing_issues_count} />
              <KV label="Conf Mismatch" value={dq.confidence_mismatch_count} />
              <KV label="Overtrading" value={dq.overtrading_signs ? "Yes" : "No"} color={dq.overtrading_signs ? "var(--red)" : "var(--green)"} />
              <KV label="Probe Quality" value={dq.probe_quality} />
              {(dq.top_good_decisions || []).length > 0 && (
                <div style={{ marginTop: 6, fontSize: 11, color: "var(--green)", fontStyle: "italic" }}>
                  {dq.top_good_decisions[0]}
                </div>
              )}
              {(dq.top_bad_decisions || []).length > 0 && (
                <div style={{ marginTop: 4, fontSize: 11, color: "var(--red)", fontStyle: "italic" }}>
                  {dq.top_bad_decisions[0]}
                </div>
              )}
            </Section>

            <Section title="Reflection & Learning" color="#8b5cf6">
              <div style={{ fontSize: 12, color: "var(--text)", lineHeight: 1.5, marginBottom: 6, fontStyle: "italic" }}>
                "{rl.key_insight}"
              </div>
              <KV label="Most Repeated" value={rl.most_repeated_lesson?.slice(0, 50)} />
              <KV label="Journals" value={rl.journal_entries_in_range} />
              {(rl.top_recurring_strengths || []).length > 0 && (
                <div style={{ marginTop: 6, fontSize: 11, color: "var(--green)" }}>
                  Strengths: {rl.top_recurring_strengths.join(", ")}
                </div>
              )}
              {(rl.top_recurring_mistakes || []).length > 0 && (
                <div style={{ marginTop: 4, fontSize: 11, color: "var(--red)" }}>
                  Mistakes: {rl.top_recurring_mistakes.join(", ")}
                </div>
              )}
            </Section>
          </div>

          {/* Adaptation + Observer side by side */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
            <Section title="Adaptation & Discipline" color="#06b6d4">
              <KV label="Attempted" value={ad.attempted_adaptations} />
              <KV label="Allowed" value={ad.allowed_adaptations} />
              <KV label="Blocked" value={ad.blocked_adaptations} />
              <KV label="Stability" value={ad.system_stability} />
              {(ad.top_block_reasons || []).map((br, i) => (
                <div key={i} style={{ fontSize: 10, color: "var(--text-muted)", paddingLeft: 8 }}>
                  Block: {br.reason} ({br.count}x)
                </div>
              ))}
            </Section>

            <Section title="Observer Summary" color="#a78bfa">
              <KV label="News Classified" value={obs.total_news_classified} />
              <KV label="Rejected Noise" value={obs.rejected_noise} />
              <KV label="Signals Found" value={obs.interesting_signals} />
              <KV label="Truth Accuracy" value={`${obs.truth_accuracy_pct}% (${obs.truth_total_graded} graded)`} />
              <KV label="Posture" value={obs.observer_posture} />
            </Section>
          </div>

          {/* Continuity Comparison (full width) */}
          <Section title="Continuity vs Lifetime" color="#f97316">
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              <div>
                <div style={{ fontSize: 10, color: "var(--text-muted)", fontWeight: 600, marginBottom: 4 }}>THIS RANGE</div>
                <KV label="PnL" value={`$${cc.range_pnl}`} color={pnlColor(cc.range_pnl)} />
                <KV label="Win Rate" value={`${cc.range_win_rate}%`} />
                <KV label="Trades" value={cc.range_trades} />
              </div>
              <div>
                <div style={{ fontSize: 10, color: "var(--text-muted)", fontWeight: 600, marginBottom: 4 }}>LIFETIME</div>
                <KV label="PnL" value={`$${cc.lifetime_pnl}`} color={pnlColor(cc.lifetime_pnl)} />
                <KV label="Win Rate" value={`${cc.lifetime_win_rate}%`} />
                <KV label="Trades" value={cc.lifetime_trades} />
              </div>
            </div>
            <div style={{ marginTop: 8, padding: "8px 12px", background: "var(--bg)", borderRadius: 6 }}>
              <KV label="PnL Improving" value={cc.pnl_improving ? "Yes" : "No"} color={cc.pnl_improving ? "var(--green)" : "var(--red)"} />
              <KV label="Identity Depth" value={cc.identity_depth} />
              <div style={{ fontSize: 12, color: "var(--text)", lineHeight: 1.5, marginTop: 6, fontStyle: "italic" }}>
                {cc.assessment}
              </div>
            </div>
          </Section>

          {/* Text export preview */}
          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", marginBottom: 6 }}>
              Raw Text Export
            </div>
            <pre
              ref={textRef}
              style={{
                padding: "14px 16px", background: "var(--bg)", border: "1px solid var(--border)",
                borderRadius: 8, fontSize: 11, lineHeight: 1.5, color: "var(--text)",
                overflow: "auto", maxHeight: 400, whiteSpace: "pre-wrap", fontFamily: "monospace",
              }}
            >
              {exportData?.text_export || "No export text."}
            </pre>
          </div>
        </>
      )}
    </div>
  );
}
