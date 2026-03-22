import { useState, useMemo } from "react";
import { useApi } from "../hooks/useApi";
import { fmtLocalTimeShort } from "../hooks/useTime";

// ---------------------------------------------------------------------------
// Collapsible + Global Collapse Controls (shared pattern with Lab.jsx)
// ---------------------------------------------------------------------------

function Collapsible({ title, badge, defaultOpen = true, forceOpen = null, children }) {
  const [localOpen, setLocalOpen] = useState(defaultOpen);
  const open = forceOpen !== null ? forceOpen : localOpen;
  return (
    <div style={{marginBottom:8}}>
      <button
        onClick={() => setLocalOpen(p => !p)}
        style={{
          display:"flex",justifyContent:"space-between",alignItems:"center",
          width:"100%",padding:"6px 12px",
          background:"var(--surface)",border:"1px solid var(--border)",
          borderRadius:open?"6px 6px 0 0":"6px",cursor:"pointer",
          fontSize:10,fontWeight:600,color:"var(--text)",
          textTransform:"uppercase",letterSpacing:0.3,
          WebkitTapHighlightColor:"transparent",minHeight:32,
        }}
      >
        <span style={{display:"flex",alignItems:"center",gap:6}}>
          {title}
          {badge && <span style={{fontSize:9,fontWeight:400,color:"var(--text-muted)",textTransform:"none",letterSpacing:0}}>{badge}</span>}
        </span>
        <span style={{fontSize:9,color:"var(--text-muted)"}}>{open?"▾":"▸"}</span>
      </button>
      {open && (
        <div style={{border:"1px solid var(--border)",borderTop:"none",borderRadius:"0 0 6px 6px",padding:"10px 12px",background:"var(--surface)"}}>
          {children}
        </div>
      )}
    </div>
  );
}

function CollapseControls({ onExpandAll, onCollapseAll }) {
  const btnStyle = {
    padding:"3px 8px",borderRadius:4,fontSize:9,fontWeight:600,
    border:"1px solid var(--border)",background:"var(--surface)",
    color:"var(--text-muted)",cursor:"pointer",
  };
  return (
    <div style={{display:"flex",gap:3}}>
      <button style={btnStyle} onClick={onExpandAll}>Expand All</button>
      <button style={btnStyle} onClick={onCollapseAll}>Collapse All</button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SVG Icons — clean, monochrome, premium sigils per level
// ---------------------------------------------------------------------------

const LEVEL_ICONS = {
  // Seed — spark
  Seed:         <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 3c-1 4-3 7-6 9 3 0 5 2 6 5 1-3 3-5 6-5-3-2-5-5-6-9z"/></svg>,
  // Novice — ring
  Novice:       <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/></svg>,
  // Apprentice — blade
  Apprentice:   <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 2l1 14-1 2-1-2 1-14zM10 18h4M11 20h2"/></svg>,
  // Monk — lotus
  Monk:         <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 21c0-4-3-7-7-8 2-1 4-3 5-6 1 3 3 5 5 6 1-1 2-3 2-6 0 3 1 5 2 6 2-1 4-3 5-6 1 3 3 5 5 6-4 1-7 4-7 8"/><path d="M12 21c0-4 3-7 7-8"/></svg>,
  // Ranger — compass
  Ranger:       <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="10"/><polygon points="12,6 14,10 12,18 10,10" fill="currentColor" opacity="0.2" stroke="currentColor"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/></svg>,
  // Sniper — crosshair
  Sniper:       <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/></svg>,
  // Operator — shield-reticle
  Operator:     <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 2l8 4v6c0 5.5-3.8 10-8 11-4.2-1-8-5.5-8-11V6l8-4z"/><circle cx="12" cy="11" r="3"/><path d="M12 6v2M12 14v2M7 11h2M15 11h2"/></svg>,
  // Strategist — abstract knight
  Strategist:   <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M9 22h6M10 14h4M12 2c-2 0-4 2-4 5 0 2 1 3 2 4l-1 3h6l-1-3c1-1 2-2 2-4 0-3-2-5-4-5z"/><path d="M12 2v3M14.5 4l-2.5 2M9.5 4l2.5 2"/></svg>,
  // Mastermind — geometric eye
  Mastermind:   <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/></svg>,
  // Oracle — radiant sigil
  Oracle:       <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 2l2 4 4-1-2 4 4 2-4 2 2 4-4-1-2 4-2-4-4 1 2-4-4-2 4-2-2-4 4 1z"/><circle cx="12" cy="12" r="3"/></svg>,
};

const MILESTONE_ICONS = {
  version_upgrade: <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.2"><path d="M8 2v12M4 6l4-4 4 4"/></svg>,
  achievement:     <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.2"><path d="M8 1l2 4h4l-3 3 1 4-4-2-4 2 1-4-3-3h4z"/></svg>,
  session:         <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.2"><circle cx="8" cy="8" r="6"/><path d="M8 4v4l3 2"/></svg>,
};

// Confidence colors
const CONF_COLORS = {
  "Very Low": "#6b7280",
  "Low": "#d97706",
  "Medium": "#3b82f6",
  "High": "#22c55e",
  "Elite": "#8b5cf6",
};

// Daily Mind State Tags
function getMindStateTag(mind) {
  if (!mind || mind.warming_up) return { label: "Awakening", color: "#6b7280" };
  const score = mind.evolution_score || 0;
  const skills = mind.skills || [];
  const discipline = skills.find(s => s.name === "Discipline")?.score || 0;
  const patience = skills.find(s => s.name === "Patience")?.score || 0;

  if (score < 50) return { label: "Awakening", color: "#6b7280" };
  if (discipline > 60 && patience > 50) return { label: "Calm / Observing", color: "#22c55e" };
  if (discipline > 45) return { label: "Focused / Selective", color: "#3b82f6" };
  if (discipline < 25) return { label: "Defensive / Noisy", color: "#f59e0b" };
  return { label: "Observing", color: "#8b5cf6" };
}

// ---------------------------------------------------------------------------
// Radar Chart
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

  const gridLines = [];
  for (let l = 1; l <= levels; l++) {
    const r = (l / levels) * maxR;
    const pts = skills.map((_, i) => {
      const angle = angleStep * i - Math.PI / 2;
      return `${cx + r * Math.cos(angle)},${cy + r * Math.sin(angle)}`;
    }).join(" ");
    gridLines.push(<polygon key={l} points={pts} fill="none" stroke="var(--border)" strokeWidth="0.5" opacity="0.5" />);
  }

  const axes = skills.map((s, i) => {
    const [x, y] = getPoint(i, 100);
    return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="var(--border)" strokeWidth="0.5" opacity="0.3" />;
  });

  const dataPoints = skills.map((s, i) => getPoint(i, s.score));
  const dataPath = dataPoints.map(p => `${p[0]},${p[1]}`).join(" ");

  const labels = skills.map((s, i) => {
    const angle = angleStep * i - Math.PI / 2;
    const labelR = maxR + 18;
    const x = cx + labelR * Math.cos(angle);
    const y = cy + labelR * Math.sin(angle);
    return (
      <text key={i} x={x} y={y} textAnchor="middle" dominantBaseline="middle"
        style={{ fontSize: 9, fill: s.warming_up ? "#6b728088" : "var(--text-muted)", fontFamily: "inherit" }}>
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
        <circle key={i} cx={p[0]} cy={p[1]} r="3" fill={skills[i]?.warming_up ? "#6b7280" : "#8b5cf6"} />
      ))}
      {labels}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Progress Bar
// ---------------------------------------------------------------------------

function ProgressBar({ value, max, label, color }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const bg = color || "linear-gradient(90deg, #6366f1, #8b5cf6)";
  return (
    <div style={{ width: "100%" }}>
      {label && <div style={{ fontSize: 10, color: "var(--text-muted)", marginBottom: 3 }}>{label}</div>}
      <div style={{ height: 6, background: "var(--border)", borderRadius: 3, overflow: "hidden" }}>
        <div style={{
          width: `${pct}%`, height: "100%", borderRadius: 3,
          background: bg,
          transition: "width 0.6s ease",
        }} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skill Card — v7.3.1 with confidence + evidence
// ---------------------------------------------------------------------------

function SkillCard({ skill }) {
  const statusColors = {
    strong: "#22c55e", developing: "#3b82f6", learning: "#eab308",
    weak: "#f97316", warming_up: "#6b7280",
  };
  const color = statusColors[skill.status] || "#6b7280";
  const confColor = skill.confidence_color || CONF_COLORS[skill.confidence_label] || "#6b7280";

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
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 6, gap: 6 }}>
        <span style={{
          fontSize: 9, padding: "1px 6px", borderRadius: 3,
          background: `${confColor}18`, color: confColor,
          fontWeight: 600, border: `1px solid ${confColor}33`,
        }}>
          {skill.confidence_label || "—"}
        </span>
        <span style={{ fontSize: 9, color: "var(--text-muted)" }}>
          {skill.evidence_count || 0} samples
        </span>
        {skill.warming_up && (
          <span style={{ fontSize: 9, color: "#6b7280", fontStyle: "italic" }}>warming up</span>
        )}
      </div>
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

export default function EvolutionPage() {
  const { data: mind, loading } = useApi("/v7/mind", 15000);
  const { data: skillsData } = useApi("/v7/mind/skills", 30000);
  const { data: lessonsData } = useApi("/v7/mind/lessons", 30000);
  const { data: timelineData } = useApi("/v7/mind/timeline", 60000);
  const { data: historyData } = useApi("/v7/mind/history?limit=50", 60000);
  const { data: patternsData } = useApi("/v7/mind/patterns", 60000);
  const { data: identityData } = useApi("/v7/mind/identity", 60000);
  const [tab, setTab] = useState("overview");
  const [globalCollapse, setGlobalCollapse] = useState(null);
  const expandAll = () => setGlobalCollapse(true);
  const collapseAll = () => setGlobalCollapse(false);
  const resetOverride = () => { if (globalCollapse !== null) setTimeout(() => setGlobalCollapse(null), 50); };

  const skills = skillsData?.skills || [];
  const feed = lessonsData?.feed || [];
  const timeline = timelineData?.timeline || [];
  const milestones = timelineData?.milestones || [];
  const history = historyData?.history || [];

  const mindLevel = mind?.mind_level || { level: "Seed", score: 0, progress_pct: 0 };
  const evolutionScore = mind?.evolution_score || 0;
  const confidence = mind?.confidence || { score: 0, label: "Very Low", color: "#6b7280" };
  const evidenceStrength = mind?.evidence_strength || { pct: 0 };
  const mindState = getMindStateTag(mind);
  const levelIcon = LEVEL_ICONS[mindLevel.level] || LEVEL_ICONS.Seed;
  const confColor = confidence.color || CONF_COLORS[confidence.label] || "#6b7280";

  const whyLevel = mind?.why_this_level || [];
  const whatNeeded = mind?.what_needed_for_next || [];

  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "skills", label: "Skills" },
    { id: "lessons", label: "Lessons" },
    { id: "timeline", label: "Timeline" },
  ];

  if (loading && !mind) {
    return (
      <div style={{ padding: 20 }}>
        <h1 style={{ fontSize: 17, fontWeight: 700, margin: 0 }}>Evolution</h1>
        <p style={{ color: "var(--text-muted)", fontSize: 13 }}>Loading evolution state...</p>
      </div>
    );
  }

  // Mind insights for the side panel
  const mindInsights = [];
  if (mind?.system_age?.total_trades > 0) {
    const wr = mind?.system_age?.win_rate;
    if (wr != null) mindInsights.push({ label: "Win Rate", value: `${wr.toFixed(0)}%`, color: wr >= 50 ? "#22c55e" : "#ef4444" });
  }
  if (mind?.system_age?.total_hours > 0) mindInsights.push({ label: "Runtime", value: `${mind.system_age.total_hours.toFixed(1)}h` });
  if (mind?.system_age?.total_cycles > 0) mindInsights.push({ label: "Cycles", value: mind.system_age.total_cycles.toLocaleString() });
  if (patternsData && !patternsData.warming_up) {
    const pc = (patternsData.insights || []).length;
    if (pc > 0) mindInsights.push({ label: "Patterns", value: pc, color: "#8b5cf6" });
  }

  return (
    <div style={{ maxWidth: 960 }}>
      {/* Header — sticky on iPad */}
      <div style={{
        position: "sticky", top: 0, zIndex: 20,
        display: "flex", alignItems: "center", gap: 10, marginBottom: 12,
        padding: "8px 0", background: "var(--bg)",
        flexWrap: "wrap",
      }}>
        <h1 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Evolution</h1>
        <span style={{
          padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 600,
          background: "#8b5cf618", color: "#8b5cf6",
          border: "1px solid #8b5cf633",
        }}>{mindLevel.level}</span>
        <span style={{
          padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 600,
          background: `${confColor}18`, color: confColor,
          border: `1px solid ${confColor}33`,
        }}>{evidenceStrength.pct}% Evidence</span>
        {/* Mini indicators in header */}
        <div style={{ display: "flex", gap: 8, fontSize: 10, color: "var(--text-muted)", marginLeft: "auto", flexWrap: "wrap", alignItems: "center" }}>
          <span>Score: <b style={{ color: "#8b5cf6" }}>{evolutionScore}</b></span>
          <span>Level: <b style={{ color: "#8b5cf6" }}>{mindLevel.level}</b></span>
          {mind?.system_age?.total_trades > 0 && <span>Trades: <b>{mind.system_age.total_trades}</b></span>}
          <CollapseControls onExpandAll={()=>{expandAll();resetOverride()}} onCollapseAll={()=>{collapseAll();resetOverride()}}/>
        </div>
      </div>

      {/* Hero Card — compact for iPad */}
      <div style={{
        padding: "14px 18px", background: "var(--surface)", border: "1px solid var(--border)",
        borderRadius: 10, marginBottom: 10, display: "flex", alignItems: "center", gap: 16,
        flexWrap: "wrap",
      }}>
        {/* Level Icon */}
        <div style={{
          width: 52, height: 52, borderRadius: 10, display: "flex", alignItems: "center",
          justifyContent: "center", background: "var(--bg)", border: "1px solid var(--border)",
          color: "#8b5cf6", flexShrink: 0,
        }}>
          {levelIcon}
        </div>

        {/* Score + Level */}
        <div style={{ flex: 1, minWidth: 180 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 3 }}>
            <span style={{ fontSize: 24, fontWeight: 700 }}>{evolutionScore}</span>
            <span style={{ fontSize: 11, color: "var(--text-muted)" }}>/ 1000</span>
            <span style={{ fontSize: 13, fontWeight: 600, color: "#8b5cf6", marginLeft: 4 }}>
              {mindLevel.level}
            </span>
          </div>
          <ProgressBar
            value={mindLevel.progress_pct}
            max={100}
            label={mindLevel.next_level ? `${mindLevel.points_to_next} pts to ${mindLevel.next_level}` : "Maximum level reached"}
          />
          <div style={{ marginTop: 4 }}>
            <ProgressBar
              value={evidenceStrength.pct}
              max={100}
              label={`Evidence: ${evidenceStrength.pct}%`}
              color={confColor}
            />
          </div>
        </div>

        {/* Quick Stats — inline on wide, wrap on narrow */}
        <div style={{ display: "flex", gap: 12, fontSize: 10, color: "var(--text-muted)", flexWrap: "wrap" }}>
          <div><div style={{ fontWeight: 600, color: "var(--text)", fontSize: 13 }}>{(mind?.system_age?.total_cycles || 0).toLocaleString()}</div>cycles</div>
          <div><div style={{ fontWeight: 600, color: "var(--text)", fontSize: 13 }}>{mind?.system_age?.total_trades || 0}</div>trades</div>
          <div><div style={{ fontWeight: 600, color: "var(--text)", fontSize: 13 }}>{(mind?.system_age?.total_hours || 0).toFixed(1)}</div>hours</div>
          <div><div style={{ fontWeight: 600, color: "#8b5cf6", fontSize: 13 }}>v{mind?.system_age?.version || "?"}</div>version</div>
          {identityData?.maturity_level && identityData.maturity_level !== "seed" && (
            <div><div style={{ fontWeight: 600, color: "#f59e0b", fontSize: 12, textTransform: "capitalize" }}>{identityData.maturity_level}</div>maturity</div>
          )}
          {identityData?.continuity_score > 0 && (
            <div><div style={{ fontWeight: 600, color: "var(--text)", fontSize: 13 }}>{identityData.continuity_score.toFixed(0)}%</div>continuity</div>
          )}
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
        <div>
          {/* Skill Radar + Level Explanation */}
          <Collapsible title="Skill Radar & Level" defaultOpen={true} forceOpen={globalCollapse}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 10 }}>
              <div>
                {skills.length > 0 ? <RadarChart skills={skills} /> : (
                  <div style={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 12 }}>
                    Collecting data...
                  </div>
                )}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {/* Why This Level */}
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 6 }}>
                    Why {mindLevel.level}?
                  </div>
                  {whyLevel.length > 0 ? whyLevel.map((reason, i) => (
                    <div key={i} style={{ fontSize: 11, color: "var(--text)", padding: "2px 0", display: "flex", gap: 6, alignItems: "flex-start" }}>
                      <span style={{ color: "var(--text-muted)", fontSize: 8, marginTop: 3 }}>•</span>
                      <span>{reason}</span>
                    </div>
                  )) : (
                    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>Analyzing system state...</div>
                  )}
                </div>
                {/* What's Needed for Next Level */}
                {whatNeeded.length > 0 && mindLevel.next_level && (
                  <div style={{ borderLeft: "3px solid #8b5cf6", paddingLeft: 10 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: "#8b5cf6", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 6 }}>
                      To reach {mindLevel.next_level}
                    </div>
                    {whatNeeded.map((req, i) => (
                      <div key={i} style={{ fontSize: 11, color: "var(--text)", padding: "2px 0", display: "flex", gap: 6, alignItems: "flex-start" }}>
                        <span style={{ color: "#8b5cf6", fontSize: 10, marginTop: 1 }}>→</span>
                        <span>{req}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </Collapsible>

          {/* Recent Learning */}
          <Collapsible title="Recent Learning" badge={feed.length > 0 ? `${feed.length} items` : ""} defaultOpen={true} forceOpen={globalCollapse}>
            <div style={{ maxHeight: 200, overflowY: "auto" }}>
              {feed.length > 0 ? feed.slice(0, 5).map((item, i) => (
                <FeedItem key={i} item={item} />
              )) : (
                <div style={{ color: "var(--text-muted)", fontSize: 12, padding: 12, textAlign: "center" }}>
                  Warming up — collecting evidence...
                </div>
              )}
            </div>
          </Collapsible>

          {/* Recurring Patterns */}
          {patternsData && !patternsData.warming_up && (patternsData.insights || []).length > 0 && (
            <Collapsible title="Recurring Patterns" badge={`${(patternsData.insights || []).length} found`} defaultOpen={true} forceOpen={globalCollapse}>
              <div style={{ borderLeft: "3px solid #8b5cf6", paddingLeft: 10 }}>
                {(patternsData.insights || []).slice(0, 3).map((ins, i) => {
                  const confColors = { low: "#6b7280", medium: "#eab308", high: "#22c55e" };
                  const cc = confColors[ins.confidence] || confColors.low;
                  return (
                    <div key={i} style={{
                      display: "flex", alignItems: "center", gap: 8, padding: "4px 0",
                      borderBottom: i < Math.min((patternsData.insights || []).length, 3) - 1 ? "1px solid var(--border)" : "none",
                    }}>
                      <span title={`${ins.confidence} confidence`} style={{
                        width: 7, height: 7, borderRadius: "50%", background: cc, flexShrink: 0,
                      }} />
                      <span style={{ fontSize: 12, color: "var(--text)", flex: 1 }}>{ins.insight}</span>
                      <span style={{ fontSize: 10, color: "var(--text-muted)" }}>(seen {ins.count}×)</span>
                    </div>
                  );
                })}
              </div>
            </Collapsible>
          )}

          {/* Evolution History */}
          {history.length > 1 && (
            <Collapsible title="Evolution Over Time" defaultOpen={false} forceOpen={globalCollapse}>
              <MiniChart data={history} />
            </Collapsible>
          )}

          {/* Growth Insights Panel */}
          {mindInsights.length > 0 && (
            <Collapsible title="Growth Insights" defaultOpen={true} forceOpen={globalCollapse}>
              <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                {mindInsights.map((ins, i) => (
                  <div key={i} style={{ textAlign: "center", minWidth: 60 }}>
                    <div style={{ fontSize: 16, fontWeight: 700, color: ins.color || "var(--text)" }}>{ins.value}</div>
                    <div style={{ fontSize: 9, color: "var(--text-muted)", textTransform: "uppercase" }}>{ins.label}</div>
                  </div>
                ))}
              </div>
            </Collapsible>
          )}
        </div>
      )}

      {tab === "skills" && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8 }}>
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
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.3, marginBottom: 10 }}>
            Session History
          </div>
          <div style={{ position: "relative", paddingLeft: 24 }}>
            <div style={{
              position: "absolute", left: 6, top: 0, bottom: 0, width: 1,
              background: "var(--border)",
            }} />

            {timeline.map((entry, i) => (
              <div key={i} style={{ position: "relative", marginBottom: 16, paddingLeft: 16 }}>
                <div style={{
                  position: "absolute", left: -21, top: 4, width: 12, height: 12,
                  borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
                  background: entry.is_active ? "#8b5cf6" : "var(--surface)",
                  border: `2px solid ${entry.is_active ? "#8b5cf6" : "var(--border)"}`,
                }}>
                  {entry.is_active && <div style={{ width: 4, height: 4, borderRadius: "50%", background: "#fff" }} />}
                </div>

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

  const areaPath = `M${padX},${padY + chartH} ` +
    scores.map((s, i) => {
      const x = padX + (i / (scores.length - 1)) * chartW;
      const y = padY + chartH - ((s - minScore) / range) * chartH;
      return `L${x},${y}`;
    }).join(" ") +
    ` L${padX + chartW},${padY + chartH} Z`;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} style={{ display: "block" }}>
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
      <path d={areaPath} fill="rgba(139, 92, 246, 0.08)" />
      <polyline points={points} fill="none" stroke="#8b5cf6" strokeWidth="2" />
      {scores.length > 0 && (() => {
        const lastX = padX + ((scores.length - 1) / (scores.length - 1)) * chartW;
        const lastY = padY + chartH - ((scores[scores.length - 1] - minScore) / range) * chartH;
        return <circle cx={lastX} cy={lastY} r="4" fill="#8b5cf6" />;
      })()}
    </svg>
  );
}
