import { useState } from "react";
import { useApi } from "../hooks/useApi";

const CARD = {
  background: "var(--surface)", border: "1px solid var(--border)",
  borderRadius: 8, padding: "14px 16px", marginBottom: 8,
};
const LBL = {
  fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase",
  letterSpacing: 0.4, marginBottom: 4,
};

/* ── Mood sigil icons (monochrome SVG) ── */
function MoodSigil({ mood, size = 52 }) {
  const s = size;
  const m = {
    calm_observing:      <svg width={s} height={s} viewBox="0 0 48 48"><circle cx="24" cy="24" r="18" fill="none" stroke="#6b7280" strokeWidth="1.8"/><circle cx="24" cy="24" r="5" fill="#6b7280" opacity="0.35"/></svg>,
    focused_selective:   <svg width={s} height={s} viewBox="0 0 48 48"><circle cx="24" cy="24" r="18" fill="none" stroke="#3b82f6" strokeWidth="1.8"/><line x1="24" y1="6" x2="24" y2="16" stroke="#3b82f6" strokeWidth="1.8"/><line x1="24" y1="32" x2="24" y2="42" stroke="#3b82f6" strokeWidth="1.8"/><line x1="6" y1="24" x2="16" y2="24" stroke="#3b82f6" strokeWidth="1.8"/><line x1="32" y1="24" x2="42" y2="24" stroke="#3b82f6" strokeWidth="1.8"/><circle cx="24" cy="24" r="3.5" fill="#3b82f6" opacity="0.45"/></svg>,
    cautious_defensive:  <svg width={s} height={s} viewBox="0 0 48 48"><path d="M24 6 L42 18 L42 34 L24 42 L6 34 L6 18 Z" fill="none" stroke="#d97706" strokeWidth="1.8"/><circle cx="24" cy="24" r="4" fill="#d97706" opacity="0.25"/></svg>,
    confident_steady:    <svg width={s} height={s} viewBox="0 0 48 48"><circle cx="24" cy="24" r="18" fill="none" stroke="#22c55e" strokeWidth="1.8"/><circle cx="24" cy="24" r="10" fill="none" stroke="#22c55e" strokeWidth="1.2" opacity="0.5"/><circle cx="24" cy="24" r="4" fill="#22c55e"/></svg>,
    alert_volatile:      <svg width={s} height={s} viewBox="0 0 48 48"><polygon points="24,4 44,40 4,40" fill="none" stroke="#ef4444" strokeWidth="1.8"/><line x1="24" y1="18" x2="24" y2="30" stroke="#ef4444" strokeWidth="2.2"/><circle cx="24" cy="35" r="1.8" fill="#ef4444"/></svg>,
    skeptical_filtering: <svg width={s} height={s} viewBox="0 0 48 48"><circle cx="24" cy="24" r="18" fill="none" stroke="#8b5cf6" strokeWidth="1.8" strokeDasharray="4 3"/><line x1="14" y1="14" x2="34" y2="34" stroke="#8b5cf6" strokeWidth="1.8"/><line x1="34" y1="14" x2="14" y2="34" stroke="#8b5cf6" strokeWidth="1.8"/></svg>,
    recovering_learning: <svg width={s} height={s} viewBox="0 0 48 48"><circle cx="24" cy="24" r="18" fill="none" stroke="#f59e0b" strokeWidth="1.8"/><path d="M16 28 Q20 18 24 24 Q28 30 32 20" fill="none" stroke="#f59e0b" strokeWidth="1.8"/></svg>,
    idle_waiting:        <svg width={s} height={s} viewBox="0 0 48 48"><circle cx="24" cy="24" r="18" fill="none" stroke="#4b5563" strokeWidth="1.2" opacity="0.45"/><circle cx="24" cy="24" r="2.5" fill="#4b5563" opacity="0.25"/></svg>,
  };
  return m[mood] || m.calm_observing;
}

/* ── Radar bar ── */
function RadarBar({ level, noiseRatio }) {
  const levels = ["clear","mild","moderate","elevated","high","extreme"];
  const cols   = {clear:"#22c55e",mild:"#84cc16",moderate:"#eab308",elevated:"#f97316",high:"#ef4444",extreme:"#dc2626"};
  const pct = Math.round((noiseRatio||0)*100);
  const c = cols[level]||"#6b7280";
  return (
    <div>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:4}}>
        <span style={{fontSize:11,fontWeight:700,color:c,textTransform:"uppercase"}}>{level}</span>
        <span style={{fontSize:11,color:"var(--text-muted)"}}>{pct}% noise</span>
      </div>
      <div style={{height:6,background:"var(--border)",borderRadius:3,overflow:"hidden"}}>
        <div style={{width:`${pct}%`,height:"100%",background:c,borderRadius:3,transition:"width 0.5s ease"}}/>
      </div>
      <div style={{display:"flex",justifyContent:"space-between",marginTop:2}}>
        {levels.map(l=>(
          <span key={l} style={{fontSize:8,color:l===level?c:"var(--text-muted)",opacity:l===level?1:0.4,fontWeight:l===level?700:400}}>{l}</span>
        ))}
      </div>
    </div>
  );
}

/* ── Fear & Greed ── */
function FGGauge({value,classification,direction}) {
  if(value==null) return <WarmUp text="Waiting for Fear & Greed data…"/>;
  const c = value<25?"#ef4444":value<45?"#f97316":value<55?"#eab308":value<75?"#84cc16":"#22c55e";
  const a = direction==="rising"?"↑":direction==="falling"?"↓":"→";
  return (
    <div style={{textAlign:"center"}}>
      <div style={{fontSize:28,fontWeight:800,color:c}}>{value}</div>
      <div style={{fontSize:11,color:c,fontWeight:600}}>{classification} {a}</div>
      <div style={{height:4,background:"var(--border)",borderRadius:2,marginTop:6,overflow:"hidden"}}>
        <div style={{width:`${value}%`,height:"100%",background:c,borderRadius:2}}/>
      </div>
      <div style={{display:"flex",justifyContent:"space-between",fontSize:8,color:"var(--text-muted)",marginTop:2}}>
        <span>Extreme Fear</span><span>Extreme Greed</span>
      </div>
    </div>
  );
}

/* ── Verdict badge ── */
function VBadge({v}) {
  const cfg = {
    interesting:{c:"#22c55e",l:"Interesting"},
    watch:{c:"#3b82f6",l:"Watching"},
    unclear:{c:"#8b5cf6",l:"Unclear"},
    reject:{c:"#6b7280",l:"Rejected"},
    noise:{c:"#4b5563",l:"Noise"},
  };
  const x = cfg[v]||cfg.noise;
  return <span style={{padding:"1px 6px",borderRadius:3,fontSize:9,fontWeight:600,background:`${x.c}18`,color:x.c}}>{x.l}</span>;
}
function SBadge({s,str}) {
  const c = {bullish:"#22c55e",bearish:"#ef4444",neutral:"#6b7280"}[s]||"#6b7280";
  return <span style={{padding:"2px 7px",borderRadius:4,fontSize:10,fontWeight:600,background:`${c}18`,color:c,border:`1px solid ${c}33`}}>{s}{str>0?` (${(str*100).toFixed(0)}%)`:""}</span>;
}

/* ── Source badge (optional) ── */
function SourceBadge({source}) {
  if(!source) return null;
  const name = typeof source === "string" ? source : "";
  if(!name) return null;
  return (
    <span style={{
      padding:"1px 5px",borderRadius:3,fontSize:8,fontWeight:500,
      background:"var(--bg)",color:"var(--text-muted)",border:"1px solid var(--border)",
      marginLeft:4,
    }}>
      {name.length > 16 ? name.slice(0,16)+"…" : name}
    </span>
  );
}

/* ── Verdict color helper ── */
function verdictColor(v) {
  const m = {interesting:"#22c55e",watch:"#3b82f6",reject:"#6b7280",noise:"#4b5563",unclear:"#8b5cf6"};
  return m[v] || "#6b7280";
}

/* ── Feed item (expandable for news) ── */
function FeedItem({item}) {
  const [open, setOpen] = useState(false);
  const ago = (()=>{try{const d=(Date.now()-new Date(item.timestamp).getTime())/1000;if(d<60)return "just now";if(d<3600)return `${Math.floor(d/60)}m ago`;if(d<86400)return `${Math.floor(d/3600)}h ago`;return `${Math.floor(d/86400)}d ago`}catch{return ""}})();
  const src = item.meta?.source || "";
  const isNews = item.type?.startsWith("news_");
  const m = item.meta || {};
  const hasDetail = isNews && (m.reasoning_text || m.body || (m.bullish_signals?.length||0)>0 || (m.bearish_signals?.length||0)>0);
  return (
    <div style={{borderBottom:"1px solid var(--border)"}}>
      <div
        style={{display:"flex",gap:10,padding:"8px 0",cursor:hasDetail?"pointer":"default"}}
        onClick={()=>hasDetail&&setOpen(!open)}
      >
        <span style={{fontSize:14,color:item.color||"var(--text-muted)",minWidth:18,textAlign:"center"}}>{item.icon||"·"}</span>
        <div style={{flex:1,minWidth:0}}>
          <div style={{fontSize:12,color:"var(--text)",lineHeight:1.4}}>
            {item.message}
            <SourceBadge source={src}/>
            {hasDetail&&<span style={{fontSize:9,color:"var(--text-muted)",marginLeft:4}}>{open?"▾":"▸"}</span>}
          </div>
          {item.detail&&<div style={{fontSize:10,color:"var(--text-muted)",marginTop:2}}>{item.detail}</div>}
        </div>
        <span style={{fontSize:9,color:"var(--text-muted)",whiteSpace:"nowrap",paddingTop:2}}>{ago}</span>
      </div>
      {open && hasDetail && (
        <div style={{padding:"4px 0 10px 28px",fontSize:10,lineHeight:1.6,color:"var(--text-muted)"}}>
          {/* Verdict + scores row */}
          <div style={{display:"flex",gap:8,flexWrap:"wrap",marginBottom:4}}>
            <span style={{padding:"1px 6px",borderRadius:4,fontSize:9,fontWeight:600,color:"#fff",background:verdictColor(m.verdict)}}>{m.verdict||"?"}</span>
            {m.sentiment&&<span style={{fontSize:9}}>Sentiment: <b style={{color:m.sentiment==="bullish"?"#22c55e":m.sentiment==="bearish"?"#ef4444":"var(--text-muted)"}}>{m.sentiment}</b></span>}
            {m.impact&&<span style={{fontSize:9}}>Impact: <b>{m.impact}</b></span>}
            {m.trust!=null&&<span style={{fontSize:9}}>Trust: <b>{(m.trust*100).toFixed(0)}%</b></span>}
            {m.bs_risk!=null&&m.bs_risk>0.1&&<span style={{fontSize:9,color:"#ef4444"}}>BS: {(m.bs_risk*100).toFixed(0)}%</span>}
          </div>
          {/* Raw body / summary */}
          {m.body&&<div style={{marginBottom:4,color:"var(--text)",opacity:0.7,fontStyle:"italic"}}>{m.body}</div>}
          {/* Reasoning text */}
          {m.reasoning_text&&<div style={{marginBottom:4}}>🔍 <span style={{color:"var(--text)"}}>{m.reasoning_text}</span></div>}
          {/* Signals */}
          {(m.bullish_signals?.length>0||m.bearish_signals?.length>0)&&(
            <div style={{display:"flex",gap:12,marginBottom:4}}>
              {m.bullish_signals?.length>0&&<span style={{color:"#22c55e"}}>▲ {m.bullish_signals.join(", ")}</span>}
              {m.bearish_signals?.length>0&&<span style={{color:"#ef4444"}}>▼ {m.bearish_signals.join(", ")}</span>}
            </div>
          )}
          {/* Link to source */}
          {m.url&&<a href={m.url} target="_blank" rel="noopener noreferrer" style={{fontSize:9,color:"#3b82f6",textDecoration:"none"}}>View source ↗</a>}
        </div>
      )}
    </div>
  );
}

/* ── Interesting item (expandable) ── */
function InterestingItem({it}) {
  const [open, setOpen] = useState(false);
  const hasExtra = it.reasoning_text || (it.bullish_signals?.length>0) || (it.bearish_signals?.length>0);
  return (
    <div style={{padding:"6px 0",borderBottom:"1px solid var(--border)"}}>
      <div style={{display:"flex",gap:6,alignItems:"center",marginBottom:3,flexWrap:"wrap",cursor:hasExtra?"pointer":"default"}} onClick={()=>hasExtra&&setOpen(!open)}>
        <VBadge v={it.verdict}/><SBadge s={it.sentiment} str={it.sentiment_strength}/>
        {it.impact&&<span style={{fontSize:9,color:"var(--text-muted)"}}>{it.impact}</span>}
        <SourceBadge source={it.source_name || it.source}/>
        {hasExtra&&<span style={{fontSize:9,color:"var(--text-muted)"}}>{open?"▾":"▸"}</span>}
      </div>
      <div style={{fontSize:11,color:"var(--text)",lineHeight:1.3}}>{it.headline}</div>
      <div style={{fontSize:10,color:"var(--text-muted)",marginTop:2,fontStyle:"italic"}}>{it.explanation}</div>
      {open && hasExtra && (
        <div style={{marginTop:4,padding:"4px 0 2px 4px",fontSize:9,lineHeight:1.6,color:"var(--text-muted)",borderLeft:"2px solid var(--border)",paddingLeft:8}}>
          {it.reasoning_text&&<div style={{marginBottom:3}}>🔍 {it.reasoning_text}</div>}
          {(it.bullish_signals?.length>0||it.bearish_signals?.length>0)&&(
            <div style={{display:"flex",gap:10}}>
              {it.bullish_signals?.length>0&&<span style={{color:"#22c55e"}}>▲ {it.bullish_signals.join(", ")}</span>}
              {it.bearish_signals?.length>0&&<span style={{color:"#ef4444"}}>▼ {it.bearish_signals.join(", ")}</span>}
            </div>
          )}
          <div style={{display:"flex",gap:8,marginTop:2}}>
            {it.trust!=null&&<span>Trust: {(it.trust*100).toFixed(0)}%</span>}
            {it.relevance!=null&&<span>Relevance: {(it.relevance*100).toFixed(0)}%</span>}
            {it.bs_risk!=null&&it.bs_risk>0.1&&<span style={{color:"#ef4444"}}>BS: {(it.bs_risk*100).toFixed(0)}%</span>}
          </div>
          {it.url&&<a href={it.url} target="_blank" rel="noopener noreferrer" style={{fontSize:9,color:"#3b82f6",textDecoration:"none",display:"block",marginTop:2}}>View source ↗</a>}
        </div>
      )}
    </div>
  );
}

/* ── Clarity bar ── */
function ClarityBar({value}) {
  const c = value>70?"#22c55e":value>45?"#3b82f6":value>25?"#eab308":"#ef4444";
  return (
    <div style={{marginTop:6}}>
      <div style={{display:"flex",justifyContent:"space-between",fontSize:9,color:"var(--text-muted)",marginBottom:2}}>
        <span>Clarity</span><span style={{color:c,fontWeight:600}}>{value}%</span>
      </div>
      <div style={{height:4,background:"var(--border)",borderRadius:2,overflow:"hidden"}}>
        <div style={{width:`${value}%`,height:"100%",background:c,borderRadius:2,transition:"width 0.4s ease"}}/>
      </div>
    </div>
  );
}

/* ── Warm-up / empty state ── */
function WarmUp({ text, sub }) {
  return (
    <div style={{textAlign:"center",padding:"20px 12px"}}>
      <div style={{fontSize:16,color:"var(--text-muted)",opacity:0.4,marginBottom:6}}>○</div>
      <div style={{fontSize:11,color:"var(--text-muted)",lineHeight:1.5}}>{text || "CryptoMind is warming up…"}</div>
      {sub && <div style={{fontSize:10,color:"var(--text-muted)",opacity:0.6,marginTop:4}}>{sub}</div>}
    </div>
  );
}

/* ── Stale data badge ── */
function StaleBadge() {
  return (
    <span style={{
      padding:"2px 7px",borderRadius:4,fontSize:9,fontWeight:600,
      background:"#f59e0b18",color:"#f59e0b",border:"1px solid #f59e0b33",
      marginLeft:6,
    }}>
      stale
    </span>
  );
}

/* ── "Why this mood?" expander ── */
function WhyMood({ reasoning, context }) {
  const [open, setOpen] = useState(false);
  if (!reasoning && !context) return null;
  return (
    <div style={{marginTop:8}}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          background:"none",border:"none",cursor:"pointer",padding:0,
          fontSize:10,color:"#8b5cf6",fontWeight:600,
        }}
      >
        {open ? "▾" : "▸"} Why this mood?
      </button>
      {open && (
        <div style={{
          marginTop:6,padding:"8px 10px",background:"var(--bg)",
          borderRadius:6,fontSize:11,color:"var(--text-muted)",lineHeight:1.5,
        }}>
          {reasoning && <div>{reasoning}</div>}
          {context && (
            <div style={{display:"flex",flexWrap:"wrap",gap:"4px 12px",marginTop:6,fontSize:10}}>
              {context.market_state && <span>Market: <b>{context.market_state}</b></span>}
              {context.fear_greed != null && <span>F&G: <b>{context.fear_greed}</b></span>}
              {context.noise_ratio != null && <span>Noise: <b>{(context.noise_ratio*100).toFixed(0)}%</b></span>}
              {context.exposure_pct != null && <span>Exposure: <b>{context.exposure_pct}%</b></span>}
              {context.win_rate != null && <span>Win rate: <b>{(context.win_rate*100).toFixed(0)}%</b></span>}
              {context.total_trades != null && <span>Trades: <b>{context.total_trades}</b></span>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}


/* ── Trait bar (for personality) ── */
function TraitBar({ name, score, warming, muted }) {
  const c = warming ? "#6b7280" : score >= 65 ? "#22c55e" : score >= 40 ? "#3b82f6" : "#f59e0b";
  return (
    <div style={{marginBottom:5,opacity:muted?0.6:1}}>
      <div style={{display:"flex",justifyContent:"space-between",fontSize:10,color:"var(--text-muted)",marginBottom:1}}>
        <span>{name}{warming?" (warming up)":""}</span>
        <span style={{color:c,fontWeight:600}}>{score}</span>
      </div>
      <div style={{height:3,background:"var(--border)",borderRadius:2,overflow:"hidden"}}>
        <div style={{width:`${score}%`,height:"100%",background:c,borderRadius:2,transition:"width 0.4s ease"}}/>
      </div>
    </div>
  );
}

/* ── Stat box (for lifetime) ── */
function StatBox({ label, value, color }) {
  return (
    <div>
      <div style={{fontSize:9,color:"var(--text-muted)",textTransform:"uppercase",letterSpacing:0.3}}>{label}</div>
      <div style={{fontSize:14,fontWeight:700,color:color||"var(--text)"}}>{value}</div>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════════════════
   LAB PAGE
   ════════════════════════════════════════════════════════════════════════════ */

export default function Lab() {
  const {data:mindState}     = useApi("/v7/mind/state", 15000);
  const {data:radarData}     = useApi("/v7/mind/radar", 30000);
  const {data:feedData}      = useApi("/v7/mind/feed?limit=35", 10000);
  const {data:interestingD}  = useApi("/v7/news/interesting?limit=10", 30000);
  const {data:rejectedD}     = useApi("/v7/news/rejected?limit=10", 30000);
  const {data:mindOverview}  = useApi("/v7/mind", 30000);
  const {data:personalityD}  = useApi("/v7/mind/personality", 30000);
  const {data:intentD}       = useApi("/v7/mind/session-intent", 30000);
  const {data:milestonesD}   = useApi("/v7/mind/milestones", 60000);
  const {data:lifetimeD}     = useApi("/v7/mind/lifetime", 60000);
  const {data:truthD}        = useApi("/v7/news/truth-reviews?limit=15", 45000);
  const {data:contextD}      = useApi("/v7/mind/context-summary", 60000);
  const {data:journalD}      = useApi("/v7/mind/journal", 60000);
  const {data:reflectionsD}  = useApi("/v7/side-hustle/reflections?limit=10", 45000);
  const {data:replayD}       = useApi("/v7/mind/replay", 60000);
  const {data:identityD}     = useApi("/v7/mind/identity", 60000);
  const {data:ltPortfolioD}  = useApi("/v7/lifetime/portfolio", 60000);
  const {data:crowdD}        = useApi("/v7/crowd/belief-vs-reality", 30000);

  const mood        = mindState?.mood || "idle_waiting";
  const moodLabel   = mindState?.mood_label || "Starting up…";
  const moodDesc    = mindState?.mood_desc || "Gathering data.";
  const moodColor   = mindState?.mood_color || "#4b5563";
  const thoughts    = mindState?.thoughts || [];
  const concerns    = mindState?.concerns || [];
  const opps        = mindState?.opportunities || [];
  const clarity     = mindState?.clarity || 50;
  const impulse     = mindState?.action_impulse || "none";
  const focus       = mindState?.current_focus || "";
  const reasoning   = mindState?.reasoning || "";
  const context     = mindState?.context || null;
  const hasError    = mindState?.error;

  const radar       = radarData || {};
  const fg          = radar.fear_greed || {};
  const feed        = feedData?.feed || [];
  const interesting = interestingD?.interesting || [];
  const rejected    = rejectedD?.rejected || [];

  const evoScore    = mindOverview?.evolution_score || 0;
  const level       = mindOverview?.mind_level?.level || "Seed";

  const personality  = personalityD || {};
  const pTraits      = personality.traits || {};
  const pDominant    = personality.dominant_trait || null;
  const pSupporting  = personality.supporting || [];
  const intent       = intentD || {};
  const milestones   = milestonesD?.milestones || [];
  const lifetime     = lifetimeD?.lifetime || {};
  const lifetimeCurve = lifetimeD?.evolution_curve || [];

  // Chunk 3 data
  const truthReviews = truthD?.reviews || [];
  const truthStats   = truthD?.stats || {};
  const ctxSummary   = contextD || {};
  const journalToday = journalD?.today || {};
  const reflections  = reflectionsD?.reflections || [];
  const reflStats    = reflectionsD?.stats || {};
  const replayTL     = replayD?.timeline || [];
  const identity     = identityD || {};
  const ltPortfolio  = ltPortfolioD || {};
  const crowd        = crowdD || {};
  const crowdCrowd   = crowd.crowd || {};
  const crowdReality = crowd.reality || {};
  const crowdComp    = crowd.comparison || {};

  // Detect warm-up: no mind state data yet, or error
  const isWarmingUp = !mindState || hasError;
  // Detect stale news
  const isStale     = radarData?.stale === true;

  return (
    <>
      {/* Header */}
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:10,flexWrap:"wrap",gap:4}}>
        <h1 style={{margin:0,fontSize:18,fontWeight:700}}>Lab</h1>
        <div style={{display:"flex",alignItems:"center",gap:6}}>
          {isStale && <StaleBadge/>}
          <span style={{fontSize:10,color:"var(--text-muted)"}}>Observer Core v7.5</span>
        </div>
      </div>

      {/* ── Hero: Mind State ── */}
      <div style={{...CARD,borderLeft:`3px solid ${moodColor}`,display:"flex",gap:16,alignItems:"flex-start",flexWrap:"wrap"}}>
        <MoodSigil mood={mood} size={56}/>
        <div style={{flex:1,minWidth:200}}>
          {isWarmingUp ? (
            <WarmUp
              text="CryptoMind is warming up. Still gathering enough world context."
              sub="Mood, thoughts, and clarity will appear once enough data arrives."
            />
          ) : (
            <>
              <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:4,flexWrap:"wrap"}}>
                <span style={{fontSize:16,fontWeight:700,color:moodColor}}>{moodLabel}</span>
                <span style={{padding:"2px 8px",borderRadius:4,fontSize:9,fontWeight:600,background:"var(--bg)",color:"var(--text-muted)"}}>
                  impulse: {impulse}
                </span>
              </div>
              <div style={{fontSize:12,color:"var(--text-muted)",marginBottom:4}}>{moodDesc}</div>
              {focus && <div style={{fontSize:10,color:"#8b5cf6",marginBottom:6}}>Focus: {focus}</div>}

              {thoughts.map((t,i)=>(
                <div key={i} style={{fontSize:11,color:"var(--text)",marginBottom:2}}>
                  <span style={{color:"#8b5cf6",marginRight:4}}>◎</span>{t}
                </div>
              ))}
              {concerns.map((c,i)=>(
                <div key={i} style={{fontSize:11,color:"#d97706",marginBottom:2}}>
                  <span style={{marginRight:4}}>◈</span>{c}
                </div>
              ))}
              {opps.map((o,i)=>(
                <div key={i} style={{fontSize:11,color:"#22c55e",marginBottom:2}}>
                  <span style={{marginRight:4}}>●</span>{o}
                </div>
              ))}

              <ClarityBar value={clarity}/>
              <WhyMood reasoning={reasoning} context={context}/>
            </>
          )}
        </div>
      </div>

      {/* ── 3-col → stacks on tablet portrait, 2-col on landscape ── */}
      <div style={{
        display:"grid",
        gridTemplateColumns:"repeat(auto-fit, minmax(240px, 1fr))",
        gap:8,marginBottom:8,
      }}>

        {/* Bullshit Radar */}
        <div style={CARD}>
          <div style={LBL}>Bullshit Radar</div>
          {radar.total_analysed > 0 ? (
            <>
              <RadarBar level={radar.level||"clear"} noiseRatio={radar.noise_ratio||0}/>
              <div style={{fontSize:11,color:"var(--text-muted)",marginTop:8,lineHeight:1.4}}>
                {radar.description||"Warming up…"}
              </div>
              {radar.hype_alert&&(
                <div style={{marginTop:6,padding:"4px 8px",borderRadius:4,fontSize:10,background:"#ef444418",color:"#ef4444"}}>
                  {radar.hype_reason}
                </div>
              )}
              <div style={{display:"flex",gap:8,marginTop:8,fontSize:10,color:"var(--text-muted)",flexWrap:"wrap"}}>
                <span>Signal: <b style={{color:"var(--text)"}}>{((radar.signal_quality||0)*100).toFixed(0)}%</b></span>
                <span>Distortion: <b style={{color:"var(--text)"}}>{((radar.narrative_distortion||0)*100).toFixed(0)}%</b></span>
                <span>Crowd: <b style={{color:"var(--text)"}}>{(radar.crowd_heat||"—").replace(/_/g," ")}</b></span>
              </div>
            </>
          ) : (
            <WarmUp
              text="Too early for strong opinions."
              sub="The radar needs a few news cycles before it can assess noise levels."
            />
          )}
        </div>

        {/* Fear & Greed */}
        <div style={CARD}>
          <div style={LBL}>Fear & Greed Index</div>
          <FGGauge value={fg.value} classification={fg.classification} direction={fg.direction}/>
        </div>

        {/* Side Hustle: Mind Snapshot */}
        <div style={CARD}>
          <div style={LBL}>Side Hustle</div>
          <div style={{textAlign:"center",padding:"8px 0"}}>
            <div style={{fontSize:22,fontWeight:800,color:"#8b5cf6"}}>{level}</div>
            <div style={{fontSize:12,color:"var(--text-muted)",marginTop:2}}>
              Score: <b style={{color:"var(--text)"}}>{evoScore}</b>/1000
            </div>
          </div>
          <div style={{display:"flex",justifyContent:"space-between",fontSize:10,color:"var(--text-muted)",marginTop:4,flexWrap:"wrap",gap:4}}>
            <span>Sentiment: <b style={{color:"var(--text)"}}>{(radar.crowd_heat||"—").replace(/_/g," ")}</b></span>
            <span>Analysed: <b style={{color:"var(--text)"}}>{radar.total_analysed||0}</b></span>
          </div>
        </div>
      </div>

      {/* ── System Identity + Lifetime Portfolio ── */}
      <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit, minmax(240px, 1fr))",gap:8,marginBottom:8}}>
        <div style={CARD}>
          <div style={LBL}>System Identity</div>
          {identity.warming_up ? (
            <WarmUp text="Identity forming…" sub="Cycles and trades build identity over time."/>
          ) : (
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginTop:4}}>
              <StatBox label="Total Cycles" value={(identity.total_cycles||0).toLocaleString()}/>
              <StatBox label="Total Sessions" value={identity.total_sessions||0}/>
              <StatBox label="Total Trades" value={(identity.total_trades||0).toLocaleString()}/>
              <StatBox label="Continuity" value={`${identity.continuity_score||0}%`} color="#8b5cf6"/>
              <StatBox label="Memories" value={identity.total_memories||0}/>
              <StatBox label="Version" value={identity.current_version||"?"}/>
            </div>
          )}
          {identity.dominant_traits?.dominant && (
            <div style={{marginTop:6,fontSize:10,color:"var(--text-muted)"}}>
              Dominant: <b style={{color:"#8b5cf6"}}>{identity.dominant_traits.dominant.replace(/_/g," ")}</b>
            </div>
          )}
        </div>
        <div style={CARD}>
          <div style={LBL}>Lifetime Portfolio</div>
          {ltPortfolio.warming_up ? (
            <WarmUp text="Portfolio initializing…" sub="Financial state persists across upgrades."/>
          ) : (
            <>
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginTop:4}}>
                <StatBox label="Cash" value={`$${(ltPortfolio.cash||0).toFixed(2)}`}/>
                <StatBox label="BTC" value={`${(ltPortfolio.btc_holdings||0).toFixed(6)}`}/>
                <StatBox label="Equity" value={`$${(ltPortfolio.total_equity||0).toFixed(2)}`} color="#22c55e"/>
                <StatBox label="Realized PnL" value={(ltPortfolio.realized_pnl||0).toFixed(4)} color={ltPortfolio.realized_pnl>0?"#22c55e":"#ef4444"}/>
                <StatBox label="Peak" value={`$${(ltPortfolio.peak_equity||0).toFixed(2)}`}/>
                <StatBox label="Max DD" value={`${(ltPortfolio.max_drawdown_pct||0).toFixed(1)}%`} color="#ef4444"/>
              </div>
              {(ltPortfolio.total_refills||0)>0 && (
                <div style={{marginTop:6,fontSize:9,color:"var(--text-muted)"}}>
                  Refills: {ltPortfolio.total_refills} (${(ltPortfolio.total_refill_amount||0).toFixed(2)} total)
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* ── Belief vs Reality ── */}
      <div style={{...CARD,borderLeft:`3px solid ${crowdComp.alignment==="aligned"?"#22c55e":crowdComp.alignment==="diverging"?"#f59e0b":"var(--border)"}`}}>
        <div style={{...LBL,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
          <span>Belief vs Reality</span>
          {crowd.data_source && <span style={{fontSize:8,color:"var(--text-muted)",fontWeight:400,textTransform:"none"}}>{crowd.data_source}</span>}
        </div>
        {crowd.warming_up ? (
          <WarmUp
            text="Crowd lens warming up."
            sub="Not enough belief data yet. Watching for crowd signals."
          />
        ) : (
          <>
            {/* Main insight */}
            <div style={{fontSize:13,fontWeight:600,color:"var(--text)",marginBottom:10,lineHeight:1.4}}>
              "{crowdComp.insight || "Watching for crowd signals."}"
            </div>

            {/* 4-column stats row */}
            <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit, minmax(110px, 1fr))",gap:10,marginBottom:10}}>
              {/* Crowd Bias */}
              <div>
                <div style={{fontSize:9,color:"var(--text-muted)",textTransform:"uppercase",letterSpacing:0.3,marginBottom:2}}>Crowd Bias</div>
                <div style={{
                  fontSize:14,fontWeight:700,
                  color:crowdCrowd.bias==="bullish"?"#22c55e":crowdCrowd.bias==="bearish"?"#ef4444":"#6b7280",
                }}>{(crowdCrowd.bias||"neutral").charAt(0).toUpperCase()+(crowdCrowd.bias||"neutral").slice(1)}</div>
              </div>
              {/* Crowd Confidence */}
              <div>
                <div style={{fontSize:9,color:"var(--text-muted)",textTransform:"uppercase",letterSpacing:0.3,marginBottom:2}}>Crowd Confidence</div>
                <div style={{fontSize:14,fontWeight:700,color:"var(--text)"}}>{(crowdCrowd.strength||0).toFixed(0)}%</div>
              </div>
              {/* Price Trend */}
              <div>
                <div style={{fontSize:9,color:"var(--text-muted)",textTransform:"uppercase",letterSpacing:0.3,marginBottom:2}}>Price Trend</div>
                <div style={{
                  fontSize:14,fontWeight:700,
                  color:crowdReality.price_trend==="up"?"#22c55e":crowdReality.price_trend==="down"?"#ef4444":"#6b7280",
                }}>
                  {crowdReality.price_trend==="up"?"Up ↑":crowdReality.price_trend==="down"?"Down ↓":"Flat →"}
                </div>
              </div>
              {/* Alignment */}
              <div>
                <div style={{fontSize:9,color:"var(--text-muted)",textTransform:"uppercase",letterSpacing:0.3,marginBottom:2}}>Alignment</div>
                <span style={{
                  display:"inline-block",padding:"2px 8px",borderRadius:4,fontSize:11,fontWeight:700,
                  background:crowdComp.alignment==="aligned"?"#22c55e18":crowdComp.alignment==="diverging"?"#f59e0b18":"var(--bg)",
                  color:crowdComp.alignment==="aligned"?"#22c55e":crowdComp.alignment==="diverging"?"#f59e0b":"var(--text-muted)",
                }}>
                  {(crowdComp.alignment||"unclear").charAt(0).toUpperCase()+(crowdComp.alignment||"unclear").slice(1)}
                </span>
              </div>
            </div>

            {/* Divergence bar */}
            <div>
              <div style={{display:"flex",justifyContent:"space-between",fontSize:9,color:"var(--text-muted)",marginBottom:2}}>
                <span>Divergence Score</span>
                <span style={{
                  fontWeight:600,
                  color:(crowdComp.divergence_score||0)>60?"#ef4444":(crowdComp.divergence_score||0)>35?"#f59e0b":"#22c55e",
                }}>{crowdComp.divergence_score||0}/100</span>
              </div>
              <div style={{height:5,background:"var(--border)",borderRadius:3,overflow:"hidden"}}>
                <div style={{
                  width:`${crowdComp.divergence_score||0}%`,height:"100%",borderRadius:3,
                  transition:"width 0.5s ease",
                  background:(crowdComp.divergence_score||0)>60?"#ef4444":(crowdComp.divergence_score||0)>35?"#f59e0b":"#22c55e",
                }}/>
              </div>
              <div style={{display:"flex",justifyContent:"space-between",marginTop:2,fontSize:8,color:"var(--text-muted)"}}>
                <span>Aligned</span><span>Diverging</span>
              </div>
            </div>

            {/* Reason line */}
            {crowdComp.reason && (
              <div style={{fontSize:10,color:"var(--text-muted)",marginTop:6,fontStyle:"italic"}}>
                {crowdComp.reason}
              </div>
            )}
          </>
        )}
      </div>

      {/* ── 2-col → stacks on narrow screens ── */}
      <div style={{
        display:"grid",
        gridTemplateColumns:"repeat(auto-fit, minmax(300px, 1fr))",
        gap:8,
      }}>

        {/* Live Mind Feed */}
        <div style={{...CARD,maxHeight:480,overflowY:"auto"}}>
          <div style={{...LBL,display:"flex",justifyContent:"space-between"}}>
            <span>Live Mind Feed</span>
            <span style={{fontWeight:400}}>{feed.length} events</span>
          </div>
          {feed.length===0 ? (
            <WarmUp
              text="CryptoMind is warming up. News and thoughts will appear here."
              sub="Still gathering enough world context to form observations."
            />
          ) : feed.map((item,i)=><FeedItem key={i} item={item}/>)}
        </div>

        {/* Right: Interesting + Rejected */}
        <div>
          {/* Interesting Now */}
          <div style={{...CARD,maxHeight:230,overflowY:"auto"}}>
            <div style={{...LBL,display:"flex",justifyContent:"space-between"}}>
              <span>Interesting Now</span>
              <span style={{fontWeight:400,color:"#22c55e"}}>{interesting.length}</span>
            </div>
            {interesting.length===0 ? (
              <WarmUp
                text="Nothing interesting yet."
                sub="The radar is scanning. Signals will surface when they're real."
              />
            ) : interesting.map((it,i)=><InterestingItem key={i} it={it}/>)}
          </div>

          {/* Rejected Today */}
          <div style={{...CARD,maxHeight:230,overflowY:"auto"}}>
            <div style={{...LBL,display:"flex",justifyContent:"space-between"}}>
              <span>Rejected Today</span>
              <span style={{fontWeight:400,color:"#6b7280"}}>{rejected.length}</span>
            </div>
            {rejected.length===0 ? (
              <WarmUp
                text="No rejected items yet."
                sub="Once headlines come in, noise gets filtered here."
              />
            ) : rejected.slice(0,8).map((it,i)=>(
              <div key={i} style={{padding:"5px 0",borderBottom:"1px solid var(--border)"}}>
                <div style={{display:"flex",gap:6,alignItems:"center"}}>
                  <VBadge v={it.verdict}/>
                  <span style={{fontSize:10,color:"var(--text-muted)",flex:1,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{it.headline}</span>
                </div>
                <div style={{fontSize:10,color:"var(--text-muted)",marginTop:1,paddingLeft:4,fontStyle:"italic"}}>{it.explanation}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Chunk 2: Personality + Session Intent ── */}
      <div style={{
        display:"grid",
        gridTemplateColumns:"repeat(auto-fit, minmax(280px, 1fr))",
        gap:8,marginTop:8,
      }}>

        {/* Personality Card */}
        <div style={CARD}>
          <div style={LBL}>Personality</div>
          {personality.warming_up || !pDominant ? (
            <WarmUp
              text="Still too early for a personality read."
              sub="Need more trades before traits emerge from real data."
            />
          ) : (
            <>
              <div style={{marginBottom:8}}>
                <div style={{fontSize:13,fontWeight:700,color:"var(--text)",marginBottom:2}}>
                  {pDominant.label}
                </div>
                <div style={{fontSize:11,color:"var(--text-muted)",lineHeight:1.4,fontStyle:"italic"}}>
                  "{pDominant.description}"
                </div>
                <TraitBar name={pDominant.label} score={pDominant.score} warming={pDominant.warming_up}/>
              </div>
              {pSupporting.map((t,i)=>(
                <TraitBar key={i} name={t.label} score={t.score} warming={t.warming_up}/>
              ))}
              {Object.values(pTraits).filter(t=>t.name!==pDominant?.name && !pSupporting.find(s=>s.name===t.name)).slice(0,4).map((t,i)=>(
                <TraitBar key={i} name={t.label} score={t.score} warming={t.warming_up} muted/>
              ))}
            </>
          )}
        </div>

        {/* Session Intent Card */}
        <div style={{...CARD,borderLeft:`3px solid ${intent.color||"var(--border)"}`}}>
          <div style={LBL}>Session Intent</div>
          {intent.warming_up ? (
            <WarmUp
              text="Too few trades for a strong stance."
              sub="Defaulting to neutral until enough evidence arrives."
            />
          ) : (
            <>
              <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:6}}>
                <span style={{fontSize:20,color:intent.color||"var(--text-muted)"}}>{intent.icon||"◉"}</span>
                <div>
                  <div style={{fontSize:14,fontWeight:700,color:intent.color||"var(--text)"}}>{intent.label||"Neutral"}</div>
                  <div style={{fontSize:10,color:"var(--text-muted)"}}>{intent.description||""}</div>
                </div>
              </div>
              <div style={{fontSize:11,color:"var(--text)",lineHeight:1.5,marginBottom:6}}>
                {intent.reasoning||""}
              </div>
              {intent.confidence != null && (
                <div style={{fontSize:10,color:"var(--text-muted)"}}>
                  Confidence: <b style={{color:"var(--text)"}}>{(intent.confidence*100).toFixed(0)}%</b>
                </div>
              )}
              {(intent.factors||[]).length > 1 && (
                <div style={{marginTop:6,fontSize:10,color:"var(--text-muted)"}}>
                  {intent.factors.slice(1,4).map((f,i)=>(
                    <div key={i} style={{marginBottom:2}}>· {f}</div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* ── Milestones + Lifetime ── */}
      <div style={{
        display:"grid",
        gridTemplateColumns:"repeat(auto-fit, minmax(280px, 1fr))",
        gap:8,marginTop:8,
      }}>

        {/* Milestones Timeline */}
        <div style={{...CARD,maxHeight:320,overflowY:"auto"}}>
          <div style={{...LBL,display:"flex",justifyContent:"space-between"}}>
            <span>Milestones</span>
            <span style={{fontWeight:400}}>{milestones.length}</span>
          </div>
          {milestones.length === 0 ? (
            <WarmUp
              text="No milestones yet."
              sub="They'll appear automatically as the system achieves real things."
            />
          ) : milestones.slice(0,12).map((m,i)=>(
            <div key={i} style={{display:"flex",gap:10,padding:"6px 0",borderBottom:"1px solid var(--border)"}}>
              <div style={{
                width:6,minHeight:20,borderRadius:3,
                background:m.milestone_type==="evolution"?"#8b5cf6":m.milestone_type==="trade"?"#22c55e":m.milestone_type==="recovery"?"#f59e0b":"#3b82f6",
              }}/>
              <div style={{flex:1}}>
                <div style={{fontSize:11,fontWeight:600,color:"var(--text)"}}>{m.title}</div>
                {m.description && <div style={{fontSize:10,color:"var(--text-muted)",marginTop:1}}>{m.description}</div>}
                <div style={{fontSize:9,color:"var(--text-muted)",marginTop:2}}>
                  {m.mind_level_at} · {m.evolution_score_at} pts
                  {m.version_tag && <span> · v{m.version_tag}</span>}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Lifetime Stats */}
        <div style={CARD}>
          <div style={LBL}>Lifetime</div>
          {!lifetime.total_trades ? (
            <WarmUp
              text="Lifetime stats are building."
              sub="Cross-session data will aggregate here over time."
            />
          ) : (
            <>
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:"8px 16px",marginBottom:8}}>
                <StatBox label="Sessions" value={lifetime.total_sessions||0}/>
                <StatBox label="Total Trades" value={lifetime.total_trades||0}/>
                <StatBox label="Total Cycles" value={lifetime.total_cycles||0}/>
                <StatBox label="Hours" value={`${(lifetime.total_hours||0).toFixed(1)}`}/>
                <StatBox label="Lifetime PnL" value={`${lifetime.lifetime_pnl>0?"+":""}${(lifetime.lifetime_pnl||0).toFixed(4)}`} color={lifetime.lifetime_pnl>0?"#22c55e":lifetime.lifetime_pnl<0?"#ef4444":"var(--text)"}/>
                <StatBox label="Avg/Session" value={`${(lifetime.avg_trades_per_session||0).toFixed(1)} trades`}/>
              </div>
              {lifetimeCurve.length > 3 && (
                <div style={{fontSize:10,color:"var(--text-muted)",marginTop:4}}>
                  Evolution: {lifetimeCurve[0]?.score||0} → {lifetimeCurve[lifetimeCurve.length-1]?.score||0} pts ({lifetimeCurve.length} snapshots)
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* ══════════ Chunk 3: Truth Validation + Deep Reflection ══════════ */}

      {/* ── Context Summary + Journal ── */}
      <div style={{
        display:"grid",
        gridTemplateColumns:"repeat(auto-fit, minmax(300px, 1fr))",
        gap:8,marginTop:8,
      }}>

        {/* Context Summary */}
        <div style={CARD}>
          <div style={LBL}>Daily Context Summary</div>
          {ctxSummary.warming_up ? (
            <WarmUp
              text="Building today's context summary…"
              sub="Needs enough market data and trades."
            />
          ) : (
            <>
              {ctxSummary.market && (
                <div style={{marginBottom:8}}>
                  <div style={{fontSize:10,fontWeight:600,color:"var(--text-muted)",marginBottom:2}}>Market</div>
                  <div style={{fontSize:11,color:"var(--text)",lineHeight:1.5}}>{ctxSummary.market.summary}</div>
                </div>
              )}
              {ctxSummary.trades && ctxSummary.trades.total > 0 && (
                <div style={{marginBottom:8}}>
                  <div style={{fontSize:10,fontWeight:600,color:"var(--text-muted)",marginBottom:2}}>Trades</div>
                  <div style={{fontSize:11,color:"var(--text)",lineHeight:1.5}}>{ctxSummary.trades.summary}</div>
                </div>
              )}
              {ctxSummary.news_vs_price && (
                <div style={{marginBottom:8}}>
                  <div style={{fontSize:10,fontWeight:600,color:"var(--text-muted)",marginBottom:2}}>News vs Price</div>
                  <div style={{fontSize:11,color:"var(--text)",lineHeight:1.5}}>{ctxSummary.news_vs_price.summary}</div>
                  {ctxSummary.news_vs_price.alignment && (
                    <span style={{
                      display:"inline-block",marginTop:3,padding:"1px 6px",borderRadius:3,fontSize:9,fontWeight:600,
                      background:ctxSummary.news_vs_price.alignment==="aligned"?"#22c55e18":ctxSummary.news_vs_price.alignment==="divergent"?"#ef444418":"var(--bg)",
                      color:ctxSummary.news_vs_price.alignment==="aligned"?"#22c55e":ctxSummary.news_vs_price.alignment==="divergent"?"#ef4444":"var(--text-muted)",
                    }}>{ctxSummary.news_vs_price.alignment}</span>
                  )}
                </div>
              )}
              {ctxSummary.posture && (
                <div style={{padding:"6px 8px",borderRadius:4,background:"var(--bg)",marginTop:4}}>
                  <div style={{fontSize:10,fontWeight:600,color:"#8b5cf6",marginBottom:2}}>Next-Day Posture Hint</div>
                  <div style={{fontSize:11,color:"var(--text)"}}>{ctxSummary.posture.summary}</div>
                  <div style={{fontSize:9,color:"var(--text-muted)",marginTop:2}}>
                    Posture: <b>{ctxSummary.posture.posture}</b> · Confidence: <b>{((ctxSummary.posture.confidence||0)*100).toFixed(0)}%</b>
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Journal */}
        <div style={CARD}>
          <div style={LBL}>Daily Journal</div>
          {journalToday.warming_up ? (
            <WarmUp
              text="Journal is building…"
              sub="Reflections appear once there's enough activity."
            />
          ) : (
            <>
              {journalToday.key_insight && (
                <div style={{marginBottom:8,padding:"6px 8px",borderLeft:"3px solid #8b5cf6",background:"var(--bg)",borderRadius:"0 4px 4px 0"}}>
                  <div style={{fontSize:10,fontWeight:600,color:"#8b5cf6",marginBottom:2}}>Key Insight</div>
                  <div style={{fontSize:11,color:"var(--text)",lineHeight:1.5}}>{journalToday.key_insight}</div>
                </div>
              )}
              {journalToday.mood_arc && (
                <div style={{fontSize:11,color:"var(--text-muted)",marginBottom:6,lineHeight:1.4}}>
                  {journalToday.mood_arc}
                </div>
              )}
              {journalToday.mistakes_text && journalToday.mistakes_text !== "No obvious mistakes detected — either a clean session or not enough data." && (
                <div style={{marginBottom:6}}>
                  <div style={{fontSize:10,fontWeight:600,color:"#ef4444",marginBottom:1}}>Mistakes</div>
                  <div style={{fontSize:10,color:"var(--text-muted)",lineHeight:1.4}}>{journalToday.mistakes_text}</div>
                </div>
              )}
              {journalToday.lessons_text && journalToday.lessons_text !== "No clear lessons yet — need more trading data." && (
                <div style={{marginBottom:6}}>
                  <div style={{fontSize:10,fontWeight:600,color:"#22c55e",marginBottom:1}}>Lessons</div>
                  <div style={{fontSize:10,color:"var(--text-muted)",lineHeight:1.4}}>{journalToday.lessons_text}</div>
                </div>
              )}
              {journalToday.bias_shifts_text && (
                <div style={{fontSize:10,color:"var(--text-muted)",marginTop:4}}>{journalToday.bias_shifts_text}</div>
              )}
              {journalToday.trades_reflection && (
                <div style={{fontSize:10,color:"var(--text-muted)",marginTop:4,paddingTop:4,borderTop:"1px solid var(--border)"}}>
                  {journalToday.trades_reflection}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* ── Truth Reviews + Action Reflections ── */}
      <div style={{
        display:"grid",
        gridTemplateColumns:"repeat(auto-fit, minmax(300px, 1fr))",
        gap:8,marginTop:8,
      }}>

        {/* Truth Reviews */}
        <div style={{...CARD,maxHeight:380,overflowY:"auto"}}>
          <div style={{...LBL,display:"flex",justifyContent:"space-between"}}>
            <span>Truth Validation</span>
            {truthStats.completed > 0 && (
              <span style={{fontWeight:400,color:truthStats.accuracy_pct>=50?"#22c55e":"#ef4444"}}>
                {truthStats.accuracy_pct}% accurate
              </span>
            )}
          </div>
          {truthReviews.length === 0 ? (
            <WarmUp
              text="No truth reviews yet."
              sub="As interesting news arrives, we'll track whether it predicted correctly."
            />
          ) : (
            <>
              {truthStats.completed > 0 && (
                <div style={{display:"flex",gap:8,flexWrap:"wrap",fontSize:10,color:"var(--text-muted)",marginBottom:8}}>
                  <span>✓ {truthStats.correct||0}</span>
                  <span>✗ {truthStats.wrong||0}</span>
                  <span>? {truthStats.unclear||0}</span>
                  <span>≈ {truthStats.mixed||0}</span>
                  <span>↻ {truthStats.faded||0}</span>
                  <span>⏳ {truthStats.pending||0}</span>
                </div>
              )}
              {truthReviews.slice(0,10).map((r,i)=>{
                const vc = {correct:"#22c55e",wrong:"#ef4444",mixed:"#eab308",unclear:"#8b5cf6",faded:"#f97316",pending:"#6b7280"}[r.verdict]||"#6b7280";
                return (
                  <div key={i} style={{padding:"5px 0",borderBottom:"1px solid var(--border)"}}>
                    <div style={{display:"flex",gap:6,alignItems:"center",marginBottom:2}}>
                      <span style={{padding:"1px 5px",borderRadius:3,fontSize:9,fontWeight:600,background:`${vc}18`,color:vc}}>{r.verdict}</span>
                      <span style={{fontSize:9,color:"var(--text-muted)"}}>+{r.review_window} cycles</span>
                      {r.actual_move_pct!=null && <span style={{fontSize:9,color:r.actual_move_pct>0?"#22c55e":"#ef4444"}}>{r.actual_move_pct>0?"+":""}{r.actual_move_pct?.toFixed(2)}%</span>}
                      {r.confidence && <span style={{fontSize:8,color:"var(--text-muted)",opacity:0.7}}>{r.confidence}</span>}
                    </div>
                    <div style={{fontSize:10,color:"var(--text)",lineHeight:1.3}}>{r.headline?.slice(0,80)}{r.headline?.length>80?"…":""}</div>
                    {r.explanation && <div style={{fontSize:9,color:"var(--text-muted)",marginTop:1,fontStyle:"italic"}}>{r.explanation}</div>}
                  </div>
                );
              })}
            </>
          )}
        </div>

        {/* Action Reflections */}
        <div style={{...CARD,maxHeight:380,overflowY:"auto"}}>
          <div style={{...LBL,display:"flex",justifyContent:"space-between"}}>
            <span>Trade Reflections</span>
            {reflStats.total > 0 && (
              <span style={{fontWeight:400}}>{reflStats.total} graded</span>
            )}
          </div>
          {reflections.length === 0 ? (
            <WarmUp
              text="No trade reflections yet."
              sub="Each trade gets graded on timing, size, and patience."
            />
          ) : (
            <>
              {reflStats.total > 0 && (
                <div style={{display:"flex",gap:6,flexWrap:"wrap",fontSize:10,color:"var(--text-muted)",marginBottom:8}}>
                  {["A","B","C","D","F"].map(g=>{
                    const cnt = reflStats[`grade_${g.toLowerCase()}`]||0;
                    if(!cnt) return null;
                    const gc = {A:"#22c55e",B:"#84cc16",C:"#eab308",D:"#f97316",F:"#ef4444"}[g];
                    return <span key={g} style={{color:gc,fontWeight:600}}>{g}:{cnt}</span>;
                  })}
                </div>
              )}
              {reflections.slice(0,8).map((r,i)=>{
                const gc = {A:"#22c55e",B:"#84cc16",C:"#eab308",D:"#f97316",F:"#ef4444"}[r.overall_grade]||"#6b7280";
                return (
                  <div key={i} style={{padding:"6px 0",borderBottom:"1px solid var(--border)"}}>
                    <div style={{display:"flex",gap:6,alignItems:"center",marginBottom:2}}>
                      <span style={{fontSize:14,fontWeight:800,color:gc}}>{r.overall_grade}</span>
                      <span style={{fontSize:11,fontWeight:600,color:"var(--text)"}}>{r.action} #{r.trade_id}</span>
                      <span style={{fontSize:9,color:"var(--text-muted)"}}>
                        T:{r.entry_timing_grade} S:{r.size_grade} P:{r.patience_impact==="helped"?"✓":r.patience_impact==="hurt"?"✗":"—"}
                        {r.confidence&&r.confidence!=="high"&&<span style={{marginLeft:3,opacity:0.7}}>({r.confidence})</span>}
                      </span>
                    </div>
                    {r.what_went_well && r.what_went_well !== "No clear strengths in this trade." && (
                      <div style={{fontSize:10,color:"#22c55e",lineHeight:1.3}}>+ {r.what_went_well.slice(0,100)}</div>
                    )}
                    {r.what_could_improve && r.what_could_improve !== "No obvious improvements needed." && (
                      <div style={{fontSize:10,color:"#f97316",lineHeight:1.3}}>− {r.what_could_improve.slice(0,100)}</div>
                    )}
                  </div>
                );
              })}
            </>
          )}
        </div>
      </div>

      {/* ── Replay Timeline ── */}
      <div style={{...CARD,marginTop:8,maxHeight:420,overflowY:"auto"}}>
        <div style={{...LBL,display:"flex",justifyContent:"space-between"}}>
          <span>Session Replay</span>
          <span style={{fontWeight:400}}>{replayTL.length} events</span>
        </div>
        {replayTL.length === 0 ? (
          <WarmUp
            text="Replay timeline is building…"
            sub="News, trades, mood shifts, and milestones will appear here chronologically."
          />
        ) : (
          <div style={{position:"relative",paddingLeft:16}}>
            <div style={{position:"absolute",left:5,top:0,bottom:0,width:2,background:"var(--border)"}}/>
            {replayTL.slice(0,30).map((m,i)=>{
              const tc = {
                trade:"#3b82f6",news:"#8b5cf6",mood_shift:"#d97706",
                milestone:"#22c55e",regime_change:"#f97316",event:"#6b7280",
              }[m.marker_type]||"#6b7280";
              const icon = {trade:"◉",news:"◆",mood_shift:"◈",milestone:"★",regime_change:"▲",event:"·"}[m.marker_type]||"·";
              return (
                <div key={i} style={{position:"relative",paddingBottom:10,paddingLeft:12}}>
                  <div style={{
                    position:"absolute",left:-3,top:3,width:8,height:8,
                    borderRadius:"50%",background:tc,border:"2px solid var(--surface)",
                  }}/>
                  <div style={{display:"flex",gap:6,alignItems:"center"}}>
                    <span style={{fontSize:11,color:tc,fontWeight:600}}>{icon}</span>
                    <span style={{fontSize:11,color:"var(--text)",fontWeight:500}}>{m.title}</span>
                    {m.importance>=7 && <span style={{fontSize:8,color:tc,fontWeight:700}}>★</span>}
                  </div>
                  {m.detail && <div style={{fontSize:10,color:"var(--text-muted)",lineHeight:1.3,marginTop:1}}>{m.detail}</div>}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}
