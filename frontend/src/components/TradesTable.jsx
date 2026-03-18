/**
 * Table showing trade history.
 * @param {Array} trades - list of trade dicts
 */
export default function TradesTable({ trades }) {
  if (!trades || trades.length === 0) {
    return <div className="loading">No trades yet.</div>;
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Action</th>
            <th>Price</th>
            <th>Qty</th>
            <th>P&L</th>
            <th>Strategy</th>
            <th>Regime</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => {
            const pnl = parseFloat(t.pnl) || 0;
            const action = (t.action || "HOLD").toUpperCase();
            return (
              <tr key={i}>
                <td>{(t.timestamp || "").slice(0, 19)}</td>
                <td>
                  <span className={`tag ${action.toLowerCase()}`}>{action}</span>
                </td>
                <td>${parseFloat(t.price || 0).toLocaleString()}</td>
                <td>{parseFloat(t.quantity || 0).toFixed(6)}</td>
                <td style={{ color: pnl >= 0 ? "var(--green)" : "var(--red)" }}>
                  ${pnl.toFixed(4)}
                </td>
                <td>{t.strategy || "-"}</td>
                <td>{t.market_condition || "-"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
