/**
 * A single metric display card.
 * @param {string} label - metric name
 * @param {string|number} value - displayed value
 * @param {string} color - "green", "red", or undefined
 */
export default function MetricCard({ label, value, color }) {
  return (
    <div className="card">
      <div className="label">{label}</div>
      <div className={`value ${color || ""}`}>{value}</div>
    </div>
  );
}
