import { useEffect, useRef, useState, useCallback } from "react";
import { createChart, ColorType, CrosshairMode, CandlestickSeries, LineSeries, AreaSeries } from "lightweight-charts";
import SafariChart from "./SafariChart";

// Use same-origin detection as useApi — never hardcode localhost
function _detectApi() {
  if (typeof window === "undefined") return "";
  const h = window.location.hostname;
  if (h === "localhost" || h === "127.0.0.1") return "http://localhost:8000";
  return ""; // same-origin for Render, iPad, production
}
const API = _detectApi();

// Detect touch Safari (iPad, iPhone) — use pure SVG fallback
// iPadOS 13+ spoofs "Macintosh" in UA, so we check touch + WebKit + no Chrome
function isSafariFallback() {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  const isTouch = "ontouchstart" in window || navigator.maxTouchPoints > 0;
  const isWebKit = /AppleWebKit/.test(ua) && !/Chrome/.test(ua) && !/CriOS/.test(ua) && !/Edg/.test(ua);
  // Any touch WebKit device = Safari on iPad/iPhone
  return isTouch && isWebKit;
}

const USE_SVG_FALLBACK = isSafariFallback();

const TIMEFRAMES = [
  { label: "1m", value: "1m" },
  { label: "5m", value: "5m" },
  { label: "15m", value: "15m" },
  { label: "1H", value: "1h" },
];

function fmtPrice(n) {
  return `$${Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function log(...args) {
  console.log("[BTCChart]", ...args);
}

export default function BTCChart({ marketState, action, confidence, livePrice }) {
  const chartRef = useRef(null);
  const containerRef = useRef(null);
  const observerRef = useRef(null);
  const [interval, setInterval_] = useState("5m");
  const [mode, setMode] = useState("simple");
  const [source, setSource] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastCandle, setLastCandle] = useState(null);
  const [priceChange, setPriceChange] = useState(0);
  const [chartError, setChartError] = useState(null);
  const pollRef = useRef(null);
  const dataRef = useRef(null); // store last good data for retry

  // ── Destroy chart safely ──
  const destroyChart = useCallback(() => {
    try {
      if (observerRef.current) { observerRef.current.disconnect(); observerRef.current = null; }
      if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; }
    } catch (_) { /* ignore */ }
  }, []);

  // ── Build chart with Safari safety ──
  const buildChart = useCallback((data, tf, chartMode) => {
    const container = containerRef.current;
    if (!container) { log("No container ref"); return; }

    // Safari fix: wait for container to have real dimensions
    const cw = container.clientWidth;
    const ch = container.clientHeight;
    log(`Container: ${cw}x${ch}`);

    if (cw < 50) {
      log("Container too narrow, retrying in 200ms...");
      setTimeout(() => buildChart(data, tf, chartMode), 200);
      return;
    }

    destroyChart();

    const candles = data.candles || [];
    if (!candles.length) { log("No candles"); return; }

    const isSimple = chartMode === "simple";
    const first = candles[0];
    const last = candles[candles.length - 1];
    const rising = last.close >= first.open;
    setPriceChange((last.close - first.open) / first.open * 100);

    // Height: smaller on touch devices with limited viewport
    const isTouch = "ontouchstart" in window || navigator.maxTouchPoints > 0;
    const vh = window.innerHeight;
    const chartHeight = (isTouch && vh <= 1100) ? 200 : 340;

    try {
      log(`Creating chart: ${cw}x${chartHeight}, mode=${chartMode}, candles=${candles.length}`);

      const chart = createChart(container, {
        width: cw,
        height: chartHeight,
        layout: {
          background: { type: ColorType.Solid, color: "transparent" },
          textColor: "#6b728066",
          fontSize: 10,
        },
        grid: {
          vertLines: { visible: !isSimple, color: "rgba(255,255,255,0.03)" },
          horzLines: { color: isSimple ? "rgba(255,255,255,0.02)" : "rgba(255,255,255,0.04)" },
        },
        crosshair: {
          mode: CrosshairMode.Magnet,
          vertLine: { color: "rgba(255,255,255,0.08)", width: 1, style: 3, labelVisible: true },
          horzLine: { color: "rgba(255,255,255,0.08)", width: 1, style: 3, labelVisible: true },
        },
        rightPriceScale: {
          borderVisible: false,
          scaleMargins: { top: 0.08, bottom: 0.08 },
          entireTextOnly: true,
        },
        timeScale: {
          borderVisible: false,
          timeVisible: true,
          secondsVisible: tf === "1m",
          rightOffset: 3,
        },
        handleScroll: { mouseWheel: true, pressedMouseMove: true },
        handleScale: { mouseWheel: true, pinch: true },
      });

      chartRef.current = chart;

      if (isSimple) {
        const lineColor = rising ? "#22c55e" : "#ef4444";
        const lineData = candles.map(c => ({ time: c.time, value: c.close }));

        const area = chart.addSeries(AreaSeries, {
          lineColor,
          lineWidth: 2,
          topColor: rising ? "rgba(34, 197, 94, 0.25)" : "rgba(239, 68, 68, 0.20)",
          bottomColor: rising ? "rgba(34, 197, 94, 0.01)" : "rgba(239, 68, 68, 0.01)",
          priceLineVisible: true,
          priceLineColor: lineColor,
          priceLineWidth: 1,
          lastValueVisible: true,
          crosshairMarkerVisible: true,
          crosshairMarkerRadius: 4,
          crosshairMarkerBackgroundColor: lineColor,
        });
        area.setData(lineData);

        if (data.ema9?.length > 0) {
          const s = chart.addSeries(LineSeries, { color: "rgba(59,130,246,0.4)", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
          s.setData(data.ema9);
        }
        if (data.ema21?.length > 0) {
          const s = chart.addSeries(LineSeries, { color: "rgba(245,158,11,0.35)", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
          s.setData(data.ema21);
        }
      } else {
        const cs = chart.addSeries(CandlestickSeries, {
          upColor: "#22c55e", downColor: "#ef4444",
          borderUpColor: "#22c55e", borderDownColor: "#ef4444",
          wickUpColor: "#22c55e88", wickDownColor: "#ef444488",
        });
        cs.setData(candles);

        if (data.ema9?.length > 0) {
          const s = chart.addSeries(LineSeries, { color: "#3b82f6", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
          s.setData(data.ema9);
        }
        if (data.ema21?.length > 0) {
          const s = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
          s.setData(data.ema21);
        }
      }

      chart.timeScale().fitContent();
      setLastCandle(last);
      setChartError(null);
      log("Chart rendered OK");

      // Resize — Safari safe with try/catch
      try {
        const obs = new ResizeObserver((entries) => {
          try {
            for (const entry of entries) {
              if (chartRef.current && entry.contentRect.width > 50) {
                chartRef.current.applyOptions({ width: entry.contentRect.width });
              }
            }
          } catch (_) { /* ignore resize errors */ }
        });
        obs.observe(container);
        observerRef.current = obs;
      } catch (_) {
        log("ResizeObserver not available, using fallback");
        // Fallback: listen to window resize
        const onResize = () => {
          if (chartRef.current && container.clientWidth > 50) {
            chartRef.current.applyOptions({ width: container.clientWidth });
          }
        };
        window.addEventListener("resize", onResize);
        observerRef.current = { disconnect: () => window.removeEventListener("resize", onResize) };
      }

    } catch (err) {
      log("Chart creation FAILED:", err.message);
      setChartError(err.message);
    }
  }, [destroyChart]);

  // ── Fetch chart data — same endpoint for all platforms ──
  const fetchCandles = useCallback(async (tf, chartMode) => {
    try {
      setLoading(true);
      setError(null);

      // Use /candles for everyone — 20s timeout (CoinGecko can be slow)
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 20000);
      const resp = await fetch(`${API}/candles?interval=${tf}`, { signal: controller.signal });
      clearTimeout(timer);

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();

      if (!data?.candles?.length) {
        setError("No data");
        setLoading(false);
        return;
      }

      log(`Got ${data.candles.length} points from ${data.source || "candles"}, safari=${USE_SVG_FALLBACK}`);
      setSource(data.source || "");
      dataRef.current = data;

      // Compute price change for header
      const first = data.candles[0];
      const last = data.candles[data.candles.length - 1];
      setPriceChange((last.close - first.open) / first.open * 100);
      setLastCandle(last);

      // Safari: just set data, no canvas needed
      if (USE_SVG_FALLBACK) {
        setLoading(false);
        return;
      }

      // Desktop: use requestAnimationFrame for canvas chart
      requestAnimationFrame(() => {
        buildChart(data, tf, chartMode);
        setLoading(false);
      });
    } catch (err) {
      log("Fetch error:", err.message);
      setError(err.name === "AbortError" ? "Timeout" : err.message);
      setLoading(false);
    }
  }, [buildChart]);

  // ── Load on interval/mode change ──
  useEffect(() => {
    fetchCandles(interval, mode);
    return () => { destroyChart(); };
  }, [interval, mode, fetchCandles, destroyChart]);

  // ── Polling + auto-retry ──
  useEffect(() => {
    const normalMs = { "1m": 15000, "5m": 30000, "15m": 60000, "1h": 120000 }[interval] || 30000;
    const ms = error ? 10000 : normalMs;
    pollRef.current = window.setInterval(() => fetchCandles(interval, mode), ms);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [interval, mode, fetchCandles, error]);

  const stateColors = { SLEEPING: "#6b7280", WAKING_UP: "#eab308", ACTIVE: "#22c55e", BREAKOUT: "#ef4444" };
  const actionColors = { BUY: "#22c55e", SELL: "#ef4444", HOLD: "#6b7280" };
  const changeColor = priceChange >= 0 ? "#22c55e" : "#ef4444";

  return (
    <div className="card" style={{ padding: 0, overflow: "hidden", marginBottom: 8 }}>
      {/* Header */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "10px 14px", flexWrap: "wrap", gap: 6,
      }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: "var(--text)" }}>BTC/USDT</span>
          {livePrice > 0 && (
            <span style={{ fontSize: 18, fontWeight: 700, color: "var(--text)" }}>{fmtPrice(livePrice)}</span>
          )}
          {priceChange !== 0 && (
            <span style={{ fontSize: 12, fontWeight: 600, color: changeColor }}>
              {priceChange >= 0 ? "+" : ""}{priceChange.toFixed(2)}%
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {marketState && (
            <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 5px", borderRadius: 3, background: `${stateColors[marketState] || "#666"}22`, color: stateColors[marketState] || "#666" }}>{marketState}</span>
          )}
          {action && (
            <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 5px", borderRadius: 3, background: `${actionColors[action] || "#666"}22`, color: actionColors[action] || "#666" }}>{action}</span>
          )}
          {source && <span style={{ fontSize: 8, color: "var(--text-muted)", opacity: 0.4 }}>{source}</span>}
          <div style={{ display: "flex", gap: 1, background: "var(--bg)", borderRadius: 4, padding: 1 }}>
            {[{ l: "Simple", v: "simple" }, { l: "Pro", v: "pro" }].map(m => (
              <button key={m.v} onClick={() => setMode(m.v)} style={{
                padding: "3px 8px", border: "none", borderRadius: 3, fontSize: 10, fontWeight: 600, cursor: "pointer",
                background: mode === m.v ? "var(--surface)" : "transparent",
                color: mode === m.v ? "var(--text)" : "var(--text-muted)",
              }}>{m.l}</button>
            ))}
          </div>
          <div style={{ display: "flex", gap: 1, background: "var(--bg)", borderRadius: 4, padding: 1 }}>
            {TIMEFRAMES.map(tf => (
              <button key={tf.value} onClick={() => setInterval_(tf.value)} style={{
                padding: "3px 8px", border: "none", borderRadius: 3, fontSize: 10, fontWeight: 600, cursor: "pointer",
                background: interval === tf.value ? "var(--surface)" : "transparent",
                color: interval === tf.value ? "var(--text)" : "var(--text-muted)",
              }}>{tf.label}</button>
            ))}
          </div>
        </div>
      </div>

      {/* Chart body — Safari/touch gets pure SVG, desktop gets canvas */}
      {USE_SVG_FALLBACK ? (
        <div style={{ padding: "0 4px" }}>
          {loading && (
            <div style={{ height: 180, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8 }}>
              <div className="spinner" />
              <span style={{ color: "var(--text-muted)", fontSize: 12 }}>Loading chart...</span>
            </div>
          )}
          {!loading && dataRef.current && (
            <SafariChart
              candles={dataRef.current.candles}
              ema9={dataRef.current.ema9}
              ema21={dataRef.current.ema21}
              height={180}
            />
          )}
          {!loading && !dataRef.current && (
            <div style={{ height: 180, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8 }}>
              <span style={{ color: "var(--text-muted)", fontSize: 12 }}>Reconnecting...</span>
              <button onClick={() => fetchCandles(interval, mode)} style={{
                padding: "4px 14px", background: "var(--bg)", border: "1px solid var(--border)",
                borderRadius: 4, color: "var(--text)", fontSize: 11, cursor: "pointer",
              }}>Retry</button>
            </div>
          )}
        </div>
      ) : (
        <>
          <div style={{ position: "relative", minHeight: 200 }}>
            {loading && !lastCandle && (
              <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", background: "var(--surface)", zIndex: 2, gap: 8 }}>
                <div className="spinner" />
                <span style={{ color: "var(--text-muted)", fontSize: 12 }}>Connecting to market data...</span>
              </div>
            )}
            {(error || chartError) && !lastCandle && (
              <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", background: "var(--surface)", zIndex: 2, gap: 8 }}>
                <div className="spinner" />
                <span style={{ color: "var(--text-muted)", fontSize: 12 }}>Reconnecting to market data...</span>
                <span style={{ color: "var(--text-muted)", fontSize: 10, opacity: 0.5 }}>Auto-retrying every 10s</span>
                <button onClick={() => fetchCandles(interval, mode)} style={{
                  padding: "4px 14px", background: "var(--bg)", border: "1px solid var(--border)",
                  borderRadius: 4, color: "var(--text)", fontSize: 11, cursor: "pointer", marginTop: 4,
                }}>Retry now</button>
              </div>
            )}
            <div ref={containerRef} style={{ width: "100%", minHeight: 200 }} />
          </div>

          {mode === "pro" && (
            <div style={{ display: "flex", gap: 12, padding: "4px 14px 8px", fontSize: 9, color: "var(--text-muted)" }}>
              <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
                <span style={{ width: 10, height: 2, background: "#3b82f6", borderRadius: 1 }} /> EMA 9
              </span>
              <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
                <span style={{ width: 10, height: 2, background: "#f59e0b", borderRadius: 1 }} /> EMA 21
              </span>
            </div>
          )}
        </>
      )}
    </div>
  );
}
