import { useEffect, useRef, useState, useCallback } from "react";
import { createChart, ColorType, CrosshairMode } from "lightweight-charts";

const API = import.meta.env.VITE_API_URL || window.location.origin;

const TIMEFRAMES = [
  { label: "1m", value: "1m" },
  { label: "5m", value: "5m" },
  { label: "15m", value: "15m" },
  { label: "1H", value: "1h" },
];

function fmtPrice(n) {
  return `$${Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function BTCChart({ marketState, action, confidence, livePrice }) {
  const chartRef = useRef(null);
  const containerRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const ema9Ref = useRef(null);
  const ema21Ref = useRef(null);
  const [interval, setInterval_] = useState("5m");
  const [source, setSource] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastCandle, setLastCandle] = useState(null);
  const pollRef = useRef(null);

  const fetchCandles = useCallback(async (tf) => {
    try {
      setLoading(true);
      setError(null);
      const resp = await fetch(`${API}/candles?interval=${tf}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();

      if (!data.candles || data.candles.length === 0) {
        setError("No candle data available");
        setLoading(false);
        return;
      }

      setSource(data.source || "unknown");

      // Destroy old chart
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }

      if (!containerRef.current) return;

      // Create chart
      const chart = createChart(containerRef.current, {
        width: containerRef.current.clientWidth,
        height: 380,
        layout: {
          background: { type: ColorType.Solid, color: "transparent" },
          textColor: "#9ca3af",
          fontSize: 11,
        },
        grid: {
          vertLines: { color: "rgba(255,255,255,0.04)" },
          horzLines: { color: "rgba(255,255,255,0.04)" },
        },
        crosshair: {
          mode: CrosshairMode.Normal,
          vertLine: { color: "rgba(255,255,255,0.1)", width: 1, style: 3 },
          horzLine: { color: "rgba(255,255,255,0.1)", width: 1, style: 3 },
        },
        rightPriceScale: {
          borderColor: "rgba(255,255,255,0.08)",
          scaleMargins: { top: 0.05, bottom: 0.05 },
        },
        timeScale: {
          borderColor: "rgba(255,255,255,0.08)",
          timeVisible: true,
          secondsVisible: tf === "1m",
          rightOffset: 5,
        },
        handleScroll: { mouseWheel: true, pressedMouseMove: true },
        handleScale: { mouseWheel: true, pinch: true },
      });

      chartRef.current = chart;

      // Candlestick series
      const candleSeries = chart.addCandlestickSeries({
        upColor: "#22c55e",
        downColor: "#ef4444",
        borderUpColor: "#22c55e",
        borderDownColor: "#ef4444",
        wickUpColor: "#22c55e88",
        wickDownColor: "#ef444488",
      });
      candleSeries.setData(data.candles);
      candleSeriesRef.current = candleSeries;

      // EMA 9 line
      if (data.ema9 && data.ema9.length > 0) {
        const ema9 = chart.addLineSeries({
          color: "#3b82f6",
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        ema9.setData(data.ema9);
        ema9Ref.current = ema9;
      }

      // EMA 21 line
      if (data.ema21 && data.ema21.length > 0) {
        const ema21 = chart.addLineSeries({
          color: "#f59e0b",
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        ema21.setData(data.ema21);
        ema21Ref.current = ema21;
      }

      chart.timeScale().fitContent();

      setLastCandle(data.candles[data.candles.length - 1]);
      setLoading(false);

      // Resize handler
      const observer = new ResizeObserver((entries) => {
        for (const entry of entries) {
          chart.applyOptions({ width: entry.contentRect.width });
        }
      });
      if (containerRef.current) observer.observe(containerRef.current);

      return () => observer.disconnect();
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }, []);

  // Initial load + interval change
  useEffect(() => {
    fetchCandles(interval);
    return () => {
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [interval, fetchCandles]);

  // Polling for live updates
  useEffect(() => {
    const pollInterval = { "1m": 15000, "5m": 30000, "15m": 60000, "1h": 120000 };
    const ms = pollInterval[interval] || 30000;

    pollRef.current = window.setInterval(() => {
      fetchCandles(interval);
    }, ms);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [interval, fetchCandles]);

  // Market state colors
  const stateColors = {
    SLEEPING: "#6b7280",
    WAKING_UP: "#eab308",
    ACTIVE: "#22c55e",
    BREAKOUT: "#ef4444",
  };
  const actionColors = { BUY: "#22c55e", SELL: "#ef4444", HOLD: "#6b7280" };

  return (
    <div className="card" style={{ padding: 0, overflow: "hidden", marginBottom: 24 }}>
      {/* Chart header */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "12px 16px", borderBottom: "1px solid var(--border)",
        flexWrap: "wrap", gap: 8,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 15, fontWeight: 700 }}>BTC/USDT</span>
          {livePrice > 0 && (
            <span style={{ fontSize: 15, fontWeight: 600, color: "var(--text)" }}>
              {fmtPrice(livePrice)}
            </span>
          )}
          {lastCandle && (
            <span style={{
              fontSize: 11,
              color: lastCandle.close >= lastCandle.open ? "#22c55e" : "#ef4444",
              fontWeight: 600,
            }}>
              {lastCandle.close >= lastCandle.open ? "▲" : "▼"}{" "}
              {((lastCandle.close - lastCandle.open) / lastCandle.open * 100).toFixed(2)}%
            </span>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {/* Bot indicators */}
          {marketState && (
            <span style={{
              fontSize: 10, fontWeight: 700, padding: "2px 6px", borderRadius: 3,
              background: `${stateColors[marketState] || "#666"}22`,
              color: stateColors[marketState] || "#666",
            }}>
              {marketState}
            </span>
          )}
          {action && (
            <span style={{
              fontSize: 10, fontWeight: 700, padding: "2px 6px", borderRadius: 3,
              background: `${actionColors[action] || "#666"}22`,
              color: actionColors[action] || "#666",
            }}>
              {action}
            </span>
          )}
          {confidence > 0 && (
            <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
              {(confidence * 100).toFixed(0)}%
            </span>
          )}

          {/* Source badge */}
          {source && (
            <span style={{ fontSize: 9, color: "var(--text-muted)", opacity: 0.5 }}>
              via {source}
            </span>
          )}

          {/* Timeframe buttons */}
          <div style={{ display: "flex", gap: 2, background: "var(--bg)", borderRadius: 6, padding: 2 }}>
            {TIMEFRAMES.map(tf => (
              <button
                key={tf.value}
                onClick={() => setInterval_(tf.value)}
                style={{
                  padding: "4px 10px", border: "none", borderRadius: 4,
                  fontSize: 11, fontWeight: 600, cursor: "pointer",
                  background: interval === tf.value ? "var(--surface)" : "transparent",
                  color: interval === tf.value ? "var(--text)" : "var(--text-muted)",
                  transition: "all 0.15s",
                }}
              >
                {tf.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Chart body */}
      <div style={{ position: "relative", minHeight: 380 }}>
        {loading && !lastCandle && (
          <div style={{
            position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
            background: "var(--surface)", zIndex: 2,
          }}>
            <span style={{ color: "var(--text-muted)", fontSize: 13 }}>Loading chart...</span>
          </div>
        )}
        {error && !lastCandle && (
          <div style={{
            position: "absolute", inset: 0, display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center", background: "var(--surface)", zIndex: 2, gap: 8,
          }}>
            <span style={{ color: "var(--text-muted)", fontSize: 13 }}>Chart unavailable</span>
            <span style={{ color: "var(--text-muted)", fontSize: 11 }}>{error}</span>
            <button onClick={() => fetchCandles(interval)} style={{
              padding: "4px 12px", background: "var(--bg)", border: "1px solid var(--border)",
              borderRadius: 4, color: "var(--text)", fontSize: 11, cursor: "pointer",
            }}>
              Retry
            </button>
          </div>
        )}
        <div ref={containerRef} style={{ width: "100%" }} />
      </div>

      {/* EMA Legend */}
      <div style={{
        display: "flex", gap: 16, padding: "6px 16px 10px",
        fontSize: 10, color: "var(--text-muted)",
      }}>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 12, height: 2, background: "#3b82f6", borderRadius: 1 }} />
          EMA 9
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 12, height: 2, background: "#f59e0b", borderRadius: 1 }} />
          EMA 21
        </span>
      </div>
    </div>
  );
}
