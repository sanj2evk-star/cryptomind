import { useState } from "react";
import { useApi } from "../hooks/useApi";
import { Loading, ErrorBox, EmptyState } from "../components/StatusMessage";
import ScopeToggle from "../components/ScopeToggle";

const API = import.meta.env.VITE_API_URL || window.location.origin;

/* ── Compact badge ── */
function Badge({ text, color }) {
  return (
    <span style={{
      display: "inline-block", padding: "2px 6px", borderRadius: 3,
      fontSize: 9, fontWeight: 700, background: `${color}22`, color,
    }}>{text}</span>
  );
}

/* ── Memory type colors ── */
const TYPE_COLORS = {
  signal_success: "#22c55e",
  signal_failure: "#ef4444",
  good_exit: "#3b82f6",
  bad_exit: "#f97316",
  sleeping_probe_success: "#8b5cf6",
  sleeping_probe_failure: "#a855f7",
  trend_follow_success: "#06b6d4",
  trend_follow_failure: "#f43f5e",
  missed_move: "#eab308",
  churn_detected: "#f59e0b",
  overtrading_penalty: "#ef4444",
  mean_revert_success: "#22c55e",
  mean_revert_failure: "#ef4444",
};

/* ── Memory Card ── */
function MemoryCard({ memory }) {
  const color = TYPE_COLORS[memory.memory_type] || "var(--text-muted)";
  return (
    <div style={{
      background: "var(--surface)", border: "1px solid var(--border)",
      borderRadius: 8, padding: 12, marginBottom: 8,
      borderLeft: `3px solid ${color}`,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
        <Badge text={memory.memory_type?.replace(/_/g, " ")} color={color} />
        <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
          {memory.times_observed}x observed
        </span>
      </div>
      <p style={{ fontSize: 12, margin: "4px 0", color: "var(--text)", lineHeight: 1.4 }}>
        {memory.lesson_text}
      </p>
      <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
        {memory.strategy && (
          <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
            Strategy: <strong>{memory.strategy}</strong>
          </span>
        )}
        {memory.regime && (
          <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
            Regime: <strong>{memory.regime}</strong>
          </span>
        )}
        {memory.pattern_signature && (
          <span style={{ fontSize: 10, color: "var(--text-muted)", opacity: 0.7 }}>
            {memory.pattern_signature}
          </span>
        )}
      </div>
    </div>
  );
}

/* ── Adaptation Card ── */
function AdaptationCard({ adaptation }) {
  const statusColors = { pending: "#eab308", helpful: "#22c55e", harmful: "#ef4444", inconclusive: "#6b7280" };
  return (
    <div style={{
      background: "var(--surface)", border: "1px solid var(--border)",
      borderRadius: 8, padding: 12, marginBottom: 8,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <Badge text={adaptation.trigger_type?.replace(/_/g, " ")} color="#3b82f6" />
        <Badge
          text={adaptation.validation_status || "pending"}
          color={statusColors[adaptation.validation_status] || "#6b7280"}
        />
      </div>
      <div style={{ fontSize: 11, marginTop: 6 }}>
        <div><span style={{ color: "var(--text-muted)" }}>Old:</span> {adaptation.old_behavior}</div>
        <div><span style={{ color: "var(--text-muted)" }}>New:</span> <strong>{adaptation.new_behavior}</strong></div>
      </div>
      <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>{adaptation.reason}</p>
    </div>
  );
}

/* ── Daily Review Card ── */
function ReviewCard({ review }) {
  if (!review) return null;
  const pnlColor = (review.net_pnl || 0) >= 0 ? "var(--green)" : "var(--red)";
  return (
    <div style={{
      background: "var(--surface)", border: "1px solid var(--border)",
      borderRadius: 8, padding: 16,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
        <h4 style={{ margin: 0, fontSize: 14 }}>Daily Review — {review.review_date}</h4>
        <span style={{ fontSize: 11, color: pnlColor, fontWeight: 700 }}>
          PnL: ${(review.net_pnl || 0).toFixed(6)}
        </span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
        <div style={{ fontSize: 11 }}>
          <span style={{ color: "var(--text-muted)" }}>Trades:</span> {review.trades_count}
          <span style={{ color: "var(--green)", marginLeft: 8 }}>{review.winning_trades}W</span>
          <span style={{ color: "var(--red)", marginLeft: 4 }}>{review.losing_trades}L</span>
        </div>
        <div style={{ fontSize: 11 }}>
          <span style={{ color: "var(--text-muted)" }}>Best:</span> {review.best_strategy || "—"}
          <span style={{ color: "var(--text-muted)", marginLeft: 12 }}>Worst:</span> {review.worst_strategy || "—"}
        </div>
      </div>
      {review.market_observation && (
        <Section title="Market" text={review.market_observation} />
      )}
      {review.what_worked && (
        <Section title="Worked" text={review.what_worked} color="var(--green)" />
      )}
      {review.what_failed && (
        <Section title="Failed" text={review.what_failed} color="var(--red)" />
      )}
      {review.behavior_observation && (
        <Section title="Behavior" text={review.behavior_observation} />
      )}
      {review.next_day_bias && (
        <Section title="Next Bias" text={review.next_day_bias} color="#3b82f6" />
      )}
    </div>
  );
}

function Section({ title, text, color }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <span style={{ fontSize: 10, fontWeight: 700, color: color || "var(--text-muted)", textTransform: "uppercase" }}>
        {title}
      </span>
      <p style={{ fontSize: 12, margin: "2px 0", lineHeight: 1.5 }}>{text}</p>
    </div>
  );
}

/* ── Behavior Profile ── */
function ProfileBar({ label, value }) {
  const v = Math.round((value || 0.5) * 100);
  const color = v > 60 ? "var(--green)" : v < 40 ? "var(--red)" : "var(--blue)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
      <span style={{ fontSize: 10, color: "var(--text-muted)", width: 100, textAlign: "right" }}>
        {label}
      </span>
      <div style={{ flex: 1, height: 6, background: "var(--bg)", borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${v}%`, height: "100%", background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 11, fontWeight: 600, color, minWidth: 30 }}>{v}%</span>
    </div>
  );
}

/* ── Session Archive Card ── */
function SessionCard({ session, isCurrent }) {
  return (
    <div style={{
      background: "var(--surface)", border: `1px solid ${isCurrent ? "var(--blue)" : "var(--border)"}`,
      borderRadius: 8, padding: 12, marginBottom: 6,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <span style={{ fontWeight: 700, fontSize: 13 }}>v{session.app_version}</span>
          {isCurrent && <Badge text="ACTIVE" color="#22c55e" />}
          {!isCurrent && <Badge text="CLOSED" color="#6b7280" />}
        </div>
        <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
          #{session.session_id}
        </span>
      </div>
      <div style={{ display: "flex", gap: 12, marginTop: 6, fontSize: 11, color: "var(--text-muted)" }}>
        <span>Trades: {session.total_trades || 0}</span>
        <span>Cycles: {session.total_cycles || 0}</span>
        <span style={{ color: (session.realized_pnl || 0) >= 0 ? "var(--green)" : "var(--red)" }}>
          PnL: ${(session.realized_pnl || 0).toFixed(6)}
        </span>
      </div>
      {session.notes && (
        <p style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>{session.notes}</p>
      )}
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════
   MAIN COMPONENT
   ══════════════════════════════════════════════════════════════ */

export default function Memory() {
  const { data: memData, loading: memLoad } = useApi("/v7/memory", 15000);
  const { data: feedbackData } = useApi("/v7/feedback", 15000);
  const { data: profileData } = useApi("/v7/behavior-profile", 30000);
  const { data: reviewData } = useApi("/v7/daily-review", 30000);
  const { data: sessionsData } = useApi("/v7/sessions", 60000);
  const { data: adaptData } = useApi("/v7/adaptations?limit=10", 30000);
  const { data: allMemories } = useApi("/v7/memories?limit=20", 15000);
  const { data: ltMemData } = useApi("/v7/lifetime/memories?scope=lifetime&limit=30", 30000);
  const { data: ltJournalData } = useApi("/v7/lifetime/journals?scope=lifetime&limit=10", 60000);

  const [tab, setTab] = useState("overview");
  const [memScope, setMemScope] = useState("session");
  const [generating, setGenerating] = useState(false);

  const generateReview = async () => {
    setGenerating(true);
    try {
      await fetch(`${API}/v7/daily-review/generate`, { method: "POST" });
    } finally {
      setTimeout(() => setGenerating(false), 1000);
    }
  };

  if (memLoad) return <Loading />;

  const memories = allMemories?.memories || [];
  const adaptations = adaptData?.adaptations || [];
  const profile = profileData?.profile || {};
  const review = reviewData?.review;
  const sessions = sessionsData?.sessions || [];
  const currentSessionId = sessionsData?.current_session_id;
  const summary = memData || {};
  const fb = feedbackData || {};

  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "memories", label: `Memories (${summary.total_memories || 0})` },
    { id: "adaptations", label: "Adaptations" },
    { id: "reviews", label: "Reviews" },
    { id: "sessions", label: "Sessions" },
  ];

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "20px 16px" }}>
      <h2 style={{ margin: "0 0 4px", fontSize: 18 }}>Memory & Reflection</h2>
      <p style={{ color: "var(--text-muted)", fontSize: 12, margin: "0 0 16px" }}>
        v7 — Self-evolving intelligence. What worked. What failed. What to remember.
      </p>

      {/* Tab bar */}
      <div style={{ display: "flex", gap: 4, marginBottom: 16, flexWrap: "wrap" }}>
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              padding: "6px 12px", borderRadius: 6, fontSize: 11, fontWeight: 600,
              background: tab === t.id ? "var(--blue)" : "var(--surface)",
              color: tab === t.id ? "#fff" : "var(--text-muted)",
              border: `1px solid ${tab === t.id ? "var(--blue)" : "var(--border)"}`,
              cursor: "pointer",
            }}
          >{t.label}</button>
        ))}
      </div>

      {/* ── OVERVIEW TAB ── */}
      {tab === "overview" && (
        <div style={{ display: "grid", gap: 12 }}>
          {/* Stats strip */}
          <div style={{
            display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
            gap: 8,
          }}>
            <StatBox label="Memories Learned" value={summary.total_memories || 0} color="var(--blue)" />
            <StatBox label="Successes" value={summary.total_successes || 0} color="var(--green)" />
            <StatBox label="Failures" value={summary.total_failures || 0} color="var(--red)" />
            <StatBox label="Adaptations" value={fb.total_adaptations || 0} color="#8b5cf6" />
          </div>

          {/* Latest memory */}
          {summary.latest_memory && (
            <div style={{
              background: "var(--surface)", border: "1px solid var(--border)",
              borderRadius: 8, padding: 12,
            }}>
              <h4 style={{ margin: "0 0 6px", fontSize: 12, color: "var(--text-muted)" }}>Latest Memory</h4>
              <p style={{ fontSize: 12, margin: 0 }}>{summary.latest_memory.lesson}</p>
              <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 4 }}>
                {summary.latest_memory.type?.replace(/_/g, " ")} · {summary.latest_memory.times_observed}x observed
              </div>
            </div>
          )}

          {/* Behavior profile preview */}
          {Object.keys(profile).length > 0 && (
            <div style={{
              background: "var(--surface)", border: "1px solid var(--border)",
              borderRadius: 8, padding: 12,
            }}>
              <h4 style={{ margin: "0 0 8px", fontSize: 12, color: "var(--text-muted)" }}>Behavior Profile</h4>
              <ProfileBar label="Aggressiveness" value={profile.aggressiveness} />
              <ProfileBar label="Patience" value={profile.patience} />
              <ProfileBar label="Probe Bias" value={profile.probe_bias} />
              <ProfileBar label="Conviction" value={profile.conviction_threshold} />
              <ProfileBar label="Noise Tolerance" value={profile.noise_tolerance} />
            </div>
          )}

          {/* Latest review preview */}
          {review && <ReviewCard review={review} />}
        </div>
      )}

      {/* ── MEMORIES TAB ── */}
      {tab === "memories" && (
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
              {memScope === "lifetime" ? `${ltMemData?.total || 0} lifetime memories` : `${memories.length} session memories`}
            </span>
            <ScopeToggle value={memScope} onChange={setMemScope} compact/>
          </div>
          {memScope === "lifetime" ? (
            (ltMemData?.memories || []).length === 0 ? (
              <EmptyState message="No lifetime memories yet." />
            ) : (
              <>
                {ltMemData.summary?.oldest && (
                  <div style={{ fontSize: 10, color: "var(--text-muted)", marginBottom: 8 }}>
                    Oldest: {ltMemData.summary.oldest?.slice(0, 10)} · Newest: {ltMemData.summary.newest?.slice(0, 10)} · Avg confidence: {((ltMemData.summary.avg_confidence || 0) * 100).toFixed(0)}%
                  </div>
                )}
                {(ltMemData.memories || []).map((m, i) => <MemoryCard key={m.memory_id || i} memory={m} />)}
              </>
            )
          ) : (
            memories.length === 0 ? (
              <EmptyState message="No memories yet. The system will learn from trade outcomes." />
            ) : (
              memories.map((m, i) => <MemoryCard key={m.memory_id || i} memory={m} />)
            )
          )}
        </div>
      )}

      {/* ── ADAPTATIONS TAB ── */}
      {tab === "adaptations" && (
        <div>
          {/* Profile */}
          {Object.keys(profile).length > 0 && (
            <div style={{
              background: "var(--surface)", border: "1px solid var(--border)",
              borderRadius: 8, padding: 12, marginBottom: 12,
            }}>
              <h4 style={{ margin: "0 0 8px", fontSize: 12, color: "var(--text-muted)" }}>Current Behavior Profile</h4>
              {Object.entries(profile).filter(([k]) =>
                !["profile_id", "session_id", "created_at", "updated_at", "notes"].includes(k)
              ).map(([k, v]) => (
                <ProfileBar key={k} label={k.replace(/_/g, " ")} value={v} />
              ))}
            </div>
          )}

          <h4 style={{ fontSize: 13, margin: "0 0 8px" }}>Recent Adaptations</h4>
          {adaptations.length === 0 ? (
            <EmptyState message="No adaptations yet. The system adapts after 50+ cycles of data." />
          ) : (
            adaptations.map((a, i) => <AdaptationCard key={a.adaptation_id || i} adaptation={a} />)
          )}
        </div>
      )}

      {/* ── REVIEWS TAB ── */}
      {tab === "reviews" && (
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
            <h4 style={{ margin: 0, fontSize: 13 }}>Daily Reviews</h4>
            <button
              onClick={generateReview}
              disabled={generating}
              style={{
                padding: "4px 12px", fontSize: 11, borderRadius: 4,
                background: "var(--blue)", color: "#fff", border: "none", cursor: "pointer",
                opacity: generating ? 0.5 : 1,
              }}
            >{generating ? "Generating..." : "Generate Now"}</button>
          </div>
          {review ? <ReviewCard review={review} /> : (
            <EmptyState message="No reviews yet. Reviews generate daily or on demand." />
          )}
        </div>
      )}

      {/* ── SESSIONS TAB ── */}
      {tab === "sessions" && (
        <div>
          <h4 style={{ fontSize: 13, margin: "0 0 8px" }}>Version Session Archive</h4>
          {sessions.length === 0 ? (
            <EmptyState message="No session history yet." />
          ) : (
            sessions.map((s, i) => (
              <SessionCard
                key={s.session_id || i}
                session={s}
                isCurrent={s.session_id === currentSessionId}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

function StatBox({ label, value, color }) {
  return (
    <div style={{
      background: "var(--surface)", border: "1px solid var(--border)",
      borderRadius: 8, padding: "10px 12px", textAlign: "center",
    }}>
      <div style={{ fontSize: 20, fontWeight: 700, color }}>{value}</div>
      <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>{label}</div>
    </div>
  );
}
