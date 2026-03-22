import { useRef, useState, useEffect } from "react";

/**
 * ChartContainer — Safari-safe chart wrapper with ResizeObserver.
 *
 * Replaces Recharts' <ResponsiveContainer> which is flaky on iPad Safari.
 * Measures the container with ResizeObserver and passes explicit width/height
 * to children. Only renders children when width > 0.
 *
 * Props:
 *   height     — fixed height in px (default: 280)
 *   expandable — show expand/collapse toggle (default: false)
 *   expandedHeight — height when expanded (default: "60vh")
 *   title      — optional chart title
 *   children   — function receiving ({ width, height, expanded }) or React elements
 */

const _isTouch = typeof window !== "undefined" &&
  ("ontouchstart" in window || navigator.maxTouchPoints > 0);

export default function ChartContainer({
  height = 280,
  expandable = false,
  expandedHeight = "60vh",
  title = null,
  children,
}) {
  const containerRef = useRef(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ width: Math.floor(width), height: Math.floor(height) });
    });

    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const containerHeight = expanded ? expandedHeight : height;

  return (
    <div style={{ marginBottom: 8 }}>
      {/* Header with title + expand toggle */}
      {(title || expandable) && (
        <div style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          marginBottom: 4,
        }}>
          {title && (
            <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)" }}>
              {title}
            </span>
          )}
          {expandable && (
            <button
              onClick={() => setExpanded(v => !v)}
              style={{
                background: "none", border: "none", cursor: "pointer",
                fontSize: 10, color: "var(--text-muted)", padding: "2px 6px",
              }}
            >
              {expanded ? "▾ Collapse" : "▸ Expand"}
            </button>
          )}
        </div>
      )}

      {/* Chart area — explicit height, ResizeObserver measures width */}
      <div
        ref={containerRef}
        key={expanded ? "expanded" : "normal"}
        style={{
          width: "100%",
          height: containerHeight,
          minHeight: 200,
          position: "relative",
        }}
      >
        {size.width > 0 && (
          typeof children === "function"
            ? children({
                width: size.width,
                height: size.height || (typeof containerHeight === "number" ? containerHeight : 280),
                expanded,
              })
            : children
        )}
      </div>
    </div>
  );
}
