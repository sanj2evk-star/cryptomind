import { useApi } from "../hooks/useApi";
import { fmtLocalTime, getTimezoneLabel } from "../hooks/useTime";
import { Loading, ErrorBox, EmptyState } from "../components/StatusMessage";

const TZ_LABEL = getTimezoneLabel();

function fmtPrice(n) {
  return `$${Number(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/* Color for action tags */
function actionColor(action) {
  if (action === "BUY") return "var(--green)";
  if (action === "SELL") return "var(--red)";
  return "var(--text-muted)";
}

/* Small colored pill */
function Pill({ text, color }) {
  return (
    <span style={{
      display: "inline-block", padding: "1px 7px", borderRadius: 3,
      fontSize: 10, fontWeight: 700, letterSpacing: 0.5,
      background: `${color}22`, color, border: `1px solid ${color}44`,
    }}>
      {text}
    </span>
  );
}

/* Score dot on a 0-100 bar */
function ScoreBar({ score, buyThresh, sellThresh }) {
  const s = Number(score ?? 50);
  const bt = Number(buyThresh ?? 65);
  const st = Number(sellThresh ?? 35);
  const dotColor = s > bt ? "var(--green)" : s < st ? "var(--red)" : "var(--text-muted)";
  return (
    <div style={{ position: "relative", height: 4, background: "var(--border)", borderRadius: 2, minWidth: 80 }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: `${st}%`, height: "100%", background: "#ef444422", borderRadius: "2px 0 0 2px" }} />
      <div style={{ position: "absolute", right: 0, top: 0, width: `${100 - bt}%`, height: "100%", background: "#22c55e22", borderRadius: "0 2px 2px 0" }} />
      <div style={{
        position: "absolute", top: -4, left: `${Math.max(0, Math.min(100, s))}%`,
        transform: "translateX(-50%)", width: 10, height: 10, borderRadius: "50%",
        background: dotColor, border: "2px solid var(--surface)",
      }} />
    </div>
  );
}

/* Single journal entry card */
function JournalEntry({ entry }) {
  const dec = entry.decision || {};
  const signals = entry.signals || {};
  const ind = entry.indicators || {};
  const adaptive = entry.adaptive || {};
  const exec = entry.execution || {};
  const pf = entry.portfolio_after || {};

  const action = dec.action || "HOLD";
  const score = dec.score ?? 50;
  const conf = ((dec.confidence ?? 0) * 100).toFixed(0);
  const volRegime = adaptive.vol_regime || ind.vol_regime || "unknown";
  const buyT = adaptive.buy_threshold ?? 65;
  const sellT = adaptive.sell_threshold ?? 35;
  const boost = adaptive.momentum_boost ?? 0;
  const isEarly = adaptive.is_early_entry ?? false;
  const isSpike = ind.is_spike ?? false;
  const emerging = ind.emerging_trend || "none";

  const volColors = { high: "#ef4444", low: "#6b7280", normal: "#3b82f6" };
  const volLabels = { high: "HIGH VOL", low: "LOW VOL", normal: "NORMAL" };

  return (
    <div style={{
      background: "var(--surface)", border: "1px solid var(--border)",
      borderRadius: 8, padding: 14, marginBottom: 10,
      borderLeft: `3px solid ${actionColor(action)}`,
    }}>
      {/* Header row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 12, color: "var(--text-muted)", fontFamily: "monospace" }}>
            #{entry.cycle ?? "—"}
          </span>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            {fmtLocalTime(entry.timestamp)}
          </span>
          <span className={`tag ${action.toLowerCase()}`} style={{ fontSize: 12, padding: "2px 8px" }}>
            {action}
          </span>
          <span style={{ fontSize: 13, fontWeight: 600 }}>
            Score: {score}/100
          </span>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
            ({conf}% conf)
          </span>
          {boost > 0 && <Pill text={`+${boost} boost`} color="#22c55e" />}
          {isEarly && <Pill text="EARLY" color="#a78bfa" />}
          {isSpike && <Pill text="SPIKE" color="#f59e0b" />}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>{fmtPrice(entry.price)}</span>
          <Pill text={volLabels[volRegime] || "?"} color={volColors[volRegime] || "#6b7280"} />
        </div>
      </div>

      {/* Score bar */}
      <div style={{ marginBottom: 8 }}>
        <ScoreBar score={score} buyThresh={buyT} sellThresh={sellT} />
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "var(--text-muted)", marginTop: 2 }}>
          <span>SELL &lt;{sellT}</span>
          <span>BUY &gt;{buyT}</span>
        </div>
      </div>

      {/* Reasoning */}
      <div style={{ fontSize: 12, color: "var(--text)", lineHeight: 1.5, marginBottom: 8 }}>
        {dec.reasoning || "No reasoning available."}
      </div>

      {/* Signals + Indicators row */}
      <div style={{ display: "flex", gap: 16, fontSize: 11, color: "var(--text-muted)", flexWrap: "wrap" }}>
        <span>EMA: <b style={{ color: signals.ema_score > 55 ? "var(--green)" : signals.ema_score < 45 ? "var(--red)" : "var(--text)" }}>{signals.ema_score ?? "—"}</b></span>
        <span>RSI: <b style={{ color: signals.rsi_score > 55 ? "var(--green)" : signals.rsi_score < 45 ? "var(--red)" : "var(--text)" }}>{signals.rsi_score ?? "—"}</b></span>
        <span>Trend: <b style={{ color: signals.trend_score > 55 ? "var(--green)" : signals.trend_score < 45 ? "var(--red)" : "var(--text)" }}>{signals.trend_score ?? "—"}</b></span>
        <span>Accel: <b style={{ color: (signals.accel_score ?? 50) > 55 ? "var(--green)" : (signals.accel_score ?? 50) < 45 ? "var(--red)" : "var(--text)" }}>{signals.accel_score ?? "—"}</b></span>
        <span style={{ opacity: 0.6 }}>|</span>
        <span>RSI: {ind.rsi?.toFixed(1) ?? "—"}</span>
        <span>Trend: {ind.trend || "—"}</span>
        <span>Vol: {((ind.volatility ?? 0) * 100).toFixed(3)}%</span>
        {emerging !== "none" && <Pill text={emerging.replace("_", " ")} color="#a78bfa" />}
      </div>

      {/* Execution + portfolio (only for BUY/SELL) */}
      {exec.action_taken !== "HOLD" && (
        <div style={{ marginTop: 8, padding: "6px 10px", background: "var(--bg)", borderRadius: 4, fontSize: 11, color: "var(--text-muted)" }}>
          {exec.reason} &nbsp;|&nbsp; Cash: {fmtPrice(pf.cash)} &nbsp;|&nbsp; BTC: {(pf.btc_holdings ?? 0).toFixed(6)} &nbsp;|&nbsp; Equity: {fmtPrice(pf.equity)}
        </div>
      )}
    </div>
  );
}

export default function Journal() {
  const { data, loading, error, retry } = useApi("/journal?limit=20", 10000);

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>Trade Journal</h1>
        <button
          onClick={retry}
          style={{
            padding: "6px 14px", background: "var(--surface)",
            border: "1px solid var(--border)", borderRadius: 6,
            color: "var(--text)", fontSize: 13, cursor: "pointer",
          }}
        >
          Refresh
        </button>
      </div>

      <p style={{ color: "var(--text-muted)", fontSize: 13, marginBottom: 20 }}>
        Every trading cycle is logged here — see how the AI thinks, what signals it reads, and why it acts or holds.
        <span style={{ opacity: 0.5, marginLeft: 8 }}>Times shown in {TZ_LABEL}</span>
      </p>

      {loading && !data && <Loading message="Loading journal..." />}
      {error && !data && <ErrorBox message={error} onRetry={retry} />}

      {data && data.entries?.length === 0 && (
        <EmptyState title="No journal entries yet" message="The auto-trader will log entries as it runs. Wait a few cycles." />
      )}

      {data?.entries?.map((entry, i) => (
        <JournalEntry key={`${entry.timestamp}-${i}`} entry={entry} />
      ))}

      {data && (
        <p style={{ fontSize: 11, color: "var(--text-muted)", textAlign: "right", marginTop: 12 }}>
          Showing {data.entries?.length ?? 0} of {data.count ?? 0} entries (newest first)
        </p>
      )}
    </>
  );
}
