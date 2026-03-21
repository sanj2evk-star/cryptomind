import { useState, useMemo } from "react";
import { useApi } from "../hooks/useApi";
import { fmtLocalTimeShort } from "../hooks/useTime";

// ---------------------------------------------------------------------------
// SVG Icons — clean, monochrome, precise
// ---------------------------------------------------------------------------

const LEVEL_ICONS = {
  Rookie:       <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/></svg>,
  Beginner:     <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="9"/><path d="M9 12l2 2 4-4"/></svg>,
  Apprentice:   <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 3l2.5 5 5.5.8-4 3.9.9 5.3L12 15.5l-4.9 2.5.9-5.3-4-3.9 5.5-.8z"/></svg>,
  Operator:     <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.2 4.2l2.8 2.8M17 17l2.8 2.8M1 12h4M19 12h4M4.2 19.8l2.8-2.8M17 7l2.8-2.8"/></svg>,
  Pro:          <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><polygon points="12,2 15,9 22,9 16.5,14 18.5,21 12,17 5.5,21 7.5,14 2,9 9,9"/></svg>,
  Elite:        <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>,
  "World Class":<svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 010 20M12 2a15.3 15.3 0 000 20"/></svg>,
  Assassin:     <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 2v4m0 12v4M2 12h4m12 0h4"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>,
  Sage:         <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 3c-1.5 5-5 8.5-9 9 4 .5 7.5 4 9 9 1.5-5 5-8.5 9-9-4-.5-7.5-4-9-9z"/></svg>,
  Godmode:      <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 2l3 7h7l-5.5 4.5L18.5 21 12 17l-6.5 4 2-7.5L2 9h7z"/><circle cx="12" cy="12" r="3"/></svg>,
};

const MILESTONE_ICONS = {
  version_upgrade: <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.2"><path d="M8 2v12M4 6l4-4 4 4"/></svg>,
  achievement:     <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.2"><path d="M8 1l2 4h4l-3 3 1 4-4-2-4 2 1-4-3-3h4z"/></svg>,
  session:         <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.2"><circle cx="8" cy="8" r="6"/><path d="M8 4v4l3 2"/></svg>,
};

// Daily Mind State Tags — computed from behavior state
function getMindStateTag(mind) {
  if (!mind || mind.warming_up) return { label: "Awakening", color: "#6b7280" };
  const score = mind.evolution_score || 0;
  const skills = mind.skills || [];
  const discipline = skills.find(s => s.name === "Discipline")?.score || 0;
  const patience = skills.find(s => s.name === "Patience")?.score || 0;

  if (score < 50) return { label: "Awakening", color: "#6b7280" };
  if (discipline > 70 && patience > 60) return { label: "Calm / Observing", color: "#22c55e" };
  if (discipline > 60) return { label: "Focused / Selective", color: "#3b82f6" };
  if (discipline < 40) return { label: "Defensive / Noisy", color: "#f59e0b" };
  return { label: "Observing", color: "#8b5cf6" };
}

// ---------------------------------------------------------------------------
// Radar Chart — clean SVG spider chart
// ---------------------------------------------------------------------------

function RadarChart({ skills }) {
  const size = 240;
  const cx = size / 2;
  const cy = size / 2;
  const maxR = 95;
  const levels = 4;

  const angleStep = (2 * Math.PI) / skills.length;

  const getPoint = (i, value) => {
    const angle = angleStep * i - Math.PI / 2;
    const r = (value / 100) * maxR;
    return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
  };

  // Grid
  const gridLines = [];
  for (let l = 1; l <= levels; l++) {
    const r = (l / levels) * maxR;
    const pts = skills.map((_, i) => {
      const angle = angleStep * i - Math.PI / 2;
      return `${cx + r * Math.cos(angle)},${cy + r * Math.sin(angle)}`;
    }).join(" ");
    gridLines.push(<polygon key={l} points={pts} fill="none" stroke="var(--border)" strokeWidth="0.5" opacity="0.5" />);
  }

  // Axes
  const axes = skills.map((s, i) => {
    const [x, y] = getPoint(i, 100);
    return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="var(--border)" strokeWidth="0.5" opacity="0.3" />;
  });

  // Data polygon
  const dataPoints = skills.map((s, i) => getPoint(i, s.score));
  const dataPath = dataPoints.map(p => `${p[0]},${p[1]}`).join(" ");

  // Labels
  const labels = skills.map((s, i) => {
    const angle = angleStep * i - Math.PI / 2;
    const labelR = maxR + 18;
    const x = cx + labelR * Math.cos(angle);
    const y = cy + labelR * Math.sin(angle);
    return (
      <text key={i} x={x} y={y} textAnchor="middle" dominantBaseline="middle"
        style={{ fontSize: 9, fill: "var(--text-muted)", fontFamily: "inherit" }}>
        {s.name}
      </text>
    );
  });

  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} style={{ display: "block", margin: "0 auto" }}>
      {gridLines}
      {axes}
      <polygon points={dataPath} fill="rgba(139, 92, 246, 0.15)" stroke="#8b5cf6" strokeWidth="1.5" />
      {dataPoints.map((p, i) => (
        <circle key={i} cx={p[0]} cy={p[1]} r="3" fill="#8b5cf6" />
      ))}
      {labels}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Progress Bar
// ---------------------------------------------------------------------------

function ProgressBar({ value, max, label }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div style={{ width: "100%" }}>
      {label && <div style={{ fontSize: 10, color: "var(--text-muted)", marginBottom: 3 }}>{label}</div>}
      <div style={{ height: 6, background: "var(--border)", borderRadius: 3, overflow: "hidden" }}>
        <div style={{
          width: `${pct}%`, height: "100%", borderRadius: 3,
          background: "linear-gradient(90deg, #6366f1, #8b5cf6)",
          transition: "width 0.6s ease",
        }} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skill Card
// ---------------------------------------------------------------------------

function SkillCard({ skill }) {
  const statusColors = {
    strong: "#22c55e", developing: "#3b82f6", learning: "#eab308",
    weak: "#f97316", warming_up: "#6b7280",
  };
  const color = statusColors[skill.status] || "#6b7280";

  return (
    <div style={{
      padding: "12px 14px", background: "var(--surface)", border: "1px solid var(--border)",
      borderRadius: 8, borderLeft: `3px solid ${color}`,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>{skill.name}</span>
        <span style={{ fontSize: 18, fontWeight: 700, color }}>{skill.score}</span>
      </div>
      <div style={{ fontSize: 10, color: "var(--text-muted)", marginBottom: 6 }}>{skill.description}</div>
      <ProgressBar value={skill.score} max={100} />
      <div style={{ fontSize: 9, color: "var(--text-muted)", marginTop: 4, fontStyle: "italic" }}>{skill.detail}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Learning Feed Item
// ---------------------------------------------------------------------------

function FeedItem({ item }) {
  const typeConfig = {
    improvement: { icon: "^", color: "#22c55e", bg: "#22c55e12" },
    regression:  { icon: "v", color: "#ef4444", bg: "#ef444412" },
    strength:    { icon: "+", color: "#3b82f6", bg: "#3b82f612" },
    weakness:    { icon: "-", color: "#f59e0b", bg: "#f59e0b12" },
    lesson_absorbed: { icon: "~", color: "#8b5cf6", bg: "#8b5cf612" },
    info:        { icon: "i", color: "#6b7280", bg: "#6b728012" },
  };
  const cfg = typeConfig[item.type] || typeConfig.info;

  return (
    <div style={{
      padding: "8px 12px", background: cfg.bg, borderRadius: 6,
      borderLeft: `2px solid ${cfg.color}`, marginBottom: 6,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
        <span style={{
          width: 18, height: 18, borderRadius: "50%", display: "flex", alignItems: "center",
          justifyContent: "center", fontSize: 11, fontWeight: 700, color: cfg.color,
          border: `1px solid ${cfg.color}33`, flexShrink: 0,
        }}>{cfg.icon}</span>
        <span style={{ fontSize: 9, color: cfg.color, fontWeight: 600, textTransform: "uppercase" }}>
          {item.type.replace("_", " ")}
        </span>
        {item.area && <span style={{ fontSize: 9, color: "var(--text-muted)" }}>{item.area}</span>}
      </div>
      <div style={{ fontSize: 12, color: "var(--text)", lineHeight: 1.5, paddingLeft: 24 }}>
        {item.message}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Mind Page
// ---------------------------------------------------------------------------

export default function MindPage() {
  const { data: mind, loading } = useApi("/v7/mind", 15000);
  const { data: skillsData } = useApi("/v7/mind/skills", 30000);
  const { data: lessonsData } = useApi("/v7/mind/lessons", 30000);
  const { data: timelineData } = useApi("/v7/mind/timeline", 60000);
  const { data: historyData } = useApi("/v7/mind/history?limit=50", 60000);
  const [tab, setTab] = useState("overview");

  const skills = skillsData?.skills || [];
  const feed = lessonsData?.feed || [];
  const timeline = timelineData?.timeline || [];
  const milestones = timelineData?.milestones || [];
  const history = historyData?.history || [];

  const mindLevel = mind?.mind_level || { level: "Rookie", score: 0, progress_pct: 0 };
  const evolutionScore = mind?.evolution_score || 0;
  const mindState = getMindStateTag(mind);
  const levelIcon = LEVEL_ICONS[mindLevel.level] || LEVEL_ICONS.Rookie;

  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "skills", label: "Skills" },
    { id: "lessons", label: "Lessons" },
    { id: "timeline", label: "Timeline" },
  ];

  if (loading && !mind) {
    return (
      <div style={{ padding: 20 }}>
        <h1 style={{ fontSize: 17, fontWeight: 700, margin: 0 }}>Mind</h1>
        <p style={{ color: "var(--text-muted)", fontSize: 13 }}>Loading mind state...</p>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 900 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <h1 style={{ margin: 0, fontSize: 17, fontWeight: 700 }}>Mind</h1>
        <span style={{
          padding: "3px 10px", borderRadius: 4, fontSize: 10, fontWeight: 600,
          background: `${mindState.color}18`, color: mindState.color,
          border: `1px solid ${mindState.color}33`,
        }}>{mindState.label}</span>
      </div>

      {/* Hero Card — Level + Score */}
      <div style={{
        padding: "20px 24px", background: "var(--surface)", border: "1px solid var(--border)",
        borderRadius: 10, marginBottom: 12, display: "flex", alignItems: "center", gap: 24,
      }}>
        {/* Level Icon */}
        <div style={{
          width: 64, height: 64, borderRadius: 12, display: "flex", alignItems: "center",
          justifyContent: "center", background: "var(--bg)", border: "1px solid var(--border)",
          color: "#8b5cf6", flexShrink: 0,
        }}>
          {levelIcon}
        </div>

        {/* Score + Level */}
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
            <span style={{ fontSize: 28, fontWeight: 700 }}>{evolutionScore}</span>
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>/ 1000</span>
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "#8b5cf6", marginBottom: 8 }}>
            {mindLevel.level}
          </div>
          <ProgressBar
            value={mindLevel.progress_pct}
            max={100}
            label={mindLevel.next_level ? `${mindLevel.points_to_next} pts to ${mindLevel.next_level}` : "Maximum level reached"}
          />
        </div>

        {/* Quick Stats */}
        <div style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 11, minWidth: 140 }}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={{ color: "var(--text-muted)" }}>Cycles</span>
            <span style={{ fontWeight: 600 }}>{(mind?.system_age?.total_cycles || 0).toLocaleString()}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={{ color: "var(--text-muted)" }}>Trades</span>
            <span style={{ fontWeight: 600 }}>{mind?.system_age?.total_trades || 0}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={{ color: "var(--text-muted)" }}>Hours</span>
            <span style={{ fontWeight: 600 }}>{(mind?.system_age?.total_hours || 0).toFixed(1)}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={{ color: "var(--text-muted)" }}>Version</span>
            <span style={{ fontWeight: 600, color: "#8b5cf6" }}>v{mind?.system_age?.version || "?"}</span>
          </div>
        </div>
      </div>

      {/* Tab Bar */}
      <div style={{
        display: "flex", gap: 2, marginBottom: 12, padding: 2,
        background: "var(--bg)", borderRadius: 6, border: "1px solid var(--border)",
      }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            flex: 1, padding: "6px 12px", border: "none", borderRadius: 4,
            fontSize: 12, fontWeight: 600, cursor: "pointer",
            background: tab === t.id ? "var(--surface)" : "transparent",
            color: tab === t.id ? "var(--text)" : "var(--text-muted)",
            transition: "all 0.15s ease",
          }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {tab === "overview" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          {/* Radar Chart */}
          <div style={{
            padding: "16px", background: "var(--surface)", border: "1px solid var(--border)",
            borderRadius: 8,
          }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 8 }}>
              Skill Radar
            </div>
            {skills.length > 0 ? <RadarChart skills={skills} /> : (
              <div style={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 12 }}>
                Collecting data...
              </div>
            )}
          </div>

          {/* Recent Lessons */}
          <div style={{
            padding: "16px", background: "var(--surface)", border: "1px solid var(--border)",
            borderRadius: 8, maxHeight: 340, overflowY: "auto",
          }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 8 }}>
              Recent Learning
            </div>
            {feed.length > 0 ? feed.slice(0, 8).map((item, i) => (
              <FeedItem key={i} item={item} />
            )) : (
              <div style={{ color: "var(--text-muted)", fontSize: 12, padding: 20, textAlign: "center" }}>
                Warming up — collecting system evidence...
              </div>
            )}
          </div>

          {/* Evolution History mini chart */}
          {history.length > 1 && (
            <div style={{
              gridColumn: "1 / -1", padding: "16px", background: "var(--surface)",
              border: "1px solid var(--border)", borderRadius: 8,
            }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 8 }}>
                Evolution Over Time
              </div>
              <MiniChart data={history} />
            </div>
          )}
        </div>
      )}

      {tab === "skills" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
          {skills.map((s, i) => <SkillCard key={i} skill={s} />)}
          {skills.length === 0 && (
            <div style={{ gridColumn: "1 / -1", padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
              Skill scores are computed from real system behavior. Warming up...
            </div>
          )}
        </div>
      )}

      {tab === "lessons" && (
        <div>
          {feed.length > 0 ? feed.map((item, i) => <FeedItem key={i} item={item} />) : (
            <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
              No learning data yet. The system will generate insights as it trades and reviews outcomes.
            </div>
          )}
        </div>
      )}

      {tab === "timeline" && (
        <div>
          {/* Version milestones */}
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 10 }}>
            Session History
          </div>
          <div style={{ position: "relative", paddingLeft: 24 }}>
            {/* Vertical line */}
            <div style={{
              position: "absolute", left: 6, top: 0, bottom: 0, width: 1,
              background: "var(--border)",
            }} />

            {timeline.map((entry, i) => (
              <div key={i} style={{ position: "relative", marginBottom: 16, paddingLeft: 16 }}>
                {/* Dot */}
                <div style={{
                  position: "absolute", left: -21, top: 4, width: 12, height: 12,
                  borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
                  background: entry.is_active ? "#8b5cf6" : "var(--surface)",
                  border: `2px solid ${entry.is_active ? "#8b5cf6" : "var(--border)"}`,
                }}>
                  {entry.is_active && <div style={{ width: 4, height: 4, borderRadius: "50%", background: "#fff" }} />}
                </div>

                {/* Content */}
                <div style={{
                  padding: "10px 14px", background: "var(--surface)", border: "1px solid var(--border)",
                  borderRadius: 6, borderLeft: entry.is_active ? "3px solid #8b5cf6" : "none",
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: "#8b5cf6" }}>v{entry.version}</span>
                    {entry.is_active && <span style={{ fontSize: 9, padding: "1px 6px", borderRadius: 3, background: "#8b5cf618", color: "#8b5cf6", fontWeight: 600 }}>ACTIVE</span>}
                    <span style={{ fontSize: 10, color: "var(--text-muted)" }}>Session #{entry.session_id}</span>
                  </div>
                  {entry.version_description && (
                    <div style={{ fontSize: 11, color: "var(--text)", marginBottom: 4 }}>{entry.version_description}</div>
                  )}
                  <div style={{ display: "flex", gap: 12, fontSize: 10, color: "var(--text-muted)" }}>
                    <span>{entry.total_cycles} cycles</span>
                    <span>{entry.total_trades} trades</span>
                    <span style={{ color: entry.realized_pnl >= 0 ? "#22c55e" : "#ef4444" }}>
                      PnL: {entry.realized_pnl >= 0 ? "+" : ""}{entry.realized_pnl?.toFixed(6) || "0"}
                    </span>
                    {entry.started_at && <span>{fmtLocalTimeShort(entry.started_at)}</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Milestones */}
          {milestones.length > 0 && (
            <>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3, marginTop: 20, marginBottom: 10 }}>
                Milestones
              </div>
              {milestones.map((m, i) => (
                <div key={i} style={{
                  display: "flex", alignItems: "center", gap: 10, padding: "8px 12px",
                  background: "var(--surface)", border: "1px solid var(--border)",
                  borderRadius: 6, marginBottom: 6,
                }}>
                  <span style={{ color: "#8b5cf6" }}>{MILESTONE_ICONS[m.milestone_type] || MILESTONE_ICONS.achievement}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12, fontWeight: 600 }}>{m.title}</div>
                    {m.description && <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{m.description}</div>}
                  </div>
                  <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
                    {m.mind_level_at} ({m.evolution_score_at} pts)
                  </div>
                </div>
              ))}
            </>
          )}

          {timeline.length === 0 && (
            <div style={{ padding: 40, textAlign: "center", color: "var(--text-muted)" }}>
              No session history yet.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Mini Evolution Chart (SVG sparkline)
// ---------------------------------------------------------------------------

function MiniChart({ data }) {
  if (!data || data.length < 2) return null;

  const reversed = [...data].reverse();
  const scores = reversed.map(d => d.evolution_score || 0);
  const maxScore = Math.max(...scores, 100);
  const minScore = Math.min(...scores, 0);
  const range = maxScore - minScore || 1;

  const w = 800;
  const h = 120;
  const padX = 40;
  const padY = 15;
  const chartW = w - padX * 2;
  const chartH = h - padY * 2;

  const points = scores.map((s, i) => {
    const x = padX + (i / (scores.length - 1)) * chartW;
    const y = padY + chartH - ((s - minScore) / range) * chartH;
    return `${x},${y}`;
  }).join(" ");

  // Area fill
  const areaPath = `M${padX},${padY + chartH} ` +
    scores.map((s, i) => {
      const x = padX + (i / (scores.length - 1)) * chartW;
      const y = padY + chartH - ((s - minScore) / range) * chartH;
      return `L${x},${y}`;
    }).join(" ") +
    ` L${padX + chartW},${padY + chartH} Z`;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} style={{ display: "block" }}>
      {/* Grid lines */}
      {[0, 0.25, 0.5, 0.75, 1].map(f => {
        const y = padY + chartH * (1 - f);
        const val = Math.round(minScore + range * f);
        return (
          <g key={f}>
            <line x1={padX} y1={y} x2={w - padX} y2={y} stroke="var(--border)" strokeWidth="0.5" opacity="0.5" />
            <text x={padX - 4} y={y + 3} textAnchor="end" style={{ fontSize: 9, fill: "var(--text-muted)" }}>{val}</text>
          </g>
        );
      })}
      {/* Area */}
      <path d={areaPath} fill="rgba(139, 92, 246, 0.08)" />
      {/* Line */}
      <polyline points={points} fill="none" stroke="#8b5cf6" strokeWidth="2" />
      {/* Current point */}
      {scores.length > 0 && (() => {
        const lastX = padX + ((scores.length - 1) / (scores.length - 1)) * chartW;
        const lastY = padY + chartH - ((scores[scores.length - 1] - minScore) / range) * chartH;
        return <circle cx={lastX} cy={lastY} r="4" fill="#8b5cf6" />;
      })()}
    </svg>
  );
}
