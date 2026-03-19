/**
 * SafariChart — Pure SVG line chart fallback for iPad Safari.
 * No canvas, no WebGL, no external libraries.
 * 100% reliable on all WebKit versions.
 */

import { useState, useRef, useCallback, memo } from "react";

function fmtPrice(n) {
  return `$${Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function SafariChartInner({ candles, ema9, ema21, height = 200 }) {
  const svgRef = useRef(null);
  const [tooltip, setTooltip] = useState(null);

  if (!candles || candles.length < 2) {
    return (
      <div style={{ height, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 12 }}>
        Waiting for price data...
      </div>
    );
  }

  const padding = { top: 10, right: 60, bottom: 24, left: 10 };
  const closes = candles.map(c => c.close);
  const times = candles.map(c => c.time);

  const currentPrice = closes[closes.length - 1];
  const allMin = Math.min(...closes);
  const allMax = Math.max(...closes);
  const fullRange = allMax - allMin || 1;

  // Smart Y-axis: always center around current price
  // Show equal distance above and below current price
  // Use the larger of: recent volatility or 2% of price
  const recentCloses = closes.slice(-Math.min(30, closes.length));
  const recentMin = Math.min(...recentCloses);
  const recentMax = Math.max(...recentCloses);
  const recentRange = recentMax - recentMin || currentPrice * 0.01;

  // Visible range = max of (recent range * 1.5) or (full range if small)
  const visibleHalf = Math.max(recentRange * 1.2, currentPrice * 0.015);

  // Center on current price
  let minP = currentPrice - visibleHalf;
  let maxP = currentPrice + visibleHalf;

  // But also show the full line if range is small enough to fit
  if (fullRange < visibleHalf * 3) {
    // Small range — show everything with padding
    minP = Math.min(minP, allMin - fullRange * 0.1);
    maxP = Math.max(maxP, allMax + fullRange * 0.1);
  }

  const priceRange = maxP - minP || 1;

  const first = closes[0];
  const last = closes[closes.length - 1];
  const rising = last >= first;
  const lineColor = rising ? "#22c55e" : "#ef4444";
  const fillColor = rising ? "rgba(34,197,94,0.12)" : "rgba(239,68,68,0.10)";

  // Chart dimensions (use CSS width via viewBox)
  const W = 800;
  const H = height;
  const plotW = W - padding.left - padding.right;
  const plotH = H - padding.top - padding.bottom;

  const toX = (i) => padding.left + (i / (candles.length - 1)) * plotW;
  const toY = (price) => padding.top + (1 - (price - minP) / priceRange) * plotH;

  // Build SVG path for price line
  const pricePath = closes.map((p, i) => `${i === 0 ? "M" : "L"}${toX(i).toFixed(1)},${toY(p).toFixed(1)}`).join(" ");

  // Fill area path (close bottom)
  const fillPath = pricePath + ` L${toX(closes.length - 1).toFixed(1)},${(padding.top + plotH).toFixed(1)} L${toX(0).toFixed(1)},${(padding.top + plotH).toFixed(1)} Z`;

  // EMA paths
  const buildEmaPath = (emaData) => {
    if (!emaData || emaData.length < 2) return null;
    // Map EMA timestamps to X positions
    const timeToIdx = {};
    times.forEach((t, i) => { timeToIdx[t] = i; });
    const points = emaData
      .filter(e => timeToIdx[e.time] !== undefined)
      .map(e => ({ x: toX(timeToIdx[e.time]), y: toY(e.value) }));
    if (points.length < 2) return null;
    return points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  };

  const ema9Path = buildEmaPath(ema9);
  const ema21Path = buildEmaPath(ema21);

  // Price labels on right axis
  const numLabels = 5;
  const priceLabels = [];
  for (let i = 0; i < numLabels; i++) {
    const price = minP + (priceRange * i) / (numLabels - 1);
    priceLabels.push({ y: toY(price), label: fmtPrice(price) });
  }

  // Time labels on bottom
  const numTimeLabels = 6;
  const timeLabels = [];
  const step = Math.floor(candles.length / numTimeLabels);
  for (let i = 0; i < candles.length; i += step) {
    timeLabels.push({ x: toX(i), label: fmtTime(times[i]) });
  }

  // Current price line
  const currentY = toY(last);

  // Tooltip on hover/touch
  const handleMove = useCallback((e) => {
    if (!svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const relX = clientX - rect.left;
    const ratio = (relX - padding.left * (rect.width / W)) / ((plotW / W) * rect.width);
    const idx = Math.round(ratio * (candles.length - 1));
    if (idx >= 0 && idx < candles.length) {
      setTooltip({ idx, price: closes[idx], time: fmtTime(times[idx]), x: toX(idx), y: toY(closes[idx]) });
    }
  }, [candles.length, closes, times, toX, toY, plotW]);

  const handleLeave = useCallback(() => setTooltip(null), []);

  return (
    <div style={{ position: "relative", width: "100%" }}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: "100%", height: "auto", display: "block", touchAction: "none" }}
        onMouseMove={handleMove}
        onTouchMove={handleMove}
        onMouseLeave={handleLeave}
        onTouchEnd={handleLeave}
      >
        {/* Grid lines */}
        {priceLabels.map((p, i) => (
          <line key={i} x1={padding.left} y1={p.y} x2={W - padding.right} y2={p.y}
            stroke="rgba(255,255,255,0.04)" strokeWidth={0.5} />
        ))}

        {/* Gradient fill */}
        <defs>
          <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={lineColor} stopOpacity={0.2} />
            <stop offset="100%" stopColor={lineColor} stopOpacity={0.01} />
          </linearGradient>
        </defs>
        <path d={fillPath} fill="url(#chartGrad)" />

        {/* EMA lines */}
        {ema9Path && <path d={ema9Path} fill="none" stroke="rgba(59,130,246,0.4)" strokeWidth={1} />}
        {ema21Path && <path d={ema21Path} fill="none" stroke="rgba(245,158,11,0.35)" strokeWidth={1} />}

        {/* Price line */}
        <path d={pricePath} fill="none" stroke={lineColor} strokeWidth={2} strokeLinejoin="round" />

        {/* Current price dashed line */}
        <line x1={padding.left} y1={currentY} x2={W - padding.right} y2={currentY}
          stroke={lineColor} strokeWidth={0.8} strokeDasharray="4,3" opacity={0.5} />

        {/* Current price label */}
        <rect x={W - padding.right + 2} y={currentY - 8} width={56} height={16} rx={3} fill={lineColor} />
        <text x={W - padding.right + 30} y={currentY + 4} textAnchor="middle" fontSize={9} fontWeight={600} fill="#fff">
          {last.toFixed(0)}
        </text>

        {/* Right axis labels */}
        {priceLabels.map((p, i) => (
          <text key={i} x={W - padding.right + 4} y={p.y + 3} fontSize={8} fill="#6b728088">{p.label}</text>
        ))}

        {/* Bottom axis labels */}
        {timeLabels.map((t, i) => (
          <text key={i} x={t.x} y={H - 4} textAnchor="middle" fontSize={8} fill="#6b728088">{t.label}</text>
        ))}

        {/* Tooltip crosshair */}
        {tooltip && (
          <>
            <line x1={tooltip.x} y1={padding.top} x2={tooltip.x} y2={padding.top + plotH}
              stroke="rgba(255,255,255,0.15)" strokeWidth={0.5} />
            <circle cx={tooltip.x} cy={tooltip.y} r={3.5} fill={lineColor} stroke="var(--surface)" strokeWidth={1.5} />
          </>
        )}
      </svg>

      {/* Tooltip overlay */}
      {tooltip && (
        <div style={{
          position: "absolute", top: 8, left: 14, padding: "3px 8px",
          background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 4,
          fontSize: 11, color: "var(--text)", pointerEvents: "none",
        }}>
          <span style={{ color: "var(--text-muted)" }}>{tooltip.time}</span>{" "}
          <span style={{ fontWeight: 600 }}>{fmtPrice(tooltip.price)}</span>
        </div>
      )}

      {/* EMA legend */}
      <div style={{ display: "flex", gap: 10, padding: "2px 10px", fontSize: 9, color: "var(--text-muted)" }}>
        <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
          <span style={{ width: 10, height: 2, background: "#3b82f6", borderRadius: 1 }} /> EMA 9
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
          <span style={{ width: 10, height: 2, background: "#f59e0b", borderRadius: 1 }} /> EMA 21
        </span>
      </div>
    </div>
  );
}

// Re-render if data actually changed (count, first time, last price, or height)
const SafariChart = memo(SafariChartInner, (prev, next) => {
  if (prev.height !== next.height) return false;
  const pLen = prev.candles?.length || 0;
  const nLen = next.candles?.length || 0;
  if (pLen !== nLen) return false;
  if (pLen === 0) return true;
  // Check first candle time (detects timeframe change)
  if (prev.candles[0]?.time !== next.candles[0]?.time) return false;
  // Check last price
  const pLast = prev.candles[pLen - 1]?.close;
  const nLast = next.candles[nLen - 1]?.close;
  return pLast === nLast;
});

export default SafariChart;
