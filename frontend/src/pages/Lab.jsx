/**
 * Lab.jsx — CryptoMind v7.8.1: The Perception Layer
 *
 * Lab = what the system SEES in the outside world.
 * Not decisions. Not portfolio. Not reflection.
 * Pure observation.
 *
 * Structure:
 *   1. Environment Snapshot (4 fields — no scroll)
 *   2. Hero Interpretation (one sentence)
 *   3. Observation Stream (filtered external events)
 */

import { useState, useRef, useEffect } from "react";
import { useApi } from "../hooks/useApi";
import { fmtLocalTimeShort } from "../hooks/useTime";

const _isTouch = typeof window !== "undefined" &&
  ("ontouchstart" in window || navigator.maxTouchPoints > 0);

export default function Lab() {
  // "Last observed" liveness tracker
  const [lastObservedAgo, setLastObservedAgo] = useState("");
  const lastDataRef = useRef(null);
  const prevStreamHashRef = useRef("");

  // External world data
  const { data: mindState } = useApi("/v7/mind/state", 15000);
  const { data: radarData } = useApi("/v7/mind/radar", 30000);
  const { data: crowdD } = useApi("/v7/crowd/belief-vs-reality", 30000);
  const { data: signalsD } = useApi("/v7/signals/latest", 30000);
  const { data: sigInsightsD } = useApi("/v7/signals/insights", 45000);
  const { data: feedData } = useApi("/v7/mind/feed?limit=20", 15000);

  // Extract state
  const radar = radarData || {};
  const fg = radar.fear_greed || {};
  const noiseLevel = radar.noise_level || "unknown";
  const noiseRatio = (radar.noise_ratio || 0);
  const clarity = mindState?.clarity || 0;

  const crowd = crowdD || {};
  const crowdBias = crowd.crowd?.bias || "unknown";
  const crowdConf = crowd.crowd?.confidence || 0;

  const signals = signalsD || {};
  const sigComposite = signals.composite || {};
  const narrative = sigComposite.narrative_state || "none";
  const tension = sigComposite.tension_score || 0;
  const sigDirection = sigComposite.overall_direction || "unclear";

  const sigInsights = sigInsightsD?.insights || [];

  // Build hero interpretation from real signal data
  const heroText = (() => {
    // Priority: signal insights > radar summary > fallback
    if (sigInsights.length > 0) {
      const top = sigInsights[0];
      return top.text || top.message || "Observing. No strong signal.";
    }
    if (noiseRatio > 0.6) return "Noise dominating. Nothing trustworthy yet.";
    if (clarity > 65) return "Clear environment. Signals readable.";
    if (crowdBias === "bullish" && crowdConf > 0.6) return "Crowd leaning bullish. No confirmation yet.";
    if (crowdBias === "bearish" && crowdConf > 0.6) return "Fear rising, but no follow-through.";
    if (fg.value != null && fg.value < 20) return "Extreme fear. Historically significant — watching.";
    if (fg.value != null && fg.value > 80) return "Extreme greed. Historically fragile — watching.";
    if (narrative === "calm") return "Quiet. No narrative forming.";
    if (narrative === "conflicted") return "Mixed signals. No consensus.";
    if (narrative === "building") return "Activity increasing, still directionless.";
    if (narrative === "overheated") return "Overheated signals. Caution.";
    return "Observing. Nothing decisive yet.";
  })();

  // Build observation stream from feed + signal insights
  const observations = (() => {
    const items = [];

    // Signal insights (highest value)
    for (const s of sigInsights.slice(0, 3)) {
      items.push({
        time: null,
        title: s.type || "Signal",
        interpretation: s.text || s.message || "",
        importance: s.importance || "low",
        source: "signals",
      });
    }

    // Fear & Greed (if available)
    if (fg.value != null) {
      items.push({
        time: null,
        title: `Fear & Greed: ${fg.value}`,
        interpretation: fg.classification
          ? `${fg.classification}${fg.direction ? ` (${fg.direction})` : ""}. ${fg.value < 25 ? "Historically significant." : fg.value > 75 ? "Caution zone." : "Neutral range."}`
          : "Monitoring.",
        importance: (fg.value < 20 || fg.value > 80) ? "high" : "low",
        source: "sentiment",
      });
    }

    // Feed items (news, events — filtered to most relevant)
    const feed = feedData?.feed || [];
    for (const f of feed.slice(0, 4)) {
      const meta = f.meta || {};
      if (f.type === "news_interesting" || f.type === "news_watch") {
        items.push({
          time: f.timestamp,
          title: meta.headline || f.message || "News event",
          interpretation: meta.explanation || `Verdict: ${meta.verdict || "watching"}`,
          importance: meta.verdict === "interesting" ? "medium" : "low",
          source: "news",
        });
      } else if (f.type?.startsWith("signal_")) {
        items.push({
          time: f.timestamp,
          title: f.message || "Signal event",
          interpretation: "",
          importance: f.type === "signal_warning" ? "high" : "low",
          source: "signals",
        });
      }
    }

    // Hypothesis tracking (shadow signals — observational only)
    if (sigComposite.overall_direction === "bullish" && tension > 40) {
      items.push({
        time: null,
        title: "Hypothesis: bullish pressure forming",
        interpretation: `Tension ${tension}/100. Tracking — no confirmation yet.`,
        importance: "hypothesis",
        source: "hypothesis",
      });
    } else if (sigComposite.overall_direction === "bearish" && tension > 40) {
      items.push({
        time: null,
        title: "Hypothesis: bearish pressure forming",
        interpretation: `Tension ${tension}/100. Tracking — no confirmation yet.`,
        importance: "hypothesis",
        source: "hypothesis",
      });
    }

    // Filter: only show what survived filtering (max 6)
    return items.slice(0, 6);
  })();

  // Stream dedup: detect if observations are identical to last render
  const streamHash = observations.map(o => o.title).join("|");
  const streamUnchanged = streamHash === prevStreamHashRef.current && streamHash !== "";
  useEffect(() => { prevStreamHashRef.current = streamHash; }, [streamHash]);

  // Liveness: track when data last changed
  useEffect(() => {
    const dataFingerprint = JSON.stringify({ noiseRatio, clarity, narrative, crowdBias, streamHash });
    if (dataFingerprint !== lastDataRef.current) {
      lastDataRef.current = dataFingerprint;
      setLastObservedAgo("just now");
    }
    const iv = setInterval(() => {
      setLastObservedAgo(prev => {
        if (prev === "just now") return "10s ago";
        if (prev === "10s ago") return "20s ago";
        if (prev === "20s ago") return "30s ago";
        const match = prev.match(/(\d+)s/);
        if (match) {
          const s = parseInt(match[1]) + 10;
          return s >= 60 ? `${Math.floor(s / 60)}m ago` : `${s}s ago`;
        }
        const mMatch = prev.match(/(\d+)m/);
        if (mMatch) return `${parseInt(mMatch[1]) + 1}m ago`;
        return prev;
      });
    }, 10000);
    return () => clearInterval(iv);
  }, [noiseRatio, clarity, narrative, crowdBias, streamHash]);

  // Snapshot values
  const noiseDisplay = noiseRatio > 0.6 ? "HIGH" : noiseRatio > 0.3 ? "MODERATE" : noiseRatio > 0.1 ? "LOW" : "CLEAR";
  const noiseColor = noiseRatio > 0.6 ? "#ef4444" : noiseRatio > 0.3 ? "#eab308" : "#22c55e";
  const clarityDisplay = clarity > 65 ? "HIGH" : clarity > 40 ? "MODERATE" : clarity > 20 ? "LOW" : "UNCLEAR";
  const clarityColor = clarity > 65 ? "#22c55e" : clarity > 40 ? "#3b82f6" : "#ef4444";
  const narrativeDisplay = narrative === "none" || narrative === "calm" ? "NONE" : narrative.toUpperCase();
  const narrativeColor = narrative === "overheated" ? "#ef4444" : narrative === "building" ? "#eab308" : "#6b7280";
  const crowdDisplay = crowdBias === "unknown" ? "WAITING" : crowdBias.toUpperCase();
  const crowdColor = crowdBias === "bullish" ? "#22c55e" : crowdBias === "bearish" ? "#ef4444" : "#6b7280";

  return (
    <div style={{ maxWidth: 800, margin: "0 auto", padding: _isTouch ? "16px 18px" : "20px 24px" }}>

      {/* ═══ 1. ENVIRONMENT SNAPSHOT ═══ */}
      <div style={{
        display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr",
        gap: _isTouch ? 12 : 10,
        marginBottom: 24,
      }}>
        {[
          { label: "Noise", value: noiseDisplay, color: noiseColor },
          { label: "Clarity", value: clarityDisplay, color: clarityColor },
          { label: "Narrative", value: narrativeDisplay, color: narrativeColor },
          { label: "Crowd", value: crowdDisplay, color: crowdColor },
        ].map(s => (
          <div key={s.label} style={{ textAlign: "center" }}>
            <div style={{
              fontSize: 9, color: "var(--text-muted)", textTransform: "uppercase",
              letterSpacing: 0.6, marginBottom: 6,
            }}>
              {s.label}
            </div>
            <div style={{
              fontSize: _isTouch ? 20 : 18, fontWeight: 700, color: s.color,
            }}>
              {s.value}
            </div>
          </div>
        ))}
      </div>

      {/* ═══ 2. HERO INTERPRETATION ═══ */}
      <div style={{
        padding: _isTouch ? "24px 20px" : "20px 18px",
        marginBottom: 24,
        borderLeft: "3px solid #6b7280",
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
          "{heroText}"
        </div>
        {/* Liveness indicator */}
        {lastObservedAgo && (
          <div style={{ marginTop: 8, fontSize: 10, color: "var(--text-muted)", opacity: 0.5 }}>
            Last observed: {lastObservedAgo}
          </div>
        )}
      </div>

      {/* ═══ 3. OBSERVATION STREAM ═══ */}
      <div>
        <div style={{
          fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase",
          letterSpacing: 0.5, marginBottom: 10,
        }}>
          Observations
        </div>

        {observations.length === 0 && (
          <div style={{
            padding: "24px", textAlign: "center",
            color: "var(--text-muted)", fontSize: 13,
          }}>
            Quiet. Nothing observed yet.
          </div>
        )}

        {streamUnchanged && observations.length > 0 && (
          <div style={{
            padding: "8px 0", fontSize: 11, color: "var(--text-muted)",
            opacity: 0.4, fontStyle: "italic",
          }}>
            No new observations.
          </div>
        )}

        <div style={{ maxHeight: _isTouch ? 360 : 400, overflowY: "auto" }}>
          {observations.map((obs, i) => {
            const impColor = obs.importance === "high" ? "#ef4444"
              : obs.importance === "medium" ? "#eab308"
              : obs.importance === "hypothesis" ? "#8b5cf6"
              : "#6b7280";

            return (
              <div key={i} style={{
                padding: _isTouch ? "10px 0" : "8px 0",
                borderBottom: i < observations.length - 1 ? "1px solid var(--border)" : "none",
                opacity: obs.importance === "low" ? 0.65 : 1,
              }}>
                <div style={{
                  display: "flex", alignItems: "center", gap: 8, marginBottom: 3,
                }}>
                  {/* Importance dot */}
                  <span style={{
                    width: 6, height: 6, borderRadius: "50%",
                    background: impColor, flexShrink: 0,
                  }} />

                  {/* Time (if available) */}
                  {obs.time && (
                    <span style={{
                      fontSize: 10, color: "var(--text-muted)",
                      fontVariantNumeric: "tabular-nums", minWidth: 44,
                    }}>
                      {fmtLocalTimeShort(obs.time)}
                    </span>
                  )}

                  {/* Title */}
                  <span style={{
                    fontSize: _isTouch ? 13 : 12,
                    fontWeight: 600,
                    color: obs.importance === "hypothesis" ? "#8b5cf6" : "var(--text)",
                    fontStyle: obs.importance === "hypothesis" ? "italic" : "normal",
                  }}>
                    {obs.title}
                  </span>

                  {/* Source tag */}
                  {obs.source === "hypothesis" && (
                    <span style={{
                      fontSize: 8, padding: "1px 5px", borderRadius: 3,
                      background: "#8b5cf618", color: "#8b5cf6", fontWeight: 600,
                    }}>
                      HYPOTHESIS
                    </span>
                  )}
                </div>

                {/* Interpretation */}
                {obs.interpretation && (
                  <div style={{
                    fontSize: _isTouch ? 12 : 11,
                    color: "var(--text-muted)",
                    marginLeft: 14,
                    lineHeight: 1.4,
                  }}>
                    {obs.interpretation}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
