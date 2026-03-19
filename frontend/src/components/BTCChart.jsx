import { useEffect, useRef, useState, useCallback } from "react";
import { createChart, ColorType, CrosshairMode, CandlestickSeries, LineSeries, AreaSeries } from "lightweight-charts";
import SafariChart from "./SafariChart";

function _detectApi() {
  if (typeof window === "undefined") return "";
  const h = window.location.hostname;
  if (h === "localhost" || h === "127.0.0.1") return "http://localhost:8000";
  return "";
}
const API = _detectApi();

function isSafariFallback() {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  const isTouch = "ontouchstart" in window || navigator.maxTouchPoints > 0;
  const isWebKit = /AppleWebKit/.test(ua) && !/Chrome/.test(ua) && !/CriOS/.test(ua) && !/Edg/.test(ua);
  return isTouch && isWebKit;
}
const USE_SVG_FALLBACK = isSafariFallback();

const TIMEFRAMES = [
  { label: "1m", value: "1m" },
  { label: "5m", value: "5m" },
  { label: "15m", value: "15m" },
  { label: "1H", value: "1h" },
  { label: "6H", value: "6h" },
  { label: "12H", value: "12h" },
  { label: "1D", value: "1d" },
  { label: "1W", value: "1w" },
  { label: "1M", value: "1M" },
  { label: "3M", value: "3M" },
  { label: "6M", value: "6M" },
];

const CHART_STORAGE_KEY = "cryptomind_chart_visible";

function fmtPrice(n) {
  return `$${Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function BTCChart({ marketState, action, confidence, livePrice }) {
  const chartRef = useRef(null);
  const containerRef = useRef(null);
  const mainSeriesRef = useRef(null);
  const ema9SeriesRef = useRef(null);
  const ema21SeriesRef = useRef(null);
  const observerRef = useRef(null);
  const currentModeRef = useRef(null);   // track what mode chart was built with
  const currentTfRef = useRef(null);     // track what timeframe chart was built with

  const [interval, setInterval_] = useState("5m");
  const [mode, setMode] = useState("simple");
  const [source, setSource] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastCandle, setLastCandle] = useState(null);
  const [priceChange, setPriceChange] = useState(0);
  const [chartError, setChartError] = useState(null);
  const [chartVisible, setChartVisible] = useState(() => {
    try { return localStorage.getItem(CHART_STORAGE_KEY) !== "false"; }
    catch { return true; }
  });
  const [expanded, setExpanded] = useState(false); // iPad expand/collapse
  const expandedRef = useRef(false); // ref for use inside callbacks

  const dataRef = useRef(null);
  const pollRef = useRef(null);
  const initCountRef = useRef(0); // track how many times chart was created

  // Keep expandedRef in sync
  expandedRef.current = expanded;

  // ── Toggle chart visibility ──
  const toggleChart = useCallback(() => {
    setChartVisible(prev => {
      const next = !prev;
      try { localStorage.setItem(CHART_STORAGE_KEY, String(next)); } catch {}
      return next;
    });
  }, []);

  // ── Destroy chart safely ──
  const destroyChart = useCallback(() => {
    try {
      if (observerRef.current) { observerRef.current.disconnect(); observerRef.current = null; }
      if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; }
      mainSeriesRef.current = null;
      ema9SeriesRef.current = null;
      ema21SeriesRef.current = null;
      currentModeRef.current = null;
      currentTfRef.current = null;
    } catch (_) {}
  }, []);

  // ── Build chart from scratch (only on first load or mode/tf change) ──
  const buildChart = useCallback((data, tf, chartMode) => {
    const container = containerRef.current;
    if (!container) return;

    const cw = container.clientWidth;
    if (cw < 50) {
      setTimeout(() => buildChart(data, tf, chartMode), 200);
      return;
    }

    destroyChart();

    const candles = data.candles || [];
    if (!candles.length) return;

    const isSimple = chartMode === "simple";
    const isTouch = "ontouchstart" in window || navigator.maxTouchPoints > 0;
    const vh = window.innerHeight;
    const isExpanded = expandedRef.current;
    const chartHeight = (isTouch && vh <= 1100) ? (isExpanded ? 340 : 200) : 340;

    try {
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
        rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.12, bottom: 0.12 }, entireTextOnly: true },
        timeScale: { borderVisible: false, timeVisible: true, secondsVisible: tf === "1m", rightOffset: 3 },
        handleScroll: { mouseWheel: true, pressedMouseMove: true },
        handleScale: { mouseWheel: true, pinch: true },
      });

      chartRef.current = chart;
      currentModeRef.current = chartMode;
      currentTfRef.current = tf;
      initCountRef.current += 1;

      const first = candles[0];
      const last = candles[candles.length - 1];
      const rising = last.close >= first.open;

      if (isSimple) {
        const lineColor = rising ? "#22c55e" : "#ef4444";
        const lineData = candles.map(c => ({ time: c.time, value: c.close }));
        const area = chart.addSeries(AreaSeries, {
          lineColor, lineWidth: 2,
          topColor: rising ? "rgba(34,197,94,0.25)" : "rgba(239,68,68,0.20)",
          bottomColor: rising ? "rgba(34,197,94,0.01)" : "rgba(239,68,68,0.01)",
          priceLineVisible: true, priceLineColor: lineColor, priceLineWidth: 1,
          lastValueVisible: true, crosshairMarkerVisible: true, crosshairMarkerRadius: 4,
          crosshairMarkerBackgroundColor: lineColor,
        });
        area.setData(lineData);
        mainSeriesRef.current = area;
      } else {
        const cs = chart.addSeries(CandlestickSeries, {
          upColor: "#22c55e", downColor: "#ef4444",
          borderUpColor: "#22c55e", borderDownColor: "#ef4444",
          wickUpColor: "#22c55e88", wickDownColor: "#ef444488",
        });
        cs.setData(candles);
        mainSeriesRef.current = cs;
      }

      // EMA overlays
      if (data.ema9?.length > 0) {
        const s = chart.addSeries(LineSeries, {
          color: isSimple ? "rgba(59,130,246,0.4)" : "#3b82f6",
          lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        });
        s.setData(data.ema9);
        ema9SeriesRef.current = s;
      }
      if (data.ema21?.length > 0) {
        const s = chart.addSeries(LineSeries, {
          color: isSimple ? "rgba(245,158,11,0.35)" : "#f59e0b",
          lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
        });
        s.setData(data.ema21);
        ema21SeriesRef.current = s;
      }

      chart.timeScale().fitContent();
      setChartError(null);

      // Resize observer
      try {
        const obs = new ResizeObserver((entries) => {
          try {
            for (const entry of entries)
              if (chartRef.current && entry.contentRect.width > 50)
                chartRef.current.applyOptions({ width: entry.contentRect.width });
          } catch (_) {}
        });
        obs.observe(container);
        observerRef.current = obs;
      } catch (_) {
        const onResize = () => {
          if (chartRef.current && container.clientWidth > 50)
            chartRef.current.applyOptions({ width: container.clientWidth });
        };
        window.addEventListener("resize", onResize);
        observerRef.current = { disconnect: () => window.removeEventListener("resize", onResize) };
      }
    } catch (err) {
      setChartError(err.message);
    }
  }, [destroyChart]);

  // ── Update existing chart data WITHOUT rebuilding ──
  const updateChartData = useCallback((data, chartMode) => {
    if (!chartRef.current || !mainSeriesRef.current) return false;

    const candles = data.candles || [];
    if (!candles.length) return false;

    try {
      const isSimple = chartMode === "simple";
      if (isSimple) {
        mainSeriesRef.current.setData(candles.map(c => ({ time: c.time, value: c.close })));
      } else {
        mainSeriesRef.current.setData(candles);
      }
      if (ema9SeriesRef.current && data.ema9?.length) ema9SeriesRef.current.setData(data.ema9);
      if (ema21SeriesRef.current && data.ema21?.length) ema21SeriesRef.current.setData(data.ema21);
      return true;
    } catch (_) {
      return false;
    }
  }, []);

  // ── Fetch and render ──
  const fetchCandles = useCallback(async (tf, chartMode) => {
    try {
      if (!dataRef.current) setLoading(true); // only show loading on first fetch
      setError(null);

      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 20000);
      const resp = await fetch(`${API}/candles?interval=${tf}`, { signal: controller.signal });
      clearTimeout(timer);

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();

      if (!data?.candles?.length) {
        if (!dataRef.current) { setError("No data"); setLoading(false); }
        return;
      }

      const newSource = data.source || "";
      const first = data.candles[0];
      const last = data.candles[data.candles.length - 1];
      const newPctChange = (last.close - first.open) / first.open * 100;
      const isFirstLoad = !dataRef.current;

      dataRef.current = data;

      // Only update state if values actually changed (prevents unnecessary re-renders)
      if (newSource !== source) setSource(newSource);
      if (Math.abs(newPctChange - priceChange) > 0.01) setPriceChange(newPctChange);
      if (!lastCandle || last.close !== lastCandle.close) setLastCandle(last);

      if (USE_SVG_FALLBACK) {
        if (isFirstLoad || loading) setLoading(false);
        return;
      }

      // If chart exists with same mode/tf → incremental update (no jitter)
      if (chartRef.current && currentModeRef.current === chartMode && currentTfRef.current === tf) {
        const ok = updateChartData(data, chartMode);
        if (ok) { setLoading(false); return; }
      }

      // Otherwise build fresh
      requestAnimationFrame(() => {
        buildChart(data, tf, chartMode);
        setLoading(false);
      });
    } catch (err) {
      if (!dataRef.current) setError(err.name === "AbortError" ? "Timeout" : err.message);
      setLoading(false);
    }
  }, [buildChart, updateChartData]);

  // ── Load on interval/mode change → full rebuild ──
  useEffect(() => {
    if (!chartVisible) return;
    // Reset refs to force rebuild on mode/tf change
    currentModeRef.current = null;
    currentTfRef.current = null;
    fetchCandles(interval, mode);
    return () => { destroyChart(); };
  }, [interval, mode, chartVisible, expanded, fetchCandles, destroyChart]);

  // ── Polling → incremental update (no jitter) ──
  useEffect(() => {
    if (!chartVisible) return;
    const ms = error ? 10000 : 60000; // slower polling = less jitter (1 min normal, 10s on error)
    pollRef.current = window.setInterval(() => fetchCandles(interval, mode), ms);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [interval, mode, chartVisible, fetchCandles, error]);

  // Cleanup on unmount
  useEffect(() => () => { destroyChart(); if (pollRef.current) clearInterval(pollRef.current); }, [destroyChart]);

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
          {livePrice > 0 && <span style={{ fontSize: 18, fontWeight: 700, color: "var(--text)" }}>{fmtPrice(livePrice)}</span>}
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

          {/* Chart ON/OFF toggle */}
          <button onClick={toggleChart} title={chartVisible ? "Hide chart" : "Show chart"} style={{
            padding: "3px 8px", border: "none", borderRadius: 3, fontSize: 10, fontWeight: 600, cursor: "pointer",
            background: chartVisible ? "var(--surface)" : "var(--border)",
            color: chartVisible ? "var(--text)" : "var(--text-muted)",
          }}>
            {chartVisible ? "📈 ON" : "📈 OFF"}
          </button>

          {/* Expand/Collapse — touch devices only */}
          {chartVisible && ("ontouchstart" in window || navigator.maxTouchPoints > 0) && (
            <button onClick={() => { setExpanded(e => !e); currentModeRef.current = null; }} title={expanded ? "Shrink chart" : "Expand chart"} style={{
              padding: "3px 8px", border: "none", borderRadius: 3, fontSize: 10, fontWeight: 600, cursor: "pointer",
              background: expanded ? "var(--surface)" : "var(--bg)",
              color: expanded ? "var(--text)" : "var(--text-muted)",
            }}>
              {expanded ? "⊟ Shrink" : "⊞ Expand"}
            </button>
          )}

          {/* Mode toggle */}
          {chartVisible && (
            <div style={{ display: "flex", gap: 1, background: "var(--bg)", borderRadius: 4, padding: 1 }}>
              {[{ l: "Simple", v: "simple" }, { l: "Pro", v: "pro" }].map(m => (
                <button key={m.v} onClick={() => setMode(m.v)} style={{
                  padding: "3px 8px", border: "none", borderRadius: 3, fontSize: 10, fontWeight: 600, cursor: "pointer",
                  background: mode === m.v ? "var(--surface)" : "transparent",
                  color: mode === m.v ? "var(--text)" : "var(--text-muted)",
                }}>{m.l}</button>
              ))}
            </div>
          )}

          {/* Timeframes */}
          {chartVisible && (
            <div style={{ display: "flex", gap: 1, background: "var(--bg)", borderRadius: 4, padding: 1 }}>
              {TIMEFRAMES.map(tf => (
                <button key={tf.value} onClick={() => setInterval_(tf.value)} style={{
                  padding: "3px 8px", border: "none", borderRadius: 3, fontSize: 10, fontWeight: 600, cursor: "pointer",
                  background: interval === tf.value ? "var(--surface)" : "transparent",
                  color: interval === tf.value ? "var(--text)" : "var(--text-muted)",
                }}>{tf.label}</button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Chart body */}
      {chartVisible && (
        USE_SVG_FALLBACK ? (
          <div style={{ padding: "0 4px", height: expanded ? 340 : 180, overflow: "hidden", transition: "height 0.3s ease" }}>
            {loading && (
              <div style={{ height: 180, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8 }}>
                <div className="spinner" />
                <span style={{ color: "var(--text-muted)", fontSize: 12 }}>Loading chart...</span>
              </div>
            )}
            {!loading && dataRef.current && (
              <SafariChart candles={dataRef.current.candles} ema9={dataRef.current.ema9} ema21={dataRef.current.ema21} height={expanded ? 340 : 180} />
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
            <div style={{ position: "relative", height: expanded ? 340 : (("ontouchstart" in window || navigator.maxTouchPoints > 0) && window.innerHeight <= 1100 ? 200 : 340), overflow: "hidden", transition: "height 0.3s ease" }}>
              {loading && !lastCandle && (
                <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", background: "var(--surface)", zIndex: 2, gap: 8 }}>
                  <div className="spinner" />
                  <span style={{ color: "var(--text-muted)", fontSize: 12 }}>Connecting to market data...</span>
                </div>
              )}
              {(error || chartError) && !lastCandle && (
                <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", background: "var(--surface)", zIndex: 2, gap: 8 }}>
                  <div className="spinner" />
                  <span style={{ color: "var(--text-muted)", fontSize: 12 }}>Reconnecting...</span>
                  <button onClick={() => fetchCandles(interval, mode)} style={{
                    padding: "4px 14px", background: "var(--bg)", border: "1px solid var(--border)",
                    borderRadius: 4, color: "var(--text)", fontSize: 11, cursor: "pointer", marginTop: 4,
                  }}>Retry now</button>
                </div>
              )}
              <div ref={containerRef} style={{ width: "100%", height: 340 }} />
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
        )
      )}
    </div>
  );
}
