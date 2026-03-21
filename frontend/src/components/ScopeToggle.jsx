import { useState } from "react";

/**
 * ScopeToggle — Session / Version / Lifetime toggle for data views.
 * Used across Trades, Performance, Memory, Journal, Lab pages.
 */
const SCOPES = [
  { key: "session", label: "Session" },
  { key: "version", label: "Version" },
  { key: "lifetime", label: "Lifetime" },
];

export default function ScopeToggle({ value, onChange, compact = false }) {
  return (
    <div style={{
      display: "inline-flex", gap: 0, borderRadius: 4,
      border: "1px solid var(--border)", overflow: "hidden",
    }}>
      {SCOPES.map(s => (
        <button
          key={s.key}
          onClick={() => onChange(s.key)}
          style={{
            padding: compact ? "2px 8px" : "3px 10px",
            fontSize: compact ? 9 : 10,
            fontWeight: value === s.key ? 700 : 400,
            background: value === s.key ? "var(--text)" : "transparent",
            color: value === s.key ? "var(--bg)" : "var(--text-muted)",
            border: "none",
            cursor: "pointer",
            transition: "all 0.15s ease",
          }}
        >
          {s.label}
        </button>
      ))}
    </div>
  );
}
